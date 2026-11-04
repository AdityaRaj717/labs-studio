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


class Refusing(Backend):
    """The engine's pre-spend check: a job whose quote is above max_credits is refused."""

    def run_job(self, tool, args, timeout, on_event=None, should_stop=None, **extra):
        from src.web.engine_client import EngineToolError

        if args["max_credits"] < 4 * args["count"]:
            self.calls.append((tool, args))
            raise EngineToolError("above max_credits", {"error_code": "BUDGET_EXCEEDED"})
        return super().run_job(tool, args, timeout, on_event, should_stop, **extra)


def test_batch_cap_stops_at_engine_refusal(tmp_path):
    backend = Refusing(tmp_path)
    provider = WebFlowVideoProvider(backend=backend, session=object())
    options = {"model": "omni", "duration": "4", "resolution": "360p", "run_cap": 10}
    provider.generate(Job("one"), options, ctx())
    provider.generate(Job("two"), options, ctx())
    with pytest.raises(ProviderError) as err:
        provider.generate(Job("three"), options, ctx())  # 8 of 10 committed: 2 left, the shot costs 4
    assert err.value.stop_queue
    assert [a["max_credits"] for _, a in backend.calls] == [10, 6, 2]


def test_app_sends_no_hidden_engine_retries(tmp_path):
    from src.gen.web_flow_image import WebFlowImageProvider

    backend = Backend(tmp_path)
    WebFlowVideoProvider(backend=backend, session=object()).generate(
        Job("a"), {"model": "omni", "duration": "4", "resolution": "360p"}, ctx())
    assert backend.calls[0][1]["max_generation_retries"] == 0

    class Images(Backend):
        def run_job(self, tool, args, timeout, on_event=None, should_stop=None, **extra):
            self.calls.append((tool, args))
            png = self.root / "i.png"
            png.write_bytes(b"png")
            return {"state": "done", "outputs": [{"file": str(png), "mediaId": "m"}]}

    images = Images(tmp_path)
    try:
        WebFlowImageProvider(backend=images, session=object()).generate(Job("b"), {}, ctx())
    except ProviderError:
        pass  # only the arguments matter here
    assert images.calls[0][1]["max_generation_retries"] == 0
