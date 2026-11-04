"""What the review controls send to the engine. Qt-free; the page calls these off the GUI thread.

The owner's click is the confirmation, so a regeneration sends ``auto_confirm``. Rows change only
when the engine's event comes back.
"""

from __future__ import annotations

from typing import Any

from src.web.engine_client import EngineError, EngineToolError


class ActionError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}


class ProductionActions:
    def __init__(self, client):
        self.client = client

    def _call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.client.call(tool, args)
        except EngineToolError as exc:
            raise ActionError(exc.code, str(exc), exc.payload.get("details")) from None
        except (EngineError, TimeoutError) as exc:
            raise ActionError("ENGINE_UNAVAILABLE", str(exc)) from None

    def _verdict(self, jobs, action: str) -> None:
        by_production: dict[str, list[dict[str, Any]]] = {}
        for job in jobs:
            by_production.setdefault(job.production_id, []).append({"id": job.item_id, "take": job.take})
        for production_id, items in by_production.items():
            self._call("flow_production_review", {"production_id": production_id, "items": items,
                                                  "action": action, "actor": "app"})

    def approve(self, jobs) -> None:
        self._verdict(jobs, "approve")

    def reject(self, jobs) -> None:
        self._verdict(jobs, "reject")

    def review_take(self, job, take: int, action: str, note: str = "") -> dict[str, Any]:
        """A verdict on one named Take, older ones included, with the owner's note when given."""
        args = {"production_id": job.production_id, "items": [{"id": job.item_id, "take": take}],
                "action": action, "actor": "app"}
        if note.strip():
            args["note"] = note.strip()
        return self._call("flow_production_review", args)

    def regenerate(self, job, prompt: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        args = {"production_id": job.production_id, "item": job.item_id, "expected_take": job.latest_take,
                "auto_confirm": True, "actor": "app"}
        if prompt is not None:
            args["prompt"] = prompt
        if dry_run:
            args["dry_run"] = True
        return self._call("flow_production_regenerate", args)

    def raise_budget(self, run_id: str, max_credits: int) -> None:
        self.set_budget(run_id, max_credits)

    # ---- the run as a whole (flow_job_control) ----------------------------
    def pause(self, run_id: str) -> dict[str, Any]:
        return self._call("flow_job_control", {"action": "pause", "run_id": run_id})

    def resume(self, run_id: str, accept_quote: bool = False) -> dict[str, Any]:
        args = {"action": "resume", "run_id": run_id}
        if accept_quote:
            args["accept_quote"] = True
        return self._call("flow_job_control", args)

    def cancel(self, run_id: str) -> dict[str, Any]:
        return self._call("flow_job_control", {"action": "cancel", "run_id": run_id})

    def set_budget(self, run_id: str, max_credits: int) -> dict[str, Any]:
        return self._call("flow_job_control", {"action": "set_budget", "run_id": run_id, "max_credits": max_credits})

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._call("flow_list_runs", {"limit": limit}).get("runs") or []

    def current(self, job) -> dict[str, Any] | None:
        """The engine's view of a row's Item, to show after a conflict."""
        cursor = 0
        while cursor is not None:
            reply = self._call("flow_production_status", {"production_id": job.production_id, "detail": "full", "cursor": cursor})
            for item in reply.get("items") or []:
                if item.get("item") == job.item_id:
                    return item
            cursor = reply.get("next_cursor")
        return None
