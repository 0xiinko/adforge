import asyncio
import json

import pytest

from engine.assembly.ffmpeg import FFmpeg
from engine.providers import build_providers
from engine.providers.assembly import AssemblyProvider
from engine.providers.base import CallContext, ProviderError
from engine.providers.mock_media import MediaMockProvider
from engine.config import EngineConfig


def ctx(tmp_path, node_id, **kw):
    work = tmp_path / ".tmp" / node_id
    work.mkdir(parents=True)
    return CallContext(node_id=node_id, model="builtin", work_dir=work, **kw)


def test_registry_has_mock_media_and_assembly():
    providers = build_providers(EngineConfig())
    assert isinstance(providers["mock_media"], MediaMockProvider)
    assert isinstance(providers["assembly"], AssemblyProvider)


def test_assembly_needs_project_dir(tmp_path):
    with pytest.raises(ProviderError, match="project directory"):
        asyncio.run(AssemblyProvider(FFmpeg()).assemble(ctx(tmp_path, "v1.timeline"), "timeline", {}))


def test_preview_needs_a_rendered_timeline(tmp_path):
    with pytest.raises(ProviderError, match="inputs.timeline"):
        asyncio.run(AssemblyProvider(FFmpeg()).assemble(
            ctx(tmp_path, "v1.preview", project_dir=tmp_path), "preview", {"timeline": str(tmp_path / "nope.json")}))


def test_timeline_with_all_inputs_missing_needs_no_ffmpeg(tmp_path):
    clip = str(tmp_path / "v1/shots/s01/clip.mp4")
    c = ctx(tmp_path, "v1.timeline", project_dir=tmp_path, sources={clip: "v1.s01.clip"})
    out = asyncio.run(AssemblyProvider(FFmpeg()).assemble(c, "timeline", {"shots": [{"clip": clip, "duration": 2}]}))
    data = json.loads(out.read_text())
    assert data["placeholders"] == ["v1.s01.clip"] and data["tracks"]["video"][0]["kind"] == "slate"
    assert AssemblyProvider(FFmpeg()).cost("timeline", {}) == 0.0
