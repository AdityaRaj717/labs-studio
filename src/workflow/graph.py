"""The workflow graph: nodes, typed connections, dependency order, JSON files.

Qt-free so the runner and tests use it without a GUI.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.workflow.registry import Registry, compatible

FORMAT = "labs-studio-workflow"
VERSION = 1


class GraphError(ValueError):
    pass


@dataclass
class Node:
    type_id: str
    params: dict[str, Any] = field(default_factory=dict)
    pos: tuple[float, float] = (0.0, 0.0)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    title: str = ""  # user label; empty = the type's label


@dataclass(frozen=True)
class Edge:
    src: str  # node id
    src_port: str
    dst: str
    dst_port: str


class Graph:
    def __init__(self, registry: Registry):
        self.registry = registry
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []

    # ---- nodes ------------------------------------------------------
    def add_node(self, type_id: str, params: dict[str, Any] | None = None,
                 pos: tuple[float, float] = (0.0, 0.0), node_id: str | None = None) -> Node:
        node_type = self.registry.get(type_id)
        merged = node_type.default_params()
        merged.update(params or {})
        node = Node(type_id, merged, (float(pos[0]), float(pos[1])))
        if node_id:
            if node_id in self.nodes:
                raise GraphError(f"Duplicate node id {node_id!r}")
            node.id = node_id
        self.nodes[node.id] = node
        return node

    def remove_node(self, node_id: str) -> None:
        self.nodes.pop(node_id, None)
        self.edges = [e for e in self.edges if node_id not in (e.src, e.dst)]

    # ---- edges ------------------------------------------------------
    def can_connect(self, src: str, src_port: str, dst: str, dst_port: str) -> str:
        """Empty string if the connection is allowed, else the reason."""
        if src not in self.nodes or dst not in self.nodes:
            return "Unknown node"
        if src == dst:
            return "A node can't connect to itself"
        out = self.registry.get(self.nodes[src].type_id).output(src_port)
        inp = self.registry.get(self.nodes[dst].type_id).input(dst_port)
        if out is None or inp is None:
            return "Unknown port"
        if not compatible(out.type, inp.type):
            return f"Can't connect {out.type} to {inp.type}"
        if self._reaches(dst, src):
            return "That connection would make a loop"
        return ""

    def connect(self, src: str, src_port: str, dst: str, dst_port: str) -> Edge:
        reason = self.can_connect(src, src_port, dst, dst_port)
        if reason:
            raise GraphError(reason)
        # An input takes one connection; a new one replaces the old.
        self.edges = [e for e in self.edges if not (e.dst == dst and e.dst_port == dst_port)]
        edge = Edge(src, src_port, dst, dst_port)
        self.edges.append(edge)
        return edge

    def disconnect(self, edge: Edge) -> None:
        self.edges = [e for e in self.edges if e != edge]

    def incoming(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.dst == node_id]

    def _reaches(self, start: str, target: str) -> bool:
        seen, stack = set(), [start]
        while stack:
            n = stack.pop()
            if n == target:
                return True
            if n in seen:
                continue
            seen.add(n)
            stack.extend(e.dst for e in self.edges if e.src == n)
        return False

    # ---- order ------------------------------------------------------
    def topo_order(self) -> list[str]:
        """Node ids so every node comes after the nodes it reads from.

        Ties keep insertion order, so runs are repeatable.
        """
        indeg = {n: 0 for n in self.nodes}
        for e in self.edges:
            indeg[e.dst] += 1
        ready = [n for n in self.nodes if indeg[n] == 0]
        order = []
        while ready:
            n = ready.pop(0)
            order.append(n)
            for e in self.edges:
                if e.src == n:
                    indeg[e.dst] -= 1
                    if indeg[e.dst] == 0:
                        ready.append(e.dst)
        if len(order) != len(self.nodes):
            raise GraphError("The graph has a loop")
        return order

    def missing_inputs(self, node_id: str) -> list[str]:
        node_type = self.registry.get(self.nodes[node_id].type_id)
        wired = {e.dst_port for e in self.incoming(node_id)}
        return [p.name for p in node_type.inputs if p.required and p.name not in wired]

    # ---- files ------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "version": VERSION,
            "nodes": [{"id": n.id, "type": n.type_id, "title": n.title,
                       "pos": [n.pos[0], n.pos[1]], "params": n.params}
                      for n in self.nodes.values()],
            "edges": [{"src": e.src, "src_port": e.src_port, "dst": e.dst, "dst_port": e.dst_port}
                      for e in self.edges],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], registry: Registry) -> Graph:
        if data.get("format") != FORMAT:
            raise GraphError("Not a Labs Studio workflow file")
        if int(data.get("version", 0)) > VERSION:
            raise GraphError("This workflow was saved by a newer version")
        graph = cls(registry)
        for raw in data.get("nodes", []):
            if raw.get("type") not in registry:
                raise GraphError(f"Unknown node type {raw.get('type')!r}")
            pos = raw.get("pos") or [0, 0]
            node = graph.add_node(raw["type"], raw.get("params") or {}, (pos[0], pos[1]),
                                  node_id=raw.get("id"))
            node.title = raw.get("title", "")
        for raw in data.get("edges", []):
            graph.connect(raw["src"], raw["src_port"], raw["dst"], raw["dst_port"])
        return graph

    def save(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path | str, registry: Registry) -> Graph:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GraphError(f"Could not read {Path(path).name}: {exc}") from exc
        return cls.from_dict(data, registry)
