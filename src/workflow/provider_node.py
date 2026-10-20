"""Wrap any ``src.gen`` Provider as a workflow node type.

    register(provider_node("openai.image", "wf_node_openai_image", "OpenAI",
                           OpenAIImageProvider, output=IMAGE))

gives a node with a ``prompt`` text input, an optional ``refs`` input, one
output, and the provider's own config fields as node settings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from src.gen.models import Job
from src.gen.output import save_outputs
from src.gen.provider import ConfigField, Provider, ProviderError
from src.workflow.registry import IMAGE, TEXT, NodeContext, NodeType, Port

COUNT_FIELD = ConfigField("count", "gen_count", "int", 1, minimum=1, maximum=8)


def as_paths(value: Any) -> list[Path]:
    """Flatten a port value (path, list of paths, None) to a list of paths."""
    if value is None:
        return []
    if isinstance(value, (str, Path)):
        return [Path(value)]
    out: list[Path] = []
    for v in value:
        out.extend(as_paths(v))
    return out


def provider_node(type_id: str, label_key: str, category: str,
                  make_provider: Callable[[], Provider], output: str = IMAGE,
                  refs: Port | None = Port("refs", IMAGE, "wf_port_refs", required=False),
                  description_key: str = "") -> NodeType:
    """``make_provider`` is called once, when the node first runs or shows its settings."""
    holder: dict[str, Provider] = {}

    def provider() -> Provider:
        if "p" not in holder:
            holder["p"] = make_provider()
        return holder["p"]

    def run(inputs: dict[str, Any], params: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
        prompt = str(inputs.get("prompt") or "").strip()
        if not prompt:
            raise ProviderError("The prompt is empty")
        p = provider()
        options = {f.key: f.default for f in p.config_fields()}
        options.update(params)
        job = Job(prompt, index=1, refs=as_paths(inputs.get(refs.name)) if refs else [])
        job.attempts = ctx.attempt
        files = p.generate(job, options, ctx.run_context())
        return {output: save_outputs(job, files, ctx.out_dir)}

    inputs = [Port("prompt", TEXT, "wf_port_prompt")]
    if refs is not None:
        inputs.append(refs)
    return NodeType(type_id, label_key, category, run, inputs=inputs,
                    outputs=[Port(output, output, f"wf_port_{output}")],
                    description_key=description_key,
                    params_factory=lambda: [*provider().config_fields(), COUNT_FIELD])
