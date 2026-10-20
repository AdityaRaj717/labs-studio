"""Image Upscaler page: Real-ESRGAN (ncnn-vulkan) with a before/after compare dialog."""

from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QWidget

from src.gen.models import JobStatus
from src.gen.provider import ConfigField
from src.i18n import tr
from src.tools import realesrgan
from src.tools.tasks import UpscaleProvider
from src.ui.tools.compare import CompareDialog
from src.ui.tools.tool_page import ToolPage

UPSCALE_FIELDS = [
    ConfigField("model", "up_model", "choice", "realesrgan-x4plus", list(realesrgan.MODELS),
                option_prefix="up_model_"),
    ConfigField("scale", "up_scale", "choice", "4", ["2", "3", "4"]),
    ConfigField("out_format", "up_format", "choice", "png", list(realesrgan.OUTPUT_FORMATS)),
    ConfigField("tile", "up_tile", "int", 0, minimum=0, maximum=2048),
    ConfigField("tta", "up_tta", "bool", False),
]
UPSCALE_VISIBLE = {"scale": ("model", ("realesr-animevideov3",))}


class UpscalerPage(ToolPage):
    def __init__(self, store=None, provider: UpscaleProvider | None = None,
                 parent: QWidget | None = None):
        super().__init__("upscaler", provider or UpscaleProvider(store), UPSCALE_FIELDS,
                         realesrgan.IMAGE_EXTS, title=tr("nav_upscaler"), intro=tr("up_intro"),
                         visible_when=UPSCALE_VISIBLE, store=store, parent=parent)
        self.btn_compare = QPushButton(tr("up_compare"))
        self.btn_compare.clicked.connect(self.compare_selected)
        self.toolbar.insertWidget(self.toolbar.indexOf(self.btn_start), self.btn_compare)
        self.table.itemSelectionChanged.connect(self._update_compare)
        self.bridge.job_updated.connect(lambda _id: self._update_compare())
        self._update_compare()

    def _selected_done(self):
        rows = self.selected_rows()
        if len(rows) != 1:
            return None
        job = self.jobs[rows[0]]
        return job if job.status is JobStatus.DONE and job.outputs else None

    def _update_compare(self) -> None:
        if hasattr(self, "btn_compare"):
            self.btn_compare.setEnabled(self._selected_done() is not None)

    def compare_dialog(self, row: int) -> CompareDialog | None:
        job = self.jobs[row]
        if job.status is not JobStatus.DONE or not job.outputs:
            return None
        return CompareDialog(job.refs[0], job.outputs[0], self)

    def compare_selected(self) -> None:
        rows = self.selected_rows()
        if len(rows) == 1:
            dlg = self.compare_dialog(rows[0])
            if dlg is not None:
                dlg.exec()

    def _on_double_click(self, row: int, col: int) -> None:
        # A finished row opens the compare dialog; anything else falls back to the base behaviour.
        dlg = self.compare_dialog(row)
        if dlg is not None:
            dlg.exec()
        else:
            super()._on_double_click(row, col)
