"""Google Flow video generation through the shared engine. Same path as images, in credits."""

from __future__ import annotations

import threading

from pathlib import Path
from typing import Any

from src.gen.models import Job, OutputFile
from src.gen.provider import ConfigField, Estimate, Provider, ProviderError, RunContext, shot_options
from src.i18n import tr
from src.gen.web_flow_image import SITE, WebFlowImageProvider, capabilities, run_engine_job


def quote(caps: dict[str, Any], model: str, duration: int, resolution: str) -> int:
    """Credits for one clip; a mix Flow does not offer is an error before any call."""
    credits = caps["video"]["models"].get(model, {}).get("credits", {})
    cost = credits.get(resolution, {}).get(str(duration))
    if cost is None:
        offered = ", ".join(f"{res} {sec}s" for res, secs in credits.items() for sec in secs)
        raise ProviderError(f"{model} can't make {resolution} {duration}s. It offers: {offered}", stop_queue=True)
    return cost


class RunTally:
    """Credits a batch has committed, for a run-level cap shared by the queue's workers."""

    def __init__(self):
        self._lock = threading.Lock()
        self.spent = 0

    def take(self, cost: int, cap: int) -> int:
        """The ``max_credits`` to send: what is left of ``cap``. Counted only when it fits,
        so a shot past the cap goes to the engine with too little and is refused unspent."""
        with self._lock:
            left = max(0, cap - self.spent)
            if cost <= left:
                self.spent += cost
            return left


class WebFlowVideoProvider(Provider):
    key = "web_flow_video"
    name = "Google Flow web (video)"
    site = SITE
    backend = WebFlowImageProvider.backend
    session = WebFlowImageProvider.session
    max_count = 4

    def __init__(self, backend=None, session=None):
        self._backend = backend
        self._session = session

    def estimate(self, jobs: list[Job], options: dict[str, Any]) -> Estimate:
        """Summed per shot: a shot's own settings change its quote."""
        caps, total = capabilities(), 0
        for job in jobs:
            o = shot_options(job, options)
            cost = quote(caps, o.get("model") or "omni", int(o.get("duration", 8)), o.get("resolution") or "720p")
            total += cost * max(1, int(o.get("count", 1)))
        return Estimate(len(jobs), total)

    def config_fields(self) -> list[ConfigField]:
        video = capabilities()["video"]
        durations = {m: sorted({s for secs in e["credits"].values() for s in secs}, key=int)
                     for m, e in video["models"].items()}
        return [
            ConfigField("model", "gen_model", "choice", video["defaultModel"], list(video["models"]), option_prefix="flow_model_"),
            ConfigField("aspect", "gen_aspect", "choice", video["ratios"][0], video["ratios"]),
            ConfigField("duration", "gen_duration", "choice", "8", durations[video["defaultModel"]],
                        depends_on="model", options_by=durations),
            ConfigField("resolution", "gen_resolution", "choice", "720p", ["720p", "360p"]),
            ConfigField("silent", "gen_silent", "bool", False),
            ConfigField("run_cap", "gen_run_cap", "int", 0, minimum=0, maximum=100000),
            ConfigField("timeout", "gen_timeout", "int", 600, minimum=60, maximum=1800),
        ]

    def generate(self, job: Job, options: dict[str, Any], ctx: RunContext) -> list[OutputFile]:
        model = options.get("model") or "omni"
        duration, resolution = int(options.get("duration", 8)), options.get("resolution") or "720p"
        count = max(1, int(options.get("count", 1)))
        cost = quote(capabilities(), model, duration, resolution)
        library = set(job.character_refs) | set(job.scene_refs)
        refs = [str(Path(r).resolve()) for r in job.refs if r not in library]
        # The owner chose this mix, so the engine's default cap of 30 is not the limit; a run cap is.
        cap = int(options.get("run_cap") or 0)
        limit = options.get("_shared", options).setdefault("_run_tally", RunTally()).take(cost * count, cap) if cap else cost * count
        args = {"prompt": job.prompt, "model": model, "ratio": options.get("aspect") or "16:9", "count": count,
                "duration": duration, "resolution": resolution, "silent": bool(options.get("silent")),
                "max_credits": limit, "max_generation_retries": 0}  # the app's retries are the only ones
        frames = {k: str(Path(v).resolve()) for k, v in (("start_frame", job.start_frame), ("end_frame", job.end_frame)) if v}
        if frames and refs:  # the engine refuses the mix too; say so before any call
            raise ProviderError(tr("gen_frames_and_refs"))
        args.update(frames)
        if refs:
            args["ingredients"] = refs
        return run_engine_job(self, job, "flow_generate_video", args, float(options.get("timeout", 600)), ctx, "video")
