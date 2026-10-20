"""Minimal i18n: ``tr(key)`` looks up the current language, falling back to en, then the key.

New languages drop in as ``src/languages/<code>.py`` exposing ``STRINGS``.
"""

from __future__ import annotations

import importlib
import logging

log = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "en"

_cache: dict[str, dict[str, str]] = {}
_current = DEFAULT_LANGUAGE


def load_language(code: str) -> dict[str, str]:
    if code not in _cache:
        try:
            module = importlib.import_module(f"src.languages.{code}")
            _cache[code] = dict(getattr(module, "STRINGS", {}))
        except ImportError:
            log.warning("Language %r not found; falling back to %r", code, DEFAULT_LANGUAGE)
            _cache[code] = {}
    return _cache[code]


def set_language(code: str) -> None:
    global _current
    load_language(code)
    _current = code


def current_language() -> str:
    return _current


def tr(key: str, **kwargs) -> str:
    text = load_language(_current).get(key)
    if text is None:
        text = load_language(DEFAULT_LANGUAGE).get(key, key)
    return text.format(**kwargs) if kwargs else text
