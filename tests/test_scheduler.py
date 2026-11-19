import asyncio
import json

from engine.config import EngineConfig
from engine.core.graph import load_manifest
from engine.core.ledger import Ledger
from engine.core.scheduler import Scheduler
from engine.core.store import ProjectStore
from tests.helpers import FAST, RecordingProvider, node

V1_S01_CHAIN = {"v1.s01.keyframe", "v1.s01.clip", "v1.timeline", "v1.preview", "v1.capcut_draft"}


def run(project_dir, provider, *, config=FAST, targets=None, sleep=None):
    sched = Scheduler(
        load_manifest(project_dir / "manifest.json"),
        ProjectStore(project_dir),
        config,
        {"mock": provider},
        Ledger(project_dir / "ledger.jsonl"),
        **({"sleep": sleep} if sleep else {}),
    )
    return asyncio.run(sched.run(targets))


def edit_manifest(project_dir, fn):
    path = project_dir / "manifest.json"
    data = json.loads(path.read_text())
    fn(data)
    path.write_text(json.dumps(data))


def test_full_run_renders_every_node(project_dir):
    p = RecordingProvider()
    report = run(project_dir, p)
    assert report.ok
    assert len(report.ran) == 17 and report.skipped == []
    assert len(p.calls) == 17
    store = ProjectStore(project_dir)
    assert all(store.get(n).status == "done" for n in report.ran)
    assert (project_dir / "v1/shots/s01/clip.mp4").exists()


def test_second_run_is_fully_cached(project_dir):
    run(project_dir, RecordingProvider())
    p = RecordingProvider()
    report = run(project_dir, p)
    assert p.calls == [] and len(report.skipped) == 17 and report.ran == []


def test_revision_rerenders_exactly_node_and_dependents(project_dir):
    run(project_dir, RecordingProvider())
    edit_manifest(project_dir, lambda d: node(d, "v1.s01.keyframe").update(prompt="darker"))
    p = RecordingProvider()
    run(project_dir, p)
    assert set(p.calls) == V1_S01_CHAIN
    assert (project_dir / "v1/shots/s01/versions/v1.s01.keyframe_v1.png").exists()


def test_concurrency_cap_is_respected(project_dir):
    p = RecordingProvider(default_delay=0.02)
    cfg = EngineConfig.from_dict({"retry": {"base_delay_s": 0}, "concurrency": {"mock": 2}})
    run(project_dir, p, config=cfg)
    assert p.max_active == 2


def test_dependents_start_as_soon_as_their_inputs_finish(project_dir):
    p = RecordingProvider(delays={"v2.s02.keyframe": 0.3})
    run(project_dir, p)
    assert p.events.index(("start", "v1.s01.clip")) < p.events.index(("end", "v2.s02.keyframe"))


def test_hard_failure_blocks_only_dependents(project_dir):
    report = run(project_dir, RecordingProvider(fail={"v1.s01.keyframe"}))
    assert not report.ok
    assert report.failed == ["v1.s01.keyframe"]
    assert set(report.blocked) == V1_S01_CHAIN - {"v1.s01.keyframe"}
    store = ProjectStore(project_dir)
    st = store.get("v1.s01.keyframe")
    assert (st.status, st.reason) == ("failed", "error") and "boom" in st.message
    assert store.get("v1.timeline").reason == "upstream v1.s01.keyframe failed"
    assert all(store.get(n).status == "done" for n in ("v2.preview", "v2.capcut_draft", "v1.s02.clip"))


def test_resume_after_failure_runs_only_unfinished_nodes(project_dir):
    run(project_dir, RecordingProvider(fail={"v1.s01.keyframe"}))
    p = RecordingProvider()
    report = run(project_dir, p)
    assert report.ok
    assert set(p.calls) == V1_S01_CHAIN


def test_transient_errors_retry_with_exponential_backoff(project_dir):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    cfg = EngineConfig.from_dict({"retry": {"max_attempts": 3, "base_delay_s": 1.0}})
    p = RecordingProvider(transient={"refs.product_hero": 2})
    report = run(project_dir, p, config=cfg, sleep=fake_sleep)
    assert report.ok
    assert p.calls.count("refs.product_hero") == 3
    assert sleeps == [1.0, 2.0]
    hero = [e for e in Ledger(project_dir / "ledger.jsonl").entries() if e["node_id"] == "refs.product_hero"]
    assert [e["ok"] for e in hero] == [False, False, True]
    assert [e["attempt"] for e in hero] == [1, 2, 3]


def test_transient_errors_give_up_after_max_attempts(project_dir):
    report = run(project_dir, RecordingProvider(transient={"v2.vo.l01": 5}))
    assert report.failed == ["v2.vo.l01"]
    assert ProjectStore(project_dir).get("v2.vo.l01").reason == "transient"


def test_refusal_goes_to_needs_review(project_dir):
    report = run(project_dir, RecordingProvider(refuse={"v2.s01.clip"}))
    assert report.needs_review == ["v2.s01.clip"]
    assert set(report.blocked) == {"v2.timeline", "v2.preview", "v2.capcut_draft"}
    st = ProjectStore(project_dir).get("v2.s01.clip")
    assert (st.status, st.reason, st.message) == ("needs_review", "refused", "content policy")


def test_unknown_provider_fails_the_node(project_dir):
    edit_manifest(project_dir, lambda d: node(d, "v1.vo.l01").update(provider="nope", model="x"))
    report = run(project_dir, RecordingProvider())
    assert report.failed == ["v1.vo.l01"]
    assert ProjectStore(project_dir).get("v1.vo.l01").reason == "config"


def test_targets_run_only_matches_and_their_ancestors(project_dir):
    p = RecordingProvider()
    run(project_dir, p, targets=["refs.*"])
    assert p.calls == ["refs.product_hero"]
    p = RecordingProvider()
    run(project_dir, p, targets=["v1.s01.clip"])
    assert set(p.calls) == {"v1.s01.keyframe", "v1.s01.clip"}


def test_ledger_logs_generation_calls_only(project_dir):
    run(project_dir, RecordingProvider(cost_per_call=0.1))
    entries = Ledger(project_dir / "ledger.jsonl").entries()
    assert len(entries) == 11
    assert {"node_id", "provider", "model", "cost_usd", "seconds", "attempt", "ok", "ts"} <= set(entries[0])
    assert round(Ledger(project_dir / "ledger.jsonl").total_cost(), 2) == 1.1


class MissingFileTTS(RecordingProvider):
    async def tts(self, ctx, text, voice, emotion):
        await self._before(ctx)
        return ctx.work_dir / "never_written.wav"


def test_commit_failure_is_isolated_to_the_node(project_dir):
    report = run(project_dir, MissingFileTTS())
    assert sorted(report.failed) == ["v1.vo.l01", "v2.vo.l01"]
    assert {"v1.timeline", "v2.timeline"} <= set(report.blocked)
    store = ProjectStore(project_dir)
    states = {n: store.get(n).status for n in load_manifest(project_dir / "manifest.json").nodes}
    assert "running" not in states.values()
    assert all(states[n] == "done" for n in states if ".keyframe" in n or ".clip" in n)
    vo = [e for e in Ledger(project_dir / "ledger.jsonl").entries() if e["node_id"].endswith(".vo.l01")]
    assert len(vo) == 2 and all(e["ok"] is False for e in vo)


def test_deleted_dependency_output_rebuilds_its_dependents(project_dir):
    run(project_dir, RecordingProvider())
    (project_dir / "v1/shots/s01/keyframe.png").unlink()
    p = RecordingProvider()
    report = run(project_dir, p)
    assert report.ok
    assert set(p.calls) == V1_S01_CHAIN
    assert set(report.ran) == V1_S01_CHAIN
    assert not any(c.startswith("v2.") for c in p.calls)


def test_dependency_rebuilt_in_an_earlier_run_still_invalidates_dependents(project_dir):
    run(project_dir, RecordingProvider())
    (project_dir / "v1/shots/s01/keyframe.png").unlink()
    p = RecordingProvider()
    run(project_dir, p, targets=["v1.s01.keyframe"])  # dependents out of scope, as after a crash
    assert p.calls == ["v1.s01.keyframe"]
    p = RecordingProvider()
    run(project_dir, p)
    assert set(p.calls) == V1_S01_CHAIN - {"v1.s01.keyframe"}


def test_commit_records_dependency_versions(project_dir):
    run(project_dir, RecordingProvider())
    st = ProjectStore(project_dir).get("v1.s01.clip")
    assert st.built_from == {"v1.s01.keyframe": 1}


def test_old_state_without_built_from_still_loads_and_is_fresh(project_dir):
    run(project_dir, RecordingProvider())
    path = project_dir / "state.json"
    data = json.loads(path.read_text())
    for st in data["nodes"].values():
        st.pop("built_from", None)
    path.write_text(json.dumps(data))
    p = RecordingProvider()
    assert len(run(project_dir, p).skipped) == 17 and p.calls == []
