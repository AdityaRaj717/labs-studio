"""Phase 14b: global character and scene library with a ``flow`` map, the Flow sync,
Scene rows, ``characters``/``scenes`` through the provider, MCP and webhook, and the
Flow-only switch that hides what does not work yet."""

from __future__ import annotations

import json
import time

import pytest
from PIL import Image

from src.characters import attach
from src.characters.flow_sync import FlowSync, SyncError, used_in_rows
from src.characters.store import CharacterStore
from src.config import Settings
from src.gen.models import Job
from src.projects.store import job_to_row, row_to_job
from src.web.mcp_client import McpToolError

A = "https://flow.google.com/project/aaa"
B = "https://flow.google.com/project/bbb"


def png(path, color="red"):
    Image.new("RGB", (8, 8), color).save(path)
    return path


@pytest.fixture
def libs(tmp_path):
    return CharacterStore(tmp_path / "characters"), CharacterStore(tmp_path / "scenes", kind="scene")


@pytest.fixture
def img(tmp_path):
    return png(tmp_path / "face.png")


class FakeMcp:
    """Records tool calls; answers like the google-flow MCP."""

    def __init__(self, present=()):
        self.calls: list[tuple[str, dict]] = []
        self.present = list(present)
        self.fail: dict[str, str] = {}

    def __call__(self, tool, args, timeout):
        self.calls.append((tool, dict(args)))
        if tool in self.fail:
            raise McpToolError(self.fail[tool], {"error_code": self.fail[tool]})
        if tool == "flow_list_characters":
            return {"status": "success", "characters": [{"name": n} for n in self.present]}
        if tool == "flow_import_character":
            self.present.append(args["name"])
            return {"status": "success", "name": args["name"], "created": True,
                    "imported_from": args["from_project_url"]}
        self.present.append(args["name"])
        return {"status": "success", "name": args["name"], "created": True}


# ---- library ----------------------------------------------------------------
def test_flow_map_persists_and_scene_store_is_separate(libs, img):
    chars, scenes = libs
    mia = chars.add("Mia", images=[img])
    bunker = scenes.add("Bunker", notes="a concrete bunker", images=[img])
    chars.set_flow(mia.id, A, "Mia")
    scenes.set_flow(bunker.id, A, "Bunker")
    assert chars.index_path.name == "characters.json" and scenes.index_path.name == "scenes.json"

    again = CharacterStore(chars.root)
    assert again.get(mia.id).flow == {A: "Mia"}
    assert CharacterStore(scenes.root, kind="scene").by_name("bunker").flow == {A: "Bunker"}
    assert again.drop_flow(mia.id, A) and not again.drop_flow(mia.id, A)
    assert CharacterStore(chars.root).get(mia.id).flow == {}
    # an old index without "flow" still loads
    data = json.loads(chars.index_path.read_text())
    data["characters"][0].pop("flow")
    chars.index_path.write_text(json.dumps(data))
    assert CharacterStore(chars.root).get(mia.id).flow == {}


def test_scenes_and_cast_on_rows(libs, tmp_path):
    chars, scenes = libs
    surv = chars.add("Survivor", images=[png(tmp_path / "s.png")])
    stranger = chars.add("Stranger", images=[png(tmp_path / "t.png", "blue")])
    bunker = scenes.add("Bunker", images=[png(tmp_path / "b.png", "gray")])
    own = png(tmp_path / "own.png", "green")
    jobs = [Job("The Survivor meets the Stranger in the Bunker", refs=[own]), Job("an empty street")]

    assert attach.match_by_name(jobs, chars, scenes) == 1
    job = jobs[0]
    assert attach.character_ids(job) == [surv.id, stranger.id] and job.scenes == [bunker.id]
    assert [p.name for p in job.refs] == ["s.png", "t.png", "b.png", "own.png"]
    assert attach.character_label(job, chars) == "Survivor, Stranger"
    assert attach.scene_label(job, scenes) == "Bunker"

    back = row_to_job(job_to_row(job), 1)
    assert back.cast == [stranger.id] and back.scenes == [bunker.id] and back.scene_refs == job.scene_refs
    assert used_in_rows([job_to_row(job), job_to_row(jobs[1])]) == ([surv.id, stranger.id], [bunker.id])

    attach.set_scenes(job, [], scenes)
    attach.detach(job)
    assert job.refs == [own] and job.cast == [] and job.scenes == []


# ---- sync -------------------------------------------------------------------
def test_ensure_creates_from_first_image_then_reuses(libs, img):
    chars, scenes = libs
    mia = chars.add("Mia", notes="red scarf", images=[img])
    bunker = scenes.add("Bunker", notes="a concrete bunker", images=[img])
    mcp = FakeMcp()
    sync = FlowSync(mcp, chars, scenes)

    assert sync.ensure("character", mia.id, A) == "Mia"
    assert sync.ensure("scene", bunker.id, A) == "Bunker"
    assert sync.ensure("character", mia.id, A) == "Mia"  # recorded: no second call
    tools = [t for t, _ in mcp.calls]
    assert tools == ["flow_create_character", "flow_create_scene"]
    args = mcp.calls[0][1]
    assert args["project_url"] == A and args["info"] == "red scarf" and args["images"][0].endswith("face.png")
    assert "prompt" not in args and "auto_confirm" not in args
    assert chars.get(mia.id).flow == {A: "Mia"} and scenes.get(bunker.id).flow == {A: "Bunker"}


def test_ensure_imports_from_another_project_and_falls_back(libs, img):
    chars, scenes = libs
    mia = chars.add("Mia", images=[img])
    chars.set_flow(mia.id, A, "Mia F")
    mcp = FakeMcp()
    sync = FlowSync(mcp, chars, scenes)
    assert sync.ensure("character", mia.id, B) == "Mia F"
    assert mcp.calls == [("flow_import_character", {"project_url": B, "from_project_url": A, "name": "Mia F"})]
    assert chars.get(mia.id).flow == {A: "Mia F", B: "Mia F"}

    # the source project is gone: create it from the image instead
    other = chars.add("Max", images=[img])
    chars.set_flow(other.id, A, "Max")
    mcp.fail["flow_import_character"] = "PROJECT_NOT_FOUND"
    assert sync.ensure("character", other.id, B) == "Max"
    assert [t for t, _ in mcp.calls[-2:]] == ["flow_import_character", "flow_create_character"]


def test_ensure_without_images_generates_from_notes_or_fails(libs):
    chars, scenes = libs
    ghost = chars.add("Ghost", notes="a pale figure in a torn coat")
    empty = scenes.add("Nowhere")
    mcp = FakeMcp()
    sync = FlowSync(mcp, chars, scenes)
    sync.ensure("character", ghost.id, A)
    assert mcp.calls[0][1]["prompt"] == "a pale figure in a torn coat" and mcp.calls[0][1]["auto_confirm"] is True
    with pytest.raises(SyncError, match="Nowhere"):
        sync.ensure("scene", empty.id, A)
    out = sync.sync(A, [ghost.id], [empty.id], verify=False)
    assert out["characters"] == {ghost.id: "Ghost"} and out["scenes"] == {} and len(out["errors"]) == 1


def test_verify_forgets_entries_deleted_in_flow_once_per_session(libs, img):
    chars, scenes = libs
    mia = chars.add("Mia", images=[img])
    bunker = scenes.add("Bunker", images=[img])
    chars.set_flow(mia.id, A, "Mia")
    scenes.set_flow(bunker.id, A, "Bunker")
    mcp = FakeMcp(present=["Mia"])  # Bunker was deleted in Flow
    sync = FlowSync(mcp, chars, scenes)

    assert sync.names(A, [mia.id], [bunker.id]) == (["Mia"], ["Bunker"])
    assert [t for t, _ in mcp.calls] == ["flow_list_characters", "flow_create_scene"]
    sync.names(A, [mia.id], [bunker.id])
    assert len(mcp.calls) == 2  # listed once, both recorded now


# ---- provider and MCP --------------------------------------------------------
class FakeBackend:
    def __init__(self, out):
        self.out = out
        self.calls = []

    def generate_image(self, args, timeout, **extra):
        self.calls.append((args, extra))
        return {"status": "success", "files": [str(png(self.out / "o.png"))]}


class FakePacer:
    cap = 0

    def cap_reached(self):
        return False

    def wait_turn(self, should_stop):
        return True

    def record_use(self):
        return 1

    def mark_done(self):
        pass


def test_provider_passes_library_ids_not_their_images(tmp_path, libs):
    from src.gen.provider import RunContext
    from src.gen.web_flow_image import WebFlowImageProvider

    chars, scenes = libs
    surv = chars.add("Survivor", images=[png(tmp_path / "s.png")])
    bunker = scenes.add("Bunker", images=[png(tmp_path / "b.png")])
    own = png(tmp_path / "own.png")
    job = Job("Survivor in the Bunker", refs=[own])
    attach.attach(job, surv.id, chars)
    attach.set_scenes(job, [bunker.id], scenes)
    (tmp_path / "gen").mkdir()
    backend = FakeBackend(tmp_path / "gen")
    provider = WebFlowImageProvider(backend=backend, pacer=FakePacer(), session=object(), out_root=tmp_path / "o")
    ctx = RunContext(should_stop=lambda: False, progress=lambda f: None)
    files = provider.generate(job, {"model": "Nano Banana 2", "aspect": "1:1"}, ctx)
    args, extra = backend.calls[0]
    assert extra == {"characters": [surv.id], "scenes": [bunker.id]}
    assert args["reference_images"] == [str(own.resolve())] and len(files) == 1

    plain = Job("no library", refs=[own])
    provider.generate(plain, {}, ctx)
    assert backend.calls[1][1] == {}


def test_flow_mcp_sets_characters_up_before_the_job(tmp_path, monkeypatch, img):
    from src import projects
    from src.characters import store as store_mod
    from tests.test_mcp_client import make_flow

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    settings = Settings(tmp_path / "settings.json")
    pstore = projects.install(settings)
    try:
        chars, scenes = store_mod.default_store(), store_mod.scene_store()
        mia = chars.add("Mia", images=[img])
        bunker = scenes.add("Bunker", images=[img])
        flow, clients, _ = make_flow(tmp_path)
        flow.generate_image({"prompt": "Mia in the Bunker"}, timeout=60, characters=[mia.id], scenes=[bunker.id])
        names = [n for n, _ in clients[0].calls]
        assert names == ["flow_connect", "flow_open_project", "flow_list_characters",
                         "flow_create_character", "flow_create_scene", "flow_generate_image"]
        url = pstore.active.flow_url
        gen = clients[0].calls[-1][1]
        assert gen["project_url"] == url and gen["characters"] == ["Mia"] and gen["scenes"] == ["Bunker"]
        assert chars.get(mia.id).flow == {url: "Mia"}

        # on switch: everything the saved rows use
        job = Job("Mia again")
        attach.attach(job, mia.id, chars)
        pstore.active.set_rows("flow_image", [job_to_row(job)])
        res = flow.sync_project(pstore.active)
        assert res["characters"] == {mia.id: "Mia"} and not res["errors"]
        assert [n for n, _ in clients[0].calls][-1] == "flow_generate_image"  # nothing new to set up
    finally:
        projects.uninstall()


# ---- webhook ----------------------------------------------------------------
def test_parse_submit_characters_and_scenes():
    from src.webhook.server import ApiError, parse_submit

    req = parse_submit({"page": "flow_image", "prompt": "x", "character": "Mia",
                        "characters": ["Max", "Mia"], "scenes": [" Bunker "]})
    assert req["characters"] == ["Mia", "Max"] and req["scenes"] == ["Bunker"]
    for bad in ({"characters": "Mia"}, {"scenes": [""]}, {"scenes": [3]}):
        with pytest.raises(ApiError):
            parse_submit({"page": "p", "prompt": "x", **bad})


def test_webhook_attaches_characters_and_scenes(qapp, tmp_path, libs):
    from src.gen.fake_provider import FakeProvider
    from src.ui.generator.page import GeneratorPage
    from src.ui.webhook.backend import PageBackend
    from src.webhook.server import ApiError

    chars, scenes = libs
    surv = chars.add("Survivor", images=[png(tmp_path / "s.png")])
    stranger = chars.add("Stranger")
    bunker = scenes.add("Bunker", images=[png(tmp_path / "b.png")])
    store = Settings(tmp_path / "settings.json")
    store.set("pages.demo.save_dir", str(tmp_path / "out"))
    page = GeneratorPage("demo", FakeProvider(), store=store, characters=chars, scenes=scenes)
    backend = PageBackend(lambda key: page, page_keys=("demo",))
    try:
        out = backend.submit({"page": "demo", "prompts": ["a"], "characters": ["survivor", "Stranger"],
                              "scenes": ["Bunker"], "start": False})
        job = page.jobs[0]
        assert attach.character_ids(job) == [surv.id, stranger.id] and job.scenes == [bunker.id]
        assert out["jobs"][0]["characters"] == [surv.id, stranger.id] and out["jobs"][0]["scenes"] == [bunker.id]
        with pytest.raises(ApiError, match="no scene named 'Lab'"):
            backend.submit({"page": "demo", "prompts": ["b"], "scenes": ["Lab"], "start": False})
    finally:
        page.shutdown()


# ---- UI ---------------------------------------------------------------------
def test_scene_column_and_menu_actions(qapp, tmp_path, libs):
    from src.gen.fake_provider import FakeProvider
    from src.ui.generator.page import GeneratorPage
    from src.ui.generator.prompt_model import COL_CHARACTER, COL_SCENE

    chars, scenes = libs
    surv = chars.add("Survivor")
    stranger = chars.add("Stranger")
    bunker = scenes.add("Bunker")
    store = Settings(tmp_path / "settings.json")
    page = GeneratorPage("t", FakeProvider(), store=store, characters=chars, scenes=scenes)
    try:
        page.add_prompts(["a", "b"])
        page.table.character_requested.emit([0], surv.id)
        page.table.character_added.emit([0], stranger.id)
        page.table.scene_requested.emit([0, 1], bunker.id)
        m = page.model
        assert m.data(m.index(0, COL_CHARACTER)) == "Survivor, Stranger"
        assert m.data(m.index(1, COL_SCENE)) == "Bunker" and m.data(m.index(1, COL_CHARACTER)) == ""
        page.table.scene_requested.emit([1], "")
        assert page.jobs[1].scenes == [] and page.table.scenes_source() == [(bunker.id, "Bunker")]
    finally:
        page.shutdown()


def test_scenes_page_and_setup_in_flow(qapp, libs, img):
    from src.ui.characters.page import CharactersPage

    _, scenes = libs
    seen = []
    page = CharactersPage(scenes, kind="scene", flow_setup=lambda kind, eid: (
        seen.append((kind, eid)), scenes.set_flow(eid, A, "Bunker")))
    sid = page.new_character()
    assert scenes.get(sid).name == "New scene" and not page.voice_row_shown
    page.add_images([img])
    page.name_edit.setText("Bunker")  # unsaved: setting up in Flow saves it first
    page.setup_in_flow()
    end = time.monotonic() + 5
    while not seen or not page.btn_flow.isEnabled():
        qapp.processEvents()
        assert time.monotonic() < end
    assert seen == [("scene", sid)] and scenes.get(sid).name == "Bunker"
    assert "Bunker" in page.flow_label.toolTip()


# ---- Flow-only switch -------------------------------------------------------
def test_flow_only_switch(monkeypatch, tmp_path):
    from src import config, features

    monkeypatch.setattr(config, "_settings", Settings(tmp_path / "s.json"))
    monkeypatch.delenv(features.ENV, raising=False)
    assert features.flow_only()  # the default
    assert not features.page_shown("grok") and features.page_shown("flow_image")
    assert features.page_shown("scenes") and features.page_shown("characters") and features.page_shown("projects")
    assert not features.shown("provider:gemini_image") and not features.shown("settings:api_keys")
    assert features.visible_pages(("flow_image", "flow_video", "demo")) == ("flow_image",)
    config.set("features.flow_only", False)
    assert features.page_shown("grok") and features.shown("settings:api_keys")
    monkeypatch.setenv(features.ENV, "flow")
    assert not features.page_shown("grok")


def test_app_in_flow_only_mode_shows_only_working_features(qapp, monkeypatch, tmp_path):
    from src import config, features
    from src.app import register_pages
    from src.gen.web_flow_image import WebFlowImageProvider
    from src.ui.main_window import MainWindow

    monkeypatch.setattr(config, "_settings", Settings(tmp_path / "s.json"))
    monkeypatch.setenv(features.ENV, "flow")
    window = MainWindow()
    try:
        register_pages(window)
        shown = [k for k, b in window.sidebar.buttons.items() if not b.isHidden()]
        assert shown == ["flow_image", "projects", "characters", "scenes", "webhook", "log", "settings", "help"]
        img_page = window.page("flow_image")
        assert isinstance(img_page.provider, WebFlowImageProvider) and img_page.provider_combo is None
        tabs = window.page("settings").tabs
        assert [tabs.tabText(i) for i in range(tabs.count())] == ["Web Sessions"]
        assert not window.page("characters").voice_row_shown
        wh = window.page("webhook")
        assert wh.backend.page_keys == ("flow_image",) and wh.btn_demo.isHidden()
        wh.shutdown()
    finally:
        window.close()
