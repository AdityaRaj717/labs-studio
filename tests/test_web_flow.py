"""Flow block and sign-in detection on saved page snapshots (no browser)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.web.adapters.base import (
    detect_block_html, detect_block_text, load_selectors, logged_in_html, page_text,
)

FIX = Path(__file__).parent / "fixtures" / "web"
SEL = load_selectors("flow")
PROJECT = "https://flow.google.com/project/7a11ef03-cf1c-48bc-a7a4-b21fa8957fcd"


def html(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name,url,kind", [
    ("flow_logged_out.html", "https://flow.google.com/about", "login"),
    ("flow_logged_out.html", "https://labs.google/fx/tools/flow", "login"),  # by page text
    ("flow_home.html", "https://flow.google.com/", None),
    ("flow_project_empty.html", PROJECT, None),
    ("flow_project_result.html", PROJECT, None),
    ("flow_project_result_x2.html", PROJECT, None),
])
def test_block_detection_on_snapshots(name, url, kind):
    assert detect_block_html(html(name), url, SEL["block"]) == kind


def test_sign_in_and_captcha_urls_are_blocks():
    rules = SEL["block"]
    assert detect_block_text("", "https://accounts.google.com/v3/signin/identifier?x", rules) == "login"
    assert detect_block_text("", "https://www.google.com/sorry/index?continue=x", rules) == "captcha"
    assert detect_block_text("Our systems have detected unusual traffic from your computer network",
                             PROJECT, rules) == "captcha"
    assert detect_block_text("Sorry, you've reached your daily limit. Try again tomorrow.",
                             PROJECT, rules) == "quota"


def test_logged_in_marker():
    assert logged_in_html(html("flow_home.html"), SEL)
    assert logged_in_html(html("flow_project_result.html"), SEL)
    assert not logged_in_html(html("flow_logged_out.html"), SEL)


def test_page_text_skips_scripts():
    assert page_text("<p>hi</p><script>var x='out of credits'</script>") == "hi"
