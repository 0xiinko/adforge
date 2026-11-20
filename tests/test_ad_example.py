"""The manifest /ad writes (skills/ad-runner/example-manifest.json) — two hooks sharing one body,
one consistent presenter — must work with the engine end to end."""
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
VARIANTS = {"v1": ["v1.s01", "v1.s02"], "v2": ["v2.s01", "v2.s02"]}
BODY = ["body.s01", "body.s02", "body.s03", "body.s04"]
CAST = "cast.maya.ref"
NO_CAST = {"body.s03"}  # the packshot: no person on screen, Maya speaks off camera
LOOK = ("Maya (the woman in the reference image: mid-thirties, warm brown skin, shoulder-length dark "
        "curly hair pulled half up, small gold hoop earrings, oversized cream knit sweater)")
VOICE = "a warm, low, unhurried American woman's voice, a little dry and knowing"
ANTI_SLOP_IMAGE = "Natural skin texture, anatomically correct hands, no extra fingers, no text, no watermark."
ANTI_SLOP_VIDEO = "Stable face and hands, no morphing or warping."


@pytest.fixture
def ad_dir(tmp_path):
    d = tmp_path / "complete-kit-four-hooks"
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
    for t in ("timeline", "preview", "capcut_draft"):
        assert cfg["routing"][t]["provider"] == "assembly"


def test_example_manifest_validates(ad_dir, capsys):
    assert main(["validate", str(ad_dir)]) == 0
    assert capsys.readouterr().out.strip() == "OK: 23 nodes"


def test_cast_reference_is_a_plain_portrait():
    cast = nodes()[CAST]
    assert cast["type"] == "image" and cast["depends_on"] == [] and cast["inputs"] == {"aspect": "9:16"}
    assert "looking straight into the camera" in cast["prompt"]
    assert cast["prompt"].endswith(ANTI_SLOP_IMAGE)


def test_every_shot_with_maya_uses_the_reference_and_the_look_phrase():
    n = nodes()
    for shot in [s for shots in VARIANTS.values() for s in shots] + BODY:
        kf = n[f"{shot}.keyframe"]
        assert kf["type"] == "image" and kf["prompt"].endswith(ANTI_SLOP_IMAGE), shot
        if shot in NO_CAST:
            assert kf["inputs"] == {"aspect": "9:16"} and kf["depends_on"] == [], shot
            assert "Maya" not in kf["prompt"], shot
        else:
            assert kf["inputs"] == {"aspect": "9:16", "refs": [f"@{CAST}"]}, shot
            assert kf["depends_on"] == [CAST], shot
            assert LOOK in kf["prompt"], shot


def test_every_clip_speaks_its_line_in_mayas_voice():
    n = nodes()
    for shot in [s for shots in VARIANTS.values() for s in shots] + BODY:
        clip = n[f"{shot}.clip"]
        assert clip["type"] == "video" and clip["depends_on"] == [f"{shot}.keyframe"], shot
        assert clip["inputs"]["first_frame"] == f"@{shot}.keyframe" and clip["inputs"]["aspect"] == "9:16"
        assert clip["inputs"]["duration"] in (4, 5), shot
        assert VOICE in clip["prompt"] and ANTI_SLOP_VIDEO in clip["prompt"], shot
        assert "natural ambient sound, no music" in clip["prompt"].lower(), shot


def test_each_variant_is_its_hook_then_the_shared_body():
    n = nodes()
    assert not [i for i, node in n.items() if node["type"] in ("tts", "sfx", "music")]
    assert not [i for i in n if i.startswith(("v1.body", "v2.body"))]
    for v, hook in VARIANTS.items():
        tl = n[f"{v}.timeline"]
        shots = tl["inputs"]["shots"]
        assert [s["clip"] for s in shots] == [f"@{x}.clip" for x in hook + BODY]
        assert tl["inputs"]["captions"] is True and "vo" not in tl["inputs"] and "music" not in tl["inputs"]
        assert set(tl["depends_on"]) == {f"{x}.{k}" for x in hook + BODY for k in ("clip", "keyframe")}
        for s, x in zip(shots, hook + BODY):
            clip = n[f"{x}.clip"]
            assert s["fallback"] == f"@{x}.keyframe" and s["audio"] is True
            assert s["duration"] == clip["inputs"]["duration"]
            words = len(s["text"].split())
            assert 0 < words <= 14 and words <= 2.6 * s["duration"], s["text"]
            assert f'"{s["text"]}"' in clip["prompt"], x
        assert n[f"{v}.preview"]["inputs"] == {"timeline": f"@{v}.timeline"}
        assert n[f"{v}.capcut_draft"]["inputs"] == {"timeline": f"@{v}.timeline"}


def test_lines_come_word_for_word_from_the_example_brief():
    brief = " ".join((ROOT / "docs" / "examples" / "brief-ellora-four-hooks.md").read_text().split())
    n = nodes()
    for v in VARIANTS:
        for s in n[f"{v}.timeline"]["inputs"]["shots"]:
            assert s["text"] in brief, s["text"]


def test_example_copy_respects_ellora_claim_rules():
    banned = ["cure", "treat", "prevent", "clinically proven", "doctor", "pharmacist", "candida", "ibs",
              "before and after", "parasite", "heal", "diagnosed", "diagnosis", "herpes", "virus", "antiviral"]
    n = nodes()
    copy = [s["text"] for v in VARIANTS for s in n[f"{v}.timeline"]["inputs"]["shots"]]
    copy += [n[f"{v}.timeline"]["inputs"]["end_card"]["text"] for v in VARIANTS]
    for line in copy:
        hits = [w for w in banned if re.search(r"\b" + re.escape(w) + r"\b", line.lower())]
        assert not hits, line


def test_bottle_shots_use_the_label_wording():
    n = nodes()
    held = n["body.s01.keyframe"]["prompt"]
    assert "Ellora Gut Cleanse (Step 1)" in held and "DIGESTIVE HEALTH & GUT BALANCE" in held
    pack = n["body.s03.keyframe"]["prompt"]
    for needle in ("Ellora Gut Cleanse (Step 1)", "DIGESTIVE HEALTH & GUT BALANCE",
                   "Ellora Zeolite Drops (Step 2)", "NATURAL HEAVY METAL DETOX SUPPORT"):
        assert needle in pack, needle
    assert pack.lower().count("dietary supplement") >= 2 and "Dietary Supplement" in held


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_example_timeline_inputs_build(ad_dir, variant):
    manifest = load_manifest(ad_dir / "manifest.json")
    node = manifest.nodes[f"{variant}.timeline"]
    inputs = resolve_inputs(manifest, ad_dir, node)
    sources, media = {}, {}
    for dep in node.depends_on:
        dn = manifest.nodes[dep]
        path = str(output_path(ad_dir, dep, dn.type))
        sources[path] = dep
        media[path] = {"image": 0.0, "video": float(dn.inputs.get("duration", 0))}[dn.type]
    audio = frozenset(p for p, dep in sources.items() if manifest.nodes[dep].type == "video")
    timeline = build_timeline(f"{variant}.timeline", inputs, sources=sources, project_dir=ad_dir,
                              media=media, audio_paths=audio)
    assert [e["audio"] for e in timeline["tracks"]["video"]] == [True] * 6
    assert timeline["warnings"] == [] and timeline["placeholders"] == []


def test_cast_preview_renders_only_the_cast(ad_dir, capsys):
    assert main(["run", str(ad_dir), "--only", "cast.*"]) == 3
    capsys.readouterr()
    assert main(["external", str(ad_dir), "--json"]) == 0
    items = json.loads(capsys.readouterr().out)
    assert [i["id"] for i in items] == [CAST]
    f = ad_dir / "maya.png"
    f.write_bytes(PNG_1X1)
    assert main(["supply", str(ad_dir), CAST, str(f), "--ref", f"ellora://{CAST}",
                 "--fingerprint", items[0]["fingerprint"]]) == 0
    assert main(["run", str(ad_dir), "--only", "cast.*"]) == 0
    assert main(["run", str(ad_dir)]) == 3
    capsys.readouterr()
    assert main(["external", str(ad_dir), "--json"]) == 0
    assert CAST not in [i["id"] for i in json.loads(capsys.readouterr().out)]


def test_example_runs_through_the_ellora_loop(ad_dir, capsys, ffmpeg):
    """Plays Claude's part: 'renders' each awaiting node (tiny real media), supplies it, re-runs."""
    passes = 0
    while (code := main(["run", str(ad_dir)])) == 3:
        passes += 1
        assert passes <= 4
        capsys.readouterr()
        assert main(["external", str(ad_dir), "--json"]) == 0
        for item in json.loads(capsys.readouterr().out):
            if item["type"] == "video":
                keyframe = item["id"].replace(".clip", ".keyframe")
                assert item["external_inputs"]["first_frame"] == f"ellora://{keyframe}"
                f = ad_dir / f"{item['id']}.mp4"
                asyncio.run(ffmpeg.run([
                    "-f", "lavfi", "-i", "color=c=gray:s=270x480:r=24",
                    "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000",
                    "-t", str(item["inputs"]["duration"]), "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(f),
                ]))
            else:
                if item["id"] == CAST or item["id"].replace(".keyframe", "") in NO_CAST:
                    assert "refs" not in item["inputs"], item["id"]
                else:
                    assert item["external_inputs"]["refs"] == [f"ellora://{CAST}"], item["id"]
                f = ad_dir / f"{item['id']}.png"
                f.write_bytes(PNG_1X1)
            assert main(["supply", str(ad_dir), item["id"], str(f), "--ref", f"ellora://{item['id']}",
                         "--fingerprint", item["fingerprint"]]) == 0
    assert code == 0 and passes == 3  # cast + packshot keyframe; keyframes (+ packshot clip); clips
    for v, hook in VARIANTS.items():
        timeline = json.loads((ad_dir / v / "timeline.json").read_text())
        assert timeline["placeholders"] == []
        info = asyncio.run(ffmpeg.probe(ad_dir / v / "preview.mp4"))
        assert (info.width, info.height) == (1080, 1920) and info.has_audio
        assert info.duration == pytest.approx(timeline["duration"], abs=0.2)
        draft = json.loads((ad_dir / v / "capcut_draft" / "draft_content.json").read_text())
        assert [m["material_name"] for m in draft["materials"]["videos"]] == [f"{x}.clip" for x in hook + BODY]
    body_versions = {json.loads((ad_dir / "state.json").read_text())["nodes"][f"{b}.clip"]["version"] for b in BODY}
    assert body_versions == {1}  # the shared body rendered exactly once
