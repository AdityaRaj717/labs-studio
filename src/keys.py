"""API key storage: OS keyring first (Windows Credential Manager), env var fallback.

Keys never go into settings.json or the log.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

SERVICE = "LabsStudio"

# Provider id -> env vars checked (in order) when nothing is stored.
ENV_VARS: dict[str, tuple[str, ...]] = {
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "openai": ("OPENAI_API_KEY",),
    "xai": ("XAI_API_KEY",),
}


class KeyStore:
    """``backend`` is any object with keyring's get/set/delete_password (tests pass a fake)."""

    def __init__(self, backend=None, environ=None):
        self._backend = backend
        self._environ = os.environ if environ is None else environ

    @property
    def backend(self):
        if self._backend is None:
            import keyring

            self._backend = keyring
        return self._backend

    def stored(self, provider: str) -> str:
        try:
            return self.backend.get_password(SERVICE, provider) or ""
        except Exception as exc:  # noqa: BLE001 - any keyring backend failure means "no key"
            log.warning("Keyring read failed for %s: %s", provider, exc)
            return ""

    def env_var(self, provider: str) -> str:
        """Name of the first env var that holds a key for ``provider``, or ''."""
        for name in ENV_VARS.get(provider, ()):
            if self._environ.get(name, "").strip():
                return name
        return ""

    def get(self, provider: str) -> str:
        key = self.stored(provider).strip()
        if key:
            return key
        name = self.env_var(provider)
        return self._environ[name].strip() if name else ""

    def source(self, provider: str) -> str:
        """``keyring`` | ``env`` | ``none``."""
        if self.stored(provider).strip():
            return "keyring"
        return "env" if self.env_var(provider) else "none"

    def set(self, provider: str, key: str) -> None:
        key = key.strip()
        if not key:
            self.clear(provider)
            return
        self.backend.set_password(SERVICE, provider, key)
        log.info("API key saved for %s", provider)

    def clear(self, provider: str) -> None:
        try:
            self.backend.delete_password(SERVICE, provider)
            log.info("API key removed for %s", provider)
        except Exception as exc:  # noqa: BLE001 - nothing stored is fine
            log.debug("Keyring delete for %s: %s", provider, exc)


_store: KeyStore | None = None


def store() -> KeyStore:
    global _store
    if _store is None:
        _store = KeyStore()
    return _store


def get_key(provider: str) -> str:
    return store().get(provider)
