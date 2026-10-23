"""Google Flow (flow.google.com) image mode.

Flow (Oct 2026) generates through a per-project agent chat. A job here:

1. open the app's own Flow project (created once, URL kept at ``web.flow_project``)
2. set the agent's image defaults: aspect, count, model, "confirm before
   generating: Never" (so the agent doesn't stop to ask)
3. start a new chat session, add reference images as ingredients, send the prompt
4. wait for the agent's reply bubble to finish (its feedback bar appears)
5. download every image option through Flow's own Download media → size menu

All labels come from ``selectors/flow.json``. ``parse_last_turn`` reads the chat
from page HTML, so it works the same on the live page and on saved fixtures.
"""

from __future__ import annotations

import logging
import tempfile
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

from src.gen.provider import StopRequested
from src.web.adapters.base import (
    GenerationRefused, SiteAdapter, SiteBlocked, UiChanged, detect_block_text,
)

log = logging.getLogger(__name__)


# ---- HTML parsing (pure, tested on fixtures) ----------------------------
@dataclass
class ChatTurn:
    """The last bubble of the agent chat."""

    is_agent: bool = False
    done: bool = False  # the feedback bar is there: the agent stopped working
    images: list[str] = field(default_factory=list)  # src of each image option
    text: str = ""  # the agent's reply text (not its "thinking")


class _ChatParser(HTMLParser):
    def __init__(self, sel: dict[str, Any]):
        super().__init__(convert_charrefs=True)
        c = sel["chat"]
        self.bubble_tag = c["bubble_tag"]
        self.reply_tag = c["reply_text_tag"]
        self.done_label = c["done_button"]
        self.gallery_label = c["gallery"]
        self.option_alt = c["option_alt_prefix"]
        self.turns: list[ChatTurn] = []
        self._depth = {"bubble": 0, "reply": 0, "gallery": 0}
        self._gallery_stack: list[str] = []
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == self.bubble_tag:
            if self._depth["bubble"] == 0:
                self.turns.append(ChatTurn())
                self._text = []
            self._depth["bubble"] += 1
        if not self._depth["bubble"]:
            return
        turn = self.turns[-1]
        if tag == self.reply_tag:
            self._depth["reply"] += 1
            turn.is_agent = True
        if a.get("aria-label") == self.gallery_label:
            self._gallery_stack.append(tag)
            turn.is_agent = True
        elif self._gallery_stack and tag == self._gallery_stack[-1]:
            self._gallery_stack.append(tag)
        if tag == "img" and self._gallery_stack and (a.get("alt") or "").startswith(self.option_alt):
            turn.images.append(a.get("src") or "")
        if a.get("aria-label") == self.done_label:
            turn.done = True
            turn.is_agent = True

    def handle_endtag(self, tag):
        if tag == self.bubble_tag and self._depth["bubble"]:
            self._depth["bubble"] -= 1
            if self._depth["bubble"] == 0 and self.turns:
                self.turns[-1].text = " ".join(self._text).strip()
        if tag == self.reply_tag and self._depth["reply"]:
            self._depth["reply"] -= 1
        if self._gallery_stack and tag == self._gallery_stack[-1]:
            self._gallery_stack.pop()

    def handle_data(self, data):
        if self._depth["reply"] and data.strip():
            self._text.append(data.strip())


def parse_chat(html: str, sel: dict[str, Any]) -> list[ChatTurn]:
    p = _ChatParser(sel)
    p.feed(html)
    p.close()
    return p.turns


def parse_last_turn(html: str, sel: dict[str, Any]) -> ChatTurn | None:
    turns = parse_chat(html, sel)
    return turns[-1] if turns else None


def logged_in_html(html: str, sel: dict[str, Any]) -> bool:
    return f'aria-label="{sel["account_button"]}"' in html


# ---- adapter -------------------------------------------------------------
class FlowAdapter(SiteAdapter):
    site = "flow"
    title = "Google Flow"

    def __init__(self, page, selectors: dict[str, Any] | None = None, store=None):
        super().__init__(page, selectors)
        if store is None:
            from src import config

            store = config.settings()
        self.store = store
        self._turns_before = 0
        self.size = "1K"
        self.turn: ChatTurn | None = None

    # ---- helpers -------------------------------------------------------
    def _btn(self, key: str, last: bool = False):
        loc = self.page.get_by_role("button", name=self.sel["buttons"][key], exact=True)
        return loc.last if last else loc.first

    def _need(self, loc, what: str, timeout: float = 15000):
        try:
            loc.wait_for(state="visible", timeout=timeout)
        except Exception:  # noqa: BLE001 - Playwright TimeoutError
            raise UiChanged(what) from None
        return loc

    def _close_overlay(self) -> None:
        backdrop = self.page.locator(".cdk-overlay-backdrop")
        if backdrop.count():
            backdrop.last.click()
            self.page.wait_for_timeout(300)

    def is_logged_in(self) -> bool:
        try:
            self.page.get_by_role("button", name=self.sel["account_button"]).first.wait_for(
                state="visible", timeout=8000)
            return True
        except Exception:  # noqa: BLE001
            return False

    def _check_block(self) -> None:
        kind = self.detect_block()
        if kind:
            raise SiteBlocked(kind)

    # ---- project -------------------------------------------------------
    def prepare(self) -> None:
        self.open_project()

    def open_project(self) -> None:
        url = self.store.get("web.flow_project", "") or ""
        # Go to the grid itself, not the edit/tools/trash views under it.
        if url and self.page.url.split("?")[0].rstrip("/") != url.rstrip("/"):
            self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        if not url:
            self._new_project()
        self._check_block()
        if not self.is_logged_in():
            raise SiteBlocked("login")
        try:
            self._prompt_box().wait_for(state="visible", timeout=20000)
        except Exception:  # noqa: BLE001 - project gone (deleted?) or page changed
            if not url:
                raise UiChanged("prompt box") from None
            log.warning("Flow project %s did not open; creating a new one", url)
            self._new_project()
            self._need(self._prompt_box(), "prompt box", 20000)

    def _new_project(self) -> None:
        self.page.goto(self.sel["home"], wait_until="domcontentloaded", timeout=60000)
        self._check_block()
        self._need(self._btn("new_project"), "New project button", 20000).click()
        self.page.wait_for_url("**/project/**", timeout=30000)
        url = self.page.url.split("?")[0].split("/edit/")[0]
        self.store.set("web.flow_project", url)
        log.info("Created Flow project for the app: %s", url)

    def _prompt_box(self):
        return self.page.get_by_role("textbox", name=self.sel["prompt_box"]).first

    # ---- agent settings -------------------------------------------------
    def apply_settings(self, opts: dict[str, Any]) -> None:
        img = self.sel["image"]
        s = self.sel["agent_settings"]
        self._need(self._btn("agent_settings", last=True), "agent Settings button").click()
        self._need(self.page.get_by_role("heading", name=s["heading"]), "Agent settings panel")
        self.page.get_by_role("radio", name=s["confirm_never"]).click()
        groups = self.page.locator("[role=radiogroup]")
        aspect = img["aspects"].get(opts.get("aspect"), next(iter(img["aspects"].values())))
        groups.nth(s["image_aspect_group"]).get_by_role("radio", name=aspect, exact=True).click()
        groups.nth(s["image_count_group"]).get_by_role(
            "radio", name=f"x{int(opts.get('count', 1))}", exact=True).click()
        model = img["models"].get(opts.get("model"), "")
        model_btn = self.page.get_by_role("button", name=s["image_model_button"])
        if model and model not in (model_btn.inner_text() or ""):
            model_btn.click()
            self._need(self.page.get_by_role("menuitem", name=model), f"model {model}").click()
        self.page.get_by_role("button", name=s["save"], exact=True).click()
        self._need(self._prompt_box(), "prompt box after saving settings")

    # ---- references -----------------------------------------------------
    def add_reference(self, path: Path) -> None:
        """Upload ``path`` as an ingredient. A finished upload usually lands in the
        prompt by itself; if the picker stays open, select it and press Add."""
        r = self.sel["refs"]
        chips = self.page.get_by_role("button", name=r["ingredient"], exact=True)
        before = chips.count()
        self._btn("ingredients").click()
        upload = self._need(self.page.get_by_role("button", name=r["upload"]), "Upload media button")
        with self.page.expect_file_chooser(timeout=15000) as fc:
            upload.click()
        fc.value.set_files(str(path))
        option = self.page.get_by_role("listbox", name=r["asset_list"]).get_by_role(
            "option", name=f"{path.name} {r['option_suffix']}", exact=True).first
        add = self.page.get_by_role("button", name=r["add_to_prompt"])
        deadline = time.monotonic() + 120
        while chips.count() <= before:
            if time.monotonic() > deadline:
                raise UiChanged(f"reference {path.name} never reached the prompt")
            if option.is_visible():
                # Clicking the asset adds it in some UI states; in others it only
                # previews it and "Add to prompt" does the adding.
                option.click()
                self.page.wait_for_timeout(1000)
                if chips.count() <= before and add.is_visible():
                    add.click()
            self.page.wait_for_timeout(1000)
        self._close_overlay()

    # ---- the job --------------------------------------------------------
    def submit(self, prompt: str, refs: list[Path], opts: dict[str, Any]) -> None:
        self.size = str(opts.get("download_size") or "1K")
        if not self._prompt_box().is_visible():
            self.open_project()
        self.apply_settings(opts)
        self._btn("new_session").click()
        self.page.wait_for_timeout(1200)
        clear = self._btn("clear_prompt")
        if clear.is_visible():  # ingredients left over from an earlier job
            clear.click()
            self.page.wait_for_timeout(500)
        for ref in refs:
            self.add_reference(Path(ref))
        box = self._need(self._prompt_box(), "prompt box")
        box.click()
        # With references the agent tends to edit them and keep their shape, so say the aspect.
        template = self.sel.get("ref_prompt_template" if refs else "prompt_template", "{prompt}")
        text = template.format(prompt=prompt, aspect=opts.get("aspect", ""))
        self.page.keyboard.insert_text(text)
        self._turns_before = len(parse_chat(self.page.content(), self.sel))
        send = self._btn("send")
        deadline = time.monotonic() + 10
        while not send.is_enabled() and time.monotonic() < deadline:
            self.page.wait_for_timeout(250)
        if not send.is_enabled():
            raise UiChanged("Start generation button stayed disabled")
        send.click()

    def wait_done(self, timeout: float, should_stop: Callable[[], bool],
                  progress: Callable[[float], None] = lambda p: None) -> None:
        start = time.monotonic()
        rules = self.sel.get("block", {})
        while True:
            if should_stop():
                raise StopRequested()
            elapsed = time.monotonic() - start
            if elapsed > timeout:
                raise TimeoutError(f"no finished reply after {timeout:.0f}s")
            progress(min(0.95, elapsed / max(timeout * 0.5, 1)))
            # A sign-in redirect or a CAPTCHA page replaces the project page.
            kind = detect_block_text("", self.page.url, rules)
            if kind:
                raise SiteBlocked(kind)
            turns = parse_chat(self.page.content(), self.sel)
            last = turns[-1] if len(turns) > self._turns_before else None
            if last is not None and last.is_agent and last.done:
                self.turn = last
                break
            self.page.wait_for_timeout(2000)
        if not last.images:
            kind = detect_block_text(last.text, "", {"quota": rules.get("quota", {}),
                                                      "captcha": rules.get("captcha", {})})
            if kind:
                raise SiteBlocked(kind)
            raise GenerationRefused(last.text[:300] or "the agent replied without an image")

    def collect(self) -> list[tuple[bytes, str]]:
        c = self.sel["collect"]
        out: list[tuple[bytes, str]] = []
        n = len(self.turn.images)
        for i in range(n):
            gallery = self.page.get_by_role("group", name=self.sel["chat"]["gallery"]).last
            gallery.get_by_role("button", name=c["open_option"]).nth(i).click()
            self._need(self._btn("download"), "Download media button", 30000).click()
            item = self.page.get_by_role("menuitem", name=c["sizes"].get(self.size, c["sizes"]["1K"]))
            self._need(item, "download size menu")
            with self.page.expect_download(timeout=120000) as dl:
                item.click()
            d = dl.value
            ext = (Path(d.suggested_filename).suffix.lstrip(".") or "jpg").lower()
            with tempfile.TemporaryDirectory(prefix="flowdl-") as tmp:
                target = Path(tmp) / f"img.{ext}"
                d.save_as(str(target))
                out.append((target.read_bytes(), "jpg" if ext == "jpeg" else ext))
            self._btn("back_from_editor").click()
            self._need(self.page.get_by_role("group", name=self.sel["chat"]["gallery"]).last,
                       "chat after download", 20000)
        return out
