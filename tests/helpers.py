"""Shared test builders. Imported as `from tests.helpers import ...`."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from engine.config import EngineConfig
from engine.providers.base import ProviderRefusal, TransientProviderError
from engine.providers.mock import MockProvider


def make_manifest(variants: tuple[str, ...] = ("v1", "v2"), shots: int = 2) -> dict:
    """A realistic manifest: one shared product hero, then per variant
    `shots` keyframe→clip pairs, one VO line, timeline, preview, CapCut draft.
    Default size: 1 + 2 * 8 = 17 nodes, 11 of them generation nodes."""
    nodes: list[dict] = [
        {
            "id": "refs.product_hero",
            "type": "image",
            "prompt": "Hero shot of a matte ceramic mug on a wooden table",
            "inputs": {"size": "1024x1024"},
            "depends_on": [],
        }
    ]
    for v in variants:
        clips: list[str] = []
        for s in range(1, shots + 1):
            sid = f"s{s:02d}"
            nodes.append({
                "id": f"{v}.{sid}.keyframe",
                "type": "image",
                "prompt": f"{v} shot {s} keyframe",
                "inputs": {"refs": ["@refs.product_hero"], "n": 2},
                "depends_on": ["refs.product_hero"],
            })
            nodes.append({
                "id": f"{v}.{sid}.clip",
                "type": "video",
                "prompt": f"{v} shot {s} slow push-in",
                "inputs": {"first_frame": f"@{v}.{sid}.keyframe", "duration": 4, "aspect": "9:16"},
                "depends_on": [f"{v}.{sid}.keyframe"],
            })
            clips.append(f"{v}.{sid}.clip")
        nodes.append({
            "id": f"{v}.vo.l01",
            "type": "tts",
            "inputs": {"text": f"Line for {v}", "voice": "narrator"},
            "depends_on": [],
        })
        keyframes = [f"{v}.s{s:02d}.keyframe" for s in range(1, shots + 1)]
        nodes.append({
            "id": f"{v}.timeline",
            "type": "timeline",
            "inputs": {
                "aspect": "9:16",
                "shots": [
                    {"clip": f"@{c}", "duration": 4, "fallback": f"@{k}"} for c, k in zip(clips, keyframes)
                ],
                "vo": [{"audio": f"@{v}.vo.l01", "text": f"Line for {v}"}],
                "end_card": {"text": "Shop now", "duration": 2},
            },
            "depends_on": clips + keyframes + [f"{v}.vo.l01"],
        })
        nodes.append({
            "id": f"{v}.preview",
            "type": "preview",
            "inputs": {"timeline": f"@{v}.timeline"},
            "depends_on": [f"{v}.timeline"],
        })
        nodes.append({
            "id": f"{v}.capcut_draft",
            "type": "capcut_draft",
            "inputs": {"timeline": f"@{v}.timeline"},
            "depends_on": [f"{v}.timeline"],
        })
    return {"manifest_version": 1, "project": "mug-launch", "nodes": nodes}


def node(data: dict, node_id: str) -> dict:
    """Return the node dict with this id from a manifest dict (mutable)."""
    return next(n for n in data["nodes"] if n["id"] == node_id)


class RecordingProvider(MockProvider):
    """MockProvider that records every call and injects per-node behaviour:
    delays (seconds), fail (hard error), transient {id: failures before success},
    refuse (content refusal)."""

    def __init__(self, *, delays=None, default_delay=0.0, fail=(), transient=None, refuse=(), cost_per_call=0.0):
        super().__init__(cost_per_call=cost_per_call)
        self.delays = dict(delays or {})
        self.default_delay = default_delay
        self.fail = set(fail)
        self.transient = dict(transient or {})
        self.refuse = set(refuse)
        self.calls: list[str] = []
        self.events: list[tuple[str, str]] = []
        self.active = 0
        self.max_active = 0

    async def _before(self, ctx):
        nid = ctx.node_id
        self.calls.append(nid)
        self.events.append(("start", nid))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delays.get(nid, self.default_delay))
            if nid in self.fail:
                raise RuntimeError("boom")
            if self.transient.get(nid, 0) > 0:
                self.transient[nid] -= 1
                raise TransientProviderError("429 rate limited")
            if nid in self.refuse:
                raise ProviderRefusal("content policy")
        finally:
            self.active -= 1
            self.events.append(("end", nid))


FAST = EngineConfig.from_dict({"retry": {"base_delay_s": 0}, "default_concurrency": 8})


GOLDEN_DIR = Path(__file__).parent / "golden"


def assert_golden(name: str, data) -> None:
    """Compare JSON-able `data` with tests/golden/<name>. Run once with
    ADFORGE_UPDATE_GOLDEN=1 to (re)write the file, then review it before committing."""
    path = GOLDEN_DIR / name
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if os.environ.get("ADFORGE_UPDATE_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    assert path.exists(), f"missing golden file {path}; run with ADFORGE_UPDATE_GOLDEN=1 and review it"
    assert json.loads(path.read_text()) == json.loads(text)
