"""The /ad plugin's files exist and are wired together."""
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ["ad-strategist", "script-writer", "cast-designer", "shot-planner", "prompt-craft", "ad-runner"]


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
                   "adengine external", "adengine supply", "--fingerprint", "generateAudio: true",
                   "check_generation", "adengine revise", "report.md", '"audio": true',
                   "referenceImageUrls", '--only "cast.*"', "look at it before supplying", "cast.<id>.ref"):
        assert needle in body, needle
    assert "generateAudio: false" not in body and "tts" not in body


def test_prompt_craft_names_the_default_models():
    body = (ROOT / "skills" / "prompt-craft" / "SKILL.md").read_text()
    for needle in ("nano-banana-pro", "kling-3.0/video", "list_models", "search_prompts", "prompts.md",
                   "Dietary Supplement", "Natural ambient sound, no music."):
        assert needle in body, needle
    assert "never describe sound" not in body


def test_strategist_detects_supplied_scripts_and_story():
    body = (ROOT / "skills" / "ad-strategist" / "SKILL.md").read_text()
    for needle in ("Script source: supplied", "Script source: written", "hooks + shared body",
                   "script-source.md", "The brief's story wins", "Never invent a script",
                   ".pdf", "the Read tool reads PDFs", "- Script source: <supplied | written>", "## Body",
                   "*(from the script)*", "ask the user before choosing"):
        assert needle in body, needle


def test_cast_designer_defines_fixed_phrases():
    body = (ROOT / "skills" / "cast-designer" / "SKILL.md").read_text()
    for needle in ("cast.md", "Look phrase", "Voice phrase", "Reference prompt", "cast.<id>.ref",
                   "word for word", "No cast", "Defaults chosen", "voice only", "may be shown on screen", "Role", "Roles are unique",
                   "Variant-writers may only use people already in cast.md",
                   "no extra fingers, no text, no watermark."):
        assert needle in body, needle
    assert "Maya's voice:" not in body


def test_ad_command_updates_cast_when_a_person_changes():
    body = (ROOT / "commands" / "ad.md").read_text()
    assert "update `cast.md`" in body


def test_writer_and_planner_handle_supplied_scripts_and_shared_body():
    writer = (ROOT / "skills" / "script-writer" / "SKILL.md").read_text()
    planner = (ROOT / "skills" / "shot-planner" / "SKILL.md").read_text()
    for needle in ("Script source: supplied", "script-source.md", "word for word", "never paraphrase",
                   "body/script.md", "compliant rewrite", "presenter (on camera)", "Target ≤ 10 words",
                   "split mid-clause", "does not apply", "copy each speaker's role exactly"):
        assert needle in writer, needle
    for needle in ("body/shots.md", "body.s01", "Cast", "cast.md", "Role lines in cast.md",
                   "re-split it at a natural pause"):
        assert needle in planner, needle
    assert "or ask script-writer to shorten it." not in planner


ANTI_SLOP_IMAGE = "Natural skin texture, anatomically correct hands, no extra fingers, no text, no watermark."
ANTI_SLOP_VIDEO = "Stable face and hands, no morphing or warping."


def test_prompt_craft_keeps_cast_consistent_and_fights_slop():
    body = (ROOT / "skills" / "prompt-craft" / "SKILL.md").read_text()
    for needle in (ANTI_SLOP_IMAGE, ANTI_SLOP_VIDEO, "look phrase", "voice phrase", "cast.md",
                   "Reference: cast.", "body/prompts.md", "word for word",
                   "Off camera, in <voice phrase>, she says:", "in <voice phrase>:", "## body.sNN",
                   "**Reference:** none"):
        assert needle in body, needle
    assert "a warm woman's voice" not in body
