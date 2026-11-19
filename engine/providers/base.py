"""Provider interface. Providers execute; they make no creative decisions."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

GENERATION_TYPES = frozenset({"image", "video", "tts", "sfx", "music"})
ASSEMBLY_TYPES = frozenset({"timeline", "preview", "capcut_draft"})


class ProviderError(Exception):
    """Hard failure: node → failed, dependents → blocked."""


class TransientProviderError(ProviderError):
    """429 / 5xx / timeout: the scheduler retries with exponential backoff."""


class ProviderRefusal(ProviderError):
    """Content refusal: node → needs_review with reason 'refused'. Never auto-rewritten."""


@dataclass
class CallContext:
    node_id: str
    model: str
    work_dir: Path  # empty directory; write outputs here and return their paths


class Provider:
    name = "base"

    async def generate_image(self, ctx: CallContext, prompt: str, refs: list[Path], size: str, n: int) -> list[Path]:
        raise NotImplementedError(f"{self.name} does not support image generation")

    async def generate_video(
        self, ctx: CallContext, prompt: str, first_frame: Path | None, last_frame: Path | None,
        duration: float, aspect: str,
    ) -> Path:
        raise NotImplementedError(f"{self.name} does not support video generation")

    async def tts(self, ctx: CallContext, text: str, voice: str, emotion: str) -> Path:
        raise NotImplementedError(f"{self.name} does not support tts")

    async def sfx(self, ctx: CallContext, prompt: str, duration: float) -> Path:
        raise NotImplementedError(f"{self.name} does not support sfx")

    async def music(self, ctx: CallContext, prompt: str, duration: float) -> Path:
        raise NotImplementedError(f"{self.name} does not support music")

    async def assemble(self, ctx: CallContext, node_type: str, inputs: dict[str, Any]) -> Path:
        raise NotImplementedError(f"{self.name} does not support {node_type}")

    def cost(self, node_type: str, params: dict[str, Any]) -> float:
        return 0.0
