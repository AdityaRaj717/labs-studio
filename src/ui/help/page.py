"""Help page (Phase 15): search + topic list on the left, the rendered Markdown topic on the right."""

from __future__ import annotations

import logging

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QImageReader, QTextCharFormat, QTextCursor, QTextDocument, QTextImageFormat
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)

from src.help import topics as help_topics
from src.i18n import current_language, tr
from src.ui.kit import PAGE_MARGIN, set_icon

log = logging.getLogger(__name__)

TOPIC_ROLE = Qt.ItemDataRole.UserRole


class HelpPage(QWidget):
    def __init__(self, lang: str | None = None, root=None, parent: QWidget | None = None):
        super().__init__(parent)
        self.topics = help_topics.load_topics(lang or current_language(), root)
        self.by_id = {t.id: t for t in self.topics}
        self.current: help_topics.Topic | None = None
        self._history: list[str] = []
        self._pos = -1

        title = QLabel(tr("nav_help"))
        title.setObjectName("PageTitle")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(tr("help_search"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._filter)
        self.topic_list = QListWidget()
        self.topic_list.currentItemChanged.connect(self._on_item)
        self.result_label = QLabel()
        self.result_label.setObjectName("PageBody")

        self.topic_list.setWordWrap(True)
        self.topic_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left = QVBoxLayout()
        left.addWidget(title)
        left.addWidget(self.search_edit)
        left.addWidget(self.topic_list, 1)
        left.addWidget(self.result_label)
        left_w = QWidget()
        left_w.setLayout(left)
        left_w.setFixedWidth(240)
        left.setContentsMargins(0, 0, 0, 0)

        self.btn_back = QPushButton(tr("help_back"))
        set_icon(self.btn_back, "caret-left")
        self.btn_forward = QPushButton(tr("help_forward"))
        set_icon(self.btn_forward, "caret-right")
        self.btn_back.clicked.connect(self.back)
        self.btn_forward.clicked.connect(self.forward)
        nav = QHBoxLayout()
        nav.addWidget(self.btn_back)
        nav.addWidget(self.btn_forward)
        nav.addStretch(1)

        self.view = QTextBrowser()
        self.view.setObjectName("HelpView")
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._on_link)
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(60)
        self._fit_timer.timeout.connect(self._fit_images)
        self.view.viewport().installEventFilter(self)

        right = QVBoxLayout()
        right.addLayout(nav)
        right.addWidget(self.view, 1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(PAGE_MARGIN, 14, PAGE_MARGIN, PAGE_MARGIN)
        layout.setSpacing(16)
        layout.addWidget(left_w)
        layout.addLayout(right, 1)

        self._filter("")
        if self.topics:
            self.open_topic(self.topics[0].id)
        else:
            self.view.setPlainText(tr("help_missing", folder=str(help_topics.help_dir())))
        self._update_nav()

    # ---- topics ------------------------------------------------------
    def open_topic(self, topic_id: str, fragment: str = "", record: bool = True) -> bool:
        topic = self.by_id.get(topic_id)
        if topic is None:
            log.warning("Help topic %r not found", topic_id)
            return False
        if record:
            del self._history[self._pos + 1:]
            if not self._history or self._history[-1] != topic_id:
                self._history.append(topic_id)
            self._pos = len(self._history) - 1
        self.current = topic
        doc = self.view.document()
        doc.setBaseUrl(QUrl.fromLocalFile(str(topic.folder) + "/"))
        self.view.setSearchPaths([str(topic.folder)])
        self.view.setMarkdown(topic.text)
        self._underline_links()
        self._fit_images()
        if fragment:
            self.view.scrollToAnchor(fragment)
        self._select_in_list(topic_id)
        self._highlight()
        self._update_nav()
        return True

    def _select_in_list(self, topic_id: str) -> None:
        for i in range(self.topic_list.count()):
            item = self.topic_list.item(i)
            if item.data(TOPIC_ROLE) == topic_id:
                if self.topic_list.currentItem() is not item:
                    self.topic_list.blockSignals(True)
                    self.topic_list.setCurrentItem(item)
                    self.topic_list.blockSignals(False)
                return
        self.topic_list.clearSelection()

    def _on_item(self, item: QListWidgetItem | None, _prev=None) -> None:
        if item is not None:
            tid = item.data(TOPIC_ROLE)
            if self.current is None or tid != self.current.id:
                self.open_topic(tid)

    def _filter(self, text: str) -> None:
        found = help_topics.search(self.topics, text)
        self.topic_list.blockSignals(True)
        self.topic_list.clear()
        for t in found:
            item = QListWidgetItem(t.title)
            item.setData(TOPIC_ROLE, t.id)
            self.topic_list.addItem(item)
        self.topic_list.blockSignals(False)
        if text.strip():
            self.result_label.setText(tr("help_results", count=len(found)))
            if found and (self.current is None or self.current not in found):
                self.open_topic(found[0].id)
            elif self.current is not None:
                self._select_in_list(self.current.id)
                self._highlight()
        else:
            self.result_label.setText("")
            if self.current is not None:
                self._select_in_list(self.current.id)

    def _highlight(self) -> None:
        words = self.search_edit.text().split()
        if not words:
            return
        self.view.moveCursor(QTextCursor.MoveOperation.Start)
        self.view.find(words[0])

    # ---- links and history ------------------------------------------
    def _on_link(self, url: QUrl) -> None:
        target = url.toString()
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)
            return
        if url.isLocalFile():  # resolved against the base URL
            local = url.toLocalFile()
            target = local.rsplit("/", 1)[-1] + (f"#{url.fragment()}" if url.hasFragment() else "")
        if self.current is None:
            return
        tid, fragment = help_topics.resolve_link(self.current, target)
        if tid is None:
            log.warning("Help link not handled: %s", target)
            return
        if tid == self.current.id and fragment:
            self.view.scrollToAnchor(fragment)
        else:
            self.open_topic(tid, fragment)

    def back(self) -> None:
        if self._pos > 0:
            self._pos -= 1
            self.open_topic(self._history[self._pos], record=False)

    def forward(self) -> None:
        if self._pos < len(self._history) - 1:
            self._pos += 1
            self.open_topic(self._history[self._pos], record=False)

    def _update_nav(self) -> None:
        self.btn_back.setEnabled(self._pos > 0)
        self.btn_forward.setEnabled(self._pos < len(self._history) - 1)

    # ---- images fit the view -----------------------------------------
    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt override
        if event.type() != event.Type.Resize:
            return False
        try:
            if obj is self.view.viewport():
                self._fit_timer.start()
        except RuntimeError:  # the view is already deleted on the C++ side during teardown
            pass
        return False

    def _underline_links(self) -> None:
        """Markdown links come in coloured only; colour alone does not say "link". The H1 takes the title face."""
        doc, block = self.view.document(), self.view.document().begin()
        while block.isValid():
            if block.blockFormat().headingLevel() == 1:
                cursor = QTextCursor(block)
                cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                title = QTextCharFormat()
                title.setFontFamilies(["Bahnschrift SemiBold SemiCondensed", "Bahnschrift", "Segoe UI"])
                title.setFontPointSize(15)  # 20 px at 96 dpi
                cursor.mergeCharFormat(title)
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.charFormat().isAnchor():
                    cursor = QTextCursor(doc)
                    cursor.setPosition(frag.position())
                    cursor.setPosition(frag.position() + frag.length(), QTextCursor.MoveMode.KeepAnchor)
                    fmt = QTextCharFormat()
                    fmt.setFontUnderline(True)
                    cursor.mergeCharFormat(fmt)
                it += 1
            block = block.next()

    def _fit_images(self) -> None:
        if self.current is None:
            return
        avail = max(200, self.view.viewport().width() - 40)
        doc: QTextDocument = self.view.document()
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                fmt = frag.charFormat()
                if fmt.isImageFormat():
                    img = fmt.toImageFormat()
                    size = QImageReader(str(self.current.folder / img.name())).size()
                    if size.isValid() and size.width() > 0:
                        width = min(size.width(), avail)
                        new = QTextImageFormat(img)
                        new.setWidth(width)
                        new.setHeight(size.height() * width / size.width())
                        cur = QTextCursor(doc)
                        cur.setPosition(frag.position())
                        cur.setPosition(frag.position() + frag.length(), QTextCursor.MoveMode.KeepAnchor)
                        cur.setCharFormat(new)
                it += 1
            block = block.next()
