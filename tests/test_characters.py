"""Phase 6: characters library store, attaching characters to rows, and the Characters page.

No network: provider requests go through httpx.MockTransport.
"""

from __future__ import annotations

import base64
import io
import json
import struct
import time
import wave

import httpx
import pytest
from PIL import Image

from src.characters import attach as char_attach
from src.characters.store import CharacterStore
from src.characters.voices import (
    VOICE_NAMES, VOICES, as_wav, build_preview_request, parse_audio, preview_voice, voice_label,
)
from src.config import Settings
from src.gen.models import Job
from src.gen.provider import ProviderError


def png(path, color=(200, 10, 10)):
    Image.new("RGB", (4, 4), color).save(path, "PNG")
    return path


@pytest.fixture
def images(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    return [png(src / "mia_front.png"), png(src / "mia_side.png", (10, 200, 10))]


@pytest.fixture
def store(tmp_path):
    return CharacterStore(tmp_path / "characters")


def run_until(qapp, cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


# ---- store -----------------------------------------------------------
def test_add_edit_delete_persist(store, images, tmp_path):
    mia = store.add("Mia", notes="red jacket", voice="Kore", images=images)
    assert mia.refs == ["mia_front.png", "mia_side.png"]
    assert all(p.is_file() and p.parent == store.folder(mia.id) for p in store.ref_paths(mia.id))
    bob = store.add("Bob")

    store.update(mia.id, name="Mia Chen", notes="blue jacket", voice="Puck")
    again = CharacterStore(tmp_path / "characters")
    got = again.get(mia.id)
    assert (got.name, got.notes, got.voice, got.refs) == ("Mia Chen", "blue jacket", "Puck", mia.refs)
    assert [c.name for c in again.all()] == ["Mia Chen", "Bob"]
    assert again.by_name("mia chen").id == mia.id

    assert store.delete(mia.id)
    assert not store.folder(mia.id).exists()
    assert [c.id for c in CharacterStore(tmp_path / "characters").all()] == [bob.id]
    assert not store.delete("nope")


def test_refs_add_remove_and_name_clash(store, images):
    char = store.add("Mia", images=images[:1])
    added = store.add_refs(char.id, [images[0], images[1], images[0].with_suffix(".txt")])
    assert added == ["mia_front_2.png", "mia_side.png"]  # copy never overwrites, non-images skipped
    assert store.remove_ref(char.id, "mia_front.png")
    assert not (store.folder(char.id) / "mia_front.png").exists()
    assert [p.name for p in store.ref_paths(char.id)] == ["mia_front_2.png", "mia_side.png"]
    assert not store.remove_ref(char.id, "missing.png")
    with pytest.raises(KeyError):
        store.update("nope", name="x")


def test_bad_index_file_loads_empty(tmp_path):
    root = tmp_path / "characters"
    root.mkdir()
    (root / "characters.json").write_text("{not json", encoding="utf-8")
    assert CharacterStore(root).all() == []


def test_listeners_called_on_save(store):
    calls = []
    store.subscribe(lambda: calls.append(1))
    store.add("Mia")
    assert calls == [1]


# ---- attaching -------------------------------------------------------
def test_attach_detach_keeps_own_refs(store, images, tmp_path):
    mia = store.add("Mia", images=images)
    own = png(tmp_path / "own.png")
    job = Job("Mia walks", refs=[own])

    assert char_attach.attach(job, mia.id, store) == 2
    assert job.character == mia.id
    assert [p.name for p in job.refs] == ["mia_front.png", "mia_side.png", "own.png"]

    # Character images change: sync picks up the new set and still keeps the row's own ref.
    store.remove_ref(mia.id, "mia_side.png")
    char_attach.sync(job, store)
    assert [p.name for p in job.refs] == ["mia_front.png", "own.png"]

    char_attach.detach(job)
    assert job.refs == [own] and job.character == "" and job.character_refs == []


def test_attach_deleted_character_clears(store, images):
    mia = store.add("Mia", images=images)
    job = Job("x")
    char_attach.attach(job, mia.id, store)
    store.delete(mia.id)
    char_attach.sync(job, store)
    assert job.refs == [] and job.character == ""


def test_match_by_name(store, images):
    mia = store.add("Mia", images=images[:1])
    cap = store.add("Captain Mia", images=images[1:])
    jobs = [Job("Captain Mia salutes"), Job("mia eats lunch"), Job("Miami beach"), Job("Mia again")]
    jobs[3].character = cap.id
    assert char_attach.match_by_name(jobs, store) == 2
    assert [j.character for j in jobs] == [cap.id, mia.id, "", cap.id]


# ---- refs reach the provider ------------------------------------------
def _gen_store(tmp_path, key):
    s = Settings(tmp_path / "settings.json")
    for k, v in {"save_dir": str(tmp_path / "out"), "delay_min": 0.0, "delay_max": 0.0,
                 "subdir_mode": "batch", "max_retries": 0}.items():
        s.set(f"pages.{key}.{k}", v)
    return s


def test_character_refs_reach_gemini_request(qapp, tmp_path, store, images):
    from src.gen.gemini_image import GeminiImageProvider
    from src.ui.generator.page import GeneratorPage
    from src.ui.generator.prompt_model import COL_REFS

    sent: list[dict] = []
    out_png = base64.b64encode(images[0].read_bytes()).decode()

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"inlineData": {"mimeType": "image/png", "data": out_png}}]}, "finishReason": "STOP"}]})

    mia = store.add("Mia", images=images)
    provider = GeminiImageProvider(key_source=lambda: "k", transport=httpx.MockTransport(handler))
    page = GeneratorPage("t_gem", provider, store=_gen_store(tmp_path, "t_gem"), characters=store)
    page.add_prompts(["Mia on a beach", "an empty room"])
    page.set_character([0], mia.id)
    assert page.model.data(page.model.index(0, COL_REFS)) == "@Mia 2"

    assert page.start() == 2
    assert run_until(qapp, lambda: not page.queue.is_running() and len(sent) == 2)
    page.shutdown()

    by_prompt = {}
    for body in sent:
        parts = body["contents"][0]["parts"]
        text = next(p["text"] for p in parts if "text" in p)
        by_prompt[text] = [p for p in parts if "inlineData" in p or "inline_data" in p]
    want = {base64.b64encode(p.read_bytes()).decode() for p in images}
    got = {(p.get("inlineData") or p.get("inline_data"))["data"] for p in by_prompt["Mia on a beach"]}
    assert got == want
    assert by_prompt["an empty room"] == []


def test_match_characters_button_and_openai_edit(qapp, tmp_path, store, images):
    from src.gen.openai_image import OpenAIImageProvider
    from src.ui.generator.page import GeneratorPage

    calls: list[httpx.Request] = []
    b64 = base64.b64encode(images[0].read_bytes()).decode()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"created": 1, "output_format": "png", "data": [{"b64_json": b64}]})

    store.add("Mia", images=images[1:])
    provider = OpenAIImageProvider(key_source=lambda: "k", transport=httpx.MockTransport(handler))
    page = GeneratorPage("t_oai", provider, store=_gen_store(tmp_path, "t_oai"), characters=store)
    page.add_prompts(["portrait of Mia"])
    assert page.match_characters() == 1
    assert page.start() == 1
    assert run_until(qapp, lambda: not page.queue.is_running() and calls)
    page.shutdown()
    assert calls[0].url.path.endswith("/images/edits")
    assert images[1].read_bytes() in calls[0].content


def test_table_context_signal_detaches(qapp, tmp_path, store, images):
    from src.gen.fake_provider import FakeProvider
    from src.ui.generator.page import GeneratorPage

    mia = store.add("Mia", images=images)
    page = GeneratorPage("t_fake", FakeProvider(), store=_gen_store(tmp_path, "t_fake"), characters=store)
    page.add_prompts(["a", "b"])
    assert page.table.characters_source() == [(mia.id, "Mia")]
    page.table.character_requested.emit([0, 1], mia.id)
    assert all(j.character == mia.id and len(j.refs) == 2 for j in page.jobs)
    page.table.character_requested.emit([1], "")
    assert page.jobs[1].refs == [] and page.jobs[0].character == mia.id
    page.shutdown()


# ---- voices ----------------------------------------------------------
def test_voice_list():
    assert len(VOICES) == 30 and len(set(VOICE_NAMES)) == 30
    assert voice_label("Kore") == "Kore (Firm)"
    url, body = build_preview_request("hi", "Kore")
    assert url.endswith("/interactions")
    assert body["generation_config"]["speech_config"] == [{"voice": "Kore"}]
    assert body["response_format"] == {"type": "audio"}
    with pytest.raises(ValueError):
        build_preview_request("hi", "Nobody")


def test_pcm_gets_wav_header():
    pcm = struct.pack("<4h", 0, 1000, -1000, 0)
    wav = as_wav(pcm, "audio/l16")
    with wave.open(io.BytesIO(wav)) as w:
        assert (w.getframerate(), w.getnchannels(), w.readframes(4)) == (24000, 1, pcm)
    assert as_wav(wav, "audio/wav") == wav
    with pytest.raises(ProviderError):
        parse_audio({"outputs": [{"type": "text", "text": "no"}]})


def _wav_reply():
    wav = as_wav(b"\x00\x00" * 10, "audio/l16")
    return {"status": "completed", "outputs": [
        {"type": "audio", "mime_type": "audio/wav", "data": base64.b64encode(wav).decode()}]}


def test_preview_voice_mocked():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=_wav_reply())

    wav = preview_voice("Puck", "hello", key_source=lambda: "k", transport=httpx.MockTransport(handler))
    assert wav[:4] == b"RIFF"
    assert seen[0].headers["x-goog-api-key"] == "k" and "k" not in str(seen[0].url)
    with pytest.raises(ProviderError):
        preview_voice("Puck", "hello", key_source=lambda: "")


# ---- page ------------------------------------------------------------
def test_characters_page_create_edit_delete(qapp, store, images):
    from src.ui.characters.page import CharactersPage

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=_wav_reply())

    page = CharactersPage(store, key_source=lambda: "k", transport=httpx.MockTransport(handler))
    page._play = lambda path: calls.append(path)  # no audio device in tests
    assert page.empty.isVisibleTo(page) and page.list.count() == 0

    cid = page.new_character()
    page.name_edit.setText("Mia")
    page.notes_edit.setPlainText("red jacket")
    page.voice_combo.setCurrentIndex(page.voice_combo.findData("Kore"))
    page.save_current()
    assert store.get(cid).name == "Mia" and store.get(cid).voice == "Kore"
    assert page.add_images(images) == 2 and page.refs.count() == 2

    page.refs.item(0).setSelected(True)
    assert page.remove_selected_refs() == 1 and len(store.get(cid).refs) == 1

    # Duplicate names are refused.
    other = page.new_character()
    page.name_edit.setText("mia")
    page.save_current()
    assert store.get(other).name != "mia" and "already" in page.status.text()

    # Preview: one mocked TTS call, then the cached file is reused.
    page.reload(cid)
    page.preview()
    assert run_until(qapp, lambda: len(calls) == 2)
    assert (store.root / "_previews" / "Kore.wav").is_file()
    page.preview()
    assert len([c for c in calls if isinstance(c, httpx.Request)]) == 1

    page.delete_current(confirm=False)
    assert store.get(cid) is None and page.list.count() == 1


def test_main_window_registers_characters(qapp, tmp_path, monkeypatch):
    from src import config
    from src.app import register_pages
    from src.characters import store as store_mod
    from src.ui.characters.page import CharactersPage
    from src.ui.main_window import MainWindow

    monkeypatch.setattr(config, "_settings", Settings(tmp_path / "settings.json"))
    monkeypatch.setattr(store_mod, "_default", CharacterStore(tmp_path / "characters"))
    window = MainWindow()
    register_pages(window)
    window.switch_page("characters")
    assert isinstance(window.page("characters"), CharactersPage)
    window.close()
