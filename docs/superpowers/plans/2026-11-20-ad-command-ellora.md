# `/ad` for Ellora Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Claude Code plugin at the AdForge repo root whose `/ad <brief>` command takes an Ellora ad from brief to rendered assets with one approval gate, rendering every image and video in Ellora Studio through the engine's external-provider loop.

**Architecture:** Prose skills (one per stage, one output file each) plus a short orchestrating command; the engine is driven through the `adengine` CLI. A complete example manifest and config ship with the `ad-runner` skill; tests validate that example against the engine (schema, external rules, timeline builder, full mock supply loop) and check the plugin's structure. No engine code changes.

**Tech Stack:** Claude Code plugin format (`.claude-plugin/plugin.json`, `commands/*.md`, `skills/*/SKILL.md`, `agents/*.md`), Python 3.11 tests with pytest and pyyaml (already dependencies).

**Spec:** `docs/superpowers/specs/2026-11-20-ad-command-ellora-design.md`

## Global Constraints

- Branch `feat/ellora`, worktree `/home/iinko/PROJECT_AUTOMATION/adforge/.claude/worktrees/ellora`. Never work in `/home/iinko/PROJECT_AUTOMATION/adforge` itself (another session uses it).
- Tests: `.venv/bin/python -m pytest -q` from the worktree root; all 203 existing tests keep passing.
- No engine code changes in this plan. No new dependencies.
- Defaults: 1 variant, 5 shots of 4–5 s, 20–25 s total, 9:16, Meta/TikTok, product Complete Kit ($49.99).
- Ellora models: image `nano-banana-pro`, video `kling-3.0/video`; clips render with `generateAudio: false`.
- Every keyframe is `type: image`, `inputs: {"aspect": "9:16"}`, no `@ref` inputs, no `n`. Every clip has `first_frame: "@vN.sXX.keyframe"`.
- VO lines ≤ 14 words. Ad copy must respect the Ellora claim rules (no cure/treat/prevent, no named conditions, no before/after bodies, no "clinically proven", no doctor/pharmacist endorsement, no testimonial stating a resolved diagnosis).
- Shell note: plain `git`, `ls`, `cat` may fail with `_lc: command not found`; prefix with `command` if so.

## File map

| File | Task | Purpose |
|---|---|---|
| `skills/ad-runner/example-manifest.json` | 1 | The exact manifest shape `/ad` writes (1 variant, 5 shots) |
| `skills/ad-runner/example-config.yaml` | 1 | The `config.yaml` `/ad` writes |
| `tests/test_ad_example.py` | 1 | Example validates, timeline builds, full mock supply loop finishes |
| `.claude-plugin/plugin.json` | 2 | Plugin manifest |
| `skills/ad-strategist/SKILL.md` | 2 | Stage 1: brief → `brand/ellora.md`, `brief.md`, `plan.md` |
| `skills/script-writer/SKILL.md` | 2 | Stage 2: `vN/script.md` incl. claim check |
| `skills/shot-planner/SKILL.md` | 2 | Stage 3: `vN/shots.md` |
| `agents/variant-writer.md` | 2 | Subagent: stages 2–4 for one variant when N > 1 |
| `tests/test_plugin_structure.py` | 2, 3 | plugin.json, skill/agent frontmatter, command wiring |
| `skills/prompt-craft/SKILL.md` | 3 | Stage 4: `vN/prompts.md` |
| `skills/ad-runner/SKILL.md` | 3 | Stage 5: manifest, gate, render loop, report, revisions |
| `commands/ad.md` | 3 | `/ad <brief>` orchestrator |

---

### Task 1: Example manifest and config, validated against the engine

**Files:**
- Create: `skills/ad-runner/example-manifest.json`
- Create: `skills/ad-runner/example-config.yaml`
- Test: `tests/test_ad_example.py`

**Interfaces:**
- Consumes: engine CLI `engine.cli.main` (`validate`, `run`, `external --json`, `supply`), `engine.core.graph.load_manifest`, `engine.core.paths.resolve_inputs`, `engine.core.paths.output_path`, `engine.assembly.timeline.build_timeline(node_id, inputs, *, sources, project_dir, media)`, `engine.providers.mock.PNG_1X1`.
- Produces: `skills/ad-runner/example-manifest.json` (19 nodes: `v1.s01`–`v1.s05` keyframe+clip, `v1.vo.l01`–`l05`, `v1.music.bed`, `v1.timeline`, `v1.preview`, `v1.capcut_draft`) and `skills/ad-runner/example-config.yaml`; Task 3's `ad-runner` skill points at both.

- [ ] **Step 1: Write the failing tests** — create `tests/test_ad_example.py`:

```python
"""The manifest /ad writes (skills/ad-runner/example-manifest.json) must work with the engine."""
import json
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


def test_example_copy_respects_ellora_claim_rules():
    banned = ["cure", "treat", "prevent", "clinically proven", "doctor", "pharmacist", "candida", "ibs",
              "before and after", "parasite"]
    n = nodes()
    copy = [n[f"v1.vo.l{i:02d}"]["inputs"]["text"] for i in range(1, 6)]
    copy.append(n["v1.timeline"]["inputs"]["end_card"]["text"])
    for line in copy:
        assert not [w for w in banned if w in line.lower()], line


def test_example_bottle_shots_use_the_label_wording():
    n = nodes()
    assert "Ellora Gut Cleanse (Step 1)" in n["v1.s02.keyframe"]["prompt"]
    assert "DIGESTIVE HEALTH & GUT BALANCE" in n["v1.s02.keyframe"]["prompt"]
    assert "Ellora Zeolite Drops (Step 2)" in n["v1.s04.keyframe"]["prompt"]
    assert "NATURAL HEAVY METAL DETOX SUPPORT" in n["v1.s04.keyframe"]["prompt"]
    for s in ("s02", "s04", "s05"):
        assert "Dietary Supplement" in n[f"v1.{s}.keyframe"]["prompt"]


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
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ad_example.py -q`
Expected: FAIL — `FileNotFoundError` for `skills/ad-runner/example-config.yaml` / `example-manifest.json`.

- [ ] **Step 3: Create `skills/ad-runner/example-config.yaml`**

```yaml
# The config.yaml /ad writes into projects/<slug>/. Ellora renders every image and
# video; Claude supplies them with `adengine supply`. Audio stays mock until real
# TTS/music providers land. Model IDs come from Ellora's list_models.
external_providers: [ellora]
routing:
  image: {provider: ellora, model: nano-banana-pro}
  video: {provider: ellora, model: kling-3.0/video}
retry:
  max_attempts: 3
```

- [ ] **Step 4: Create `skills/ad-runner/example-manifest.json`**

```json
{
  "manifest_version": 1,
  "project": "complete-kit-dustpan",
  "nodes": [
    {
      "id": "v1.s01.keyframe",
      "type": "image",
      "prompt": "Photoreal vertical 9:16 frame. A woman in her late thirties stands at a kitchen counter in warm late-afternoon light, one hand resting on her stomach, a half-eaten salad beside her, expression tired and fed up. Natural, lived-in home kitchen, shallow depth of field. No text, no bottles.",
      "inputs": {"aspect": "9:16"},
      "depends_on": []
    },
    {
      "id": "v1.s01.clip",
      "type": "video",
      "prompt": "Slow push-in on the woman as she exhales and lets her hand drop from her stomach. Subtle, natural movement, steady camera, warm afternoon light holds.",
      "inputs": {"first_frame": "@v1.s01.keyframe", "duration": 4, "aspect": "9:16"},
      "depends_on": ["v1.s01.keyframe"]
    },
    {
      "id": "v1.s02.keyframe",
      "type": "image",
      "prompt": "Photoreal vertical 9:16 packshot of Ellora Gut Cleanse (Step 1): a squat 30 mL amber-brown glass dropper bottle with round shoulders, a matte black ribbed child-resistant screw collar and a smooth black rubber dropper bulb, the liquid inside showing as a darker column, standing upright dead centre. Deep sea-green / teal label wrapping the lower two-thirds: \"Ellora\" in white in a clean geometric sans top left, \"Gut Cleanse\" set large and bold across two lines in white, a thin white rule, then \"DIGESTIVE HEALTH & GUT BALANCE\" in small white capitals; on the right a white single-stroke line drawing of a looped, continuous intestine running the full height; a small white outlined circle reading \"30 SERVINGS\"; \"Dietary Supplement / 30 mL\" at the bottom left and \"(1 fl oz)\" at the bottom right; a thin vertical white rule just inside the left edge. Seamless warm greige backdrop, one soft key light from the upper left, soft shadow falling to the right, no props, no hands.",
      "inputs": {"aspect": "9:16"},
      "depends_on": []
    },
    {
      "id": "v1.s02.clip",
      "type": "video",
      "prompt": "Slow 15-degree orbit around the bottle. The label stays sharp and readable, light glints softly on the amber glass, backdrop and shadow stay steady.",
      "inputs": {"first_frame": "@v1.s02.keyframe", "duration": 5, "aspect": "9:16"},
      "depends_on": ["v1.s02.keyframe"]
    },
    {
      "id": "v1.s03.keyframe",
      "type": "image",
      "prompt": "Photoreal vertical 9:16 frame, looking down. A wooden broom has swept a small pile of dust and crumbs into the middle of a clean, pale kitchen floor. There is no dustpan anywhere in the frame. Soft daylight, minimal composition, slightly wry mood. No people, no text, no bottles.",
      "inputs": {"aspect": "9:16"},
      "depends_on": []
    },
    {
      "id": "v1.s03.clip",
      "type": "video",
      "prompt": "The broom gives one last short sweep and stops. The dust pile just sits there; a faint drift of dust settles back around it. Camera holds still.",
      "inputs": {"first_frame": "@v1.s03.keyframe", "duration": 5, "aspect": "9:16"},
      "depends_on": ["v1.s03.keyframe"]
    },
    {
      "id": "v1.s04.keyframe",
      "type": "image",
      "prompt": "Photoreal vertical 9:16 packshot of two identical squat 30 mL amber-brown glass dropper bottles with round shoulders, matte black ribbed child-resistant screw collars and smooth black rubber dropper bulbs, standing upright side by side, centred. Left: Ellora Gut Cleanse (Step 1), deep sea-green / teal label with \"Ellora\" in white top left, \"Gut Cleanse\" large and bold across two lines in white, a thin white rule, \"DIGESTIVE HEALTH & GUT BALANCE\" in small white capitals, a white single-stroke intestine line drawing on the right, a \"30 SERVINGS\" circle, \"Dietary Supplement / 30 mL\" bottom left and \"(1 fl oz)\" bottom right. Right: Ellora Zeolite Drops (Step 2), identical layout on a dusty slate-blue label with \"Ellora\" top left, \"Zeolite Drops\" large and bold across two lines in white, a thin white rule, \"NATURAL HEAVY METAL DETOX SUPPORT\" in small white capitals, a white outline drawing of an elongated six-sided crystal on the right, the same \"30 SERVINGS\" circle, \"Dietary supplement / 30 mL\" and \"(1 fl oz)\" at the bottom. Seamless warm greige backdrop, one soft key light from the upper left, soft shadows falling to the right, no props, no hands.",
      "inputs": {"aspect": "9:16"},
      "depends_on": []
    },
    {
      "id": "v1.s04.clip",
      "type": "video",
      "prompt": "Very slow push-in on the two bottles. Both labels stay sharp and readable; light shifts gently across the amber glass. No other movement.",
      "inputs": {"first_frame": "@v1.s04.keyframe", "duration": 5, "aspect": "9:16"},
      "depends_on": ["v1.s04.keyframe"]
    },
    {
      "id": "v1.s05.keyframe",
      "type": "image",
      "prompt": "Photoreal vertical 9:16 frame. The same woman, now relaxed and smiling slightly, at a bright kitchen counter, holding Ellora Gut Cleanse (Step 1) over a tall glass of water: a squat 30 mL amber-brown glass dropper bottle with a matte black ribbed collar and black rubber dropper bulb, deep sea-green / teal label with \"Ellora\" and \"Gut Cleanse\" in white, \"DIGESTIVE HEALTH & GUT BALANCE\" in small white capitals, a white intestine line drawing, and \"Dietary Supplement / 30 mL\" legible at the bottom. Morning light, clean and calm.",
      "inputs": {"aspect": "9:16"},
      "depends_on": []
    },
    {
      "id": "v1.s05.clip",
      "type": "video",
      "prompt": "She squeezes the dropper bulb and one dropperful falls into the glass of water, the liquid swirling darker for a moment before it settles. Calm, satisfied expression. Slow push-in.",
      "inputs": {"first_frame": "@v1.s05.keyframe", "duration": 4, "aspect": "9:16"},
      "depends_on": ["v1.s05.keyframe"]
    },
    {
      "id": "v1.vo.l01",
      "type": "tts",
      "inputs": {"text": "Bloated by three p.m. every day, no matter what you eat?", "voice": "narrator"},
      "depends_on": []
    },
    {
      "id": "v1.vo.l02",
      "type": "tts",
      "inputs": {"text": "Most cleanses sell you step one and stop there.", "voice": "narrator"},
      "depends_on": []
    },
    {
      "id": "v1.vo.l03",
      "type": "tts",
      "inputs": {"text": "That's a broom with no dustpan. What gets swept up just sits there.", "voice": "narrator"},
      "depends_on": []
    },
    {
      "id": "v1.vo.l04",
      "type": "tts",
      "inputs": {"text": "Ellora is both steps: Gut Cleanse first, then Zeolite to bind and flush.", "voice": "narrator"},
      "depends_on": []
    },
    {
      "id": "v1.vo.l05",
      "type": "tts",
      "inputs": {"text": "The Complete Kit is $49.99, with a 30-day money-back guarantee.", "voice": "narrator"},
      "depends_on": []
    },
    {
      "id": "v1.music.bed",
      "type": "music",
      "prompt": "Warm, understated acoustic groove, light and confident, no vocals.",
      "inputs": {"duration": 25},
      "depends_on": []
    },
    {
      "id": "v1.timeline",
      "type": "timeline",
      "inputs": {
        "aspect": "9:16",
        "shots": [
          {"clip": "@v1.s01.clip", "duration": 4, "fallback": "@v1.s01.keyframe"},
          {"clip": "@v1.s02.clip", "duration": 5, "fallback": "@v1.s02.keyframe"},
          {"clip": "@v1.s03.clip", "duration": 5, "fallback": "@v1.s03.keyframe"},
          {"clip": "@v1.s04.clip", "duration": 5, "fallback": "@v1.s04.keyframe"},
          {"clip": "@v1.s05.clip", "duration": 4, "fallback": "@v1.s05.keyframe"}
        ],
        "vo": [
          {"audio": "@v1.vo.l01", "text": "Bloated by three p.m. every day, no matter what you eat?"},
          {"audio": "@v1.vo.l02", "text": "Most cleanses sell you step one and stop there."},
          {"audio": "@v1.vo.l03", "text": "That's a broom with no dustpan. What gets swept up just sits there."},
          {"audio": "@v1.vo.l04", "text": "Ellora is both steps: Gut Cleanse first, then Zeolite to bind and flush."},
          {"audio": "@v1.vo.l05", "text": "The Complete Kit is $49.99, with a 30-day money-back guarantee."}
        ],
        "music": {"audio": "@v1.music.bed"},
        "end_card": {"text": "Complete Kit $49.99 · myellora.com", "duration": 2},
        "captions": true
      },
      "depends_on": [
        "v1.s01.clip", "v1.s02.clip", "v1.s03.clip", "v1.s04.clip", "v1.s05.clip",
        "v1.s01.keyframe", "v1.s02.keyframe", "v1.s03.keyframe", "v1.s04.keyframe", "v1.s05.keyframe",
        "v1.vo.l01", "v1.vo.l02", "v1.vo.l03", "v1.vo.l04", "v1.vo.l05", "v1.music.bed"
      ]
    },
    {
      "id": "v1.preview",
      "type": "preview",
      "inputs": {"timeline": "@v1.timeline"},
      "depends_on": ["v1.timeline"]
    },
    {
      "id": "v1.capcut_draft",
      "type": "capcut_draft",
      "inputs": {"timeline": "@v1.timeline"},
      "depends_on": ["v1.timeline"]
    }
  ]
}
```

(Shot durations 4+5+5+5+4 = 23 s; music 23 + 2 s end card = 25 s.)

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (203 + 7). If `test_example_timeline_inputs_build` raises a `TimelineError`, fix the example manifest's timeline inputs to the shape `engine/assembly/timeline.py` requires — never the engine.

- [ ] **Step 6: Commit**

```bash
git add skills/ad-runner/example-manifest.json skills/ad-runner/example-config.yaml tests/test_ad_example.py
git commit -m "feat(ad): example Ellora manifest and config, validated against the engine loop"
```

---

### Task 2: Plugin skeleton and stages 1–3 (strategy, script, shots)

**Files:**
- Create: `.claude-plugin/plugin.json`
- Create: `skills/ad-strategist/SKILL.md`
- Create: `skills/script-writer/SKILL.md`
- Create: `skills/shot-planner/SKILL.md`
- Create: `agents/variant-writer.md`
- Test: `tests/test_plugin_structure.py`

**Interfaces:**
- Consumes: nothing from Task 1 at runtime.
- Produces: skill names `ad-strategist`, `script-writer`, `shot-planner`; agent `variant-writer`; file contracts `projects/<slug>/brand/ellora.md`, `brief.md`, `plan.md`, `vN/script.md`, `vN/shots.md` (formats defined in the skills below). Task 3's `prompt-craft` reads `vN/shots.md`; `ad-runner` reads all of them.

- [ ] **Step 1: Write the failing test** — create `tests/test_plugin_structure.py`:

```python
"""The /ad plugin's files exist and are wired together."""
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ["ad-strategist", "script-writer", "shot-planner"]


def frontmatter(path: Path) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", path.read_text(), re.S)
    assert m, f"{path} has no YAML frontmatter"
    return yaml.safe_load(m.group(1))


def test_plugin_manifest():
    data = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert data["name"] == "adforge"
    assert data["version"] and data["description"]


@pytest.mark.parametrize("skill", SKILLS)
def test_skill_has_name_and_description(skill):
    fm = frontmatter(ROOT / "skills" / skill / "SKILL.md")
    assert fm["name"] == skill
    assert len(fm["description"]) > 40


def test_variant_writer_agent():
    fm = frontmatter(ROOT / "agents" / "variant-writer.md")
    assert fm["name"] == "variant-writer"
    assert fm["description"]
    body = (ROOT / "agents" / "variant-writer.md").read_text()
    for skill in ("script-writer", "shot-planner", "prompt-craft"):
        assert skill in body


def test_stage_files_are_named_consistently():
    strategist = (ROOT / "skills" / "ad-strategist" / "SKILL.md").read_text()
    writer = (ROOT / "skills" / "script-writer" / "SKILL.md").read_text()
    shots = (ROOT / "skills" / "shot-planner" / "SKILL.md").read_text()
    assert "brand/ellora.md" in strategist and "plan.md" in strategist
    assert "plan.md" in writer and "script.md" in writer
    assert "script.md" in shots and "shots.md" in shots
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_plugin_structure.py -q`
Expected: FAIL — `FileNotFoundError` for `.claude-plugin/plugin.json` and the skill files.

- [ ] **Step 3: Create `.claude-plugin/plugin.json`**

```json
{
  "name": "adforge",
  "version": "0.1.0",
  "description": "AdForge: turn an ad brief into rendered short-form ad variants with one approval gate. /ad for Ellora renders every image and video in Ellora Studio through the adengine render loop."
}
```

- [ ] **Step 4: Create `skills/ad-strategist/SKILL.md`**

````markdown
---
name: ad-strategist
description: Stage 1 of /ad. Turns an ad brief into projects/<slug>/plan.md (product, audience, offer, defaults, one angle per variant), after saving the Ellora brand context and house rules to brand/ellora.md. Use at the start of every /ad run.
---

# Ad strategist (stage 1)

You turn the user's brief into a plan the later stages follow. You make the strategic calls; you never render anything.

## 1. Brand file (Ellora)

Call the Ellora Studio connector's `get_brand_context` and `get_house_rules` once. Write both, verbatim, to `projects/<slug>/brand/ellora.md`:

```markdown
# Ellora brand file — fetched <YYYY-MM-DD>

## Brand context
<get_brand_context output, verbatim>

## House rules
<get_house_rules output, verbatim>
```

Every later stage reads this file instead of calling Ellora again. If the project already has `brand/ellora.md`, keep it (the ad was written against it) unless the user asks to refresh the brand file.

If the Ellora connector is not available in this session, stop and tell the user: /ad for Ellora needs the Ellora Studio connector.

## 2. Slug and brief

- Slug: `<product>-<angle>` in lowercase with hyphens, e.g. `complete-kit-dustpan`. If `projects/<slug>/` already holds a different ad, add `-2`, `-3`.
- Write the user's brief, word for word, to `projects/<slug>/brief.md`.

## 3. Defaults

Use the brief's value when it gives one; otherwise the default, marked *(default)* in the plan.

| Field | Default |
|---|---|
| Product | Complete Kit ($49.99) — the hero SKU |
| Audience | US women, roughly 28–55, tired of a symptom nobody has explained (bloating by the afternoon, fog, poor sleep) |
| Offer | 30-day money-back guarantee, even on opened bottles |
| Platform | Meta / TikTok |
| Length | 20–25 s plus a 2 s end card |
| Aspect | 9:16 |
| Variants | 1 (more only when the brief asks, e.g. "3 variants") |
| Shots per variant | 5, each 4 or 5 s |

## 4. Angles

Pick one angle per variant, each different, from the brand's strongest material:

1. **Broom with no dustpan** — most cleanses sell Step 1 alone; Ellora is the complete two-step protocol.
2. **The week-two crash** — people quit cleanses at week two; Step 2 is the part that was missing.
3. **"Tests came back normal"** — the unexplained-symptom frustration, answered with the two-step routine.
4. **Great-grandmother's remedy, done properly** — an old remedy with the binder step added.
5. **The arithmetic** — three failed attempts elsewhere cost $130–210; the kit is $49.99.

If the brief names an angle, use it for v1.

## 5. Write `projects/<slug>/plan.md`

```markdown
# Plan — <slug>

- Product: <name and price>
- Audience: <...>
- Offer: <...>
- Platform: <...>
- Length: <...>
- Aspect: <...>
- Variants: <N>
- Shots per variant: <...>

## Angles
- v1: <angle name> — <one line on how this ad argues it>
- v2: ...

## Assumptions
- <every field above marked *(default)*, one line each>
```

Mark each defaulted value with *(default)* in place as well. Then hand over to the script-writer stage (or variant-writer agents when N > 1).
````

- [ ] **Step 5: Create `skills/script-writer/SKILL.md`**

````markdown
---
name: script-writer
description: Stage 2 of /ad. Writes projects/<slug>/vN/script.md for one variant from plan.md and brand/ellora.md, including a claim check of every line against the Ellora ad-claim rules.
---

# Script writer (stage 2)

Input: `projects/<slug>/plan.md` (the variant's angle), `projects/<slug>/brand/ellora.md`.
Output: `projects/<slug>/vN/script.md`.

If the Ellora connector's `list_storyboards` returns any storyboards, read the one or two newest with `get_storyboard` and match their structure and tone. If there are none, the brand file is the only style source.

## Structure

- 5 beats, one per shot (or the plan's shot count).
- Beat 1 is the hook: it must land in the first 2 seconds and name a feeling the audience recognises (in their own words from the brand file: bloated by the afternoon, foggy, tests came back normal, crashed at week two).
- Middle beats argue the angle. The two-step argument (kill first, flush second; a broom with no dustpan) is the brand's strongest material.
- Last beat is the offer and CTA: product, price, the 30-day money-back guarantee.
- End card: short, e.g. "Complete Kit $49.99 · myellora.com".

## Lines

- One VO line per beat, **14 words or fewer**, spoken naturally.
- One on-screen caption per beat (may repeat the VO's key words; ≤ 6 words).
- Tone: plain, unembarrassed, a bit conspiratorial about what the industry leaves out. Not clinical. Not wellness-influencer.
- Music mood: one line (e.g. "warm, understated acoustic groove, no vocals").

## Claim check (Ellora)

Check every VO line, caption and the end card against the brand file's "do not write" list:

- cures, treats or prevents any disease;
- naming herpes, candida as an infection, or any named condition;
- before-and-after body claims;
- "clinically proven";
- a doctor or pharmacist recommending it;
- a testimonial stating a diagnosis was resolved.

Safe ground: digestive comfort, bloating, regularity, energy, gut health support, detox support, feeling like yourself again. Frame results as what a customer noticed, not what the product does. A testimonial-style line needs an on-screen results disclaimer ("Individual results vary").

## Write `projects/<slug>/vN/script.md`

```markdown
# Script — vN (<angle>)

| Beat | VO (≤ 14 words) | Caption |
|---|---|---|
| 1 hook | ... | ... |
| 2 | ... | ... |
| 3 | ... | ... |
| 4 | ... | ... |
| 5 CTA | ... | ... |

- End card: ...
- Music mood: ...

## Claim check
Clean.
```

If the check finds anything, replace "Clean." with one row per hit and keep the original line in the table until the user decides at the gate:

```markdown
| Line | Rule it breaks | Compliant rewrite |
|---|---|---|
| "..." | names a condition | "..." |
```
````

- [ ] **Step 6: Create `skills/shot-planner/SKILL.md`**

````markdown
---
name: shot-planner
description: Stage 3 of /ad. Turns projects/<slug>/vN/script.md into vN/shots.md — one shot per beat, 4 or 5 seconds each, with framing, motion and which Ellora bottle (if any) is on screen.
---

# Shot planner (stage 3)

Input: `projects/<slug>/vN/script.md`, `projects/<slug>/plan.md`.
Output: `projects/<slug>/vN/shots.md`.

## Rules

- One shot per beat: `s01`, `s02`, … in beat order.
- Each shot is 4 or 5 seconds; the total is within the plan's length (default 20–25 s, plus the 2 s end card).
- Each shot is one continuous, simple action that a single image-to-video clip can show. No cuts inside a shot.
- Bottle shots: say which product is on screen — "Gut Cleanse (Step 1)", "Zeolite Drops (Step 2)", or both. A bottle must be upright and its label readable.
- Packshots use the house look from the brand file: seamless warm greige backdrop, one soft key from the upper left, soft shadow to the right, no props, no hands, bottle dead centre.
- People: ordinary, believable, the audience's age; never a doctor, pharmacist or anyone in a white coat; no before/after bodies.
- No on-screen text inside the shots; captions and the end card are added in assembly.

## Write `projects/<slug>/vN/shots.md`

```markdown
# Shots — vN

| Shot | Seconds | On screen | Framing | Camera / motion | Bottle | VO |
|---|---|---|---|---|---|---|
| s01 | 4 | ... | medium, eye level | slow push-in | none | <beat 1 VO> |
| s02 | 5 | ... | packshot, centred | slow orbit | Gut Cleanse (Step 1) | <beat 2 VO> |
| ... |

Total: <sum> s + 2 s end card.
```
````

- [ ] **Step 7: Create `agents/variant-writer.md`**

````markdown
---
name: variant-writer
description: Writes one ad variant for /ad when the plan has more than one — runs the script-writer, shot-planner and prompt-craft stages for its variant only and returns the three file paths. Dispatched one per variant, in parallel.
---

You write ONE variant of an ad. The orchestrator tells you the project folder (`projects/<slug>/`) and your variant id (`v2`, `v3`, …).

1. Read `projects/<slug>/plan.md` (your variant's angle) and `projects/<slug>/brand/ellora.md`.
2. Follow the **script-writer** skill for your variant → `projects/<slug>/<vN>/script.md`.
3. Follow the **shot-planner** skill → `projects/<slug>/<vN>/shots.md`.
4. Follow the **prompt-craft** skill → `projects/<slug>/<vN>/prompts.md`.

Touch only your own `<vN>/` folder. Do not render anything, do not write `manifest.json`, and do not call Ellora's `generate_image` or `generate_video`.

Reply with only: your variant id, its angle, the three file paths, and "claim check: clean" or the number of hits.
````

- [ ] **Step 8: Run tests**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add .claude-plugin/plugin.json skills/ad-strategist skills/script-writer skills/shot-planner agents/variant-writer.md tests/test_plugin_structure.py
git commit -m "feat(ad): plugin skeleton with strategy, script and shot stages for Ellora"
```

---

### Task 3: Stages 4–5 (prompts, gate and run) and the `/ad` command

**Files:**
- Create: `skills/prompt-craft/SKILL.md`
- Create: `skills/ad-runner/SKILL.md`
- Create: `commands/ad.md`
- Modify: `tests/test_plugin_structure.py`

**Interfaces:**
- Consumes: Task 1's `skills/ad-runner/example-manifest.json` and `example-config.yaml`; Task 2's stage files (`plan.md`, `vN/script.md`, `vN/shots.md`, `brand/ellora.md`) and skill names; the engine CLI `adengine validate|run|external|supply|revise|status`.
- Produces: skill names `prompt-craft`, `ad-runner`; command `/ad`; file contracts `vN/prompts.md`, `manifest.json`, `config.yaml`, `report.md`.

- [ ] **Step 1: Extend the failing test** — in `tests/test_plugin_structure.py` change `SKILLS` and append tests:

```python
SKILLS = ["ad-strategist", "script-writer", "shot-planner", "prompt-craft", "ad-runner"]
```

```python
def test_ad_command_runs_every_stage_in_order():
    path = ROOT / "commands" / "ad.md"
    fm = frontmatter(path)
    assert fm["description"] and fm["argument-hint"]
    body = path.read_text()
    positions = [body.index(skill) for skill in SKILLS]
    assert positions == sorted(positions), "stages must appear in order"
    assert "variant-writer" in body and "$ARGUMENTS" in body


def test_ad_runner_points_at_its_examples_and_the_engine_loop():
    body = (ROOT / "skills" / "ad-runner" / "SKILL.md").read_text()
    for needle in ("example-manifest.json", "example-config.yaml", "adengine validate", "adengine run",
                   "adengine external", "adengine supply", "--fingerprint", "generateAudio: false",
                   "check_generation", "adengine revise", "report.md"):
        assert needle in body, needle


def test_prompt_craft_names_the_default_models():
    body = (ROOT / "skills" / "prompt-craft" / "SKILL.md").read_text()
    for needle in ("nano-banana-pro", "kling-3.0/video", "list_models", "search_prompts", "prompts.md",
                   "Dietary Supplement"):
        assert needle in body, needle
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_plugin_structure.py -q`
Expected: FAIL — missing `skills/prompt-craft/SKILL.md`, `skills/ad-runner/SKILL.md`, `commands/ad.md`.

- [ ] **Step 3: Create `skills/prompt-craft/SKILL.md`**

````markdown
---
name: prompt-craft
description: Stage 4 of /ad. Writes projects/<slug>/vN/prompts.md — an Ellora image prompt for each shot's keyframe and a motion prompt for its clip — using the brand file's exact label wording so Ellora attaches the right bottle reference.
---

# Prompt craft (stage 4)

Input: `projects/<slug>/vN/shots.md`, `projects/<slug>/brand/ellora.md`.
Output: `projects/<slug>/vN/prompts.md`.

## Models

Call the Ellora connector's `list_models` once per brief and confirm the defaults are still offered:
- image: `nano-banana-pro` (legible label text, takes reference images);
- video: `kling-3.0/video` (takes a first frame, 9:16, 3–15 s).

If the user named other models, use those. Check every shot's duration and the 9:16 aspect are within the chosen video model's options; if not, pick the nearest allowed duration and update `shots.md`.

Use `search_prompts` with a few key words of each shot (e.g. "packshot greige", "dropper water") and reuse phrasing the team already uses. Apply every rule in the brand file's House rules section.

## Keyframe (image) prompts

- Start with "Photoreal vertical 9:16" and describe one frame: subject, setting, light, mood.
- **Bottle shots:** name the product exactly — "Ellora Gut Cleanse (Step 1)" or "Ellora Zeolite Drops (Step 2)" — then describe the bottle and label with the brand file's wording: the squat 30 mL amber-brown glass dropper bottle, round shoulders, matte black ribbed child-resistant collar, smooth black rubber dropper bulb; the label colour, the white "Ellora" and product name, the small-capitals line, the line drawing, the "30 SERVINGS" circle. Naming the product attaches Ellora's reference picture automatically; the wording makes sure the label is drawn right. Both bottles are the same physical object — only the label differs.
- Every bottle shown keeps "Dietary Supplement" legible.
- Packshots: the house look (seamless warm greige backdrop, soft key from the upper left, soft shadow to the right, no props, no hands, dead centre).
- Never: text overlays, doctors or pharmacists, white coats, before/after bodies, named conditions.
- One image per keyframe.

## Clip (motion) prompts

- Describe only the movement over the shot's seconds: what moves, how the camera moves, what stays still. The keyframe is the first frame, so do not re-describe the scene.
- Keep labels sharp and readable in bottle shots ("the label stays sharp and readable").
- Clips are rendered without native audio; never describe sound.

## Write `projects/<slug>/vN/prompts.md`

```markdown
# Prompts — vN

- Image model: nano-banana-pro
- Video model: kling-3.0/video
- Aspect: 9:16

## s01 (4 s)
**Keyframe:** <image prompt>
**Motion:** <motion prompt>

## s02 (5 s)
...
```

See `skills/ad-runner/example-manifest.json` for five complete, approved-style examples.
````

- [ ] **Step 4: Create `skills/ad-runner/SKILL.md`**

````markdown
---
name: ad-runner
description: Stage 5 of /ad. Shows the single approval gate, writes manifest.json and config.yaml, then runs the adengine render loop with Claude rendering every image and video in Ellora Studio, and reports previews, drafts and anything needing attention. Also handles revisions after the report.
---

# Ad runner (stage 5)

Input: everything under `projects/<slug>/` from stages 1–4.
Output: `projects/<slug>/manifest.json`, `config.yaml`, `report.md`, and the rendered ad.

The engine CLI runs from the AdForge repo root (the plugin root): `uv run adengine <command> projects/<slug>`. Check it works (`uv run adengine --help`) before the gate; if it doesn't, stop and tell the user.

## 1. Manifest and config

- `config.yaml`: copy `skills/ad-runner/example-config.yaml`, replacing the model IDs if prompt-craft chose others.
- `manifest.json`: follow `skills/ad-runner/example-manifest.json` exactly — same node ids, types and input shapes — with this ad's prompts, VO text, durations, music mood and end card. Per variant `vN`:
  - `vN.sXX.keyframe` (image): prompt = keyframe prompt; `inputs: {"aspect": "9:16"}`; no refs; no `n`.
  - `vN.sXX.clip` (video): prompt = motion prompt; `inputs: {"first_frame": "@vN.sXX.keyframe", "duration": <s>, "aspect": "9:16"}`.
  - `vN.vo.lXX` (tts, mock): `{"text": <VO line>, "voice": "narrator"}`.
  - `vN.music.bed` (music, mock): prompt = music mood; `duration` = shots total + end card.
  - `vN.timeline`, `vN.preview`, `vN.capcut_draft` as in the example; the timeline's `vo[].text` is the VO line, `end_card.text` the end card.
  - `project` = the slug.
- Run `uv run adengine validate projects/<slug>` until it prints `OK`. Fix errors in the manifest, never in engine code.

## 2. The gate

Show, in this order, then stop and wait for the user:

1. **Assumptions** — every *(default)* from `plan.md`.
2. **Script** per variant — hook, VO lines, captions, end card.
3. **Claim check** — "clean", or each hit with the rule and the compliant rewrite. The gate cannot be approved while a hit is unresolved: the user accepts the rewrite or edits the line.
4. **Shots and prompts** — per shot: seconds, keyframe prompt, motion prompt.
5. **Render list** — per variant: 5 Ellora images (`nano-banana-pro`) and 5 Ellora videos (`kling-3.0/video`), N variants in total. Say plainly: these spend your Ellora credits (videos far more than images) and land in your Ellora library.

The user may approve, edit lines or shots, change an angle, drop or add variants, or ask for new prompts. Redo only the affected stage, update the manifest, re-validate, and show the gate again.

Approval confirms exactly the listed renders and downloading their results into the project. Anything not on that list later (a revision, an extra shot) needs a new confirmation.

## 3. Render loop

1. `uv run adengine run projects/<slug>`. Exit `0` → go to §4. Exit `1` → go to §4 and report what needs attention. Exit `3` → continue.
2. `uv run adengine external projects/<slug> --json` — the nodes waiting for Ellora, with `prompt`, `model`, `inputs`, `external_inputs` and `fingerprint`.
3. Render each node in Ellora:
   - **image:** `generate_image` with `prompt`, `modelId` = the node's `model`, `aspectRatio: "9:16"`. Independent keyframes can render in parallel.
   - **video:** `generate_video` with `prompt`, `modelId`, `firstFrameUrl` = `external_inputs.first_frame`, `durationSec` = `inputs.duration`, `aspectRatio: "9:16"`, `generateAudio: false` (VO and music come from the timeline). Then `check_generation` with `wait: true`, repeating until it is finished or failed.
4. Download each finished file from the link `check_generation` returns into `projects/<slug>/.tmp/ellora/<node id>.<ext>`, then:
   `uv run adengine supply projects/<slug> <node id> <file> --ref <Ellora path> --id <generation id> --fingerprint <fingerprint>`.
   Supplies may run in parallel; the engine locks its state.
5. Problems:
   - Ellora render failed or timed out → `adengine supply ... --failed "<Ellora's message>"`. The next run lists it again; render it once more. A second failure → stop the loop and report it.
   - Ellora refused the prompt → `adengine supply ... --refused "<message>"`, rewrite the prompt once within the claim and prompt rules, `uv run adengine revise projects/<slug> <node id> --json '{"prompt": "<new prompt>"}' --no-run`, and continue the loop (a re-render of the same shot is covered by the gate approval). A second refusal → report it.
6. Back to step 1. Expect two passes per variant (keyframes, then clips) before assembly finishes.

## 4. Report

Write `projects/<slug>/report.md` and show the same to the user:

- per variant: `vN/preview.mp4` and `vN/capcut_draft/` paths;
- the Ellora generation IDs used (from `adengine status` / the ledger);
- every node `failed` or `needs_review`, with its reason;
- what is still placeholder: audio (mock TTS and music), and assembly while the real preview/CapCut providers are not merged in.

## 5. Revisions

After the report, turn feedback into node changes:
- "shot 3 too dark" → `uv run adengine revise projects/<slug> v1.s03.keyframe --json '{"prompt": "<revised prompt>"}' --no-run`.
- Motion only → revise `v1.s03.clip` instead (the keyframe stays).
- A VO line → revise `v1.vo.lXX` `inputs.text` **and** the matching `vo[].text` in `v1.timeline`.

List the renders the change causes (e.g. "1 image + 1 video in Ellora") and get the user's OK, then run the render loop again. The engine re-renders only the changed node, what depends on it, and the assembly.
````

- [ ] **Step 5: Create `commands/ad.md`**

````markdown
---
description: Turn an Ellora ad brief into a rendered ad — script, shots, Ellora prompts, one approval gate, then every image and video rendered in Ellora Studio and assembled by adengine.
argument-hint: <brief, e.g. "Complete Kit, broom-with-no-dustpan angle, 2 variants">
---

# /ad — Ellora

Brief: $ARGUMENTS

If the brief is empty, ask the user for one (product, angle or audience, anything they care about) and stop.

Run these stages in order. Each stage is a skill in this plugin; follow it exactly and let it write its file before moving on.

1. **ad-strategist** — brand file, slug, `brief.md`, `plan.md`.
2. **script-writer** — `v1/script.md` with the claim check.
3. **shot-planner** — `v1/shots.md`.
4. **prompt-craft** — `v1/prompts.md`.
   When `plan.md` has more than one variant, do stages 2–4 for v1 yourself and dispatch one **variant-writer** agent per other variant, in parallel, then wait for all of them.
5. **ad-runner** — manifest and config, then **the gate: stop and wait for the user's approval**. Only after approval: the Ellora render loop, the report, and revisions.

Never call Ellora's `generate_image` or `generate_video` before the user approves the gate.
````

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add skills/prompt-craft skills/ad-runner/SKILL.md commands/ad.md tests/test_plugin_structure.py
git commit -m "feat(ad): prompt-craft and ad-runner stages, and the /ad command"
```

---

## After the plan: manual end-to-end trial (spends Ellora credits)

Not a task for an implementer. With the user: load the plugin (`claude --plugin-dir /home/iinko/PROJECT_AUTOMATION/adforge/.claude/worktrees/ellora`), run `/ad Complete Kit, broom-with-no-dustpan angle`, review the gate together, and only render after the user approves.
