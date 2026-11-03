"""Google Flow video generation through the shared engine. Same path as images, in credits."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.gen.models import Job, OutputFile
from src.gen.provider import ConfigField, Estimate, Provider, ProviderError, RunContext
from src.gen.web_flow_image import SITE, WebFlowImageProvider, capabilities, run_engine_job


def quote(caps: dict[str, Any], model: str, duration: int, resolution: str) -> int:
    """Credits for one clip; a mix Flow does not offer is an error before any call."""
    credits = caps["video"]["models"].get(model, {}).get("credits", {})
    cost = credits.get(resolution, {}).get(str(duration))
    if cost is None:
        offered = ", ".join(f"{res} {sec}s" for res, secs in credits.items() for sec in secs)
        raise ProviderError(f"{model} can't make {resolution} {duration}s. It offers: {offered}", stop_queue=True)
    return cost


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
        cost = quote(capabilities(), options.get("model") or "omni", int(options.get("duration", 8)),
                     options.get("resolution") or "720p")
        return Estimate(len(jobs), cost * max(1, int(options.get("count", 1))) * len(jobs))

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
            ConfigField("timeout", "gen_timeout", "int", 600, minimum=60, maximum=1800),
        ]

    def generate(self, job: Job, options: dict[str, Any], ctx: RunContext) -> list[OutputFile]:
        model = options.get("model") or "omni"
        duration, resolution = int(options.get("duration", 8)), options.get("resolution") or "720p"
        count = max(1, int(options.get("count", 1)))
        cost = quote(capabilities(), model, duration, resolution)
        library = set(job.character_refs) | set(job.scene_refs)
        refs = [str(Path(r).resolve()) for r in job.refs if r not in library]
        args = {"prompt": job.prompt, "model": model, "ratio": options.get("aspect") or "16:9", "count": count,
                "duration": duration, "resolution": resolution, "silent": bool(options.get("silent")),
                "max_credits": cost * count}  # the owner chose this mix, so the engine's default cap of 30 is not the limit
        if refs:
            args["ingredients"] = refs
        return run_engine_job(self, job, "flow_generate_video", args, float(options.get("timeout", 600)), ctx, "video")
