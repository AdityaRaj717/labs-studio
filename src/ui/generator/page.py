"""GeneratorPage: config panel + toolbar + stats header + prompt table + queue."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from src import config
from src.characters import attach as char_attach
from src.gen.importer import load_prompts, parse_text
from src.gen.models import Job, JobStatus
from src.gen.output import default_save_dir, output_dir, save_outputs
from src.gen.provider import Provider
from src.gen.queue import JobQueue, QueueSettings, count_statuses
from src.gen.refmatch import match_refs
from src.i18n import tr
from src.ui.generator.config_panel import COMMON_FIELDS, ConfigPanel
from src.ui.generator.prompt_model import COL_PROMPT, PromptTableModel
from src.ui.generator.prompt_table import PromptTable
from src.ui.generator.queue_bridge import QueueBridge
from src.ui.generator.stats_header import StatsHeader

log = logging.getLogger(__name__)


class GeneratorPage(QWidget):
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

        self.config_panel = ConfigPanel(page_key, provider.config_fields() + COMMON_FIELDS, store)
        self.model = PromptTableModel(self)
        self.table = PromptTable(self.model)
        self.stats_header = StatsHeader()
        self.bridge = QueueBridge(self)
        self.queue = JobQueue(provider, self._save, self.bridge.on_update, self.bridge.on_finished)
        self.bridge.job_updated.connect(self._on_job_updated)
        self.bridge.finished.connect(self._on_finished)

        # Left: settings in a scroll area.
        self.scroll = scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.config_panel)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedWidth(330)

        # Right: banner, toolbar, stats, table.
        right = QVBoxLayout()
        if title:
            heading = QLabel(title)
            heading.setStyleSheet("font-size: 18px; font-weight: 600;")
            right.addWidget(heading)
        self.provider_combo: QComboBox | None = None
        if len(self.providers) > 1:
            self.provider_combo = QComboBox()
            for p, _ in self.providers:
                self.provider_combo.addItem(p.name, p.key)
            pick = QHBoxLayout()
            pick.addWidget(QLabel(tr("gen_provider")))
            pick.addWidget(self.provider_combo)
            pick.addStretch(1)
            right.addLayout(pick)
        self.banner_label = QLabel(banner)
        self.banner_label.setWordWrap(True)
        self.banner_label.setObjectName("DemoBanner")
        self.banner_label.setVisible(bool(banner))
        right.addWidget(self.banner_label)

        self.btn_import = self._button("gen_import", self.import_dialog)
        self.btn_paste = self._button("gen_paste", self.paste_dialog)
        self.btn_match = self._button("gen_match_refs", self.match_refs)
        self.btn_match_chars = self._button("gen_match_characters", self.match_characters)
        self.btn_match_chars.setToolTip(tr("gen_match_characters_tip"))
        self.btn_clear = self._button("gen_clear", self.clear)
        self.btn_start = self._button("gen_start", self.start)
        self.btn_pause = self._button("gen_pause", self.toggle_pause)
        self.btn_stop = self._button("gen_stop", self.stop)
        self.btn_retry = self._button("gen_retry_failed", self.retry_failed)
        self.btn_folder = self._button("gen_open_folder", self.open_output_folder)
        self.btn_start.setObjectName("PrimaryButton")

        bar = QHBoxLayout()
        for b in (self.btn_import, self.btn_paste, self.btn_match, self.btn_match_chars, self.btn_clear):
            bar.addWidget(b)
        bar.addStretch(1)
        for b in (self.btn_start, self.btn_pause, self.btn_stop, self.btn_retry, self.btn_folder):
            bar.addWidget(b)
        right.addLayout(bar)
        right.addWidget(self.stats_header)
        right.addWidget(self.table, 1)

        layout = QHBoxLayout(self)
        layout.addWidget(scroll)
        layout.addLayout(right, 1)

        self.table.files_dropped.connect(self.import_files)
        self.table.edit_requested.connect(self.edit_row)
        self.table.retry_requested.connect(self.retry_rows)
        self.table.remove_requested.connect(self.remove_rows)
        self.table.open_output_requested.connect(self.open_output)
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
        self.load_rows()
        for sig in (self.model.rowsInserted, self.model.rowsRemoved, self.model.modelReset, self.model.dataChanged):
            sig.connect(lambda *_: self._save_timer.start())
        if self.provider_combo is not None:
            store_ = store if store is not None else config.settings()
            saved = store_.get(f"pages.{page_key}.provider", provider.key)
            self.provider_combo.setCurrentIndex(max(0, self.provider_combo.findData(saved)))
            self.provider_combo.currentIndexChanged.connect(self._on_provider_picked)
            self._on_provider_picked(self.provider_combo.currentIndex(), save=False)
        self._update_controls()

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
        self.banner_label.setText(banner)
        self.banner_label.setVisible(bool(banner))
        if provider is self.provider:
            return
        self.provider = provider
        self.queue.provider = provider
        self.config_panel = ConfigPanel(self.page_key, provider.config_fields() + COMMON_FIELDS, self._store)
        self.scroll.setWidget(self.config_panel)
        log.info("%s: provider set to %s", self.page_key, provider.name)

    def _button(self, key: str, slot) -> QPushButton:
        b = QPushButton(tr(key))
        b.clicked.connect(lambda _checked=False: slot())
        return b

    # ---- project rows (Phase 12) ---------------------------------------
    def load_rows(self) -> int:
        """Restore this page's prompt rows from the active project (if projects are on)."""
        from src import projects
        from src.projects.store import row_to_job

        self._project = projects.current()
        if self._project is None:
            return 0
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
        added = match_refs(self.jobs, folder)
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
        changed = char_attach.match_by_name(self.jobs, self.characters, self.scenes)
        log.info(tr("gen_characters_matched", count=changed))
        self.model.refresh_all()
        return changed

    def _sync_characters(self) -> None:
        for job in self.jobs:
            if job.character or job.character_refs or job.cast or job.scenes or job.scene_refs:
                char_attach.sync(job, self.characters, self.scenes)

    def edit_row(self, row: int) -> None:
        if self._busy_guard():
            return
        job = self.model.job_at(row)
        text, ok = QInputDialog.getMultiLineText(self, tr("gen_edit_title"), tr("gen_col_prompt"), job.prompt)
        if ok and text.strip():
            self.model.setData(self.model.index(row, COL_PROMPT), text)

    def remove_rows(self, rows: list[int]) -> None:
        if self._busy_guard():
            return
        self.queue.forget(self.model.job_at(r) for r in rows)
        self.model.remove_rows(rows)
        self._refresh_stats()

    def clear(self) -> None:
        if self._busy_guard():
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

    def start(self) -> int:
        if self.queue.is_running():
            return 0
        self._sync_characters()
        if self.config_panel.value("ref_dir"):
            self.match_refs()
        self._apply_config()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self._batch_folder = output_dir(self._base_dir(), self.config_panel.value("subdir_mode"), stamp)
        todo = [j for j in self.jobs if j.status is JobStatus.PENDING]
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
        return self._retry(jobs)

    def retry_failed(self) -> int:
        return self._retry([j for j in self.jobs if j.status in (JobStatus.FAILED, JobStatus.STOPPED)])

    def _retry(self, jobs: list[Job]) -> int:
        if not jobs:
            return 0
        self._apply_config()
        if self._batch_folder is None:
            self._batch_folder = output_dir(self._base_dir(), self.config_panel.value("subdir_mode"))
        self.stats_header.start_clock()
        n = self.queue.retry(jobs)
        self._update_controls()
        return n

    def toggle_pause(self) -> None:
        if self.queue.paused:
            self.queue.resume()
        else:
            self.queue.pause()
        self._update_controls()

    def stop(self) -> None:
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

    def _refresh_stats(self) -> None:
        self.stats_header.update_stats(count_statuses(self.jobs))
        self._update_controls()

    def _update_controls(self) -> None:
        running = self.queue.is_running()
        stats = self.stats_header.stats
        self.model.editable = not running
        for b in (self.btn_import, self.btn_paste, self.btn_match, self.btn_match_chars, self.btn_clear):
            b.setEnabled(not running)
        self.btn_start.setEnabled(not running and stats.get("pending", 0) > 0)
        self.btn_pause.setEnabled(running)
        self.btn_pause.setText(tr("gen_resume") if self.queue.paused else tr("gen_pause"))
        self.btn_stop.setEnabled(running)
        self.btn_retry.setEnabled(stats.get("failed", 0) + stats.get("stopped", 0) > 0)
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
        if self.queue.is_running():
            self.queue.stop()
            self.queue.wait(5)
        self.save_rows()

