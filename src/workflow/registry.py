"""Node types and the registry the editor and runner look them up in.

A node type says what ports it has, which settings it shows, and how it runs.
Providers and tools add their own types by dropping a module into
``src/workflow/nodes/`` that calls ``register(...)`` at import time; the
editor lists whatever is registered, so it never changes for a new node.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from src.gen.provider import ConfigField, RunContext

log = logging.getLogger(__name__)

# Port value types. ``text`` carries a str; ``image`` and ``video`` carry a
# list of file paths. ``any`` connects to anything.
TEXT = "text"
IMAGE = "image"
VIDEO = "video"
ANY = "any"
PORT_TYPES = (TEXT, IMAGE, VIDEO, ANY)


def compatible(out_type: str, in_type: str) -> bool:
    return out_type == in_type or ANY in (out_type, in_type)


@dataclass
class Port:
    name: str
    type: str
    label_key: str = ""
    required: bool = True


@dataclass
class NodeContext:
    """What a node's ``run`` gets besides its inputs and settings."""

    node_id: str
    out_dir: Path  # where this node writes its files
    progress: Callable[[float], None]
    should_stop: Callable[[], bool]
    attempt: int = 1  # 2+ when the runner retries after a retryable error

    def run_context(self) -> RunContext:
        return RunContext(progress=self.progress, should_stop=self.should_stop)


# run(inputs, params, ctx) -> {output port name: value}
RunFn = Callable[[dict[str, Any], dict[str, Any], NodeContext], dict[str, Any]]


@dataclass
class NodeType:
    type_id: str
    label_key: str
    category: str
    run: RunFn
    inputs: list[Port] = field(default_factory=list)
    outputs: list[Port] = field(default_factory=list)
    params: list[ConfigField] = field(default_factory=list)
    description_key: str = ""
    # Builds ``params`` on first use instead (e.g. from a provider's fields),
    # so registering a node never creates an HTTP client.
    params_factory: Callable[[], list[ConfigField]] | None = None

    def fields(self) -> list[ConfigField]:
        if self.params_factory is not None:
            self.params = list(self.params_factory())
            self.params_factory = None
        return self.params

    def input(self, name: str) -> Port | None:
        return next((p for p in self.inputs if p.name == name), None)

    def output(self, name: str) -> Port | None:
        return next((p for p in self.outputs if p.name == name), None)

    def default_params(self) -> dict[str, Any]:
        return {f.key: f.default for f in self.fields()}


class Registry:
    def __init__(self):
        self._types: dict[str, NodeType] = {}

    def register(self, node_type: NodeType, replace: bool = False) -> NodeType:
        if node_type.type_id in self._types and not replace:
            raise ValueError(f"Node type {node_type.type_id!r} is already registered")
        self._types[node_type.type_id] = node_type
        return node_type

    def unregister(self, type_id: str) -> None:
        self._types.pop(type_id, None)

    def get(self, type_id: str) -> NodeType:
        try:
            return self._types[type_id]
        except KeyError:
            raise KeyError(f"Unknown node type {type_id!r}") from None

    def __contains__(self, type_id: str) -> bool:
        return type_id in self._types

    def types(self) -> list[NodeType]:
        return list(self._types.values())

    def categories(self) -> dict[str, list[NodeType]]:
        out: dict[str, list[NodeType]] = {}
        for t in self._types.values():
            out.setdefault(t.category, []).append(t)
        return out


_default: Registry | None = None


def default_registry() -> Registry:
    """The app-wide registry, filled from every module in ``src/workflow/nodes``."""
    global _default
    if _default is None:
        _default = Registry()
        load_node_modules()
    return _default


def register(node_type: NodeType, replace: bool = False) -> NodeType:
    """Add a type to the app-wide registry (call from a ``nodes/`` module)."""
    reg = _default if _default is not None else default_registry()
    return reg.register(node_type, replace=replace)


def load_node_modules() -> None:
    from src.workflow import nodes

    for info in sorted(pkgutil.iter_modules(nodes.__path__), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue
        try:
            importlib.import_module(f"{nodes.__name__}.{info.name}")
        except Exception:  # one broken node module must not break the editor
            log.exception("Could not load workflow nodes from %s", info.name)
