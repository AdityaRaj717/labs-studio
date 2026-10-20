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
    assert keys.get("gemini") == "" and keys.source("gemini") == "none"
    keys.set("gemini", "  abc123  ")
    assert ring.data[(SERVICE, "gemini")] == "abc123"
    assert keys.get("gemini") == "abc123" and keys.source("gemini") == "keyring"
    keys.clear("gemini")
    assert keys.get("gemini") == "" and keys.source("gemini") == "none"
    keys.clear("gemini")  # clearing twice is harmless


def test_env_fallback_and_priority():
    ring = FakeKeyring()
    keys = KeyStore(ring, environ={"GOOGLE_API_KEY": "from-google", "GEMINI_API_KEY": ""})
    assert keys.get("gemini") == "from-google" and keys.source("gemini") == "env"
    assert keys.env_var("gemini") == "GOOGLE_API_KEY"
    keys = KeyStore(ring, environ={"GOOGLE_API_KEY": "g", "GEMINI_API_KEY": "gem"})
    assert keys.get("gemini") == "gem"
    keys.set("gemini", "stored")
    assert keys.get("gemini") == "stored" and keys.source("gemini") == "keyring"


def test_empty_set_clears_and_backend_failure_is_no_key():
    ring = FakeKeyring()
    keys = KeyStore(ring, environ={})
    keys.set("gemini", "x")
    keys.set("gemini", "   ")
    assert keys.source("gemini") == "none"
    broken = KeyStore(FakeKeyring(fail=True), environ={"GEMINI_API_KEY": "env-key"})
    assert broken.get("gemini") == "env-key" and broken.source("gemini") == "env"
