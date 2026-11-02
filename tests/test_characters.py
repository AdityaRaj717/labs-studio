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


def test_table_context_signal_detaches(qapp, tmp_path, store, images):
    from fake_provider import FakeProvider
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


# ---- page ------------------------------------------------------------
def test_characters_page_create_edit_delete(qapp, store, images):
    from src.ui.characters.page import CharactersPage

    page = CharactersPage(store)
    assert page.empty.isVisibleTo(page) and page.list.count() == 0

    cid = page.new_character()
    page.name_edit.setText("Mia")
    page.notes_edit.setPlainText("red jacket")
    page.save_current()
    assert store.get(cid).name == "Mia"
    assert page.add_images(images) == 2 and page.refs.count() == 2

    page.refs.item(0).setSelected(True)
    assert page.remove_selected_refs() == 1 and len(store.get(cid).refs) == 1

    # Duplicate names are refused.
    other = page.new_character()
    page.name_edit.setText("mia")
    page.save_current()
    assert store.get(other).name != "mia" and "already" in page.status.text()

    page.reload(cid)
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
