"""Flow adapter parsing and block detection on saved page snapshots (no browser)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.web.adapters.base import detect_block_html, detect_block_text, load_selectors, page_text
from src.web.adapters.flow import logged_in_html, parse_chat, parse_last_turn

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


def test_empty_project_has_no_chat_turns():
    assert parse_chat(html("flow_project_empty.html"), SEL) == []
    assert parse_last_turn(html("flow_project_empty.html"), SEL) is None


def test_finished_turn_with_one_image():
    turns = parse_chat(html("flow_project_result.html"), SEL)
    assert len(turns) == 2 and not turns[0].is_agent
    last = turns[-1]
    assert last.is_agent and last.done
    assert len(last.images) == 1 and last.images[0].startswith("https://flow.google.com/asb/")
    assert last.text.startswith("Here is your image of a single red apple")
    assert "Analyzing" not in last.text  # the agent's thinking is not the reply


def test_finished_turn_with_two_images():
    last = parse_last_turn(html("flow_project_result_x2.html"), SEL)
    assert last.done and len(last.images) == 2
    assert "green apple" in last.text


def test_turn_still_running_is_not_done():
    running = html("flow_project_result.html").replace('aria-label="Good response"', "")
    last = parse_last_turn(running, SEL)
    assert last.is_agent and not last.done


def test_text_only_reply_has_no_images():
    page = ("<flow-chat-bubble><span>a cat</span></flow-chat-bubble>"
            "<flow-chat-bubble><flow-a2ui-text><p>I can't create images of that.</p></flow-a2ui-text>"
            '<button aria-label="Good response"></button></flow-chat-bubble>')
    last = parse_last_turn(page, SEL)
    assert last.done and last.images == [] and last.text == "I can't create images of that."


def test_page_text_skips_scripts():
    assert page_text("<p>hi</p><script>var x='out of credits'</script>") == "hi"
