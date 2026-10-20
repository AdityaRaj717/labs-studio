"""Built-in nodes that need no provider: prompt text, joining text, image files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.gen.provider import ConfigField, ProviderError
from src.workflow.registry import IMAGE, TEXT, NodeContext, NodeType, Port, register

CATEGORY = "wf_cat_basic"


def _prompt(inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
    text = str(params.get("text") or "").strip()
    if not text:
        raise ProviderError("The prompt is empty")
    return {"text": text}


def _join(inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
    parts = [str(inputs.get(k) or "").strip() for k in ("a", "b")]
    sep = str(params.get("separator", " ")).replace("\n", "\n")
    return {"text": sep.join(p for p in parts if p)}


def _image_file(inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
    raw = str(params.get("path") or "").strip()
    path = Path(raw)
    if not raw or not path.is_file():
        raise ProviderError(f"Image file not found: {raw or '(none chosen)'}")
    return {"image": [path]}


PROMPT = NodeType("prompt", "wf_node_prompt", CATEGORY, _prompt,
                  outputs=[Port("text", TEXT, "wf_port_text")],
                  params=[ConfigField("text", "wf_param_text", "multiline", "")])

JOIN = NodeType("text_join", "wf_node_join", CATEGORY, _join,
                inputs=[Port("a", TEXT, "wf_port_a"), Port("b", TEXT, "wf_port_b", required=False)],
                outputs=[Port("text", TEXT, "wf_port_text")],
                params=[ConfigField("separator", "wf_param_separator", "text", " ")])

IMAGE_FILE = NodeType("image_file", "wf_node_image_file", CATEGORY, _image_file,
                      outputs=[Port("image", IMAGE, "wf_port_image")],
                      params=[ConfigField("path", "wf_param_image_path", "file", "")])

for _t in (PROMPT, JOIN, IMAGE_FILE):
    register(_t)
