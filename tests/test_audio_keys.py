"""The keys tab holds Fish Audio and Stability, and the engine gets them over its local link."""

from __future__ import annotations

import pytest

from src import keys_push
from src.keys import ENV_VARS, KeyStore
from src.keys_push import NoKeysError, forgetKey, pushKeys
from src.ui.pages.settings_page import SettingsPage
from test_keys import FakeKeyring

VALUE = "test-value-not-a-real-key"


class FakeEngine:
    def ensure(self):
        return {"port": 1, "token": "t"}

    @staticmethod
    def _url(lock):
        return f"http://127.0.0.1:{lock['port']}"

    @staticmethod
    def _headers(lock):
        return {"authorization": f"Bearer {lock['token']}"}


@pytest.fixture
def posts(monkeypatch):
    sent = []

    class Reply:
        status_code = 200

    def post(url, headers, json, timeout):
        sent.append((url, headers, json))
        return Reply()
    monkeypatch.setattr(keys_push.httpx, "post", post)
    return sent


def test_keys_tab_lists_fish_and_stability_only(qapp):
    page = SettingsPage(KeyStore(FakeKeyring(), environ={}))
    assert set(page.keys_tab.rows) == {"fish", "stability"} and set(ENV_VARS) == {"fish", "stability"}
    assert page.tabs.indexOf(page.keys_tab) >= 0  # the tab is shown again


def test_pushkeys_posts_to_secrets(posts):
    store = KeyStore(FakeKeyring(), environ={})
    store.set("fish", VALUE)
    assert pushKeys(FakeEngine(), store) == ["FISH_API_KEY"]
    url, headers, body = posts[0]
    assert url == "http://127.0.0.1:1/secrets" and headers["authorization"] == "Bearer t"
    assert body == {"FISH_API_KEY": VALUE}


def test_no_key_means_a_clear_error(posts):
    with pytest.raises(NoKeysError, match="Settings"):
        pushKeys(FakeEngine(), KeyStore(FakeKeyring(), environ={}))
    assert posts == []


def test_a_refused_push_doesnt_quote_the_key(monkeypatch):
    class Reply:
        status_code = 400
    monkeypatch.setattr(keys_push.httpx, "post", lambda *a, **k: Reply())
    store = KeyStore(FakeKeyring(), environ={"STABILITY_API_KEY": VALUE})
    with pytest.raises(RuntimeError) as err:
        pushKeys(FakeEngine(), store)
    assert VALUE not in str(err.value)


def test_forgetting_a_key_tells_the_engine(posts):
    forgetKey(FakeEngine(), "stability")
    assert posts[0][2] == {"STABILITY_API_KEY": ""}


def test_save_and_remove_notify_without_the_value_in_the_ui(qapp):
    seen = []
    page = SettingsPage(KeyStore(FakeKeyring(), environ={}))
    row = page.keys_tab.rows["fish"]
    row.on_change = lambda provider, removed: seen.append((provider, removed))
    row.edit.setText(VALUE)
    row.save()
    row.clear()
    assert seen == [("fish", False), ("fish", True)] and VALUE not in row.status.text()
