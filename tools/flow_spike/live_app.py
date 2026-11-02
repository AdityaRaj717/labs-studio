"""Live Task 13-14: the app's own bridge against real Flow, without the window."""
import json
import sys
import uuid

sys.path.insert(0, ".")
from src.web.flow_mcp import flow_mcp  # noqa: E402

PROJECT = "https://flow.google.com/project/065acc3b-852c-4cf2-84c6-80359d0543bd"
mcp = flow_mcp()
print("data dir", mcp.data_dir)
print("status", json.dumps(mcp.status())[:300])
events = []
tag = uuid.uuid4().hex[:6]
key = f"app:live:{tag}"
args = {"project_url": PROJECT, "prompt": f"A yellow rubber duck on a desk, {tag}", "auto_confirm": True, "idempotency_key": key}
r = mcp.run_job("flow_generate_image", args, 400, on_event=events.append)
print("image", json.dumps(r)[:500])
print("events", len(events), json.dumps(events[:1] + events[-1:])[:400])
print("repeat", json.dumps(mcp.run_job("flow_generate_image", args, 60))[:200])
v = mcp.run_job("flow_generate_video", {"project_url": PROJECT, "prompt": f"A duck paddles across a pond, {tag}", "model": "omni", "resolution": "360p", "duration": 4, "silent": True, "auto_confirm": True, "max_credits": 4, "idempotency_key": f"{key}:v"}, 500)
print("video", json.dumps(v)[:600])
try:
    print("veo 4s", mcp.run_job("flow_generate_video", {"project_url": PROJECT, "prompt": "x", "model": "veoLite", "duration": 4, "auto_confirm": True}, 30))
except Exception as err:  # the refusal is the pass
    print("veo 4s refused:", str(err)[:200])
print("status", json.dumps(mcp.status())[:300])
mcp.close()
