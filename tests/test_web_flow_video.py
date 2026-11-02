"""The Flow Video provider against a stub backend. No browser, nothing spent."""

from __future__ import annotations

import pytest

from src.gen.models import Job
from src.gen.provider import ProviderError, RunContext
from src.gen.web_flow_video import WebFlowVideoProvider


class Backend:
    def __init__(self, root):
        self.root, self.calls = root, []

    def run_job(self, tool, args, timeout, on_event=None, should_stop=None, **extra):
        self.calls.append((tool, args))
        clip = self.root / "c.mp4"
        clip.write_bytes(b"mp4")
        return {"state": "done", "outputs": [{"file": str(clip), "mediaId": "m", "model": args["model"], "quotedCredits": 4}]}


def ctx():
    return RunContext(progress=lambda p: None, should_stop=lambda: False)


def test_fields_reuse_the_config_widgets(qapp):
    keys = {f.key: f for f in WebFlowVideoProvider().config_fields()}
    assert {"model", "aspect", "duration", "resolution", "silent"} <= set(keys)
    assert keys["silent"].kind == "bool" and keys["model"].default == "omni"


def test_omni_360p_4s_goes_to_the_engine(tmp_path):
    backend = Backend(tmp_path)
    files = WebFlowVideoProvider(backend=backend, session=object()).generate(
        Job("a fox"), {"model": "omni", "duration": "4", "resolution": "360p", "silent": True, "count": 2}, ctx())
    tool, args = backend.calls[0]
    assert tool == "flow_generate_video" and (args["duration"], args["resolution"], args["silent"]) == (4, "360p", True)
    assert args["max_credits"] == 8 and files[0].ext == "mp4"


@pytest.mark.parametrize("model,duration,resolution", [("veoLite", "4", "720p"), ("veoFast", "8", "360p"), ("omni", "5", "720p")])
def test_video_provider_rejects_invalid_mixes_before_a_call(tmp_path, model, duration, resolution):
    backend = Backend(tmp_path)
    provider = WebFlowVideoProvider(backend=backend, session=object())
    with pytest.raises(ProviderError) as err:
        provider.generate(Job("x"), {"model": model, "duration": duration, "resolution": resolution}, ctx())
    assert err.value.stop_queue and backend.calls == []
