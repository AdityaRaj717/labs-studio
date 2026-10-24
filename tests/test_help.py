"""Phase 15: help topics, search, links, images, screenshot specs, Help page and "?" buttons."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.help import shots
from src.help import topics as help_topics

HELP = help_topics.help_dir()
EN = HELP / "en"


@pytest.fixture(scope="module")
def topics():
    return help_topics.load_topics("en")


def test_help_folder_is_found():
    assert EN.is_dir()
    assert (EN / help_topics.INDEX_FILE).is_file()


def test_topics_load_in_readme_order_with_titles(topics):
    order = help_topics.topic_order(EN)
    assert [t.id for t in topics] == order
    assert order[0] == "getting-started"
    for t in topics:
        assert t.title and t.title != t.id, t.id
        assert t.text.startswith(f"# {t.title}")


def test_every_topic_file_is_in_the_readme(topics):
    files = {p.stem for p in EN.glob("*.md") if p.name != help_topics.INDEX_FILE}
    assert files == {t.id for t in topics}


def test_required_topics_exist(topics):
    ids = {t.id for t in topics}
    for tid in ("getting-started", "google-flow-sign-in", "flow-image", "projects", "characters-and-scenes",
                "api-generators", "video-tools", "video-editor", "workflow", "webhook-api", "mcp-agents",
                "troubleshooting", "terms-and-risks"):
        assert tid in ids, tid


def test_search_finds_and_ranks(topics):
    assert help_topics.search(topics, "") == topics
    hits = help_topics.search(topics, "curl")
    assert hits and hits[0].id == "webhook-api"
    hits = help_topics.search(topics, "Claude Desktop config")
    assert hits[0].id == "mcp-agents"
    assert help_topics.search(topics, "zzqx-not-a-word") == []
    # every word must match somewhere
    assert all("token" in t.text.lower() and "lan" in t.text.lower()
               for t in help_topics.search(topics, "token lan"))


def _all_md():
    return [EN / help_topics.INDEX_FILE] + sorted(p for p in EN.glob("*.md") if p.name != help_topics.INDEX_FILE)


@pytest.mark.parametrize("path", _all_md(), ids=lambda p: p.name)
def test_every_link_resolves(path):
    topic = help_topics.Topic(path.stem, "", path, path.read_text(encoding="utf-8"))
    for target in help_topics.links(topic):
        if help_topics.is_external(target):
            assert target.startswith("https://"), target
            continue
        tid, _ = help_topics.resolve_link(topic, target)
        assert tid is not None, f"{path.name}: unsupported link {target}"
        assert (EN / f"{tid}.md").is_file(), f"{path.name}: broken link {target}"


@pytest.mark.parametrize("path", _all_md(), ids=lambda p: p.name)
def test_every_image_exists(path):
    topic = help_topics.Topic(path.stem, "", path, path.read_text(encoding="utf-8"))
    for target in help_topics.images(topic):
        assert not help_topics.is_external(target), target
        assert (EN / target).is_file(), f"{path.name}: missing image {target}"


def test_every_screenshot_has_a_spec_and_every_spec_validates():
    specs = shots.load_specs(EN)
    assert specs
    pngs = {p.stem for p in (EN / "img").glob("*.png")}
    assert pngs == set(specs), "every png comes from a spec, and every spec has a png"
    for name, spec in specs.items():
        assert shots.validate_spec(spec) == [], name


def test_images_are_used_by_topics(topics):
    used = {Path(i).stem for t in topics for i in help_topics.images(t)}
    assert used == {p.stem for p in (EN / "img").glob("*.png")}


def test_numbered_list_matches_callouts(topics):
    """The numbered list right under an image has one item per callout."""
    specs = shots.load_specs(EN)
    for t in topics:
        lines = t.text.splitlines()
        for i, line in enumerate(lines):
            if not line.startswith("![") or "](img/" not in line:
                continue
            name = Path(line.split("](", 1)[1].rstrip(")")).stem
            n = 0
            for nxt in lines[i + 2:]:
                if not nxt.startswith(f"{n + 1}. "):
                    break
                n += 1
            assert n == len(specs[name]["callouts"]), f"{t.id}: {name} has {len(specs[name]['callouts'])} callouts, list has {n}"


@pytest.mark.parametrize("bad, fragment", [
    ([], "JSON object"),
    ({}, "'page'"),
    ({"page": "x", "features": "some"}, "'features'"),
    ({"page": "x", "size": [10, 10]}, "'size'"),
    ({"page": "x", "callouts": [{"n": 1}]}, "exactly one of"),
    ({"page": "x", "callouts": [{"n": 1, "target": "a"}, {"n": 1, "target": "b"}]}, "used twice"),
    ({"page": "x", "callouts": [{"n": 2, "target": "a"}]}, "no gaps"),
    ({"page": "x", "callouts": [{"n": 1, "target": "a", "shape": "arrow"}]}, "'from'"),
    ({"page": "x", "callouts": [{"n": 1, "target": "a", "badge": "middle"}]}, "'badge'"),
    ({"page": "x", "callouts": [{"n": 1, "rect": [0, 0, 0, 5]}]}, "'rect'"),
    ({"page": "x", "colour": "red"}, "unknown key"),
])
def test_validate_spec_rejects(bad, fragment):
    errors = shots.validate_spec(bad)
    assert any(fragment in e for e in errors), errors


def test_validate_spec_accepts_minimal():
    assert shots.validate_spec({"page": "flow_image"}) == []
    assert shots.validate_spec({"page": "log", "callouts": [
        {"n": 1, "target": ["a", "b/c"], "shape": "arrow", "from": [10, -20]},
        {"n": 2, "rect": [1, 2, 3, 4]}]}) == []


def test_specs_name_real_pages_and_setups():
    from src.ui.sidebar import NAV_KEYS
    import importlib.util

    spec = importlib.util.spec_from_file_location("shots_tool", Path(__file__).parents[1] / "tools" / "make_help_screenshots.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    for name, s in shots.load_specs(EN).items():
        assert s["page"] in NAV_KEYS, name
        if "setup" in s:
            assert s["setup"] in tool.SETUPS, name


def test_page_topics_exist(topics):
    from src.ui.main_window import PAGE_TOPICS
    from src.ui.sidebar import NAV_KEYS

    ids = {t.id for t in topics}
    for key, tid in PAGE_TOPICS.items():
        assert tid in ids, (key, tid)
        assert key in NAV_KEYS or key == "demo", key


def test_load_topics_falls_back_to_english(tmp_path):
    (tmp_path / "en").mkdir()
    (tmp_path / "en" / "README.md").write_text("[A](a.md)\n[B](b.md)\n", encoding="utf-8")
    (tmp_path / "en" / "a.md").write_text("# Alpha\n", encoding="utf-8")
    (tmp_path / "en" / "b.md").write_text("# Beta\n", encoding="utf-8")
    (tmp_path / "de").mkdir()
    (tmp_path / "de" / "a.md").write_text("# Alfa\n", encoding="utf-8")
    got = help_topics.load_topics("de", tmp_path)
    assert [(t.id, t.title) for t in got] == [("a", "Alfa"), ("b", "Beta")]


# ---- the Help page ------------------------------------------------------
def test_help_page_opens_topics_and_follows_links(qapp):
    from PySide6.QtCore import QUrl

    from src.ui.help.page import HelpPage

    page = HelpPage("en")
    assert page.topic_list.count() == len(page.topics)
    assert page.current.id == "getting-started"
    assert page.open_topic("webhook-api")
    assert "curl" in page.view.toPlainText()
    assert page.topic_list.currentItem().data(0x0100) == "webhook-api"

    page._on_link(QUrl("projects.md"))
    assert page.current.id == "projects"
    page.back()
    assert page.current.id == "webhook-api"
    page.forward()
    assert page.current.id == "projects"
    assert not page.open_topic("no-such-topic")


def test_help_page_search_filters_list(qapp):
    from src.ui.help.page import HelpPage

    page = HelpPage("en")
    page.search_edit.setText("codex")
    ids = [page.topic_list.item(i).data(0x0100) for i in range(page.topic_list.count())]
    assert ids and ids[0] == "mcp-agents"
    assert page.current.id in ids
    page.search_edit.setText("")
    assert page.topic_list.count() == len(page.topics)


def test_help_page_scales_images_to_the_view(qapp):
    from PySide6.QtGui import QTextImageFormat

    from src.ui.help.page import HelpPage

    page = HelpPage("en")
    page.resize(700, 600)
    page.show()
    qapp.processEvents()
    page.open_topic("flow-image")
    widths = []
    block = page.view.document().begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            fmt = it.fragment().charFormat()
            if fmt.isImageFormat():
                widths.append(QTextImageFormat(fmt.toImageFormat()).width())
            it += 1
        block = block.next()
    page.hide()
    assert widths and all(0 < w <= page.view.viewport().width() for w in widths)


def test_help_buttons_open_their_topic(qapp, tmp_path, monkeypatch):
    from src import config
    from src.app import register_pages
    from src.config import Settings
    from src.ui.main_window import PAGE_TOPICS, MainWindow

    monkeypatch.setattr(config, "_settings", Settings(tmp_path / "s.json"))
    window = MainWindow()
    register_pages(window)
    try:
        for key in ("flow_image", "characters", "webhook", "settings", "log"):
            page = window.page(key)
            btn = page.help_button
            assert btn.topic == PAGE_TOPICS[key]
            btn.click()
            assert window.current_key == "help"
            assert window.page("help").current.id == PAGE_TOPICS[key]
        assert not hasattr(window.page("meta_vibes"), "help_button")  # placeholder pages have none
    finally:
        for p in window.pages.values():
            if callable(getattr(p, "shutdown", None)):
                p.shutdown()
        window.close()
