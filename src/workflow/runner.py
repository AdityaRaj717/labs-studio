"""Runs a graph in dependency order on a worker thread.

Each node gets the outputs of the nodes wired into it. A node whose upstream
failed (or was skipped) is skipped. Events go to ``on_event`` from the worker
thread; the UI turns them into Qt signals.
"""

from __future__ import annotations

import copy
import enum
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from src.gen.provider import ProviderError, StopRequested
from src.workflow.graph import Graph, GraphError
from src.workflow.registry import NodeContext

log = logging.getLogger(__name__)


class NodeStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    STOPPED = "stopped"


@dataclass
class NodeState:
    status: NodeStatus = NodeStatus.PENDING
    progress: float = 0.0
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass
class RunEvent:
    kind: str  # "node" (state changed) | "finished"
    node_id: str = ""
    state: NodeState | None = None


class GraphRunner:
    """One run of one graph. Build a new runner for each run."""

    def __init__(self, graph: Graph, out_dir: Path | str,
                 on_event: Callable[[RunEvent], None] | None = None, max_attempts: int = 2):
        # Snapshot so edits in the editor during a run don't race the worker.
        self.graph = Graph(graph.registry)
        self.graph.nodes = copy.deepcopy(graph.nodes)
        self.graph.edges = list(graph.edges)
        self.out_dir = Path(out_dir)
        self.on_event = on_event or (lambda e: None)
        self.max_attempts = max(1, max_attempts)
        self.states: dict[str, NodeState] = {n: NodeState() for n in self.graph.nodes}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- control ----------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self.run, name="workflow-runner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def wait(self, timeout: float | None = None) -> bool:
        if self._thread is not None:
            self._thread.join(timeout)
        return not self.is_running()

    # ---- run --------------------------------------------------------
    def run(self) -> dict[str, NodeState]:
        try:
            order = self.graph.topo_order()
        except GraphError as exc:
            for node_id in self.graph.nodes:
                self._set(node_id, NodeStatus.FAILED, error=str(exc))
            self.on_event(RunEvent("finished"))
            return self.states

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for node_id in order:
            if self._stop.is_set():
                self._set(node_id, NodeStatus.STOPPED)
                continue
            self._run_node(node_id, self.out_dir / stamp / node_id)
        self.on_event(RunEvent("finished"))
        return self.states

    def _run_node(self, node_id: str, out_dir: Path) -> None:
        node = self.graph.nodes[node_id]
        node_type = self.graph.registry.get(node.type_id)

        inputs: dict[str, Any] = {}
        for edge in self.graph.incoming(node_id):
            upstream = self.states[edge.src]
            if upstream.status is not NodeStatus.DONE:
                self._set(node_id, NodeStatus.SKIPPED, error="An earlier node didn't finish")
                return
            inputs[edge.dst_port] = upstream.outputs.get(edge.src_port)
        missing = self.graph.missing_inputs(node_id)
        if missing:
            self._set(node_id, NodeStatus.FAILED, error=f"Input not connected: {', '.join(missing)}")
            return

        self._set(node_id, NodeStatus.RUNNING)
        for attempt in range(1, self.max_attempts + 1):
            ctx = NodeContext(node_id=node_id, out_dir=out_dir,
                              progress=lambda p: self._progress(node_id, p),
                              should_stop=self._stop.is_set, attempt=attempt)
            try:
                outputs = node_type.run(inputs, dict(node.params), ctx) or {}
            except StopRequested:
                self._set(node_id, NodeStatus.STOPPED)
                return
            except ProviderError as exc:
                if exc.retryable and attempt < self.max_attempts and not self._stop.is_set():
                    log.warning("Node %s: %s (retrying)", node_id, exc)
                    continue
                self._set(node_id, NodeStatus.FAILED, error=str(exc))
                return
            except Exception as exc:  # a node bug fails that node, not the run
                log.exception("Node %s (%s) crashed", node_id, node.type_id)
                self._set(node_id, NodeStatus.FAILED, error=str(exc) or type(exc).__name__)
                return
            self.states[node_id].outputs = outputs
            self._set(node_id, NodeStatus.DONE, progress=1.0)
            return

    def _set(self, node_id: str, status: NodeStatus, error: str = "",
             progress: float | None = None) -> None:
        state = self.states[node_id]
        state.status = status
        state.error = error
        if progress is not None:
            state.progress = progress
        self.on_event(RunEvent("node", node_id, state))

    def _progress(self, node_id: str, p: float) -> None:
        state = self.states[node_id]
        state.progress = max(0.0, min(1.0, float(p)))
        self.on_event(RunEvent("node", node_id, state))
