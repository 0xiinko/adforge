import asyncio
import json

from engine.core.cache import compute_fingerprints
from engine.core.graph import load_manifest
from engine.core.ledger import Ledger
from engine.core.scheduler import Scheduler
from engine.core.store import ProjectStore
from engine.providers.mock import PNG_1X1
from tests.helpers import ELLORA, RecordingProvider, node

KEYFRAMES = {"v1.s01.keyframe", "v1.s02.keyframe", "v2.s01.keyframe", "v2.s02.keyframe"}


def run(project_dir, provider):
    sched = Scheduler(
        load_manifest(project_dir / "manifest.json"), ProjectStore(project_dir), ELLORA,
        {"mock": provider}, Ledger(project_dir / "ledger.jsonl"),
    )
    return asyncio.run(sched.run())


def edit_manifest(project_dir, fn):
    path = project_dir / "manifest.json"
    data = json.loads(path.read_text())
    fn(data)
    path.write_text(json.dumps(data))


def supply_directly(project_dir, node_id):
    """What `adengine supply` does at its core: commit a file against the expected fingerprint."""
    store = ProjectStore(project_dir)
    n = load_manifest(project_dir / "manifest.json").nodes[node_id]
    f = project_dir / f"{node_id}.supplied"
    f.write_bytes(PNG_1X1)
    store.commit(n, f, store.get(node_id).expected_fingerprint)


def test_external_node_waits_and_everything_else_runs(ellora_dir):
    p = RecordingProvider()
    report = run(ellora_dir, p)
    assert report.awaiting == ["refs.product_hero"]
    assert not report.ok
    assert sorted(p.calls) == ["v1.vo.l01", "v2.vo.l01"]
    assert report.blocked == [] and report.failed == []
    store = ProjectStore(ellora_dir)
    hero = store.get("refs.product_hero")
    fps = compute_fingerprints(load_manifest(ellora_dir / "manifest.json"), ELLORA, ellora_dir, {})
    assert hero.status == "awaiting_external" and hero.reason == "external"
    assert hero.expected_fingerprint == fps["refs.product_hero"]
    assert store.get("v1.s01.keyframe").status == "pending"
    assert store.get("v1.timeline").status == "pending"  # assembly waits: no placeholder
    assert not (ellora_dir / "v1" / "timeline.json").exists()


def test_rerun_without_supply_is_still_awaiting(ellora_dir):
    run(ellora_dir, RecordingProvider())
    p = RecordingProvider()
    report = run(ellora_dir, p)
    assert report.awaiting == ["refs.product_hero"] and p.calls == []


def test_supplied_node_is_cached_and_its_dependents_wait_next(ellora_dir):
    run(ellora_dir, RecordingProvider())
    supply_directly(ellora_dir, "refs.product_hero")
    report = run(ellora_dir, RecordingProvider())
    assert "refs.product_hero" in report.skipped
    assert set(report.awaiting) == KEYFRAMES
    store = ProjectStore(ellora_dir)
    assert store.get("refs.product_hero").expected_fingerprint is None  # commit clears it


def test_reported_external_failure_holds_until_revised(ellora_dir):
    run(ellora_dir, RecordingProvider())
    ProjectStore(ellora_dir).update("refs.product_hero", status="needs_review", reason="refused", message="policy")
    report = run(ellora_dir, RecordingProvider())
    assert report.needs_review == ["refs.product_hero"] and report.awaiting == []
    assert KEYFRAMES <= set(report.blocked)
    assert "v1.timeline" in report.ran  # assembly runs with placeholders, as for any failure
    edit_manifest(ellora_dir, lambda d: node(d, "refs.product_hero").update(prompt="a new hero"))
    report = run(ellora_dir, RecordingProvider())
    assert report.awaiting == ["refs.product_hero"] and report.needs_review == []


def test_reported_external_hard_failure_is_failed(ellora_dir):
    """Failed retries: the next run lists the node as awaiting again, like engine renders retry."""
    run(ellora_dir, RecordingProvider())
    ProjectStore(ellora_dir).update("refs.product_hero", status="failed", reason="external", message="timeout")
    assert ProjectStore(ellora_dir).get("refs.product_hero").status == "failed"
    report = run(ellora_dir, RecordingProvider())
    assert report.failed == [] and report.awaiting == ["refs.product_hero"]


def test_old_state_file_loads(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"nodes": {"refs.hero": {
        "status": "done", "version": 1, "fingerprint": "x", "reason": None, "message": None,
        "pinned_version": None, "built_from": None,
    }}}))
    st = ProjectStore(tmp_path).get("refs.hero")
    assert st.expected_fingerprint is None and st.external is None and st.external_history is None
