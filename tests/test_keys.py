"""KeyStore: keyring first, env fallback, failures treated as no key."""

from __future__ import annotations

from src.keys import SERVICE, KeyStore


class FakeKeyring:
    def __init__(self, fail: bool = False):
        self.data: dict[tuple[str, str], str] = {}
        self.fail = fail

    def get_password(self, service, user):
        if self.fail:
            raise RuntimeError("no backend")
        return self.data.get((service, user))

    def set_password(self, service, user, value):
        self.data[(service, user)] = value

    def delete_password(self, service, user):
        if (service, user) not in self.data:
            raise KeyError(user)
        del self.data[(service, user)]


def test_set_get_clear_roundtrip():
    ring = FakeKeyring()
    keys = KeyStore(ring, environ={})
    assert keys.get("fish") == "" and keys.source("fish") == "none"
    keys.set("fish", "  abc123  ")
    assert ring.data[(SERVICE, "fish")] == "abc123"
    assert keys.get("fish") == "abc123" and keys.source("fish") == "keyring"
    keys.clear("fish")
    assert keys.get("fish") == "" and keys.source("fish") == "none"
    keys.clear("fish")  # clearing twice is harmless


def test_env_fallback_and_priority():
    ring = FakeKeyring()
    keys = KeyStore(ring, environ={"FISH_API_KEY": ""})
    assert keys.get("fish") == "" and keys.source("fish") == "none"
    keys = KeyStore(ring, environ={"FISH_API_KEY": "gem"})
    assert keys.get("fish") == "gem" and keys.source("fish") == "env"
    assert keys.env_var("fish") == "FISH_API_KEY"
    keys.set("fish", "stored")
    assert keys.get("fish") == "stored" and keys.source("fish") == "keyring"


def test_empty_set_clears_and_backend_failure_is_no_key():
    ring = FakeKeyring()
    keys = KeyStore(ring, environ={})
    keys.set("fish", "x")
    keys.set("fish", "   ")
    assert keys.source("fish") == "none"
    broken = KeyStore(FakeKeyring(fail=True), environ={"FISH_API_KEY": "env-key"})
    assert broken.get("fish") == "env-key" and broken.source("fish") == "env"
