"""Phase 9: workflow graph, registry, runner and page. No network."""

from __future__ import annotations

import base64
import json
import time

import httpx
import pytest
from PIL import Image

from src.config import Settings
from src.gen.fake_provider import FakeProvider
from src.gen.provider import ProviderError
from src.workflow.graph import Graph, GraphError
from src.workflow.nodes import basic, demo, gemini
from src.workflow.registry import IMAGE, TEXT, NodeType, Port, Registry, default_registry
from src.workflow.runner import GraphRunner, NodeStatus

MP4 = b"\x00\x00\x00\x18ftypmp42fake-video-bytes"


def fake_registry() -> Registry:
    reg = Registry()
    for t in (basic.PROMPT, basic.JOIN, basic.IMAGE_FILE):
        reg.register(t)
    reg.register(demo.image_node(lambda: FakeProvider(step_seconds=0)))
    reg.register(demo.video_node(lambda: demo.FakeVideoProvider(step_seconds=0, frames=3)))
    return reg


def chain(reg: Registry, image="demo.image", video="demo.video", text="a red fox"):
    g = Graph(reg)
    p = g.add_node("prompt", {"text": text})
    i = g.add_node(image)
    v = g.add_node(video)
    g.connect(p.id, "text", i.id, "prompt")
    g.connect(p.id, "text", v.id, "prompt")
    g.connect(i.id, "image", v.id, "start")
    return g, p, i, v


# ---- graph ---------------------------------------------------------------
def test_connect_checks_types_and_loops():
    reg = fake_registry()
    g, p, i, v = chain(reg)
    with pytest.raises(GraphError, match="text to image|Can't connect"):
        g.connect(p.id, "text", v.id, "start")
    j = g.add_node("text_join")
    g.connect(p.id, "text", j.id, "a")
    j2 = g.add_node("text_join")
    g.connect(j.id, "text", j2.id, "a")
    with pytest.raises(GraphError, match="loop"):
        g.connect(j2.id, "text", j.id, "b")
    with pytest.raises(GraphError):
        g.connect(j.id, "text", j.id, "b")


def test_input_takes_one_connection():
    reg = fake_registry()
    g, p, i, v = chain(reg)
    p2 = g.add_node("prompt", {"text": "other"})
    g.connect(p2.id, "text", i.id, "prompt")
    assert [e.src for e in g.incoming(i.id)] == [p2.id]


def test_topo_order_and_remove():
    reg = fake_registry()
    g, p, i, v = chain(reg)
    # Add out of order: the order must still follow the wires.
    g.nodes = {v.id: v, i.id: i, p.id: p}
    assert g.topo_order() == [p.id, i.id, v.id]
    g.remove_node(i.id)
    assert all(i.id not in (e.src, e.dst) for e in g.edges)
    assert g.missing_inputs(v.id) == []


def test_json_round_trip(tmp_path):
    reg = fake_registry()
    g, p, i, v = chain(reg)
    i.title = "Hero shot"
    i.pos = (12.5, -40.0)
    path = tmp_path / "wf" / "graph.json"
    g.save(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format"] == "labs-studio-workflow" and data["version"] == 1
    g2 = Graph.load(path, reg)
    assert list(g2.nodes) == list(g.nodes)
    assert g2.edges == g.edges
    assert g2.nodes[i.id].title == "Hero shot" and g2.nodes[i.id].pos == (12.5, -40.0)
    assert g2.nodes[p.id].params["text"] == "a red fox"


def test_load_rejects_bad_files(tmp_path):
    reg = fake_registry()
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    with pytest.raises(GraphError):
        Graph.load(bad, reg)
    with pytest.raises(GraphError, match="Not a Labs Studio"):
        Graph.from_dict({"nodes": []}, reg)
    with pytest.raises(GraphError, match="Unknown node type"):
        Graph.from_dict({"format": "labs-studio-workflow", "version": 1,
                         "nodes": [{"id": "x", "type": "nope"}]}, reg)


# ---- registry ------------------------------------------------------------
def test_default_registry_loads_node_modules():
    reg = default_registry()
    for type_id in ("prompt", "text_join", "image_file", "gemini.image", "gemini.video",
                    "demo.image", "demo.video"):
        assert type_id in reg
    # Provider settings appear as node settings, plus the output count.
    keys = [f.key for f in reg.get("gemini.video").fields()]
    assert keys[0] == "model" and "count" in keys


def test_registering_a_new_type_needs_no_editor_change():
    reg = fake_registry()
    reg.register(NodeType("upper", "upper", "tools", lambda i, p, c: {"text": i["text"].upper()},
                          inputs=[Port("text", TEXT)], outputs=[Port("text", TEXT)]))
    with pytest.raises(ValueError):
        reg.register(NodeType("upper", "x", "x", lambda i, p, c: {}))
    g = Graph(reg)
    p = g.add_node("prompt", {"text": "shout"})
    u = g.add_node("upper")
    g.connect(p.id, "text", u.id, "text")
    assert "tools" in reg.categories()


# ---- runner --------------------------------------------------------------
def test_three_node_chain_runs_with_fake_providers(tmp_path):
    reg = fake_registry()
    g, p, i, v = chain(reg)
    events = []
    runner = GraphRunner(g, tmp_path / "out", events.append)
    runner.start()
    assert runner.wait(10)
    s = runner.states
    assert [s[n].status for n in (p.id, i.id, v.id)] == [NodeStatus.DONE] * 3
    assert s[p.id].outputs == {"text": "a red fox"}
    (img,) = s[i.id].outputs["image"]
    (gif,) = s[v.id].outputs["video"]
    assert img.suffix == ".png" and img.is_file()
    assert gif.suffix == ".gif" and Image.open(gif).n_frames == 3
    assert img.parent.name == i.id and gif.parent.name == v.id
    assert events[-1].kind == "finished"
    assert any(e.kind == "node" and e.node_id == v.id and e.state.progress > 0 for e in events)


def test_failure_skips_downstream(tmp_path):
    reg = fake_registry()
    g, p, i, v = chain(reg, text="a [fail] owl")
    states = GraphRunner(g, tmp_path).run()
    assert states[p.id].status is NodeStatus.DONE
    assert states[i.id].status is NodeStatus.FAILED and "Fake failure" in states[i.id].error
    assert states[v.id].status is NodeStatus.SKIPPED


def test_retryable_error_is_retried(tmp_path):
    reg = fake_registry()
    g, p, i, v = chain(reg, text="a [flaky] owl")
    states = GraphRunner(g, tmp_path).run()
    assert states[v.id].status is NodeStatus.DONE


def test_unwired_required_input_fails(tmp_path):
    reg = fake_registry()
    g = Graph(reg)
    n = g.add_node("demo.image")
    states = GraphRunner(g, tmp_path).run()
    assert states[n.id].status is NodeStatus.FAILED and "prompt" in states[n.id].error


def test_node_crash_fails_only_that_node(tmp_path):
    reg = fake_registry()

    def boom(i, p, c):
        raise RuntimeError("kaput")

    reg.register(NodeType("boom", "boom", "x", boom, outputs=[Port("text", TEXT)]))
    g = Graph(reg)
    b = g.add_node("boom")
    ok = g.add_node("prompt", {"text": "fine"})
    states = GraphRunner(g, tmp_path).run()
    assert states[b.id].status is NodeStatus.FAILED and states[b.id].error == "kaput"
    assert states[ok.id].status is NodeStatus.DONE


def test_stop_marks_remaining_nodes(tmp_path):
    reg = fake_registry()
    reg.register(demo.image_node(lambda: FakeProvider(step_seconds=0.05)), replace=True)
    g, p, i, v = chain(reg)
    runner = GraphRunner(g, tmp_path)
    runner.start()
    deadline = time.monotonic() + 5
    while runner.states[i.id].status is not NodeStatus.RUNNING and time.monotonic() < deadline:
        time.sleep(0.005)
    runner.stop()
    assert runner.wait(5)
    assert runner.states[i.id].status is NodeStatus.STOPPED
    assert runner.states[v.id].status in (NodeStatus.STOPPED, NodeStatus.SKIPPED)


def test_runner_snapshot_ignores_later_edits(tmp_path):
    reg = fake_registry()
    g, p, i, v = chain(reg)
    runner = GraphRunner(g, tmp_path)
    g.nodes[p.id].params["text"] = "changed"
    states = runner.run()
    assert states[p.id].outputs["text"] == "a red fox"


def test_image_file_node(tmp_path):
    reg = fake_registry()
    pic = tmp_path / "start.png"
    Image.new("RGB", (8, 8), (10, 200, 10)).save(pic)
    g = Graph(reg)
    f = g.add_node("image_file", {"path": str(pic)})
    p = g.add_node("prompt", {"text": "grow"})
    v = g.add_node("demo.video")
    g.connect(f.id, "image", v.id, "start")
    g.connect(p.id, "text", v.id, "prompt")
    missing = g.add_node("image_file", {"path": str(tmp_path / "none.png")})
    states = GraphRunner(g, tmp_path / "out").run()
    assert states[v.id].status is NodeStatus.DONE
    assert states[missing.id].status is NodeStatus.FAILED


# ---- Gemini nodes over mocked transports -------------------------------
def _png_bytes():
    import io

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 10, 10)).save(buf, "PNG")
    return buf.getvalue()


def test_gemini_chain_with_mocked_transports(tmp_path):
    from src.gen.gemini_image import GeminiImageProvider
    from src.gen.gemini_video import GeminiVideoProvider

    image_calls, video_calls = [], []

    def image_handler(request):
        image_calls.append(json.loads(request.content))
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(_png_bytes()).decode()}}
        ]}, "finishReason": "STOP"}]})

    def video_handler(request):
        video_calls.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "v1", "status": "completed", "steps": [
            {"type": "model_output", "content": [
                {"type": "video", "mime_type": "video/mp4", "data": base64.b64encode(MP4).decode()}]}]})

    reg = fake_registry()
    reg.register(gemini.image_node(lambda: GeminiImageProvider(
        key_source=lambda: "test-key", transport=httpx.MockTransport(image_handler))))
    reg.register(gemini.video_node(lambda: GeminiVideoProvider(
        key_source=lambda: "test-key", transport=httpx.MockTransport(video_handler),
        sleep=lambda s: None)))
    g, p, i, v = chain(reg, image="gemini.image", video="gemini.video", text="a lighthouse")
    states = GraphRunner(g, tmp_path).run()
    assert [states[n].status for n in (p.id, i.id, v.id)] == [NodeStatus.DONE] * 3, \
        [states[n].error for n in (i.id, v.id)]
    assert image_calls[0]["contents"][0]["parts"][-1] == {"text": "a lighthouse"}
    # The image from the first node is the video's start frame.
    items = video_calls[0]["input"]
    assert [x["type"] for x in items] == ["image", "text"]
    assert base64.b64decode(items[0]["data"]) == states[i.id].outputs["image"][0].read_bytes()
    (mp4,) = states[v.id].outputs["video"]
    assert mp4.suffix == ".mp4" and mp4.read_bytes() == MP4


def test_gemini_node_without_key_fails_cleanly(tmp_path):
    from src.gen.gemini_image import GeminiImageProvider

    def no_network(request):
        raise AssertionError("must not call the API without a key")

    reg = fake_registry()
    reg.register(gemini.image_node(lambda: GeminiImageProvider(
        key_source=lambda: "", transport=httpx.MockTransport(no_network))))
    g, p, i, v = chain(reg, image="gemini.image")
    states = GraphRunner(g, tmp_path).run()
    assert states[i.id].status is NodeStatus.FAILED and "No Gemini API key" in states[i.id].error
    assert states[v.id].status is NodeStatus.SKIPPED


def test_empty_prompt_fails(tmp_path):
    reg = fake_registry()
    g, p, i, v = chain(reg, text="   ")
    states = GraphRunner(g, tmp_path).run()
    assert states[p.id].status is NodeStatus.FAILED
    with pytest.raises(ProviderError):
        basic._prompt({}, {"text": ""}, None)


# ---- page ----------------------------------------------------------------
def run_until(qapp, cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def make_page(tmp_path, reg=None):
    from src.ui.workflow.page import WorkflowPage

    return WorkflowPage(registry=reg or fake_registry(), data_dir=tmp_path / "wf",
                        out_dir=tmp_path / "out")


def test_page_runs_starter_chain(qapp, tmp_path):
    page = make_page(tmp_path)
    graph = page.scene.graph
    assert [n.type_id for n in graph.nodes.values()] == ["prompt", "demo.image", "demo.video"]
    assert len(page.scene.edge_items) == 3
    assert page.run()
    assert run_until(qapp, lambda: not page.is_running() and page.btn_run.isEnabled())
    items = list(page.scene.node_items.values())
    assert [it.state.status for it in items] == [NodeStatus.DONE] * 3
    assert items[1]._thumb is not None  # the image node shows its picture
    assert "3 done" in page.status.text()
    page.shutdown()
    assert (tmp_path / "wf" / "autosave.json").is_file()


def test_page_edit_save_load(qapp, tmp_path):
    page = make_page(tmp_path)
    page.new_graph()
    assert not page.scene.graph.nodes
    a = page.add_node_at_center("prompt")
    b = page.add_node_at_center("demo.image")
    assert page.inspector.item is b
    assert not page.scene.connect_ports(a.node.id, "text", b.node.id, "refs")  # text → image
    assert "Can't connect" in page.status.text()
    assert page.scene.connect_ports(a.node.id, "text", b.node.id, "prompt")
    assert len(page.scene.edge_items) == 1

    page.scene.clearSelection()
    a.setSelected(True)
    assert page.inspector.item is a
    page.inspector._set_param("text", "edited prompt")
    assert a.node.params["text"] == "edited prompt"

    path = tmp_path / "saved.json"
    page.save(path)
    page.new_graph()
    assert page.load(path)
    graph = page.scene.graph
    assert len(graph.nodes) == 2 and len(graph.edges) == 1
    assert graph.nodes[a.node.id].params["text"] == "edited prompt"

    page.scene.clearSelection()
    page.scene.node_items[a.node.id].setSelected(True)
    page.delete_selected()
    assert a.node.id not in graph.nodes and not page.scene.edge_items
    page.shutdown()


def test_page_reopens_autosave(qapp, tmp_path):
    page = make_page(tmp_path)
    page.new_graph()
    page.add_node_at_center("prompt")
    page.shutdown()
    again = make_page(tmp_path)
    assert [n.type_id for n in again.scene.graph.nodes.values()] == ["prompt"]
    again.shutdown()


def test_param_editors_cover_field_kinds(qapp):
    from src.gen.provider import ConfigField
    from src.ui.workflow.page import param_editor

    seen = {}
    for field, value in [
        (ConfigField("c", "gen_model", "choice", "b", ["a", "b"]), "b"),
        (ConfigField("i", "gen_count", "int", 1, minimum=1, maximum=8), 3),
        (ConfigField("f", "x", "float", 0.5, maximum=1), 0.5),
        (ConfigField("t", "x", "bool", False), True),
        (ConfigField("m", "x", "multiline", ""), "hi"),
        (ConfigField("p", "x", "file", ""), "C:/a.png"),
        (ConfigField("s", "x", "text", ""), "plain"),
    ]:
        w = param_editor(field, value, lambda v, k=field.key: seen.__setitem__(k, v))
        assert w is not None
    assert seen == {}


def test_main_window_registers_workflow(qapp, tmp_path, monkeypatch):
    from src import config
    from src.app import register_pages
    from src.ui.main_window import MainWindow
    from src.ui.workflow import page as page_mod

    monkeypatch.setattr(config, "_settings", Settings(tmp_path / "settings.json"))
    monkeypatch.setattr(config, "app_data_dir", lambda: tmp_path)
    window = MainWindow()
    register_pages(window)
    window.switch_page("workflow")
    page = window.page("workflow")
    assert isinstance(page, page_mod.WorkflowPage)
    assert page.data_dir == tmp_path / "workflows"
    window.close()
