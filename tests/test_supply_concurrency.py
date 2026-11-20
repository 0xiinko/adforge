"""Parallel `adengine supply` processes must not clobber each other's state (spec §4 loop)."""
import asyncio
import subprocess
import sys
from pathlib import Path

from engine.core.project import Project
from engine.core.store import ProjectStore
from engine.providers.mock import PNG_1X1
from tests.helpers import ELLORA, RecordingProvider

HERO = "refs.product_hero"
KEYFRAMES = ["v1.s01.keyframe", "v1.s02.keyframe", "v2.s01.keyframe", "v2.s02.keyframe"]
ROOT = Path(__file__).resolve().parent.parent


def run(d):
    return asyncio.run(Project(d, ELLORA).run(providers={"mock": RecordingProvider()}))


def png(d, name):
    f = d / name
    f.write_bytes(PNG_1X1)
    return f


def spawn_supply(d, nid, f, ref):
    return subprocess.Popen(
        [sys.executable, "-m", "engine.cli", "supply", str(d), nid, str(f), "--ref", ref],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def test_parallel_supplies_of_different_nodes_all_land(ellora_dir):
    run(ellora_dir)
    Project(ellora_dir, ELLORA).supply(HERO, png(ellora_dir, "hero.png"), ref="ellora://hero")
    assert sorted(run(ellora_dir).awaiting) == sorted(KEYFRAMES)
    procs = [spawn_supply(ellora_dir, k, png(ellora_dir, f"{k}.png"), f"ellora://{k}") for k in KEYFRAMES]
    results = [(p.wait(timeout=60), *p.communicate()) for p in procs]
    assert all(code == 0 for code, _, _ in results), results
    store = ProjectStore(ellora_dir)
    for k in KEYFRAMES:
        st = store.get(k)
        assert (st.status, st.version) == ("done", 1), (k, st)
        assert st.external == {"provider": "ellora", "ref": f"ellora://{k}", "id": None}
    clips = [k.replace(".keyframe", ".clip") for k in KEYFRAMES]
    assert sorted(run(ellora_dir).awaiting) == sorted(clips)


def test_two_supplies_of_the_same_node_one_wins(ellora_dir):
    run(ellora_dir)
    procs = [spawn_supply(ellora_dir, HERO, png(ellora_dir, f"hero{i}.png"), f"ellora://hero{i}") for i in range(2)]
    results = [(p.wait(timeout=60), *p.communicate()) for p in procs]
    codes = sorted(code for code, _, _ in results)
    assert codes == [0, 1], results
    [(_, _, err)] = [r for r in results if r[0] == 1]
    assert err.strip() == f"ERROR: {HERO} is done, not awaiting_external; run adengine run first"
    st = ProjectStore(ellora_dir).get(HERO)
    assert (st.status, st.version) == ("done", 1)
    [(_, out, _)] = [r for r in results if r[0] == 0]
    assert out.strip() == f"supplied {HERO} as v1"
    winner = next(i for i, r in enumerate(results) if r[0] == 0)
    assert st.external["ref"] == f"ellora://hero{winner}"


def test_update_from_a_stale_store_keeps_another_process_commit(ellora_dir):
    run(ellora_dir)
    stale = ProjectStore(ellora_dir)  # loaded before the supply below
    Project(ellora_dir, ELLORA).supply(HERO, png(ellora_dir, "hero.png"), ref="ellora://hero")
    stale.update(HERO, status="pending")
    st = ProjectStore(ellora_dir).get(HERO)
    assert (st.status, st.version) == ("pending", 1)
    assert st.fingerprint is not None and st.external["ref"] == "ellora://hero"
    assert st.external_history == {"1": st.external}
