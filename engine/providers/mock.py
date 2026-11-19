"""Instant placeholder outputs for tests and dry runs. No network.
Video/audio files are JSON stamps with media extensions; plan 2 upgrades
them to real media so assembly can be tested end to end."""
from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any

from engine.providers.base import ASSEMBLY_TYPES, CallContext, Provider

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


class MockProvider(Provider):
    name = "mock"

    def __init__(self, cost_per_call: float = 0.0, delay_s: float = 0.0):
        self.cost_per_call = cost_per_call
        self.delay_s = delay_s

    async def _before(self, ctx: CallContext) -> None:
        """Runs at the start of every call. Tests override it to inject delays/failures."""
        if self.delay_s:
            await asyncio.sleep(self.delay_s)

    def _stamp(self, ctx: CallContext, **fields: Any) -> bytes:
        return json.dumps(
            {"mock": True, "node": ctx.node_id, "model": ctx.model, **fields}, sort_keys=True, default=str
        ).encode()

    def _write(self, ctx: CallContext, filename: str, payload: bytes) -> Path:
        path = ctx.work_dir / filename
        path.write_bytes(payload)
        return path

    async def generate_image(self, ctx, prompt, refs, size, n):
        await self._before(ctx)
        return [self._write(ctx, f"candidate_{i}.png", PNG_1X1) for i in range(n)]

    async def generate_video(self, ctx, prompt, first_frame, last_frame, duration, aspect):
        await self._before(ctx)
        return self._write(ctx, "clip.mp4", self._stamp(
            ctx, prompt=prompt, first_frame=first_frame, last_frame=last_frame, duration=duration, aspect=aspect,
        ))

    async def tts(self, ctx, text, voice, emotion):
        await self._before(ctx)
        return self._write(ctx, "vo.wav", self._stamp(ctx, text=text, voice=voice, emotion=emotion))

    async def sfx(self, ctx, prompt, duration):
        await self._before(ctx)
        return self._write(ctx, "sfx.wav", self._stamp(ctx, prompt=prompt, duration=duration))

    async def music(self, ctx, prompt, duration):
        await self._before(ctx)
        return self._write(ctx, "music.mp3", self._stamp(ctx, prompt=prompt, duration=duration))

    async def assemble(self, ctx, node_type, inputs):
        await self._before(ctx)
        if node_type == "capcut_draft":
            d = ctx.work_dir / "capcut_draft"
            d.mkdir()
            (d / "draft_content.json").write_bytes(self._stamp(ctx, inputs=inputs))
            return d
        ext = {"timeline": ".json", "preview": ".mp4"}[node_type]
        return self._write(ctx, f"{node_type}{ext}", self._stamp(ctx, node_type=node_type, inputs=inputs))

    def cost(self, node_type, params):
        return 0.0 if node_type in ASSEMBLY_TYPES else self.cost_per_call
