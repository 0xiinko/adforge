"""The manifest /ad writes (skills/ad-runner/example-manifest.json) must work with the engine."""
import asyncio
import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

from engine.assembly.timeline import build_timeline
from engine.cli import main
from engine.core.graph import load_manifest
from engine.core.paths import output_path, resolve_inputs
from engine.providers.mock import PNG_1X1

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "skills" / "ad-runner" / "example-manifest.json"
CONFIG = ROOT / "skills" / "ad-runner" / "example-config.yaml"
SHOTS = [f"s{i:02d}" for i in range(1, 6)]


@pytest.fixture
def ad_dir(tmp_path):
    d = tmp_path / "complete-kit-dustpan"
    d.mkdir()
    shutil.copy(EXAMPLE, d / "manifest.json")
    shutil.copy(CONFIG, d / "config.yaml")
    return d


def nodes():
    return {n["id"]: n for n in json.loads(EXAMPLE.read_text())["nodes"]}


def test_example_config_routes_images_and_video_to_ellora():
    cfg = yaml.safe_load(CONFIG.read_text())
    assert cfg["external_providers"] == ["ellora"]
    assert cfg["routing"]["image"] == {"provider": "ellora", "model": "nano-banana-pro"}
    assert cfg["routing"]["video"] == {"provider": "ellora", "model": "kling-3.0/video"}


def test_example_manifest_validates(ad_dir, capsys):
    assert main(["validate", str(ad_dir)]) == 0
    assert capsys.readouterr().out.strip() == "OK: 13 nodes"


def test_example_manifest_shape():
    n = nodes()
    assert len(n) == 13
    assert not [i for i, node in n.items() if node["type"] in ("tts", "sfx", "music")]
    for s in SHOTS:
        kf, clip = n[f"v1.{s}.keyframe"], n[f"v1.{s}.clip"]
        assert kf["type"] == "image" and kf["inputs"] == {"aspect": "9:16"} and kf["depends_on"] == []
        assert kf["prompt"].strip() and clip["prompt"].strip()
        assert clip["type"] == "video" and clip["depends_on"] == [f"v1.{s}.keyframe"]
        assert clip["inputs"]["first_frame"] == f"@v1.{s}.keyframe"
        assert clip["inputs"]["aspect"] == "9:16" and clip["inputs"]["duration"] in (4, 5)
    total = sum(n[f"v1.{s}.clip"]["inputs"]["duration"] for s in SHOTS)
    assert 20 <= total <= 25
    tl = n["v1.timeline"]["inputs"]
    assert "vo" not in tl and "music" not in tl and tl["captions"] is True
    assert not [d for d in n["v1.timeline"]["depends_on"] if ".vo." in d or "music" in d]
    for k, s in enumerate(SHOTS):
        shot = tl["shots"][k]
        clip = n[f"v1.{s}.clip"]
        assert shot["duration"] == clip["inputs"]["duration"]
        assert shot["clip"] == f"@v1.{s}.clip"
        assert shot["fallback"] == f"@v1.{s}.keyframe"
        assert shot["audio"] is True
        words = len(shot["text"].split())
        assert 0 < words <= 14 and words <= 2.6 * shot["duration"], shot["text"]
        assert f'"{shot["text"]}"' in clip["prompt"]
        assert "natural ambient sound, no music" in clip["prompt"].lower()


def test_example_copy_respects_ellora_claim_rules():
    banned = ["cure", "treat", "prevent", "clinically proven", "doctor", "pharmacist", "candida", "ibs",
              "before and after", "parasite", "heal", "diagnosed", "diagnosis"]
    n = nodes()
    tl = n["v1.timeline"]["inputs"]
    copy = [shot["text"] for shot in tl["shots"]]
    copy.append(tl["end_card"]["text"])
    for line in copy:
        hits = [w for w in banned if re.search(r"\b" + re.escape(w) + r"\b", line.lower())]
        assert not hits, line


def test_example_bottle_shots_use_the_label_wording():
    n = nodes()
    assert "Ellora Gut Cleanse (Step 1)" in n["v1.s02.keyframe"]["prompt"]
    assert "DIGESTIVE HEALTH & GUT BALANCE" in n["v1.s02.keyframe"]["prompt"]
    assert "Ellora Zeolite Drops (Step 2)" in n["v1.s04.keyframe"]["prompt"]
    assert "NATURAL HEAVY METAL DETOX SUPPORT" in n["v1.s04.keyframe"]["prompt"]
    for s in ("s02", "s04", "s05"):
        assert "Dietary Supplement" in n[f"v1.{s}.keyframe"]["prompt"]
    assert n["v1.s04.keyframe"]["prompt"].lower().count("dietary supplement") >= 2
    assert "the same woman" not in n["v1.s05.keyframe"]["prompt"].lower()


def test_example_timeline_inputs_build(ad_dir):
    manifest = load_manifest(ad_dir / "manifest.json")
    node = manifest.nodes["v1.timeline"]
    inputs = resolve_inputs(manifest, ad_dir, node)
    sources, media = {}, {}
    for dep in node.depends_on:
        dn = manifest.nodes[dep]
        path = str(output_path(ad_dir, dep, dn.type))
        sources[path] = dep
        media[path] = {"image": 0.0, "video": float(dn.inputs.get("duration", 0))}[dn.type]
    audio = frozenset(p for p, dep in sources.items() if manifest.nodes[dep].type == "video")
    timeline = build_timeline("v1.timeline", inputs, sources=sources, project_dir=ad_dir, media=media,
                              audio_paths=audio)
    assert [e["audio"] for e in timeline["tracks"]["video"]] == [True] * 5
    assert timeline["tracks"]["vo"] == [] and timeline["tracks"]["music"] is None
    assert timeline["tracks"]["captions"][0]["start"] == 0.0 and timeline["warnings"] == []


def test_example_config_assembles_for_real():
    routing = yaml.safe_load(CONFIG.read_text())["routing"]
    for t in ("timeline", "preview", "capcut_draft"):
        assert routing[t]["provider"] == "assembly"
    assert not {"tts", "sfx", "music"} & set(routing)


def test_example_runs_through_the_ellora_loop(ad_dir, capsys, ffmpeg):
    """Plays Claude's part: 'renders' each awaiting node (tiny real media via ffmpeg),
    supplies it, and re-runs until the real preview and CapCut draft exist."""
    passes = 0
    while (code := main(["run", str(ad_dir)])) == 3:
        passes += 1
        assert passes <= 3
        capsys.readouterr()
        assert main(["external", str(ad_dir), "--json"]) == 0
        for item in json.loads(capsys.readouterr().out):
            if item["type"] == "video":
                keyframe = item["id"].replace(".clip", ".keyframe")
                assert item["external_inputs"]["first_frame"] == f"ellora://{keyframe}"
                f = ad_dir / f"{item['id']}.mp4"
                asyncio.run(ffmpeg.run([  # Ellora clips carry their own audio (spoken line + sound)
                    "-f", "lavfi", "-i", "color=c=gray:s=270x480:r=24",
                    "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000",
                    "-t", str(item["inputs"]["duration"]), "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(f),
                ]))
            else:
                assert "refs" not in item["inputs"]
                f = ad_dir / f"{item['id']}.png"
                f.write_bytes(PNG_1X1)
            assert main(["supply", str(ad_dir), item["id"], str(f), "--ref", f"ellora://{item['id']}",
                         "--fingerprint", item["fingerprint"]]) == 0
    assert code == 0 and passes == 2  # keyframes, then clips
    timeline = json.loads((ad_dir / "v1" / "timeline.json").read_text())
    assert timeline["placeholders"] == [] and timeline["warnings"] == []
    assert [e["audio"] for e in timeline["tracks"]["video"]] == [True] * 5
    info = asyncio.run(ffmpeg.probe(ad_dir / "v1" / "preview.mp4"))
    assert (info.width, info.height) == (1080, 1920) and info.has_audio
    assert info.duration == pytest.approx(timeline["duration"], abs=0.2)
    draft = json.loads((ad_dir / "v1" / "capcut_draft" / "draft_content.json").read_text())
    assert [m["material_name"] for m in draft["materials"]["videos"]] == [f"v1.{s}.clip" for s in SHOTS]
    main_track = next(t for t in draft["tracks"] if t["name"] == "main")
    assert [s["volume"] for s in main_track["segments"]] == [1.0] * 5
    assert not [t for t in draft["tracks"] if t["type"] == "audio"]
