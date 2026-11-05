"""ConfigPanel: a form built from ConfigField lists, saved per page in settings."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit,
    QPushButton, QSpinBox, QWidget,
)

from src import config
from src.gen.importer import MODES as IMPORT_MODES
from src.gen.output import SUBDIR_MODES
from src.gen.provider import ConfigField
from src.i18n import tr
from src.ui import kit

COMMON_FIELDS: list[ConfigField] = [
    ConfigField("count", "gen_count", "int", 1, minimum=1, maximum=8),
    ConfigField("threads", "gen_threads", "int", 2, minimum=1, maximum=8),
    ConfigField("delay_min", "gen_delay_min", "float", 1.0, minimum=0, maximum=600),
    ConfigField("delay_max", "gen_delay_max", "float", 3.0, minimum=0, maximum=600),
    ConfigField("max_retries", "gen_retries", "int", 1, minimum=0, maximum=5),
    ConfigField("save_dir", "gen_save_dir", "folder", ""),
    ConfigField("subdir_mode", "gen_subdir_mode", "choice", "date", list(SUBDIR_MODES),
                option_prefix="subdir_"),
    ConfigField("ref_dir", "gen_ref_dir", "folder", ""),
    ConfigField("import_mode", "gen_import_mode", "choice", "auto", list(IMPORT_MODES),
                option_prefix="import_"),
]


def fields_for(provider) -> list[ConfigField]:
    """The provider's fields plus the common ones, with Count capped at what the provider takes."""
    common = [replace(f, maximum=provider.max_count) if f.key == "count" else f for f in COMMON_FIELDS]
    return provider.config_fields() + common


class FolderEdit(QWidget):
    changed = Signal(str)

    def __init__(self, value: str, placeholder: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.edit = QLineEdit(value)
        self.edit.setPlaceholderText(placeholder)
        browse = QPushButton(tr("gen_browse"))
        browse.clicked.connect(self._browse)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit, 1)
        layout.addWidget(browse)
        self.edit.editingFinished.connect(lambda: self.changed.emit(self.edit.text().strip()))

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("gen_browse"), self.edit.text())
        if folder:
            self.edit.setText(folder)
            self.changed.emit(folder)

    def text(self) -> str:
        return self.edit.text().strip()


class ConfigPanel(QWidget):
    """Form for ``fields``; each value lives at ``pages.<page_key>.<field.key>``."""

    changed = Signal(str, object)

    def __init__(self, page_key: str, fields: list[ConfigField], store=None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.page_key = page_key
        self.fields = {f.key: f for f in fields}
        self.store = store if store is not None else config.settings()
        self._values: dict[str, Any] = {}
        self.editors: dict[str, QWidget] = {}

        form = kit.label_column(QFormLayout(self))
        form.setContentsMargins(0, 0, 8, 8)
        form.setVerticalSpacing(5)
        for f in fields:
            if f.depends_on:
                f = self.fields[f.key] = replace(f, options=self._options(f))
            value = self.store.get(self._path(f.key), f.default)
            if f.kind == "choice" and value not in f.options and f.options:
                value = f.default if f.default in f.options else f.options[0]
            self._values[f.key] = value
            editor = self._make_editor(f, value)
            self.editors[f.key] = editor
            form.addRow(kit.column_label(tr(f.label_key)), editor)

    def _options(self, f: ConfigField) -> list[str]:
        return f.options_by.get(self._values.get(f.depends_on), f.options)

    def _refill(self, f: ConfigField) -> None:
        """A choice whose options follow another field: keep the value if still offered."""
        options = self._options(f)
        self.fields[f.key] = f = replace(f, options=options)
        w = self.editors[f.key]
        w.blockSignals(True)
        w.clear()
        for opt in options:
            w.addItem(tr(f.option_prefix + opt) if f.option_prefix else opt, opt)
        w.blockSignals(False)
        value = self._values[f.key]
        if value not in options and options:
            value = f.default if f.default in options else options[0]
        self.set_value(f.key, value)

    def _path(self, key: str) -> str:
        return f"pages.{self.page_key}.{key}"

    def _make_editor(self, f: ConfigField, value: Any) -> QWidget:
        def commit(v: Any, key: str = f.key) -> None:
            self.set_value(key, v, update_editor=False)

        if f.kind == "choice":
            w = kit.fit_combo(QComboBox())
            for opt in f.options:
                w.addItem(tr(f.option_prefix + opt) if f.option_prefix else opt, opt)
            w.setCurrentIndex(max(0, w.findData(value)))
            w.currentIndexChanged.connect(lambda _i, w=w: commit(w.currentData()))
        elif f.kind == "int":
            w = QSpinBox()
            w.setRange(int(f.minimum), int(f.maximum))
            w.setValue(int(value))
            w.valueChanged.connect(commit)
        elif f.kind == "float":
            w = QDoubleSpinBox()
            w.setRange(float(f.minimum), float(f.maximum))
            w.setDecimals(1)
            w.setSingleStep(0.5)
            w.setValue(float(value))
            w.valueChanged.connect(commit)
        elif f.kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(value))
            w.toggled.connect(commit)
        elif f.kind == "folder":
            hint = tr("gen_save_dir_hint") if f.key == "save_dir" else ""
            w = FolderEdit(str(value or ""), hint)
            w.changed.connect(commit)
        else:
            w = QLineEdit(str(value or ""))
            w.editingFinished.connect(lambda w=w: commit(w.text()))
        return w

    def value(self, key: str) -> Any:
        return self._values[key]

    def values(self) -> dict[str, Any]:
        return dict(self._values)

    def set_value(self, key: str, value: Any, update_editor: bool = True) -> None:
        self._values[key] = value
        self.store.set(self._path(key), value)
        if update_editor:
            w = self.editors[key]
            w.blockSignals(True)
            if isinstance(w, QComboBox):
                w.setCurrentIndex(max(0, w.findData(value)))
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                w.setValue(value)
            elif isinstance(w, QCheckBox):
                w.setChecked(bool(value))
            elif isinstance(w, FolderEdit):
                w.edit.setText(str(value))
            elif isinstance(w, QLineEdit):
                w.setText(str(value))
            w.blockSignals(False)
        self.changed.emit(key, value)
        for f in list(self.fields.values()):
            if f.depends_on == key:
                self._refill(f)
