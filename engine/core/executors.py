"""Dispatch a node to the right provider method based on its type."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.core.graph import Node
from engine.providers.base import ASSEMBLY_TYPES, CallContext, Provider, ProviderError


def _path_or_none(value: Any) -> Path | None:
    return Path(value) if value else None


def cost_params(node: Node, inputs: dict[str, Any]) -> dict[str, Any]:
    return {"prompt": node.prompt, **inputs}


async def execute(node: Node, provider: Provider, ctx: CallContext, inputs: dict[str, Any]) -> Path:
    """`inputs` are already resolved (refs → absolute paths). Returns the produced path."""
    t, prompt = node.type, node.prompt or ""
    if t == "image":
        candidates = await provider.generate_image(
            ctx, prompt, [Path(p) for p in inputs.get("refs", [])],
            str(inputs.get("size", "1024x1792")), int(inputs.get("n", 1)),
        )
        if not candidates:
            raise ProviderError(f"{node.id}: image provider returned no candidates")
        return candidates[0]  # plan 4 replaces this with the vision judge's pick
    if t == "video":
        return await provider.generate_video(
            ctx, prompt, _path_or_none(inputs.get("first_frame")), _path_or_none(inputs.get("last_frame")),
            float(inputs.get("duration", 4)), str(inputs.get("aspect", "9:16")),
        )
    if t == "tts":
        if "text" not in inputs:
            raise ProviderError(f"{node.id}: tts node needs inputs.text")
        return await provider.tts(
            ctx, str(inputs["text"]), str(inputs.get("voice", "default")), str(inputs.get("emotion", "neutral")),
        )
    if t == "sfx":
        return await provider.sfx(ctx, prompt, float(inputs.get("duration", 1.0)))
    if t == "music":
        return await provider.music(ctx, prompt, float(inputs.get("duration", 30.0)))
    if t in ASSEMBLY_TYPES:
        return await provider.assemble(ctx, t, inputs)
    raise ProviderError(f"{node.id}: unknown node type {t}")
