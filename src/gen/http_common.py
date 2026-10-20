"""Small HTTP helpers shared by the OpenAI and xAI providers."""

from __future__ import annotations

import re
from typing import Callable

import httpx

from src.gen.provider import ProviderError

RETRY_STATUS = {429, 500, 502, 503, 504}
POLICY_RE = re.compile(
    r"\b(moderation|moderated|safety|policy|policies|blocked|prohibited|content[_ ]filter|filtered)\b",
    re.IGNORECASE)
EXT_BY_MIME = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp",
               "video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov"}


def send(call: Callable[[], httpx.Response]) -> httpx.Response:
    """Run one request; network failures become retryable ProviderErrors."""
    try:
        return call()
    except httpx.TimeoutException as exc:
        raise ProviderError(f"Network timeout: {type(exc).__name__}", retryable=True) from None
    except httpx.HTTPError as exc:
        raise ProviderError(f"Network error: {type(exc).__name__}", retryable=True) from None


def json_body(resp: httpx.Response, who: str) -> dict:
    try:
        data = resp.json()
    except ValueError:
        raise ProviderError(f"{who} returned a response that isn't JSON", retryable=True) from None
    if not isinstance(data, dict):
        raise ProviderError(f"{who} returned unexpected JSON", retryable=True)
    return data


def error_info(resp: httpx.Response) -> tuple[str, str]:
    """(message, code) from an OpenAI-style or xAI-style error body, best effort."""
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200].strip(), ""
    if not isinstance(body, dict):
        return str(body)[:200], ""
    err = body.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or "").strip(), str(err.get("code") or err.get("type") or "")
    if isinstance(err, str):
        return err.strip(), str(body.get("code") or "")
    return str(body.get("message") or "").strip(), str(body.get("code") or "")


def map_http_error(resp: httpx.Response, who: str) -> ProviderError:
    """Auth → not retryable; 429/5xx → retryable (except quota); policy → not retryable."""
    code = resp.status_code
    message, err_code = error_info(resp)
    detail = message or err_code or resp.reason_phrase
    if code == 401 or err_code in ("invalid_api_key", "incorrect_api_key"):
        return ProviderError(f"{who} rejected the API key ({detail})")
    if err_code == "insufficient_quota" or (code == 429 and "billing" in message.lower()):
        return ProviderError(f"{who} quota or billing limit reached ({detail})")
    if code == 429:
        return ProviderError(f"Rate limit reached ({detail})", retryable=True)
    if code in RETRY_STATUS:
        return ProviderError(f"{who} server error {code} ({detail})", retryable=True)
    if err_code == "moderation_blocked" or POLICY_RE.search(f"{message} {err_code}"):
        return ProviderError(f"Refused by {who} content policy ({detail})")
    if code == 403:
        return ProviderError(f"{who} refused the request ({detail})")
    return ProviderError(f"{who} error {code}: {detail}")


def download(client: httpx.Client, url: str, who: str, timeout: float = 300) -> bytes:
    """GET a result file. No auth header: result URLs are pre-signed and may sit on another host."""
    resp = send(lambda: client.get(url, timeout=timeout, follow_redirects=True))
    if resp.status_code != 200:
        raise map_http_error(resp, who)
    return resp.content
