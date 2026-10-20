"""Video Cut page: Slicer and Frame extractor tabs, both on ffmpeg."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from src.gen.provider import ConfigField
from src.i18n import tr
from src.tools import ffmpeg
from src.tools.tasks import FrameExtractorProvider, SlicerProvider
from src.ui.tools.tool_page import ToolPage

SLICER_FIELDS = [
    ConfigField("slice_mode", "cut_slice_mode", "choice", "duration", list(ffmpeg.SLICE_MODES),
                option_prefix="cut_mode_"),
    ConfigField("segment_seconds", "cut_segment_seconds", "float", 10.0, minimum=0.5, maximum=36000),
    ConfigField("parts", "cut_parts", "int", 2, minimum=1, maximum=500),
    ConfigField("ranges", "cut_ranges", "text", ""),
    ConfigField("encode", "cut_encode", "choice", "copy", list(ffmpeg.ENCODE_MODES),
                option_prefix="cut_encode_"),
    ConfigField("crf", "cut_crf", "int", 18, minimum=0, maximum=51),
]
SLICER_VISIBLE = {
    "segment_seconds": ("slice_mode", ("duration",)),
    "parts": ("slice_mode", ("parts",)),
    "ranges": ("slice_mode", ("ranges",)),
    "crf": ("encode", ("reencode",)),
}

FRAME_FIELDS = [
    ConfigField("frame_mode", "frames_mode", "choice", "interval", list(ffmpeg.FRAME_MODES),
                option_prefix="frames_mode_"),
    ConfigField("interval", "frames_interval", "float", 1.0, minimum=0.1, maximum=3600),
    ConfigField("frame_count", "frames_count", "int", 10, minimum=1, maximum=1000),
    ConfigField("timestamps", "frames_timestamps", "text", ""),
    ConfigField("frame_format", "frames_format", "choice", "png", list(ffmpeg.FRAME_FORMATS)),
    ConfigField("jpg_quality", "frames_jpg_quality", "int", 92, minimum=1, maximum=100),
]
FRAME_VISIBLE = {
    "interval": ("frame_mode", ("interval",)),
    "frame_count": ("frame_mode", ("count",)),
    "timestamps": ("frame_mode", ("times",)),
    "jpg_quality": ("frame_format", ("jpg",)),
}


class VideoCutPage(QWidget):
    def __init__(self, store=None, slicer: SlicerProvider | None = None,
                 extractor: FrameExtractorProvider | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.slicer = ToolPage(
            "video_cut", slicer or SlicerProvider(store), SLICER_FIELDS, ffmpeg.VIDEO_EXTS,
            intro=tr("cut_slicer_intro"), visible_when=SLICER_VISIBLE, store=store)
        self.frames = ToolPage(
            "frame_extractor", extractor or FrameExtractorProvider(store), FRAME_FIELDS,
            ffmpeg.VIDEO_EXTS, intro=tr("frames_intro"), visible_when=FRAME_VISIBLE, store=store)

        title = QLabel(tr("nav_video_cut"))
        title.setObjectName("PageTitle")
        self.tabs = QTabWidget()
        self.tabs.addTab(self.slicer, tr("cut_tab_slicer"))
        self.tabs.addTab(self.frames, tr("cut_tab_frames"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.addWidget(title)
        layout.addWidget(self.tabs, 1)

    def shutdown(self) -> None:
        self.slicer.shutdown()
        self.frames.shutdown()
