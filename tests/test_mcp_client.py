"""MCP stdio client against a fake server, and FlowMcp's connect/retry logic."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.config import Settings
from src.web.flow_mcp import FlowMcp
from src.web.mcp_client import McpError, McpStdioClient, McpToolError, tool_payload

FAKE = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"


@pytest.fixture
def client(tmp_path):
    c = McpStdioClient([sys.executable, "-I", str(FAKE)], stderr_path=tmp_path / "err.log", name="fake")
    c.start(timeout=20)
    yield c
    c.close()


def test_handshake_list_and_call(client):
    assert client.server_info == {"name": "fake-mcp", "version": "0.0.1"}
    assert client.list_tools() == ["echo", "fail", "crash"]
    assert client.call_tool("echo", {"a": 1, "s": "é"}) == {"echo": {"a": 1, "s": "é"}}


def test_tool_error_carries_code(client):
    with pytest.raises(McpToolError) as err:
        client.call_tool("fail", {"code": "NOT_LOGGED_IN"})
    assert err.value.code == "NOT_LOGGED_IN" and str(err.value) == "nope"


def test_protocol_error_and_crash(client):
    with pytest.raises(McpError):
        client.call_tool("missing")
    with pytest.raises(McpError):
        client.call_tool("crash", timeout=10)
    assert not client.is_alive() or client.proc.wait(5) == 3


def test_start_failure_is_mcp_error(tmp_path):
    with pytest.raises(McpError):
        McpStdioClient([str(tmp_path / "no-such-node.exe")]).start()


def test_tool_payload_shapes():
    assert tool_payload({"content": [{"type": "text", "text": "plain"}]}) == {"text": "plain"}
    assert tool_payload({"content": []}) == {}


class FakeClient:
    def __init__(self, command, cwd=None, name="", stderr_path=None, env=None):
        self.command, self.cwd, self.env = command, cwd, env
        self.calls: list[tuple[str, dict]] = []
        self.alive = True
        self.fail_next: list[str] = []

    def start(self):
        pass

    def is_alive(self):
        return self.alive

    def close(self):
        self.alive = False

    def call_tool(self, name, args=None, timeout=None):
        self.calls.append((name, dict(args or {})))
        if name in ("flow_generate_image", "flow_open_project") and self.fail_next:
            code = self.fail_next.pop(0)
            raise McpToolError(code, {"error_code": code})
        if name == "flow_open_project":
            url = (args or {}).get("url") or f"https://flow.google.com/project/new{len(self.calls)}"
            return {"status": "success", "url": url, "created": not (args or {}).get("url"),
                    "title": (args or {}).get("name", "")}
        return {"status": "connected"} if name == "flow_connect" else {"status": "success", "files": []}


class FakeChrome:
    def __init__(self):
        self.ensured = 0

    def ensure_running(self, url=None):
        self.ensured += 1


def make_flow(tmp_path):
    store = Settings(tmp_path / "s.json")
    store.set("web.flow_mcp_dir", str(tmp_path / "mcp"))
    store.set("web.node_path", "node.exe")
    chrome = FakeChrome()
    clients: list[FakeClient] = []

    def factory(*a, **kw):
        clients.append(FakeClient(*a, **kw))
        return clients[-1]

    return FlowMcp(store=store, session=chrome, client_factory=factory), clients, chrome


def test_flow_mcp_starts_once_and_connects_once(tmp_path):
    flow, clients, chrome = make_flow(tmp_path)
    flow.generate_image({"prompt": "a"}, timeout=60)
    flow.generate_image({"prompt": "b"}, timeout=60)
    assert len(clients) == 1 and chrome.ensured == 1
    c = clients[0]
    assert c.command == ["node.exe", str(tmp_path / "mcp" / "src" / "index.js")]
    assert [n for n, _ in c.calls] == ["flow_connect", "flow_generate_image", "flow_generate_image"]
    args = c.calls[1][1]
    assert args["auto_confirm"] is True and args["campaign"] == "labs-studio"
    assert args["timeout_ms"] == 60000 and args["wait_ms"] > args["timeout_ms"]


def test_flow_mcp_reconnects_after_browser_lost(tmp_path):
    flow, clients, chrome = make_flow(tmp_path)
    flow.ensure()
    clients[0].fail_next = ["BROWSER_NOT_CONNECTED"]
    assert flow.generate_image({"prompt": "a"}, timeout=60)["status"] == "success"
    names = [n for n, _ in clients[0].calls]
    assert names == ["flow_connect", "flow_generate_image", "flow_connect", "flow_generate_image"]


def test_flow_mcp_restarts_dead_server(tmp_path):
    flow, clients, _ = make_flow(tmp_path)
    flow.ensure()
    clients[0].alive = False
    flow.generate_image({"prompt": "a"}, timeout=60)
    assert len(clients) == 2


def test_flow_mcp_other_errors_propagate(tmp_path):
    flow, clients, _ = make_flow(tmp_path)
    flow.ensure()
    clients[0].fail_next = ["GOOGLE_LIMIT_REACHED"]
    with pytest.raises(McpToolError) as err:
        flow.generate_image({"prompt": "a"}, timeout=60)
    assert err.value.code == "GOOGLE_LIMIT_REACHED"
