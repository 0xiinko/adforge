"""The manifest /ad writes (skills/ad-runner/example-manifest.json) must work with the engine."""
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
    assert capsys.readouterr().out.strip() == "OK: 19 nodes"


def test_example_manifest_shape():
    n = nodes()
    assert len(n) == 19
    for s in SHOTS:
        kf, clip = n[f"v1.{s}.keyframe"], n[f"v1.{s}.clip"]
        assert kf["type"] == "image" and kf["inputs"] == {"aspect": "9:16"} and kf["depends_on"] == []
        assert kf["prompt"].strip() and clip["prompt"].strip()
        assert clip["type"] == "video" and clip["depends_on"] == [f"v1.{s}.keyframe"]
        assert clip["inputs"]["first_frame"] == f"@v1.{s}.keyframe"
        assert clip["inputs"]["aspect"] == "9:16" and clip["inputs"]["duration"] in (4, 5)
    total = sum(n[f"v1.{s}.clip"]["inputs"]["duration"] for s in SHOTS)
    assert 20 <= total <= 25
    for i in range(1, 6):
        vo = n[f"v1.vo.l{i:02d}"]
        assert vo["type"] == "tts" and len(vo["inputs"]["text"].split()) <= 14
    assert n["v1.music.bed"]["inputs"]["duration"] == total + n["v1.timeline"]["inputs"]["end_card"]["duration"]
    tl = n["v1.timeline"]["inputs"]
    for i in range(1, 6):
        assert tl["vo"][i - 1]["text"] == n[f"v1.vo.l{i:02d}"]["inputs"]["text"]
        assert tl["vo"][i - 1]["audio"] == f"@v1.vo.l{i:02d}"
    for k, s in enumerate(SHOTS):
        shot = tl["shots"][k]
        assert shot["duration"] == n[f"v1.{s}.clip"]["inputs"]["duration"]
        assert shot["clip"] == f"@v1.{s}.clip"
        assert shot["fallback"] == f"@v1.{s}.keyframe"


def test_example_copy_respects_ellora_claim_rules():
    banned = ["cure", "treat", "prevent", "clinically proven", "doctor", "pharmacist", "candida", "ibs",
              "before and after", "parasite", "heal", "diagnosed", "diagnosis"]
    n = nodes()
    tl = n["v1.timeline"]["inputs"]
    copy = [n[f"v1.vo.l{i:02d}"]["inputs"]["text"] for i in range(1, 6)]
    copy += [v["text"] for v in tl["vo"]]
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
        media[path] = {"image": 0.0, "video": float(dn.inputs.get("duration", 0)), "tts": 3.0,
                       "music": float(dn.inputs.get("duration", 0))}[dn.type]
    timeline = build_timeline("v1.timeline", inputs, sources=sources, project_dir=ad_dir, media=media)
    assert isinstance(timeline, dict) and timeline


def test_example_runs_through_the_ellora_loop(ad_dir, capsys):
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
                f.write_bytes(b"clip")
            else:
                assert "refs" not in item["inputs"]
                f = ad_dir / f"{item['id']}.png"
                f.write_bytes(PNG_1X1)
            assert main(["supply", str(ad_dir), item["id"], str(f), "--ref", f"ellora://{item['id']}",
                         "--fingerprint", item["fingerprint"]]) == 0
    assert code == 0 and passes == 2  # keyframes, then clips
    assert (ad_dir / "v1" / "preview.mp4").exists()
    assert (ad_dir / "v1" / "capcut_draft").is_dir()
