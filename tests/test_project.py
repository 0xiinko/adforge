import asyncio

import pytest

from engine.core.graph import ManifestError
from engine.core.project import Project
from tests.helpers import FAST, RecordingProvider


def run(project, provider=None):
    provider = provider or RecordingProvider()
    report = asyncio.run(project.run(providers={"mock": provider}))
    return report, provider


def test_dry_run_on_fresh_project_plans_everything(project_dir):
    report = Project(project_dir, FAST).dry_run(providers={"mock": RecordingProvider(cost_per_call=0.5)})
    assert len(report.to_run) == 17 and report.cached == []
    assert report.total_cost == pytest.approx(11 * 0.5)
    first = report.to_run[0]
    assert (first.node_id, first.provider, first.model) == ("refs.product_hero", "mock", "mock-image")
    assert not (project_dir / "state.json").exists()


def test_dry_run_makes_no_provider_calls(project_dir):
    p = RecordingProvider()
    Project(project_dir, FAST).dry_run(providers={"mock": p})
    assert p.calls == []


def test_dry_run_after_run_is_all_cached(project_dir):
    project = Project(project_dir, FAST)
    run(project)
    report = project.dry_run(providers={"mock": RecordingProvider()})
    assert report.to_run == [] and len(report.cached) == 17


def test_dry_run_flags_unregistered_provider(project_dir):
    project = Project(project_dir, FAST)
    project.revise("v1.vo.l01", {"provider": "fishaudio", "model": "s1"})
    planned = {p.node_id: p for p in project.dry_run(providers={"mock": RecordingProvider()}).to_run}
    assert planned["v1.vo.l01"].provider_available is False


def test_status_lists_nodes_in_topological_order(project_dir):
    project = Project(project_dir, FAST)
    run(project)
    rows = project.status()
    assert rows[0][0] == "refs.product_hero"
    assert len(rows) == 17 and all(st.status == "done" and st.version == 1 for _, st in rows)


def test_revise_prompt_rerenders_chain(project_dir):
    project = Project(project_dir, FAST)
    run(project)
    project.revise("v1.s01.keyframe", {"prompt": "darker"})
    assert project.manifest().nodes["v1.s01.keyframe"].prompt == "darker"
    assert {p.node_id for p in project.dry_run(providers={"mock": RecordingProvider()}).to_run} == {
        "v1.s01.keyframe", "v1.s01.clip", "v1.timeline", "v1.preview", "v1.capcut_draft",
    }


def test_revise_merges_inputs(project_dir):
    project = Project(project_dir, FAST)
    project.revise("v1.s01.clip", {"inputs": {"duration": 5, "aspect": None}})
    assert project.manifest().nodes["v1.s01.clip"].inputs == {"first_frame": "@v1.s01.keyframe", "duration": 5}


def test_revise_rejects_unknown_fields_and_nodes(project_dir):
    project = Project(project_dir, FAST)
    with pytest.raises(ValueError, match="cannot revise"):
        project.revise("v1.s01.clip", {"type": "image"})
    with pytest.raises(KeyError):
        project.revise("v9.s01.clip", {"prompt": "x"})


def test_invalid_revision_leaves_manifest_untouched(project_dir):
    project = Project(project_dir, FAST)
    before = (project_dir / "manifest.json").read_text()
    with pytest.raises(ManifestError):
        project.revise("v1.s01.clip", {"inputs": {"first_frame": "@v9.s01.keyframe"}})
    assert (project_dir / "manifest.json").read_text() == before


def test_rollback_pins_until_next_revise(project_dir):
    project = Project(project_dir, FAST)
    run(project)
    project.revise("v1.vo.l01", {"inputs": {"text": "Second take"}})
    run(project)
    out = project_dir / "v1/vo/l01.wav"
    assert b"Second take" in out.read_bytes()

    assert project.rollback("v1.vo.l01", 1) == 3
    assert b"Line for v1" in out.read_bytes()

    _, p = run(project)
    assert set(p.calls) == {"v1.timeline", "v1.preview", "v1.capcut_draft"}
    _, p = run(project)
    assert p.calls == []

    project.revise("v1.vo.l01", {"inputs": {"text": "Third take"}})
    _, p = run(project)
    assert set(p.calls) == {"v1.vo.l01", "v1.timeline", "v1.preview", "v1.capcut_draft"}


def test_open_uses_project_config_yaml(project_dir):
    (project_dir / "config.yaml").write_text("concurrency: {mock: 3}\n")
    assert Project.open(project_dir).config.limit("mock") == 3


def test_dry_run_matches_run_after_dependency_output_deleted(project_dir):
    project = Project(project_dir, FAST)
    run(project)
    (project_dir / "v1/shots/s01/keyframe.png").unlink()
    planned = {p.node_id for p in project.dry_run(providers={"mock": RecordingProvider()}).to_run}
    report, _ = run(project)
    assert planned == set(report.ran) == {
        "v1.s01.keyframe", "v1.s01.clip", "v1.timeline", "v1.preview", "v1.capcut_draft",
    }


def test_pinned_node_is_kept_when_its_dependency_rebuilds(project_dir):
    project = Project(project_dir, FAST)
    run(project)
    project.revise("v1.s01.clip", {"prompt": "take two"})
    run(project)
    project.rollback("v1.s01.clip", 1)
    run(project)
    (project_dir / "v1/shots/s01/keyframe.png").unlink()
    _, p = run(project)
    assert set(p.calls) == {"v1.s01.keyframe"}
