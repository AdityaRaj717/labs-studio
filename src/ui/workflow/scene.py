"""Graph scene: node boxes with typed ports, curved connections, drag to connect.

The scene owns a ``Graph`` and keeps it in step with the items: moving,
adding, deleting and connecting go through here so the model never drifts.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsEllipseItem, QGraphicsItem, QGraphicsObject, QGraphicsPathItem, QGraphicsScene,
)

from src import theme
from src.i18n import tr
from src.workflow.graph import Edge, Graph, GraphError, Node
from src.workflow.registry import ANY, IMAGE, TEXT, VIDEO, Port
from src.workflow.runner import NodeState, NodeStatus

NODE_W = 210
HEADER_H = 26
ROW_H = 22
PORT_R = 6
FOOTER_H = 22
THUMB_H = 72

PORT_COLORS = {TEXT: "#e0b04a", IMAGE: "#4fb6ff", VIDEO: "#c56cf0", ANY: "#9aa3ad"}
STATUS_COLORS = {
    NodeStatus.PENDING: None, NodeStatus.RUNNING: "#4f8cff", NodeStatus.DONE: "#3fb27f",
    NodeStatus.FAILED: "#e5534b", NodeStatus.SKIPPED: "#8b919c", NodeStatus.STOPPED: "#d29922",
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def _c(token: str) -> QColor:
    return QColor(theme.COLORS[theme.current_mode()][token])


class PortItem(QGraphicsEllipseItem):
    def __init__(self, node_item: NodeItem, port: Port, is_output: bool):
        super().__init__(-PORT_R, -PORT_R, PORT_R * 2, PORT_R * 2, node_item)
        self.node_item = node_item
        self.port = port
        self.is_output = is_output
        color = QColor(PORT_COLORS.get(port.type, PORT_COLORS[ANY]))
        self.setBrush(QBrush(color if port.required or is_output else _c("panel")))
        self.setPen(QPen(color, 2))
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setToolTip(f"{tr(port.label_key) if port.label_key else port.name} ({port.type})")
        self.setAcceptHoverEvents(True)
        self.setZValue(2)

    def scene_center(self) -> QPointF:
        return self.mapToScene(QPointF(0, 0))


class EdgeItem(QGraphicsPathItem):
    def __init__(self, edge: Edge, src: PortItem, dst: PortItem):
        super().__init__()
        self.edge = edge
        self.src = src
        self.dst = dst
        self.setZValue(-1)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.update_path()

    def update_path(self) -> None:
        self.setPath(curve(self.src.scene_center(), self.dst.scene_center()))
        color = QColor(PORT_COLORS.get(self.src.port.type, PORT_COLORS[ANY]))
        self.setPen(QPen(_c("accent") if self.isSelected() else color, 3 if self.isSelected() else 2))

    def itemChange(self, change, value):  # noqa: N802 - Qt override
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self.update_path()
        return super().itemChange(change, value)


def curve(a: QPointF, b: QPointF) -> QPainterPath:
    path = QPainterPath(a)
    dx = max(40.0, abs(b.x() - a.x()) * 0.5)
    path.cubicTo(QPointF(a.x() + dx, a.y()), QPointF(b.x() - dx, b.y()), b)
    return path


class NodeItem(QGraphicsObject):
    def __init__(self, node: Node, scene: WorkflowScene):
        super().__init__()
        self.node = node
        self.wf_scene = scene
        self.node_type = scene.graph.registry.get(node.type_id)
        self.state = NodeState()
        self._thumb: QPixmap | None = None
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                      | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                      | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setPos(QPointF(*node.pos))
        rows = max(len(self.node_type.inputs), len(self.node_type.outputs), 1)
        self._body_h = HEADER_H + rows * ROW_H + 6
        self.inputs: dict[str, PortItem] = {}
        self.outputs: dict[str, PortItem] = {}
        for i, port in enumerate(self.node_type.inputs):
            item = PortItem(self, port, False)
            item.setPos(0, HEADER_H + i * ROW_H + ROW_H / 2)
            self.inputs[port.name] = item
        for i, port in enumerate(self.node_type.outputs):
            item = PortItem(self, port, True)
            item.setPos(NODE_W, HEADER_H + i * ROW_H + ROW_H / 2)
            self.outputs[port.name] = item

    def title(self) -> str:
        return self.node.title or tr(self.node_type.label_key)

    def height(self) -> float:
        return self._body_h + (THUMB_H if self._thumb else 0) + FOOTER_H

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt override
        return QRectF(-PORT_R - 2, -2, NODE_W + 2 * PORT_R + 4, self.height() + 4)

    def set_state(self, state: NodeState) -> None:
        self.prepareGeometryChange()
        self.state = state
        self._thumb = None
        if state.status is NodeStatus.DONE:
            for value in state.outputs.values():
                files = value if isinstance(value, list) else []
                pic = next((Path(f) for f in files if Path(f).suffix.lower() in IMAGE_EXTS), None)
                if pic is not None:
                    pix = QPixmap(str(pic))
                    if not pix.isNull():
                        self._thumb = pix.scaled(NODE_W - 16, THUMB_H,
                                                 Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation)
                    break
        self.setToolTip(state.error)
        self.update()

    def summary(self) -> str:
        if self.state.status is NodeStatus.FAILED and self.state.error:
            return self.state.error
        if self.state.status is NodeStatus.RUNNING:
            return f"{tr('wf_status_running')} {int(self.state.progress * 100)}%"
        if self.state.status is not NodeStatus.PENDING:
            return tr(f"wf_status_{self.state.status.value}")
        text = self.node.params.get("text") or self.node.params.get("path") or ""
        return str(text).replace("\n", " ")

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, NODE_W, self.height())
        status_color = STATUS_COLORS.get(self.state.status)
        border = _c("accent") if self.isSelected() else QColor(status_color or _c("border"))
        painter.setPen(QPen(border, 2 if self.isSelected() or status_color else 1))
        painter.setBrush(_c("panel"))
        painter.drawRoundedRect(rect, 7, 7)

        header = QPainterPath()
        header.addRoundedRect(QRectF(0, 0, NODE_W, HEADER_H), 7, 7)
        header.addRect(QRectF(0, HEADER_H / 2, NODE_W, HEADER_H / 2))
        painter.fillPath(header, _c("hover"))
        font = QFont(painter.font())
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(_c("text"))
        painter.drawText(QRectF(10, 0, NODE_W - 20, HEADER_H),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         painter.fontMetrics().elidedText(self.title(), Qt.TextElideMode.ElideRight,
                                                          NODE_W - 20))
        font.setBold(False)
        painter.setFont(font)

        painter.setPen(_c("text_muted"))
        for name, item in self.inputs.items():
            label = tr(item.port.label_key) if item.port.label_key else name
            painter.drawText(QRectF(12, item.y() - ROW_H / 2, NODE_W / 2, ROW_H),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
        for name, item in self.outputs.items():
            label = tr(item.port.label_key) if item.port.label_key else name
            painter.drawText(QRectF(NODE_W / 2 - 12, item.y() - ROW_H / 2, NODE_W / 2, ROW_H),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, label)

        y = self._body_h
        if self._thumb:
            painter.drawPixmap(QPointF((NODE_W - self._thumb.width()) / 2, y + 2), self._thumb)
            y += THUMB_H
        if self.state.status is NodeStatus.RUNNING:
            bar = QRectF(8, y + 2, (NODE_W - 16) * self.state.progress, 3)
            painter.fillRect(bar, QColor(STATUS_COLORS[NodeStatus.RUNNING]))
        painter.setPen(QColor(status_color) if status_color else _c("text_muted"))
        painter.drawText(QRectF(8, y + 4, NODE_W - 16, FOOTER_H - 4),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         painter.fontMetrics().elidedText(self.summary(), Qt.TextElideMode.ElideRight,
                                                          NODE_W - 16))

    def itemChange(self, change, value):  # noqa: N802 - Qt override
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.node.pos = (self.pos().x(), self.pos().y())
            self.wf_scene.update_edges(self.node.id)
            self.wf_scene.changed_graph()
        return super().itemChange(change, value)


class WorkflowScene(QGraphicsScene):
    graph_changed = Signal()
    message = Signal(str)

    def __init__(self, graph: Graph, parent=None):
        super().__init__(parent)
        self.graph = graph
        self.node_items: dict[str, NodeItem] = {}
        self.edge_items: list[EdgeItem] = []
        self._drag_from: PortItem | None = None
        self._drag_line: QGraphicsPathItem | None = None
        self._loading = False
        self.setSceneRect(-4000, -4000, 8000, 8000)
        self.setBackgroundBrush(_c("bg"))
        self.set_graph(graph)

    # ---- model <-> items ---------------------------------------------
    def set_graph(self, graph: Graph) -> None:
        self._loading = True
        self.clear()
        self.node_items.clear()
        self.edge_items.clear()
        self._drag_line = None
        self.graph = graph
        for node in graph.nodes.values():
            self._add_item(node)
        for edge in graph.edges:
            self._add_edge_item(edge)
        self._loading = False

    def _add_item(self, node: Node) -> NodeItem:
        item = NodeItem(node, self)
        self.addItem(item)
        self.node_items[node.id] = item
        return item

    def _add_edge_item(self, edge: Edge) -> EdgeItem:
        src = self.node_items[edge.src].outputs[edge.src_port]
        dst = self.node_items[edge.dst].inputs[edge.dst_port]
        item = EdgeItem(edge, src, dst)
        self.addItem(item)
        self.edge_items.append(item)
        return item

    def add_node(self, type_id: str, pos: tuple[float, float] = (0, 0),
                 params: dict | None = None) -> NodeItem:
        node = self.graph.add_node(type_id, params, pos)
        item = self._add_item(node)
        self.changed_graph()
        return item

    def connect_ports(self, src: str, src_port: str, dst: str, dst_port: str) -> bool:
        try:
            edge = self.graph.connect(src, src_port, dst, dst_port)
        except GraphError as exc:
            self.message.emit(str(exc))
            return False
        self._sync_edges()
        self.changed_graph()
        return edge in self.graph.edges

    def remove_selected(self) -> None:
        for item in self.selectedItems():
            if isinstance(item, EdgeItem):
                self.graph.disconnect(item.edge)
        for item in self.selectedItems():
            if isinstance(item, NodeItem):
                self.graph.remove_node(item.node.id)
                self.node_items.pop(item.node.id, None)
                self.removeItem(item)
        self._sync_edges()
        self.changed_graph()

    def _sync_edges(self) -> None:
        for item in self.edge_items:
            self.removeItem(item)
        self.edge_items.clear()
        for edge in self.graph.edges:
            self._add_edge_item(edge)

    def update_edges(self, node_id: str) -> None:
        for item in self.edge_items:
            if node_id in (item.edge.src, item.edge.dst):
                item.update_path()

    def changed_graph(self) -> None:
        if not self._loading:
            self.graph_changed.emit()

    def set_node_state(self, node_id: str, state: NodeState) -> None:
        item = self.node_items.get(node_id)
        if item is not None:
            item.set_state(state)
            self.update_edges(node_id)

    def reset_states(self) -> None:
        for item in self.node_items.values():
            item.set_state(NodeState())

    def selected_node(self) -> NodeItem | None:
        nodes = [i for i in self.selectedItems() if isinstance(i, NodeItem)]
        return nodes[0] if len(nodes) == 1 else None

    # ---- drag to connect ---------------------------------------------
    def _port_at(self, pos: QPointF) -> PortItem | None:
        for item in self.items(pos):
            if isinstance(item, PortItem):
                return item
        # A little slack: ports are small.
        for item in self.items(QRectF(pos.x() - 8, pos.y() - 8, 16, 16)):
            if isinstance(item, PortItem):
                return item
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        port = self._port_at(event.scenePos()) if event.button() == Qt.MouseButton.LeftButton else None
        if port is None:
            super().mousePressEvent(event)
            return
        if not port.is_output:
            # Grabbing a wired input picks up its connection from the source end.
            wired = next((e for e in self.graph.edges
                          if e.dst == port.node_item.node.id and e.dst_port == port.port.name), None)
            if wired is not None:
                self.graph.disconnect(wired)
                self._sync_edges()
                self.changed_graph()
                port = self.node_items[wired.src].outputs[wired.src_port]
        self._drag_from = port
        self._drag_line = QGraphicsPathItem()
        self._drag_line.setPen(QPen(QColor(PORT_COLORS.get(port.port.type, PORT_COLORS[ANY])), 2,
                                    Qt.PenStyle.DashLine))
        self._drag_line.setZValue(5)
        self.addItem(self._drag_line)
        self._update_drag(event.scenePos())
        event.accept()

    def _update_drag(self, pos: QPointF) -> None:
        start = self._drag_from.scene_center()
        self._drag_line.setPath(curve(start, pos) if self._drag_from.is_output else curve(pos, start))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._drag_from is not None:
            self._update_drag(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._drag_from is None:
            super().mouseReleaseEvent(event)
            return
        start, self._drag_from = self._drag_from, None
        self.removeItem(self._drag_line)
        self._drag_line = None
        end = self._port_at(event.scenePos())
        if end is not None and end.is_output != start.is_output:
            out, inp = (start, end) if start.is_output else (end, start)
            self.connect_ports(out.node_item.node.id, out.port.name,
                               inp.node_item.node.id, inp.port.name)
        event.accept()
