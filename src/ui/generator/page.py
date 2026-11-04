"""GeneratorPage: the desk. Run bar, tool row, the sheet or queue, and the Inspector; the viewer fills it all."""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton, QScrollArea, QSlider,
    QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

from src import config
from src.characters import attach as char_attach
from src.gen.importer import load_prompts, parse_text
from src.gen.models import Job, JobStatus
from src.gen.output import default_save_dir, output_dir, save_outputs
from src.gen.provider import Provider, ProviderError, shot_options
from src.gen.queue import JobQueue, QueueSettings, count_statuses
from src.gen.refmatch import match_refs
from src.i18n import tr
from src.ui.generator.config_panel import ConfigPanel, fields_for
from src.ui.generator.prompt_model import COL_PROMPT, PromptTableModel
from src.ui.generator.prompt_table import PromptTable
from src.ui.generator.queue_bridge import QueueBridge
from src.ui.generator.credit_meter import CreditMeter
from src.ui.generator.sheet import FILTERS, RunStrip, SheetView
from src.ui.generator.stats_header import StatsHeader
from src.ui.generator.take_panel import TakePanel
from src.ui.generator.viewer import TakeViewer
from src.ui.kit import HELP_GUTTER, IconButton, Segmented, flow_row, page_title, set_icon
from src.web.production_actions import ActionError, ProductionActions
from src.web.run_mirror import apply_item, banner_text

log = logging.getLogger(__name__)

INSPECTOR_WIDTH = 300
INSPECTOR_MIN_PAGE = 900  # below this the sheet keeps the room until the panel is asked for
FRAME_WIDTHS = (140, 480, 240)  # minimum, maximum, default


class _EmptyState(QWidget):
    """Nothing to show: a heading, a note, the ways in, and drop anywhere."""

    files_dropped = Signal(list)

    def __init__(self, title: str, hint: str, *buttons: QPushButton):
        super().__init__()
        self.setAcceptDrops(True)
        heading = QLabel(title)
        heading.setObjectName("EmptyTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note = QLabel(hint)
        note.setObjectName("Hint")
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setVisible(bool(hint))
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addStretch(1)
        for b in buttons:
            row.addWidget(b)
        row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addStretch(1)
        layout.addWidget(heading)
        layout.addWidget(note)
        layout.addLayout(row)
        layout.addStretch(2)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt override
        event.acceptProposedAction() if PromptTable._import_paths(event) else event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        paths = PromptTable._import_paths(event)
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(paths)


def _flow_status() -> dict:
    """Flow's status from a running engine only: the meter never starts one."""
    from src.web.flow_mcp import flow_mcp

    health = flow_mcp().client.health()
    if health is None or health.down:
        raise ConnectionError("the Flow engine is not running")
    return flow_mcp().status()


RUN_BAR_COMPACT = 1200  # page width below which Pause, Stop, Retry and Open folder go icon-only


class GeneratorPage(QWidget):
    _action_back = Signal(object)  # a callable to run on the GUI thread
    animate_stills = Signal(list)  # [(prompt, still path)] for the video page, wired by the app

    def __init__(self, page_key: str, provider: Provider, title: str = "", banner: str = "",
                 store=None, parent: QWidget | None = None, characters=None,
                 alternatives: list[tuple[Provider, str]] | None = None, scenes=None):
        """``alternatives``: extra (provider, banner) pairs offered in a Provider picker."""
        super().__init__(parent)
        self.page_key = page_key
        self._characters = characters  # CharacterStore; the app-wide one is loaded on first use
        self._scenes = scenes  # the scene library (Phase 14b), same
        self.provider = provider
        self._store = store
        self._batch_folder: Path | None = None
        self.providers: list[tuple[Provider, str]] = [(provider, banner)] + list(alternatives or [])

        self.config_panel = ConfigPanel(page_key, fields_for(provider), store)
        self.model = PromptTableModel(self)
        self.table = PromptTable(self.model)
        self.stats_header = StatsHeader()
        self.bridge = QueueBridge(self)
        self.queue = JobQueue(provider, self._save, self.bridge.on_update, self.bridge.on_finished)
        self.bridge.job_updated.connect(self._on_job_updated)
        self.bridge.finished.connect(self._on_finished)

        self._prefs = store if store is not None else config.settings()
        self.title = title
        self.sheet = SheetView(self.model)
        self.sheet.setSelectionModel(self.table.selectionModel())
        self.run_strip = RunStrip(self.model)
        self.viewer = TakeViewer(self.model)
        self.take_panel = TakePanel()

        self.btn_import = self._button("gen_import", self.import_dialog, "upload-simple")
        self.btn_paste = self._button("gen_paste", self.paste_dialog, "clipboard-text")
        self.btn_match = IconButton("link-simple", tr("gen_match_refs"), self.match_refs)
        self.btn_match_chars = IconButton("user-focus", tr("gen_match_characters"), self.match_characters)
        self.btn_match_chars.setToolTip(tr("gen_match_characters_tip"))
        self.btn_clear = IconButton("eraser", tr("gen_clear"), self._confirm_clear)
        self.btn_start = self._button("gen_start", self._confirm_start, "play", "accent_text")
        self.btn_pause = self._button("gen_pause", self.toggle_pause, "pause")
        self.btn_stop = self._button("gen_stop", self.stop, "stop")
        self.btn_retry = self._button("gen_retry_failed", self.retry_failed, "arrow-clockwise")
        self.btn_folder = self._button("gen_open_folder", self.open_output_folder, "folder-open")
        self.btn_start.setObjectName("PrimaryButton")

        # Run bar: the name, what the run is doing, and the strip that reads from across the room.
        run_row = QHBoxLayout()
        run_row.setContentsMargins(0, 0, HELP_GUTTER - 14, 0)
        run_row.setSpacing(6)
        if title:
            run_row.addWidget(page_title(title))
            run_row.addSpacing(10)
        self.credit_meter = CreditMeter(_flow_status, self._tab_idle)
        run_row.addWidget(self.credit_meter)
        run_row.addStretch(1)
        for b in (self.btn_start, self.btn_pause, self.btn_stop, self.btn_retry, self.btn_folder):
            run_row.addWidget(b)
        self.stats_header.setWordWrap(True)
        run_bar = QVBoxLayout()
        run_bar.setContentsMargins(14, 8, 14, 0)
        run_bar.setSpacing(6)
        run_bar.addLayout(run_row)
        run_bar.addWidget(self.stats_header)
        run_bar.addWidget(self.run_strip)

        # Tool row: wraps instead of clipping at the minimum window size.
        self.view_switch = Segmented([("sheet", tr("gen_view_sheet")), ("queue", tr("gen_view_queue"))],
                                     self._prefs.get(f"pages.{page_key}.view", "sheet"))
        self.filter_bar = Segmented([(k, tr(f"gen_filter_{k}")) for k in FILTERS])
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(FRAME_WIDTHS[0], FRAME_WIDTHS[1])
        self.size_slider.setFixedWidth(110)
        self.size_slider.setToolTip(tr("gen_frame_size"))
        self.size_slider.setAccessibleName(tr("gen_frame_size"))
        self.size_slider.setValue(int(self._prefs.get(f"pages.{page_key}.frame_width", FRAME_WIDTHS[2])))
        self.btn_inspector = IconButton("sidebar-simple", tr("gen_inspector_toggle"), self.toggle_inspector, checkable=True)
        self.tools = flow_row(self.btn_import, self.btn_paste, self.btn_match, self.btn_match_chars, self.btn_clear,
                              self.view_switch, self.filter_bar, self.size_slider, self.btn_inspector)
        tool_box = QVBoxLayout()
        tool_box.setContentsMargins(14, 8, 14, 8)
        tool_box.addWidget(self.tools)

        # Centre: empty state, sheet, queue, or the filter's empty note.
        self.run_notice = QLabel()
        self.run_notice.setObjectName("RunNotice")
        self.run_notice.setWordWrap(True)
        self.run_notice.setContentsMargins(14, 0, 14, 6)
        self.run_notice.hide()
        # What the owner can do about a held Production, by the engine's reason.
        self.btn_accept_quote = self._button("run_accept_quote", self.accept_quote)
        self.btn_raise_cap = self._button("run_raise_cap", self.raise_cap)
        self.btn_resume_run = self._button("run_resume", self.resume_run, "play")
        self.run_actions = QWidget()
        actions_row = QHBoxLayout(self.run_actions)
        actions_row.setContentsMargins(14, 0, 14, 6)
        for b in (self.btn_accept_quote, self.btn_raise_cap, self.btn_resume_run):
            actions_row.addWidget(b)
        actions_row.addStretch(1)
        self.run_actions.hide()
        self._production_run: dict = {}
        empty_import = self._button("gen_import", self.import_dialog, "upload-simple")
        empty_paste = self._button("gen_paste", self.paste_dialog, "clipboard-text")
        self.empty = _EmptyState(tr("gen_empty_title"), tr("gen_empty_hint"), empty_import, empty_paste)
        self.empty.files_dropped.connect(self.import_files)
        self.empty_buttons = (empty_import, empty_paste)
        show_all = QPushButton(tr("gen_filter_all"))
        show_all.clicked.connect(lambda _checked=False: self.set_filter("all"))
        self.filter_empty = _EmptyState(tr("gen_filter_empty"), "", show_all)
        self.views = QStackedWidget()
        for w in (self.empty, self.sheet, self.table, self.filter_empty):
            self.views.addWidget(w)

        # Inspector: the selected take, and the settings for the next shots.
        self.scroll = scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.config_panel)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        settings = QWidget()
        settings_box = QVBoxLayout(settings)
        settings_box.setContentsMargins(12, 12, 4, 0)
        settings_box.setSpacing(8)
        self.provider_combo: QComboBox | None = None
        if len(self.providers) > 1:
            self.provider_combo = QComboBox()
            for p, _ in self.providers:
                self.provider_combo.addItem(p.name, p.key)
            pick = QHBoxLayout()
            pick.addWidget(QLabel(tr("gen_provider")))
            pick.addWidget(self.provider_combo, 1)
            settings_box.addLayout(pick)
        self._provider_banner = banner
        self._production_banner = ""
        self._engine_notice = ""
        self.banner_label = QLabel(banner)
        self.banner_label.setWordWrap(True)
        self.banner_label.setObjectName("DemoBanner")
        self.banner_label.setVisible(bool(banner))
        settings_box.addWidget(self.banner_label)
        settings_box.addWidget(scroll, 1)
        self.inspector_tabs = QTabWidget()
        self.inspector_tabs.setDocumentMode(True)
        self.inspector_tabs.tabBar().setDrawBase(False)
        self.inspector_tabs.addTab(self.take_panel, tr("gen_tab_take"))
        self.inspector_tabs.addTab(settings, tr("gen_tab_settings"))
        self.inspector = QFrame()
        self.inspector.setObjectName("Inspector")
        self.inspector.setFixedWidth(INSPECTOR_WIDTH)
        inspector_box = QVBoxLayout(self.inspector)
        inspector_box.setContentsMargins(0, 4, 0, 0)
        inspector_box.addWidget(self.inspector_tabs)
        self._inspector_wanted = bool(self._prefs.get(f"pages.{page_key}.inspector", True))
        self._narrow = False

        centre = QVBoxLayout()
        centre.setContentsMargins(0, 0, 0, 0)
        centre.setSpacing(0)
        centre.addWidget(self.run_notice)
        centre.addWidget(self.run_actions)
        centre.addWidget(self.views, 1)
        work = QHBoxLayout()
        work.setContentsMargins(0, 0, 0, 0)
        work.setSpacing(0)
        work.addLayout(centre, 1)
        work.addWidget(self.inspector)

        desk_box = QVBoxLayout()
        desk_box.setContentsMargins(0, 0, 0, 0)
        desk_box.setSpacing(0)
        desk_box.addLayout(run_bar)
        desk_box.addLayout(tool_box)
        desk_box.addLayout(work, 1)
        self.desk = QWidget()
        self.desk.setLayout(desk_box)
        self.surface = QStackedWidget()
        self.surface.addWidget(self.desk)
        self.surface.addWidget(self.viewer)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.surface)

        self.sheet.set_frame_width(self.size_slider.value())
        self.size_slider.valueChanged.connect(self._on_frame_width)
        self.view_switch.changed.connect(self.set_view)
        self.filter_bar.changed.connect(self.set_filter)
        self.sheet.filter_changed.connect(lambda _n: self._on_filtered())
        self.sheet.files_dropped.connect(self.import_files)
        self.sheet.open_requested.connect(self.open_viewer)
        self.sheet.approve_requested.connect(self.approve_rows)
        self.sheet.reject_requested.connect(self.reject_rows)
        self.sheet.retry_requested.connect(self._confirm_retry)
        self.sheet.edit_requested.connect(self.edit_row)
        self.sheet.menu_requested.connect(self._sheet_menu)
        self.run_strip.row_clicked.connect(self.select_row)
        self.viewer.closed.connect(self.close_viewer)
        self.viewer.row_changed.connect(self._on_viewer_row)
        self.viewer.approve_requested.connect(self.approve_rows)
        self.viewer.reject_requested.connect(self.reject_rows)
        self.viewer.take_review_requested.connect(self.review_take)
        self.viewer.retry_requested.connect(self._confirm_retry)
        self.viewer.edit_requested.connect(self.edit_row)
        self.viewer.open_requested.connect(self._open)
        self.take_panel.approve_requested.connect(self.approve_rows)
        self.take_panel.reject_requested.connect(self.reject_rows)
        self.take_panel.take_review_requested.connect(self.review_take)
        self.take_panel.retry_requested.connect(self._confirm_retry)
        self.take_panel.edit_requested.connect(self.edit_row)
        self.take_panel.view_requested.connect(self.open_viewer)
        self.take_panel.open_requested.connect(self.open_output)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._refresh_take())
        self.model.dataChanged.connect(lambda *_: self._refresh_take())
        self.model.modelReset.connect(lambda *_: self._refresh_take())

        self.table.files_dropped.connect(self.import_files)
        self.table.edit_requested.connect(self.edit_row)
        self.table.retry_requested.connect(self.retry_rows)
        self.table.cancel_requested.connect(self.cancel_rows)
        self.table.remove_requested.connect(self.remove_rows)
        self.table.approve_requested.connect(self.approve_rows)
        self.table.reject_requested.connect(self.reject_rows)
        self.table.regenerate_requested.connect(self.retry_rows)
        self._actions = None
        self._action_back.connect(self._run_back)
        self.table.open_output_requested.connect(self.open_output)
        self.table.animate_enabled = page_key == "flow_image"
        self.table.chain_enabled = page_key == "flow_video"
        self.table.animate_requested.connect(self.animate_rows)
        self.table.chain_requested.connect(self.chain_last_frame)
        self.table.clip_mode_requested.connect(self.clip_mode)
        self.table.clip_modes = self._clip_modes if page_key == "flow_video" else (lambda job: [])
        self.take_panel.frames_enabled = page_key == "flow_video"
        self.take_panel.frame_changed.connect(self.set_frame)
        self.take_panel.set_shot_fields(fields_for(self.provider), lambda: self.config_panel.values())
        self.take_panel.shot_override_changed.connect(self.set_shot_override)
        self.table.open_folder_requested.connect(self.open_row_folder)
        self.table.characters_source = lambda: [(c.id, c.name) for c in self.characters.all()]
        self.table.character_requested.connect(self.set_character)
        self.table.character_added.connect(self.add_character)
        self.model.character_name = lambda job: char_attach.character_label(job, self.characters)
        self.table.scenes_source = lambda: [(s.id, s.name) for s in self.scenes.all()]
        self.table.scene_requested.connect(self.set_scene)
        self.model.scene_name = lambda job: char_attach.scene_label(job, self.scenes)
        # Phase 12: rows live in the active project and are saved shortly after each change.
        self._project = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self.save_rows)
        # Elapsed clocks tick: once a second, only live rows repaint.
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(1000)
        self._live_timer.timeout.connect(self._tick_live)
        self._live_timer.start()
        self.load_rows()
        for sig in (self.model.rowsInserted, self.model.rowsRemoved, self.model.modelReset, self.model.dataChanged):
            sig.connect(lambda *_: (self._save_timer.start(), self._refresh_stats()))
        if self.provider_combo is not None:
            store_ = store if store is not None else config.settings()
            saved = store_.get(f"pages.{page_key}.provider", provider.key)
            self.provider_combo.setCurrentIndex(max(0, self.provider_combo.findData(saved)))
            self.provider_combo.currentIndexChanged.connect(self._on_provider_picked)
            self._on_provider_picked(self.provider_combo.currentIndex(), save=False)
        self._update_controls()
        self.set_view(self.view_switch.current(), save=False)
        self._update_inspector()

    # ---- provider picker ----------------------------------------------
    def set_provider(self, key: str) -> bool:
        """Switch to the provider with ``key`` (not while a batch runs)."""
        if self.provider_combo is None or self.queue.is_running():
            return False
        idx = self.provider_combo.findData(key)
        if idx < 0:
            return False
        self.provider_combo.setCurrentIndex(idx)
        return self.provider.key == key

    def _on_provider_picked(self, index: int, save: bool = True) -> None:
        provider, banner = self.providers[max(0, index)]
        if self.queue.is_running():
            self.provider_combo.blockSignals(True)
            self.provider_combo.setCurrentIndex(self.provider_combo.findData(self.provider.key))
            self.provider_combo.blockSignals(False)
            return
        if save:
            (self._store if self._store is not None else config.settings()).set(
                f"pages.{self.page_key}.provider", provider.key)
        self._provider_banner = banner
        self._show_banner()
        if provider is self.provider:
            return
        self.provider = provider
        self.queue.provider = provider
        self.config_panel = ConfigPanel(self.page_key, fields_for(provider), self._store)
        self.scroll.setWidget(self.config_panel)
        self.take_panel.set_shot_fields(fields_for(provider), lambda: self.config_panel.values())
        log.info("%s: provider set to %s", self.page_key, provider.name)

    def _show_banner(self) -> None:
        text = "\n".join(filter(None, [self._provider_banner, self._production_banner]))
        self.banner_label.setText(text)
        self.banner_label.setVisible(bool(text))
        notice = "\n".join(filter(None, [self._engine_notice, self._production_banner]))
        self.run_notice.setText(notice)
        self.run_notice.setVisible(bool(notice))

    def set_engine_health(self, health) -> None:
        """Engine pause or outage in the run bar, for any run on it, agent runs included."""
        notice = ""
        if health is not None and health.down:
            notice = tr("engine_down")
        elif health is not None and health.paused_reason:
            notice = tr("engine_paused", reason=health.paused_reason)
        if notice != self._engine_notice:
            self._engine_notice = notice
            self._show_banner()

    def set_production_summary(self, summary: dict, name: str) -> None:
        self._production_banner = banner_text(summary, name)
        self._production_run = summary
        paused = summary.get("paused") or {}
        held = summary.get("status") == "paused"
        self.btn_accept_quote.setVisible(held and paused.get("reason") == "quote_drift")
        self.btn_raise_cap.setVisible(held and paused.get("reason") == "budget")
        self.btn_resume_run.setVisible(held and paused.get("reason") not in ("quote_drift", "budget"))
        self.run_actions.setVisible(held and bool(summary.get("runId")))
        self._update_controls()
        self.run_notice.setProperty("live", summary.get("status") == "running")
        self.run_notice.style().unpolish(self.run_notice)
        self.run_notice.style().polish(self.run_notice)
        self._show_banner()

    def _button(self, key: str, slot, icon: str = "", token: str = "text") -> QPushButton:
        b = QPushButton(tr(key))
        if icon:
            set_icon(b, icon, token)
        b.clicked.connect(lambda _checked=False: slot())
        return b

    # ---- the desk: views, filter, Inspector, viewer ---------------------
    def set_view(self, key: str, save: bool = True) -> None:
        self.view_switch.set_current(key)
        if save:
            self._prefs.set(f"pages.{self.page_key}.view", key)
        self._update_view()

    def set_filter(self, key: str) -> None:
        self.filter_bar.set_current(key)
        self.sheet.set_filter(key)

    def _on_frame_width(self, width: int) -> None:
        self.sheet.set_frame_width(width)
        self._prefs.set(f"pages.{self.page_key}.frame_width", width)

    def _on_filtered(self) -> None:
        """The queue shows what the sheet shows, and a decided frame hands the selection on."""
        rows = range(self.model.rowCount())
        for row in rows:
            self.table.setRowHidden(row, self.sheet.isRowHidden(row))
        selected = self.table.selected_rows()
        if selected and all(self.sheet.isRowHidden(r) for r in selected):
            shown = [r for r in rows if not self.sheet.isRowHidden(r)]
            following = [r for r in shown if r > selected[-1]]
            if shown:
                self.select_row((following or shown)[0])
            else:
                self.table.clearSelection()
        self._update_view()

    def _update_view(self) -> None:
        if not self.model.rowCount():
            target = self.empty
        elif not self.sheet.visible_count():
            target = self.filter_empty
        else:
            target = self.sheet if self.view_switch.current() == "sheet" else self.table
        self.views.setCurrentWidget(target)
        # Nothing to filter or size until there are rows.
        has_rows = self.model.rowCount() > 0
        for w, shown in ((self.view_switch, has_rows), (self.filter_bar, has_rows), (self.run_strip, has_rows),
                         (self.size_slider, has_rows and self.view_switch.current() == "sheet")):
            if w.isHidden() == shown:
                w.setVisible(shown)
                self.tools.updateGeometry()

    def select_row(self, row: int) -> None:
        index = self.model.index(row, COL_PROMPT)
        self.table.selectionModel().setCurrentIndex(
            index, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
        self.sheet.scrollTo(self.model.index(row, self.sheet.modelColumn()))
        self.table.scrollTo(index)

    def _tick_live(self) -> None:
        live = [j for j in self.jobs if j.status in (JobStatus.RUNNING, JobStatus.QUEUED)]
        for job in live:
            self.model.refresh_job(job.id)
        if live and self.inspector.isVisible():
            self._refresh_take()

    def _scroll_to_current(self) -> None:
        rows = self.table.selected_rows()
        if rows:
            self.sheet.scrollTo(self.model.index(rows[0], self.sheet.modelColumn()))
            self.table.scrollTo(self.model.index(rows[0], COL_PROMPT))

    def _refresh_take(self) -> None:
        if self.inspector.isHidden():
            return
        rows = self.table.selected_rows()
        if len(rows) == 1:
            job = self.model.job_at(rows[0])
            self.take_panel.show_rows(self.model, rows, char_attach.character_label(job, self.characters),
                                      char_attach.scene_label(job, self.scenes))
        else:
            self.take_panel.show_rows(self.model, rows)

    def toggle_inspector(self) -> None:
        shown = self.inspector.isHidden()
        if not self._narrow:
            self._inspector_wanted = shown
            self._prefs.set(f"pages.{self.page_key}.inspector", shown)
        self.inspector.setVisible(shown)
        self.btn_inspector.setChecked(shown)
        self._refresh_take()
        QTimer.singleShot(0, self.table, self._scroll_to_current)  # after the reflow, or the row slides out of view

    def _update_inspector(self) -> None:
        shown = self._inspector_wanted and not self._narrow
        self.inspector.setVisible(shown)
        self.btn_inspector.setChecked(shown)
        self._refresh_take()
        QTimer.singleShot(0, self.table, self._scroll_to_current)  # after the reflow, or the row slides out of view

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        narrow = event.size().width() < INSPECTOR_MIN_PAGE
        if narrow != self._narrow:
            self._narrow = narrow
            self._update_inspector()
        compact = event.size().width() < RUN_BAR_COMPACT
        if compact != getattr(self, "_compact", False):
            self._compact = compact
            for b in (self.btn_pause, self.btn_stop, self.btn_retry, self.btn_folder):
                self._label_run_button(b, b.property("label") or b.text())

    def _label_run_button(self, b: QPushButton, text: str) -> None:
        """Below ``RUN_BAR_COMPACT`` the run bar's secondary buttons show their icon only; the name stays
        in the tooltip and the accessible name, so nothing is clipped at 900 px."""
        b.setProperty("label", text)
        b.setAccessibleName(text)
        compact = getattr(self, "_compact", False)
        b.setText("" if compact else text)
        if compact:
            b.setToolTip(text)

    def open_viewer(self, row: int) -> None:
        self.viewer.open_row(row, [r for r in range(self.model.rowCount()) if not self.sheet.isRowHidden(r)])
        self.surface.setCurrentWidget(self.viewer)
        self.viewer.setFocus()
        if getattr(self, "help_button", None) is not None:
            self.help_button.set_on_black(True)

    def close_viewer(self) -> None:
        self.surface.setCurrentWidget(self.desk)
        self.views.currentWidget().setFocus()
        if getattr(self, "help_button", None) is not None:
            self.help_button.set_on_black(False)

    def _on_viewer_row(self, row: int) -> None:
        if row not in self.table.selected_rows():
            self.select_row(row)

    def _sheet_menu(self, pos) -> None:
        rows = self.sheet.selected_rows()
        if rows:
            current = self.sheet.currentIndex().row()
            self.table._build_menu(current if current in rows else rows[0], rows).exec(pos)

    def palette_commands(self) -> list[tuple[str, object]]:
        out = [(b.text() or b.accessibleName(), b.click) for b in (
            self.btn_start, self.btn_pause, self.btn_stop, self.btn_retry, self.btn_folder, self.btn_import,
            self.btn_paste, self.btn_match, self.btn_match_chars, self.btn_clear) if b.isEnabled()]
        out += [(tr("palette_view", name=tr(f"gen_view_{k}")), lambda k=k: self.set_view(k)) for k in ("sheet", "queue")]
        out += [(tr("palette_filter", name=tr(f"gen_filter_{k}")), lambda k=k: self.set_filter(k)) for k in FILTERS]
        out.append((tr("gen_inspector_toggle"), self.toggle_inspector))
        return out

    def _confirm_clear(self) -> None:
        if self.jobs and QMessageBox.question(
                self, self.page_key, tr("gen_clear_confirm", count=len(self.jobs))) == QMessageBox.StandardButton.Yes:
            self.clear()

    def _confirm_retry(self, rows: list[int]) -> None:
        """One key must not spend again on a frame that already has a picture."""
        done = sum(1 for r in rows if self.model.job_at(r).status is JobStatus.DONE)
        if done and QMessageBox.question(
                self, self.page_key, tr("gen_retry_confirm", count=done)) != QMessageBox.StandardButton.Yes:
            return
        self.retry_rows(rows)

    # ---- project rows (Phase 12) ---------------------------------------
    def load_rows(self) -> int:
        """Restore this page's prompt rows from the active project (if projects are on)."""
        from src import projects
        from src.projects.store import row_to_job

        self._project = projects.current()
        if self._project is None:
            return 0
        self._production_banner = self._project.get("production_banner", "")
        self._show_banner()
        jobs = [row_to_job(r, i + 1) for i, r in enumerate(self._project.rows(self.page_key))]
        if jobs:
            self.model.add_jobs(jobs)
            self._refresh_stats()
        return len(jobs)

    def save_rows(self) -> None:
        if self._project is None:
            return
        from src.projects.store import job_to_row

        self._save_timer.stop()
        self._project.set_rows(self.page_key, [job_to_row(j) for j in self.jobs])

    # ---- prompts -----------------------------------------------------
    @property
    def jobs(self) -> list[Job]:
        return self.model.jobs

    def add_prompts(self, prompts: list[str]) -> list[Job]:
        jobs = self.model.add_prompts(prompts)
        if jobs:
            log.info(tr("gen_imported", count=len(jobs)))
            if self.config_panel.value("ref_dir"):
                self.match_refs()
        self._refresh_stats()
        return jobs

    def import_files(self, paths: list[Path]) -> int:
        total = 0
        for path in paths:
            try:
                total += len(self.add_prompts(load_prompts(path, self.config_panel.value("import_mode"))))
            except Exception as exc:  # noqa: BLE001 - show any parse error to the user
                log.error(tr("gen_import_failed", name=Path(path).name, error=exc))
                QMessageBox.warning(self, tr("gen_import"), tr("gen_import_failed", name=Path(path).name, error=exc))
        return total

    def import_dialog(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, tr("gen_import"), "",
                                                "Prompts (*.txt *.xlsx);;All files (*)")
        if files:
            self.import_files([Path(f) for f in files])

    def paste_dialog(self) -> None:
        text, ok = QInputDialog.getMultiLineText(self, tr("gen_paste_title"), tr("gen_paste_label"))
        if ok and text.strip():
            self.add_prompts(parse_text(text, self.config_panel.value("import_mode")))

    def match_refs(self) -> int:
        folder = self.config_panel.value("ref_dir")
        if not folder:
            return 0
        added = match_refs([j for j in self.jobs if not j.production_id], folder)
        log.info(tr("gen_refs_matched", count=added))
        self.model.refresh_all()
        return added

    # ---- characters (Phase 6) ---------------------------------------
    @property
    def characters(self):
        if self._characters is None:
            from src.characters.store import default_store

            self._characters = default_store()
        return self._characters

    def set_character(self, rows: list[int], char_id: str) -> None:
        """Attach a character to the rows (``""`` detaches)."""
        if self._busy_guard():
            return
        for row in rows:
            job = self.model.job_at(row)
            if char_id:
                char_attach.attach(job, char_id, self.characters)
            else:
                char_attach.detach(job)
        self.model.refresh_all()

    def add_character(self, rows: list[int], char_id: str) -> None:
        """Put one more character in the rows' shot (Flow takes several by name)."""
        if self._busy_guard():
            return
        for row in rows:
            job = self.model.job_at(row)
            char_attach.set_characters(job, char_attach.character_ids(job) + [char_id], self.characters)
        self.model.refresh_all()

    # ---- scenes (Phase 14b) ------------------------------------------
    @property
    def scenes(self):
        if self._scenes is None:
            from src.characters.store import scene_store

            self._scenes = scene_store()
        return self._scenes

    def set_scene(self, rows: list[int], scene_id: str) -> None:
        """Set the rows' scene (``""`` clears it)."""
        if self._busy_guard():
            return
        for row in rows:
            char_attach.set_scenes(self.model.job_at(row), [scene_id] if scene_id else [], self.scenes)
        self.model.refresh_all()

    def match_characters(self) -> int:
        """Attach the characters and scenes each row's prompt names."""
        changed = char_attach.match_by_name([j for j in self.jobs if not j.production_id], self.characters, self.scenes)
        log.info(tr("gen_characters_matched", count=changed))
        self.model.refresh_all()
        return changed

    def _sync_characters(self) -> None:
        for job in self.jobs:
            if job.character or job.character_refs or job.cast or job.scenes or job.scene_refs:
                char_attach.sync(job, self.characters, self.scenes)

    # ---- Production review -------------------------------------------
    @property
    def actions(self) -> ProductionActions:
        if self._actions is None:
            from src.web.flow_mcp import flow_mcp

            self._actions = ProductionActions(flow_mcp().client)  # this client starts the engine on demand
        return self._actions

    @staticmethod
    def _run_back(callback) -> None:
        callback()

    def _act(self, work, done=None, jobs=(), failed=None) -> None:
        """Run ``work`` off the GUI thread, then ``done(result)`` or the error handling on it."""
        def run() -> None:
            try:
                result = work()
            except ActionError as exc:
                error = exc
                self._action_back.emit(lambda: (failed or (lambda e: self._action_failed(e, jobs)))(error))
            else:
                if done is not None:
                    self._action_back.emit(lambda: done(result))
        threading.Thread(target=run, name="production-action", daemon=True).start()

    def _action_failed(self, error: ActionError, jobs=()) -> None:
        if error.code == "REVIEW_CONFLICT":
            for job in jobs:
                self._act(lambda j=job: self.actions.current(j), lambda item, j=job: self._show_item(j, item))
        QMessageBox.warning(self, self.page_key, tr("gen_engine_error", message=error.message))

    def _show_item(self, job: Job, item: dict | None) -> None:
        if item is not None:
            apply_item(job, item)
            self.model.refresh_job(job.id)

    def _mark_local(self, rows: list[int], mark: str) -> None:
        """A local still is decided here; the same mark again takes it back."""
        for job in map(self.model.job_at, rows):
            if job.production_id or job.status is not JobStatus.DONE:
                continue
            job.review = "" if job.review == mark else mark
            self.model.refresh_job(job.id)
            if job.review == "approved":
                self.sheet.draw_ring_on(job)

    def approve_rows(self, rows: list[int]) -> None:
        self._mark_local(rows, "approved")
        jobs = [j for j in map(self.model.job_at, rows) if j.review == "pending_review"]
        if jobs:
            self._act(lambda: self.actions.approve(jobs), jobs=jobs)

    def review_take(self, row: int, take: int, action: str, note: str = "") -> None:
        """A verdict on one named Take of a Production frame; the row changes when the engine's event returns."""
        job = self.model.job_at(row)
        if job.production_id:
            self._act(lambda: self.actions.review_take(job, take, action, note), jobs=[job])

    def reject_rows(self, rows: list[int]) -> None:
        self._mark_local(rows, "rejected")
        jobs = [j for j in map(self.model.job_at, rows)
                if j.production_id and j.review in ("pending_review", "approved")]
        if jobs:
            self._act(lambda: self.actions.reject(jobs), jobs=jobs)

    def _regenerate(self, job: Job, prompt: str | None = None) -> None:
        go = lambda: self._act(lambda: self.actions.regenerate(job, prompt), jobs=[job])  # noqa: E731
        if self.page_key != "flow_video":  # images use quota only
            go()
            return

        def confirm(reply: dict) -> None:
            text = tr("gen_regen_cost", item=job.item_id, credits=reply.get("estimated_credits"))
            if QMessageBox.question(self, self.page_key, text) == QMessageBox.StandardButton.Yes:
                go()

        def over_budget(error: ActionError) -> None:
            if error.code != "BUDGET_EXCEEDED" or "max_credits" not in error.details:
                self._action_failed(error, [job])
                return
            d = error.details
            cap = d["max_credits"] + d["credits"] - d["remaining"]
            text = tr("gen_regen_raise", item=job.item_id, credits=d["credits"], remaining=d["remaining"], cap=cap)
            if QMessageBox.question(self, self.page_key, text) != QMessageBox.StandardButton.Yes:
                return

            def raise_and_go():
                self.actions.raise_budget(d["run_id"], cap)
                return self.actions.regenerate(job, prompt)
            self._act(raise_and_go, jobs=[job])

        self._act(lambda: self.actions.regenerate(job, prompt, dry_run=True), confirm, failed=over_budget)

    def _regenerate_all(self, jobs: list[Job]) -> None:
        for job in jobs:
            if job.review in ("pending_review", "approved", "rejected") or job.status is JobStatus.FAILED:
                self._regenerate(job)

    def edit_row(self, row: int) -> None:
        job = self.model.job_at(row)
        if job.production_id:
            text, ok = QInputDialog.getMultiLineText(self, tr("gen_edit_title"), tr("gen_col_prompt"), job.prompt)
            if ok and text.strip():
                self._regenerate(job, None if text.strip() == job.prompt else text.strip())
            return
        if self._busy_guard():
            return
        text, ok = QInputDialog.getMultiLineText(self, tr("gen_edit_title"), tr("gen_col_prompt"), job.prompt)
        if ok and text.strip():
            self.model.setData(self.model.index(row, COL_PROMPT), text)

    def remove_rows(self, rows: list[int]) -> None:
        if self._busy_guard():
            return
        rows = [r for r in rows if not self.model.job_at(r).production_id]
        self.queue.forget(self.model.job_at(r) for r in rows)
        self.model.remove_rows(rows)
        self._refresh_stats()

    def clear(self) -> None:
        if self._busy_guard():
            return
        if any(j.production_id for j in self.jobs):
            self.remove_rows(list(range(len(self.jobs))))
            return
        self.queue.forget(self.jobs)
        self.model.clear()
        self._batch_folder = None
        self.stats_header.reset_clock()
        self._refresh_stats()

    def _busy_guard(self) -> bool:
        if self.queue.is_running():
            QMessageBox.information(self, self.page_key, tr("gen_busy"))
            return True
        return False

    # ---- queue -------------------------------------------------------
    def _apply_config(self) -> None:
        v = self.config_panel.values()
        self.queue.options = v
        self.queue.settings = QueueSettings(
            threads=int(v["threads"]), delay_min=float(v["delay_min"]),
            delay_max=float(v["delay_max"]), max_retries=int(v["max_retries"]),
        )

    def _base_dir(self) -> Path:
        save_dir = self.config_panel.value("save_dir")
        return Path(save_dir) if save_dir else default_save_dir(self.page_key)

    def _save(self, job: Job, files) -> list[Path]:
        folder = self._batch_folder or self._base_dir()
        return save_outputs(job, files, folder)

    def _confirm_start(self) -> int:
        """The Start button: say what the run asks for first. ``start`` itself stays unasked for the webhook."""
        if self.queue.is_running():
            return 0
        todo = [j for j in self.jobs if j.status is JobStatus.PENDING and j.origin != "agent"]
        if not todo:
            return 0
        options = self.config_panel.values()
        try:
            est = self.provider.estimate(todo, options)
        except ProviderError as exc:
            QMessageBox.warning(self, self.page_key, str(exc))
            return 0
        cost = tr(est.note) if est.note else tr("gen_start_confirm_credits", credits=est.credits)
        text = " ".join((tr("gen_start_confirm_shots", shots=est.shots), cost,
                         tr("gen_start_confirm_retries", retries=int(options.get("max_retries", 0))),
                         tr("gen_start_confirm_quote")))
        if QMessageBox.question(self, self.page_key, text) != QMessageBox.StandardButton.Yes:
            return 0
        return self.start()

    def start(self) -> int:
        if self.queue.is_running():
            return 0
        self._sync_characters()
        if self.config_panel.value("ref_dir"):
            self.match_refs()
        self._apply_config()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self._batch_folder = output_dir(self._base_dir(), self.config_panel.value("subdir_mode"), stamp)
        todo = [j for j in self.jobs if j.status is JobStatus.PENDING and j.origin != "agent"]
        if not todo:
            return 0
        self.stats_header.reset_clock()
        self.stats_header.start_clock()
        queued = self.queue.start(todo)
        log.info("Batch started: %d job(s) -> %s", queued, self._batch_folder)
        self._update_controls()
        return queued

    def retry_rows(self, rows: list[int]) -> int:
        jobs = [self.model.job_at(r) for r in rows]
        self._regenerate_all([j for j in jobs if j.production_id])
        return self._retry([j for j in jobs if not j.production_id])

    def retry_failed(self) -> int:
        self._regenerate_all([j for j in self.jobs if j.production_id and j.status is JobStatus.FAILED])
        return self._retry([j for j in self.jobs if j.status in (JobStatus.FAILED, JobStatus.STOPPED) and not j.production_id])

    def _retry(self, jobs: list[Job]) -> int:
        jobs = [j for j in jobs if j.origin != "agent"]  # a new try would spend: the agent decides
        if not jobs:
            return 0
        for job in jobs:
            job.review = ""
        self._apply_config()
        if self._batch_folder is None:
            self._batch_folder = output_dir(self._base_dir(), self.config_panel.value("subdir_mode"))
        self.stats_header.start_clock()
        n = self.queue.retry(jobs)
        self._update_controls()
        return n

    # ---- the engine's run (a Production shown on this page) -----------------
    def _engine_run(self) -> str:
        """The shown Production's run id, when the run bar acts on the engine, not the local queue."""
        if self.queue.is_running():
            return ""
        return str(self._production_run.get("runId") or "") if self._production_run.get("status") in ("running", "paused") else ""

    def accept_quote(self) -> None:
        paused = self._production_run.get("paused") or {}
        text = tr("run_accept_quote_confirm", item=paused.get("item"), old=paused.get("estimate"), new=paused.get("quoted"))
        if QMessageBox.question(self, self.page_key, text) == QMessageBox.StandardButton.Yes:
            run_id = self._engine_run()
            self._act(lambda: self.actions.resume(run_id, accept_quote=True))

    def raise_cap(self) -> None:
        credits = self._production_run.get("credits") or {}
        paused = self._production_run.get("paused") or {}
        floor = int(credits.get("spent") or 0) + int(paused.get("quoted") or 0)
        cap, ok = QInputDialog.getInt(self, self.page_key, tr("run_raise_cap_ask", max=credits.get("max"), quoted=paused.get("quoted")),
                                      max(floor, int(credits.get("max") or 0)), 0, 1_000_000)
        if ok:
            run_id = self._engine_run()
            self._act(lambda: self.actions.set_budget(run_id, cap))

    def resume_run(self) -> None:
        reason = str((self._production_run.get("paused") or {}).get("reason") or "")
        if QMessageBox.question(self, self.page_key, tr("run_resume_confirm", reason=reason.replace("_", " ")))                 == QMessageBox.StandardButton.Yes:
            run_id = self._engine_run()
            self._act(lambda: self.actions.resume(run_id))

    def cancel_rows(self, rows: list[int]) -> None:
        """Own queued frames leave the run before they start."""
        self.queue.cancel([self.model.job_at(r) for r in rows])
        self._refresh_stats()

    def toggle_pause(self) -> None:
        run_id = self._engine_run()
        if run_id:
            if self._production_run.get("status") == "paused":
                self.resume_run()
            else:
                self._act(lambda: self.actions.pause(run_id))
            return
        if self.queue.paused:
            self.queue.resume()
        else:
            self.queue.pause()
        self._update_controls()

    def stop(self) -> None:
        run_id = self._engine_run()
        if run_id:
            if QMessageBox.question(self, self.page_key, tr("run_cancel_confirm")) == QMessageBox.StandardButton.Yes:
                self._act(lambda: self.actions.cancel(run_id))
            return
        self.queue.stop()
        self._update_controls()

    def _on_job_updated(self, job_id: int) -> None:
        self.model.refresh_job(job_id)
        self._refresh_stats()
        self._save_timer.start()

    def _on_finished(self) -> None:
        if self.queue.is_running():
            return  # a retry restarted the workers in the meantime
        if self.queue.paused:
            self.queue.resume()
        self.stats_header.stop_clock()
        self._refresh_stats()
        self._update_controls()
        self.credit_meter.refresh()

    def _refresh_stats(self) -> None:
        self.stats_header.update_stats(count_statuses(self.jobs))
        for key, test in FILTERS.items():
            count = sum(1 for j in self.jobs if test(j))
            self.filter_bar.set_label(key, f"{tr(f'gen_filter_{key}')} {count}")
        self._update_controls()

    def _tab_idle(self) -> bool:
        """No job of ours or of an agent holds the Flow tab."""
        health = getattr(self.window(), "engine_health", None)
        return not self.queue.is_running() and not (health is not None and health.active)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt name
        super().showEvent(event)
        self.credit_meter.refresh()

    def _update_controls(self) -> None:
        running = self.queue.is_running()
        self.credit_meter.setVisible(self.provider.key.startswith("web_flow"))
        stats = self.stats_header.stats
        self.model.editable = not running
        for b in (self.btn_import, self.btn_paste, self.btn_match, self.btn_match_chars, self.btn_clear):
            b.setEnabled(not running)
        for b in self.empty_buttons:
            b.setEnabled(not running)
        self.btn_start.setEnabled(not running and stats.get("pending", 0) > 0)
        engine_run = bool(self._engine_run())
        held = self.queue.paused or (engine_run and self._production_run.get("status") == "paused")
        self.btn_pause.setEnabled(running or engine_run)
        self._label_run_button(self.btn_pause, tr("gen_resume") if held else tr("gen_pause"))
        self.btn_stop.setEnabled(running or engine_run)
        self.btn_retry.setEnabled(stats.get("failed", 0) + stats.get("stopped", 0) > 0)
        if not running and not self.jobs:
            for b in (self.btn_match, self.btn_match_chars, self.btn_clear):
                b.setEnabled(False)
        if self.provider_combo is not None:
            self.provider_combo.setEnabled(not running)

    # ---- output ------------------------------------------------------
    @staticmethod
    def _open(path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_output(self, row: int) -> None:
        job = self.model.job_at(row)
        if job.outputs:
            self._open(job.outputs[0])

    # ---- frames and chaining (Flow's Frames mode) ----------------------
    def animate_rows(self, rows: list[int]) -> None:
        """Each still goes to the video page as a new shot that starts on it."""
        stills = [(j.prompt, j.outputs[0]) for j in map(self.model.job_at, rows) if j.outputs]
        if stills:
            self.animate_stills.emit(stills)

    def add_frame_shots(self, stills: list[tuple[str, Path]]) -> list[Job]:
        jobs = self.model.add_jobs([Job(prompt, start_frame=Path(path)) for prompt, path in stills])
        self._refresh_stats()
        return jobs

    def _video_caps(self) -> dict:
        from src.gen.web_flow_image import capabilities
        return capabilities()["video"]

    def _clip_modes(self, job: Job) -> list[str]:
        """Extend and Edit, each only where the model that would run it offers it."""
        models = self._video_caps()["models"]
        model = shot_options(job, self.config_panel.values()).get("model")
        own = models.get(model, {}).get("modes", [])
        return [m for m in ("extend", "edit") if m in own]

    def clip_mode(self, row: int, mode: str) -> Job | None:
        """A new shot that extends or edits this clip; its cost is stated before anything is added."""
        from src.gen.web_flow_video import quote
        job = self.model.job_at(row)
        if not job.flow_url:
            return None
        o = shot_options(job, self.config_panel.values())
        model, duration, resolution = o.get("model") or "omni", int(o.get("duration", 8)), o.get("resolution") or "720p"
        try:
            credits = quote({"video": self._video_caps()}, model, duration, resolution, mode)
        except ProviderError as exc:
            QMessageBox.warning(self, self.page_key, str(exc))
            return None
        label = tr(f"gen_{mode}_cost", model=tr(f"flow_model_{model}"), resolution=resolution, duration=duration,
                   credits=credits)
        title = tr("gen_extend_title" if mode == "extend" else "gen_edit_title_clip")
        text, ok = QInputDialog.getMultiLineText(self, title, label, "")
        if not ok or not text.strip():
            return None
        shot = Job(text.strip(), video_mode=mode, source_url=job.flow_url,
                   overrides={"model": model, "duration": str(duration), "resolution": resolution, "count": 1})
        self.model.add_jobs([shot])
        self._refresh_stats()
        return shot

    def set_shot_override(self, rows: list[int], key: str, value) -> None:
        """A shot's own setting; None goes back to the page's."""
        for job in map(self.model.job_at, rows):
            if job.production_id or job.status in (JobStatus.RUNNING, JobStatus.QUEUED):
                continue
            if value is None:
                job.overrides.pop(key, None)
            else:
                job.overrides[key] = value
            self.model.refresh_job(job.id)

    def set_frame(self, row: int, which: str, path) -> None:
        """``which``: start_frame or end_frame; ``path`` None clears it."""
        job = self.model.job_at(row)
        setattr(job, which, Path(path) if path else None)
        self.model.refresh_job(job.id)

    def chain_last_frame(self, row: int) -> None:
        """The clip's last frame (free, local FFmpeg) becomes the start of the next shot, made if missing."""
        job = self.model.job_at(row)
        if not job.outputs:
            return
        from src.editor import ffmpeg
        from src.editor.stitch import resolve_ffmpeg

        def work():
            try:
                return ffmpeg.last_frame(resolve_ffmpeg(), job.outputs[0])
            except Exception as exc:  # noqa: BLE001 - shown to the owner as is
                raise ActionError("LAST_FRAME_FAILED", tr("gen_last_frame_failed", error=exc)) from None

        def done(frame: Path) -> None:
            nxt = job.index  # rows are 1-based; the next row's position is this index
            target = self.model.job_at(nxt) if nxt < self.model.rowCount() else None
            if target is not None and target.status in (JobStatus.PENDING, JobStatus.FAILED) and not target.production_id:
                target.start_frame = frame
                self.model.refresh_job(target.id)
            else:
                self.add_frame_shots([(job.prompt, frame)])

        self._act(work, done, failed=lambda e: QMessageBox.warning(self, self.page_key, e.message))

    def open_row_folder(self, row: int) -> None:
        job = self.model.job_at(row)
        if job.outputs:
            self._open(job.outputs[0].parent)

    def open_output_folder(self) -> None:
        folder = self._batch_folder if self._batch_folder and self._batch_folder.exists() else self._base_dir()
        folder.mkdir(parents=True, exist_ok=True)
        self._open(folder)

    def shutdown(self) -> None:
        """Stop workers and save the rows (window closing or project switch)."""
        self._live_timer.stop()
        if self.queue.is_running():
            self.queue.stop()
            self.queue.wait(5)
        self.save_rows()

