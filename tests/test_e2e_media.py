"""Spec §10 mock end-to-end with real media: manifest → parallel run (mock_media)
→ timeline → preview.mp4 → CapCut draft, through the adengine CLI."""
import asyncio
import json
import shutil
from pathlib import Path

import pytest
import yaml

from engine.cli import main

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.yaml"


@pytest.fixture
def media_project(project_dir, ffmpeg):
    shutil.copy(EXAMPLE, project_dir / "config.yaml")
    return project_dir


def test_full_render_produces_previews_and_drafts(media_project, ffmpeg):
    assert main(["run", str(media_project)]) == 0
    for v in ("v1", "v2"):
        info = asyncio.run(ffmpeg.probe(media_project / v / "preview.mp4"))
        assert (info.width, info.height) == (1080, 1920) and info.has_audio
        assert info.duration == pytest.approx(10.0, abs=0.2)
        timeline = json.loads((media_project / v / "timeline.json").read_text())
        assert timeline["placeholders"] == [] and timeline["duration"] == 10.0
        draft = json.loads((media_project / v / "capcut_draft/draft_content.json").read_text())
        assert [t["name"] for t in draft["tracks"]] == ["main", "vo", "captions", "end_card"]
        assert [m["material_name"] for m in draft["materials"]["videos"]] == [f"{v}.s01.clip", f"{v}.s02.clip"]


def test_failed_clip_degrades_to_keyframe_placeholder(media_project, ffmpeg, capsys):
    assert main(["revise", str(media_project), "v1.s01.clip", "--json",
                 '{"provider": "nope", "model": "x"}', "--no-run"]) == 0
    assert main(["run", str(media_project), "--only", "v1.preview"]) == 1
    assert "ATTENTION v1.s01.clip" in capsys.readouterr().out
    timeline = json.loads((media_project / "v1/timeline.json").read_text())
    assert timeline["placeholders"] == ["v1.s01.clip"]
    assert timeline["tracks"]["video"][0]["kind"] == "image"
    info = asyncio.run(ffmpeg.probe(media_project / "v1/preview.mp4"))
    assert info.duration == pytest.approx(10.0, abs=0.2)


def test_capcut_draft_exported_to_drafts_dir_with_rewritten_paths(media_project, tmp_path):
    path = media_project / "config.yaml"
    config = yaml.safe_load(path.read_text())
    config["capcut"] = {"drafts_dir": str(tmp_path / "drafts"), "media_root": "C:/AdForge/projects"}
    path.write_text(yaml.safe_dump(config))
    assert main(["run", str(media_project), "--only", "v1.capcut_draft"]) == 0
    exported = tmp_path / "drafts" / "mug-launch_v1" / "draft_content.json"
    draft = json.loads(exported.read_text())
    assert draft["materials"]["videos"][0]["path"] == "C:/AdForge/projects/mug-launch/v1/shots/s01/clip.mp4"
