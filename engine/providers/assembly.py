"""Engine-internal provider for timeline, preview and capcut_draft nodes (spec §7).
Free: assembly never reaches the ledger."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from engine.assembly.capcut_draft import build_draft, write_draft
from engine.assembly.ffmpeg import FFmpeg
from engine.assembly.ffmpeg_preview import render_preview, render_slate_image
from engine.assembly.timeline import IMAGE_SUFFIXES, build_timeline, media_paths
from engine.config import CapcutConfig
from engine.core.paths import output_path
from engine.providers.base import CallContext, Provider, ProviderError


class AssemblyProvider(Provider):
    name = "assembly"

    def __init__(self, ffmpeg: FFmpeg | None = None, capcut: CapcutConfig | None = None,
                 clock: Callable[[], float] = time.time):
        self.ff = ffmpeg or FFmpeg()
        self.capcut = capcut or CapcutConfig()
        self.clock = clock

    async def assemble(self, ctx: CallContext, node_type: str, inputs: dict[str, Any]) -> Path:
        if ctx.project_dir is None:
            raise ProviderError(f"{ctx.node_id}: assembly needs the project directory")
        if node_type == "timeline":
            return await self._timeline(ctx, inputs)
        timeline = self._load_timeline(ctx, inputs)
        if node_type == "preview":
            return await render_preview(timeline, ctx.project_dir, ctx.work_dir, self.ff)
        if node_type == "capcut_draft":
            return await self._capcut_draft(ctx, timeline)
        raise ProviderError(f"{ctx.node_id}: assembly does not handle {node_type}")

    async def _timeline(self, ctx: CallContext, inputs: dict[str, Any]) -> Path:
        media: dict[str, float] = {}
        audio_paths: set[str] = set()
        for path in dict.fromkeys(media_paths(inputs)):
            p = Path(path)
            if ctx.sources.get(path) not in ctx.unavailable and p.exists():
                if p.suffix.lower() in IMAGE_SUFFIXES:
                    media[path] = 0.0
                else:
                    info = await self.ff.probe(p)
                    media[path] = info.duration
                    if info.has_audio:
                        audio_paths.add(path)
        data = build_timeline(ctx.node_id, inputs, sources=ctx.sources, project_dir=ctx.project_dir, media=media,
                              audio_paths=frozenset(audio_paths))
        out = ctx.work_dir / "timeline.json"
        out.write_text(json.dumps(data, indent=2) + "\n")
        return out

    def _load_timeline(self, ctx: CallContext, inputs: dict[str, Any]) -> dict[str, Any]:
        path = inputs.get("timeline")
        if not isinstance(path, str) or not Path(path).exists():
            raise ProviderError(f"{ctx.node_id}: inputs.timeline must reference a rendered timeline node")
        return json.loads(Path(path).read_text())

    async def _capcut_draft(self, ctx: CallContext, timeline: dict[str, Any]) -> Path:
        project_dir = ctx.project_dir
        draft_name = f"{project_dir.name}_{ctx.node_id.split('.')[0]}"
        final_dir = output_path(project_dir, ctx.node_id, "capcut_draft")
        out_dir = ctx.work_dir / "capcut_draft"
        placeholders = out_dir / "placeholders"
        placeholders.mkdir(parents=True)
        slates: dict[int, Path] = {}
        for i, e in enumerate(timeline["tracks"]["video"]):
            if e["kind"] == "slate":
                name = f"slate_{i:02d}.png"
                await render_slate_image(self.ff, placeholders, name, timeline["width"], timeline["height"],
                                         f"MISSING\n{e['placeholder_for']}")
                slates[i] = final_dir / "placeholders" / name
        export_dir = self.capcut.drafts_dir / draft_name if self.capcut.drafts_dir else None
        draft, meta = build_draft(
            timeline, project_dir=project_dir, draft_dir=export_dir or final_dir, draft_name=draft_name,
            media_root=self.capcut.media_root, now_us=int(self.clock() * 1_000_000), slates=slates,
        )
        write_draft(out_dir, draft, meta)
        if export_dir:
            if export_dir.exists():
                shutil.rmtree(export_dir)
            shutil.copytree(out_dir, export_dir)
        return out_dir
