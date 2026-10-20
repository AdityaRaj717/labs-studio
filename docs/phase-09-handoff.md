# Phase 9 handoff — Workflow node editor (done 2026-10-21)

## State
- Everything in `docs/phase-09-workflow.md` is built on branch `claude/phase-9-workflow-cd1036` and not merged. `pytest`: 114 passed (91 before, 23 new in `tests/test_workflow.py`). No test touches the network: the Gemini chain test uses `httpx.MockTransport`, and the others use the Phase 2 `FakeProvider` and the offline `FakeVideoProvider`.
- The 3-node chain prompt → image → video runs in tests twice: with the demo providers and with Gemini image + Gemini video on mocked transports. The second test checks that the image node's file is sent as the video's start frame.
- `python run.py` launches. Sidebar **Workflow** opens the editor with the starter chain (demo nodes). In a real window (Windows 11, dark, network blocked, app data redirected to `D:\tmp_render\phase9\data`), **Run** finished with 3 done and 0 failed. Screenshot: `D:\tmp_render\phase9\phase9_workflow.png`. The script that made it is `D:\tmp_render\phase9\shot.py`.
- No new deps.

## Shared-file edits (small, for merging with phases 5/7/8)
- `src/app.py` `register_pages`: two lines at the end (`from src.ui.workflow.page import WorkflowPage` and `window.register_page("workflow", WorkflowPage)`).
- `src/languages/en.py`: `wf_*` keys appended at the end.
- Everything else is new: `src/workflow/`, `src/ui/workflow/`, `tests/test_workflow.py`, and these docs.

## How Phase 5 (OpenAI / Grok) and Phase 7 (video tools) add nodes
The editor, scene and runner don't change. Drop a module into `src/workflow/nodes/`. `default_registry()` imports every non-underscore module there, and a module that fails to import is logged and skipped.

**A generator provider** (anything implementing `src.gen.provider.Provider`):
```python
# src/workflow/nodes/openai.py
from src.workflow.provider_node import provider_node
from src.workflow.registry import IMAGE, Port, register

def _provider():
    from src.gen.openai_image import OpenAIImageProvider   # lazy: no client at import
    return OpenAIImageProvider()

register(provider_node("openai.image", "wf_node_openai_image", "wf_cat_openai", _provider,
                       output=IMAGE, refs=Port("refs", IMAGE, "wf_port_refs", required=False)))
```
The node gets a `prompt` text input, the optional refs port (pass `refs=None` for none), one output named after its type, and the provider's `config_fields()` plus `count` as settings. The fields are built on first use. Expose a builder (`def image_node(make_provider=_provider)`) as `nodes/gemini.py` does, so tests can register it with a mocked transport into their own `Registry()`.

**A tool that isn't a Provider** (upscale, cut, concat):
```python
from src.gen.provider import ConfigField, ProviderError
from src.workflow.provider_node import as_paths
from src.workflow.registry import VIDEO, NodeType, Port, register

def _trim(inputs, params, ctx):          # runs on the worker thread
    clips = as_paths(inputs["video"])
    ctx.out_dir.mkdir(parents=True, exist_ok=True)
    ...                                   # call ctx.progress(p); check ctx.should_stop()
    return {"video": [out_path]}

register(NodeType("tools.trim", "wf_node_trim", "wf_cat_tools", _trim,
                  inputs=[Port("video", VIDEO, "wf_port_video")],
                  outputs=[Port("video", VIDEO, "wf_port_video")],
                  params=[ConfigField("start", "wf_param_start", "float", 0.0, maximum=600)]))
```
Rules: raise `ProviderError(msg, retryable=...)` for expected failures, and raise `StopRequested` when `ctx.should_stop()` is true. Write files under `ctx.out_dir`. Image and video values are `list[Path]`. Settings kinds the inspector can edit are `choice`, `int`, `float`, `bool`, `text`, `multiline`, `file` and `folder`. Add the label keys (`wf_node_*`, `wf_cat_*`, `wf_param_*`, `wf_port_*`) to the end of `en.py`. A new port type only needs a colour in `scene.PORT_COLORS`; without one it is drawn grey.

## Unverified / known gaps
- The Gemini nodes haven't made a real call. They reuse the Phase 3/4 providers unchanged, so the open points in `phase-04-handoff.md` still apply. The Gemini node settings come from the provider defaults, not from the Flow Image/Video page settings.
- The edge from prompt → video in the starter graph is drawn behind the image node (edges sit under nodes). It's only cosmetic.
- No undo, copy/paste, batch-over-prompt-list or per-node rerun. Every run reruns the whole graph and bills real providers again.
- The demo video node writes a GIF, not an MP4, so it stays dependency-free and offline.

## Next
Merge with phases 5/7/8. Expected conflicts are only at the end of `register_pages` and at the end of `en.py`. Then each of those phases can add its node module as described above.
