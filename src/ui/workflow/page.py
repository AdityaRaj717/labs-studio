"""Workflow page: toolbar, graph view, node settings, and the runner bridge."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGraphicsView,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QPlainTextEdit,
    QPushButton, QScrollArea, QSpinBox, QSplitter, QToolButton, QVBoxLayout, QWidget,
)

from src import theme
from src.gen.provider import ConfigField
from src.i18n import tr
from src.ui.workflow.scene import NodeItem, WorkflowScene
from src.workflow.graph import Graph, GraphError
from src.workflow.registry import Registry, default_registry
from src.workflow.runner import GraphRunner, NodeStatus, RunEvent

log = logging.getLogger(__name__)


class RunnerBridge(QObject):
    """Runner events (worker thread) -> Qt signals (GUI thread)."""

    node_changed = Signal(str, object)  # node id, NodeState
    finished = Signal()

    def on_event(self, event: RunEvent) -> None:
        if event.kind == "finished":
            self.finished.emit()
        else:
            self.node_changed.emit(event.node_id, event.state)


class GraphView(QGraphicsView):
    """Wheel zooms, middle button pans, drag on empty space selects."""

    def __init__(self, scene: WorkflowScene):
        super().__init__(scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self._pan_from = None

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt override
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        scale = self.transform().m11() * factor
        if 0.25 <= scale <= 3:
            self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_from = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._pan_from is not None:
            delta = event.position() - self._pan_from
            self._pan_from = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_from = None
            self.unsetCursor()
            return
        super().mouseReleaseEvent(event)


def param_editor(field: ConfigField, value, on_change) -> QWidget:
    """One editor widget for a node setting; ``on_change(value)`` on every edit."""
    kind = field.kind
    if kind == "choice":
        w = QComboBox()
        for opt in field.options:
            w.addItem(tr(field.option_prefix + opt) if field.option_prefix else opt, opt)
        idx = w.findData(value)
        w.setCurrentIndex(idx if idx >= 0 else 0)
        w.currentIndexChanged.connect(lambda _i: on_change(w.currentData()))
        return w
    if kind == "int":
        w = QSpinBox()
        w.setRange(int(field.minimum), int(field.maximum))
        w.setValue(int(value if value is not None else field.default or 0))
        w.valueChanged.connect(on_change)
        return w
    if kind == "float":
        w = QDoubleSpinBox()
        w.setRange(field.minimum, field.maximum)
        w.setValue(float(value if value is not None else field.default or 0))
        w.valueChanged.connect(on_change)
        return w
    if kind == "bool":
        w = QCheckBox()
        w.setChecked(bool(value))
        w.toggled.connect(on_change)
        return w
    if kind == "multiline":
        w = QPlainTextEdit(str(value or ""))
        w.setMinimumHeight(110)
        w.textChanged.connect(lambda: on_change(w.toPlainText()))
        return w
    if kind in ("file", "folder"):
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(str(value or ""))
        edit.textChanged.connect(on_change)
        browse = QPushButton("…")
        browse.setFixedWidth(30)

        def pick():
            if kind == "folder":
                path = QFileDialog.getExistingDirectory(box, tr(field.label_key), edit.text())
            else:
                path, _ = QFileDialog.getOpenFileName(
                    box, tr(field.label_key), edit.text(),
                    "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp);;All files (*)")
            if path:
                edit.setText(path)

        browse.clicked.connect(pick)
        row.addWidget(edit, 1)
        row.addWidget(browse)
        box.edit = edit
        return box
    w = QLineEdit(str(value if value is not None else ""))
    w.textChanged.connect(on_change)
    return w


class Inspector(QWidget):
    """Settings and outputs of the selected node."""

    edited = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.item: NodeItem | None = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 10, 10, 10)
        self.heading = QLabel()
        self.heading.setStyleSheet("font-size: 15px; font-weight: 600;")
        self.heading.setWordWrap(True)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f"color: {theme.COLORS[theme.current_mode()]['text_muted']};")
        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        self.form.setContentsMargins(0, 6, 0, 6)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #e5534b;")
        self.outputs = QListWidget()
        self.outputs.setMaximumHeight(140)
        self.outputs.itemDoubleClicked.connect(
            lambda it: QDesktopServices.openUrl(QUrl.fromLocalFile(it.data(Qt.ItemDataRole.UserRole))))
        self.outputs_label = QLabel(tr("wf_outputs"))
        for w in (self.heading, self.hint, self.form_host, self.error, self.outputs_label, self.outputs):
            self._layout.addWidget(w)
        self._layout.addStretch(1)
        self.show_item(None)

    def show_item(self, item: NodeItem | None) -> None:
        self.item = item
        while self.form.rowCount():
            self.form.removeRow(0)
        if item is None:
            self.heading.setText(tr("wf_inspector_none"))
            self.hint.setText(tr("wf_help"))
            for w in (self.error, self.outputs_label, self.outputs):
                w.hide()
            return
        node = item.node
        self.heading.setText(item.title())
        self.hint.setText(tr(item.node_type.description_key) if item.node_type.description_key else "")
        title = QLineEdit(node.title)
        title.setPlaceholderText(tr(item.node_type.label_key))
        title.textChanged.connect(lambda t: self._set_title(t))
        self.form.addRow(tr("wf_node_title"), title)
        for field in item.node_type.fields():
            editor = param_editor(field, node.params.get(field.key, field.default),
                                  lambda v, k=field.key: self._set_param(k, v))
            self.form.addRow(tr(field.label_key), editor)
        self.refresh_state()

    def refresh_state(self) -> None:
        item = self.item
        if item is None:
            return
        state = item.state
        self.error.setText(state.error)
        self.error.setVisible(bool(state.error) and state.status is NodeStatus.FAILED)
        self.outputs.clear()
        for port, value in state.outputs.items():
            values = value if isinstance(value, list) else [value]
            for v in values:
                text = str(v)
                entry = QListWidgetItem(f"{port}: {Path(text).name if isinstance(v, Path) else text}")
                if isinstance(v, Path):
                    entry.setData(Qt.ItemDataRole.UserRole, str(v))
                    entry.setToolTip(str(v))
                self.outputs.addItem(entry)
        has = self.outputs.count() > 0
        self.outputs_label.setVisible(has)
        self.outputs.setVisible(has)

    def _set_param(self, key: str, value) -> None:
        if self.item is not None:
            self.item.node.params[key] = value
            self.item.update()
            self.edited.emit()

    def _set_title(self, text: str) -> None:
        if self.item is not None:
            self.item.node.title = text.strip()
            self.heading.setText(self.item.title())
            self.item.update()
            self.edited.emit()


class WorkflowPage(QWidget):
    def __init__(self, registry: Registry | None = None, data_dir: Path | str | None = None,
                 out_dir: Path | str | None = None, parent=None):
        super().__init__(parent)
        from src.config import app_data_dir
        from src.gen.output import default_save_dir

        self.registry = registry or default_registry()
        self.data_dir = Path(data_dir) if data_dir else app_data_dir() / "workflows"
        self.out_dir = Path(out_dir) if out_dir else default_save_dir("workflow")
        self.autosave_path = self.data_dir / "autosave.json"
        self.file_path: Path | None = None
        self.runner: GraphRunner | None = None

        self.scene = WorkflowScene(self._initial_graph(), self)
        self.view = GraphView(self.scene)
        self.inspector = Inspector()
        self.bridge = RunnerBridge(self)
        self.bridge.node_changed.connect(self._on_node_changed)
        self.bridge.finished.connect(self._on_finished)
        self.scene.selectionChanged.connect(self._on_selection)
        self.scene.graph_changed.connect(self._schedule_autosave)
        self.scene.message.connect(self._show_message)
        self.inspector.edited.connect(self._schedule_autosave)

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(600)
        self._autosave_timer.timeout.connect(self.autosave)

        heading = QLabel(tr("nav_workflow"))
        heading.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.btn_add = QToolButton()
        self.btn_add.setText(tr("wf_add_node"))
        self.btn_add.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_add.setMenu(self._build_add_menu())
        self.btn_run = self._button("wf_run", self.run)
        self.btn_run.setObjectName("PrimaryButton")
        self.btn_stop = self._button("wf_stop", self.stop)
        self.btn_stop.setEnabled(False)
        self.btn_new = self._button("wf_new", self.new_graph)
        self.btn_open = self._button("wf_open", self.open_dialog)
        self.btn_save = self._button("wf_save", self.save_dialog)
        self.btn_folder = self._button("wf_open_folder", self.open_output_folder)
        self.status = QLabel()

        bar = QHBoxLayout()
        bar.addWidget(heading)
        bar.addSpacing(12)
        for w in (self.btn_add, self.btn_run, self.btn_stop, self.btn_new, self.btn_open,
                  self.btn_save, self.btn_folder):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(self.status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.inspector)
        scroll.setMinimumWidth(280)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.view)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 1)
        splitter.setSizes([900, 320])

        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(splitter, 1)

        delete = QAction(self)
        delete.setShortcuts([QKeySequence.StandardKey.Delete, QKeySequence(Qt.Key.Key_Backspace)])
        delete.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        delete.triggered.connect(self.delete_selected)
        self.view.addAction(delete)
        QTimer.singleShot(0, self.fit)

    # ---- setup -------------------------------------------------------
    def _button(self, key: str, slot) -> QPushButton:
        btn = QPushButton(tr(key))
        btn.clicked.connect(slot)
        return btn

    def _build_add_menu(self) -> QMenu:
        menu = QMenu(self)
        for category, types in self.registry.categories().items():
            sub = menu.addMenu(tr(category))
            for t in types:
                action = sub.addAction(tr(t.label_key))
                action.triggered.connect(lambda _c=False, tid=t.type_id: self.add_node_at_center(tid))
        return menu

    def _initial_graph(self) -> Graph:
        if self.autosave_path.is_file():
            try:
                return Graph.load(self.autosave_path, self.registry)
            except GraphError as exc:
                log.warning("Workflow autosave not loaded: %s", exc)
        return starter_graph(self.registry)

    # ---- editing -----------------------------------------------------
    def add_node_at_center(self, type_id: str) -> NodeItem:
        center = self.view.mapToScene(self.view.viewport().rect().center())
        offset = 24 * (len(self.scene.node_items) % 6)
        item = self.scene.add_node(type_id, (center.x() - 100 + offset, center.y() - 40 + offset))
        self.scene.clearSelection()
        item.setSelected(True)
        return item

    def delete_selected(self) -> None:
        if self._busy():
            return
        self.inspector.show_item(None)
        self.scene.remove_selected()

    def new_graph(self) -> None:
        if self._busy():
            return
        self.file_path = None
        self._set_graph(Graph(self.registry))

    def _set_graph(self, graph: Graph) -> None:
        self.inspector.show_item(None)
        self.scene.set_graph(graph)
        self._schedule_autosave()
        self.fit()

    def fit(self) -> None:
        rect = self.scene.itemsBoundingRect()
        if rect.isEmpty():
            return
        self.view.fitInView(rect.adjusted(-60, -60, 60, 60), Qt.AspectRatioMode.KeepAspectRatio)
        if self.view.transform().m11() > 1:
            self.view.resetTransform()
            self.view.centerOn(rect.center())

    # ---- files -------------------------------------------------------
    def save(self, path: Path | str) -> None:
        self.scene.graph.save(path)
        self.file_path = Path(path)
        self._show_message(tr("wf_saved", name=self.file_path.name))

    def load(self, path: Path | str) -> bool:
        if self._busy():
            return False
        try:
            graph = Graph.load(path, self.registry)
        except GraphError as exc:
            self._show_message(str(exc))
            return False
        self.file_path = Path(path)
        self._set_graph(graph)
        self._show_message(tr("wf_loaded", name=self.file_path.name))
        return True

    def save_dialog(self) -> None:
        start = str(self.file_path or self.data_dir / "workflow.json")
        path, _ = QFileDialog.getSaveFileName(self, tr("wf_save"), start, "Workflow (*.json)")
        if path:
            self.save(path)

    def open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("wf_open"), str(self.data_dir),
                                              "Workflow (*.json)")
        if path:
            self.load(path)

    def _schedule_autosave(self) -> None:
        self._autosave_timer.start()

    def autosave(self) -> None:
        try:
            self.scene.graph.save(self.autosave_path)
        except OSError as exc:
            log.warning("Workflow autosave failed: %s", exc)

    def open_output_folder(self) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.out_dir)))

    # ---- running -----------------------------------------------------
    def _busy(self) -> bool:
        if self.runner is not None and self.runner.is_running():
            self._show_message(tr("wf_busy"))
            return True
        return False

    def run(self) -> bool:
        if self._busy():
            return False
        if not self.scene.graph.nodes:
            self._show_message(tr("wf_empty"))
            return False
        self.scene.reset_states()
        self.inspector.refresh_state()
        self.runner = GraphRunner(self.scene.graph, self.out_dir, self.bridge.on_event)
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._show_message(tr("wf_running"))
        self.runner.start()
        return True

    def stop(self) -> None:
        if self.runner is not None:
            self.runner.stop()

    def is_running(self) -> bool:
        return self.runner is not None and self.runner.is_running()

    def _on_node_changed(self, node_id: str, state) -> None:
        self.scene.set_node_state(node_id, state)
        if self.inspector.item is not None and self.inspector.item.node.id == node_id:
            self.inspector.refresh_state()

    def _on_finished(self) -> None:
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        states = self.runner.states.values() if self.runner else []
        done = sum(s.status is NodeStatus.DONE for s in states)
        failed = sum(s.status is NodeStatus.FAILED for s in states)
        self._show_message(tr("wf_finished", done=done, failed=failed))

    def _on_selection(self) -> None:
        self.inspector.show_item(self.scene.selected_node())

    def _show_message(self, text: str) -> None:
        self.status.setText(text)
        log.info("Workflow: %s", text)

    def shutdown(self) -> None:
        self._autosave_timer.stop()
        self.autosave()
        if self.runner is not None:
            self.runner.stop()
            self.runner.wait(2.0)


def starter_graph(registry: Registry) -> Graph:
    """prompt → image → video with the offline demo nodes, so Run works without a key."""
    graph = Graph(registry)
    prompt = graph.add_node("prompt", {"text": "a red fox in a snowy forest, golden hour"}, (-380, -40))
    image = graph.add_node("demo.image", None, (-100, -40))
    video = graph.add_node("demo.video", None, (180, -40))
    graph.connect(prompt.id, "text", image.id, "prompt")
    graph.connect(prompt.id, "text", video.id, "prompt")
    graph.connect(image.id, "image", video.id, "start")
    return graph
