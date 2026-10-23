"""A tiny stdio MCP server for tests: newline-delimited JSON-RPC.

Tools: ``echo`` returns its arguments, ``fail`` returns an isError result with
an ``error_code``, ``crash`` exits the process.
"""

import json
import sys


def reply(rid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": rid}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def text(obj, is_error=False):
    out = {"content": [{"type": "text", "text": json.dumps(obj)}]}
    if is_error:
        out["isError"] = True
    return out


for line in sys.stdin:
    msg = json.loads(line)
    method, rid = msg.get("method"), msg.get("id")
    if rid is None:
        continue  # notification
    if method == "initialize":
        sys.stdout.write("not json, should be ignored\n")
        reply(rid, {"protocolVersion": msg["params"]["protocolVersion"], "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake-mcp", "version": "0.0.1"}})
    elif method == "tools/list":
        reply(rid, {"tools": [{"name": "echo"}, {"name": "fail"}, {"name": "crash"}]})
    elif method == "tools/call":
        name, args = msg["params"]["name"], msg["params"].get("arguments") or {}
        if name == "echo":
            reply(rid, text({"echo": args}))
        elif name == "fail":
            reply(rid, text({"error": True, "message": "nope", "error_code": args.get("code")}, is_error=True))
        elif name == "crash":
            sys.exit(3)
        else:
            reply(rid, error={"code": -32601, "message": f"unknown tool {name}"})
    else:
        reply(rid, error={"code": -32601, "message": f"unknown method {method}"})
