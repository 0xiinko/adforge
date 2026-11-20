"""The /ad plugin's files exist and are wired together."""
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ["ad-strategist", "script-writer", "shot-planner", "prompt-craft", "ad-runner"]


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
                   "adengine external", "adengine supply", "--fingerprint", "generateAudio: false",
                   "check_generation", "adengine revise", "report.md"):
        assert needle in body, needle


def test_prompt_craft_names_the_default_models():
    body = (ROOT / "skills" / "prompt-craft" / "SKILL.md").read_text()
    for needle in ("nano-banana-pro", "kling-3.0/video", "list_models", "search_prompts", "prompts.md",
                   "Dietary Supplement"):
        assert needle in body, needle
