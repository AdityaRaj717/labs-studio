"""Phase 1 tests: settings store, theme tokens, nav strings."""

from __future__ import annotations

import json

from src import theme
from src.config import DEFAULTS, Settings
from src.i18n import load_language, tr
from src.languages import en
from src.ui.sidebar import NAV_ITEMS


def test_defaults_when_file_missing(tmp_path):
    s = Settings(tmp_path / "settings.json")
    assert s.get("theme") == DEFAULTS["theme"]
    assert s.get("language") == "en"
    assert s.get("sidebar_collapsed") is False
    assert s.get("window.geometry") is None


def test_dotted_get_set_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    s = Settings(path)
    s.set("theme", "light")
    s.set("window.geometry", "abc==")
    s.set("pages.flow_image.count", 4)
    s.set("sidebar_collapsed", True)

    reloaded = Settings(path)
    assert reloaded.get("theme") == "light"
    assert reloaded.get("window.geometry") == "abc=="
    assert reloaded.get("pages.flow_image.count") == 4
    assert reloaded.get("pages.flow_image") == {"count": 4}
    assert reloaded.get("sidebar_collapsed") is True


def test_get_missing_returns_default(tmp_path):
    s = Settings(tmp_path / "settings.json")
    assert s.get("nope", 7) == 7
    assert s.get("theme.deeper", "x") == "x"  # walking through a non-dict
    assert s.get("window.nope") is None


def test_set_overwrites_scalar_with_dict(tmp_path):
    s = Settings(tmp_path / "settings.json")
    s.set("theme.sub", 1)
    assert s.get("theme.sub") == 1


def test_partial_file_merges_with_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"theme": "light", "window": {}}), encoding="utf-8")
    s = Settings(path)
    assert s.get("theme") == "light"
    assert s.get("language") == "en"
    assert s.get("window.geometry") is None


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    s = Settings(path)
    assert s.get("theme") == DEFAULTS["theme"]


def test_set_without_save_does_not_write(tmp_path):
    path = tmp_path / "settings.json"
    s = Settings(path)
    s.set("theme", "light", save=False)
    assert not path.exists()
    s.save()
    assert json.loads(path.read_text(encoding="utf-8"))["theme"] == "light"


def test_theme_tokens_present_for_every_mode():
    assert set(theme.MODES) == {"dark", "light"}
    for mode in theme.MODES:
        tokens = theme.COLORS[mode]
        for name in theme.TOKEN_NAMES:
            assert name in tokens, f"{mode} missing {name}"
            assert tokens[name].startswith("#")
        qss = theme.build_qss(mode)
        assert tokens["bg"] in qss and tokens["accent"] in qss


def test_every_nav_key_resolves_in_en():
    strings = load_language("en")
    assert len(NAV_ITEMS) == 9
    for _, label_key, _ in NAV_ITEMS:
        assert label_key in strings, label_key
        assert tr(label_key) == en.STRINGS[label_key]
        assert tr(label_key) != label_key


def test_nav_order_matches_spec():
    expected = [
        "Flow Image", "Flow Video", "Projects", "Characters", "Scenes", "Webhook API", "Detailed Log", "Settings", "Help",
    ]
    assert [tr(lk) for _, lk, _ in NAV_ITEMS] == expected


def test_tr_falls_back_to_key_and_formats():
    assert tr("does_not_exist") == "does_not_exist"
    assert tr("version", version="1.2.3") == "Version 1.2.3"


def test_nav_visible_default(monkeypatch):
    from src import features
    from src.ui.sidebar import NAV_KEYS

    monkeypatch.setenv(features.ENV, "flow")
    assert features.visible_pages(NAV_KEYS) == (
        "flow_image", "flow_video", "projects", "characters", "scenes", "webhook", "log", "settings", "help")
