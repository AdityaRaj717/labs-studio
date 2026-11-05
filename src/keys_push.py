"""Hand the saved audio keys to the engine's memory, over its authenticated local link.

The engine never reads the keyring and never writes a key down. It keeps what this sends until
it stops, so it gets them again when the app starts it.
"""

from __future__ import annotations

import httpx

from src.keys import ENV_VARS, KeyStore, store as default_store

TIMEOUT = 5.0


class NoKeysError(Exception):
    """No audio key is saved or in the environment."""


def _post(engine, lock, values: dict[str, str]) -> None:
    reply = httpx.post(f"{engine._url(lock)}/secrets", headers=engine._headers(lock), json=values, timeout=TIMEOUT)
    if reply.status_code != 200:  # the reply's text can't hold a key, but its status is all a caller needs
        raise RuntimeError(f"The Flow engine refused the keys ({reply.status_code})")


def pushKeys(engine, keys: KeyStore | None = None, lock=None) -> list[str]:  # noqa: N802 - the plan's name
    """Send every audio key there is. Returns the variable names sent, never their values."""
    keys = keys or default_store()
    values = {names[0]: keys.get(provider) for provider, names in ENV_VARS.items()}
    values = {name: value for name, value in values.items() if value}
    if not values:
        raise NoKeysError("No Fish Audio or Stability key is set. Add one in Settings, API keys.")
    _post(engine, lock or engine.ensure(), values)
    return list(values)


def forgetKey(engine, provider: str) -> None:  # noqa: N802
    """After a key is removed. An empty value reads as no key in the engine."""
    _post(engine, engine.ensure(), {ENV_VARS[provider][0]: ""})
