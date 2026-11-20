import asyncio
import json

import pytest

from engine.core.ledger import Ledger
from engine.core.project import Project
from engine.core.store import ProjectStore
from engine.providers.mock import PNG_1X1
from tests.helpers import ELLORA, RecordingProvider, node

HERO = "refs.product_hero"


def run(d):
    return asyncio.run(Project(d, ELLORA).run(providers={"mock": RecordingProvider()}))


def png(d, name="hero.png"):
    f = d / name
    f.write_bytes(PNG_1X1)
    return f


def revise_hero(d, prompt):
    data = json.loads((d / "manifest.json").read_text())
    node(data, HERO).update(prompt=prompt)
    (d / "manifest.json").write_text(json.dumps(data))


def test_supply_commits_and_the_pipeline_continues(ellora_dir):
    run(ellora_dir)
    src = png(ellora_dir)
    version = Project(ellora_dir, ELLORA).supply(HERO, src, ref="ellora://hero", external_id="g1")
    assert version == 1
    assert src.exists()  # copied, not moved
    assert (ellora_dir / "refs" / "product_hero.png").read_bytes() == PNG_1X1
    st = ProjectStore(ellora_dir).get(HERO)
    assert st.status == "done" and st.expected_fingerprint is None
    assert st.external == {"provider": "ellora", "ref": "ellora://hero", "id": "g1"}
    assert st.external_history == {"1": st.external}
    [entry] = [e for e in Ledger(ellora_dir / "ledger.jsonl").entries() if e["node_id"] == HERO]
    assert entry["ok"] is True and entry["cost_usd"] == 0.0 and entry["external_id"] == "g1"
    assert entry["provider"] == "ellora" and entry["model"] == "ellora-image"
    report = run(ellora_dir)
    assert HERO in report.skipped and "v1.s01.keyframe" in report.awaiting


def test_resupply_after_revision_archives_the_old_version(ellora_dir):
    p = Project(ellora_dir, ELLORA)
    run(ellora_dir)
    p.supply(HERO, png(ellora_dir), ref="r1")
    revise_hero(ellora_dir, "second take")
    run(ellora_dir)
    assert p.supply(HERO, png(ellora_dir), ref="r2") == 2
    assert (ellora_dir / "refs" / "versions" / "refs.product_hero_v1.png").exists()


def test_supply_rejects_a_node_changed_since_listing(ellora_dir):
    run(ellora_dir)
    revise_hero(ellora_dir, "changed")
    with pytest.raises(ValueError, match="changed since it was listed"):
        Project(ellora_dir, ELLORA).supply(HERO, png(ellora_dir), ref="r")


def test_supply_rejects_a_fingerprint_mismatch(ellora_dir):
    run(ellora_dir)
    with pytest.raises(ValueError, match="--fingerprint does not match"):
        Project(ellora_dir, ELLORA).supply(HERO, png(ellora_dir), ref="r", fingerprint="nope")


def test_supply_rejects_nodes_that_are_not_awaiting_or_not_external(ellora_dir):
    p = Project(ellora_dir, ELLORA)
    with pytest.raises(ValueError, match="not awaiting_external"):
        p.supply(HERO, png(ellora_dir), ref="r")
    run(ellora_dir)
    with pytest.raises(ValueError, match="not routed to an external provider"):
        p.supply("v1.vo.l01", png(ellora_dir), ref="r")
    with pytest.raises(KeyError):
        p.supply("v9.nope", png(ellora_dir), ref="r")


def test_supply_rejects_wrong_extension_and_missing_file(ellora_dir):
    run(ellora_dir)
    p = Project(ellora_dir, ELLORA)
    clip = ellora_dir / "clip.mp4"
    clip.write_bytes(b"x")
    with pytest.raises(ValueError, match="image needs one of"):
        p.supply(HERO, clip, ref="r")
    with pytest.raises(FileNotFoundError):
        p.supply(HERO, ellora_dir / "missing.png", ref="r")
    assert ProjectStore(ellora_dir).get(HERO).status == "awaiting_external"


def test_jpg_is_converted_to_png(ellora_dir, ffmpeg):
    # JPG rather than WebP here: every ffmpeg build can encode it, so the test fixture is portable.
    run(ellora_dir)
    jpg = ellora_dir / "hero.jpg"
    asyncio.run(ffmpeg.run(["-f", "lavfi", "-i", "color=red:s=8x8", "-frames:v", "1", str(jpg)]))
    Project(ellora_dir, ELLORA).supply(HERO, jpg, ref="r")
    assert (ellora_dir / "refs" / "product_hero.png").read_bytes()[:4] == b"\x89PNG"


def test_refused_supply_holds_and_blocks_until_revised(ellora_dir):
    run(ellora_dir)
    Project(ellora_dir, ELLORA).supply_failure(HERO, refused=True, message="content policy")
    st = ProjectStore(ellora_dir).get(HERO)
    assert (st.status, st.reason, st.message) == ("needs_review", "refused", "content policy")
    [entry] = [e for e in Ledger(ellora_dir / "ledger.jsonl").entries() if e["node_id"] == HERO]
    assert entry["ok"] is False
    report = run(ellora_dir)
    assert report.needs_review == [HERO] and "v1.s01.keyframe" in report.blocked
    revise_hero(ellora_dir, "softer wording")
    assert run(ellora_dir).awaiting == [HERO]


def test_failed_supply_marks_failed(ellora_dir):
    run(ellora_dir)
    Project(ellora_dir, ELLORA).supply_failure(HERO, refused=False, message="timed out")
    assert ProjectStore(ellora_dir).get(HERO).status == "failed"
    assert run(ellora_dir).failed == [HERO]


def test_rollback_restores_the_external_ref(ellora_dir):
    p = Project(ellora_dir, ELLORA)
    run(ellora_dir)
    p.supply(HERO, png(ellora_dir), ref="r1")
    revise_hero(ellora_dir, "second take")
    run(ellora_dir)
    p.supply(HERO, png(ellora_dir), ref="r2")
    new_version = p.rollback(HERO, 1)
    st = ProjectStore(ellora_dir).get(HERO)
    assert st.external["ref"] == "r1"
    assert st.external_history[str(new_version)]["ref"] == "r1"


def count_saves(monkeypatch):
    saves = []
    real = ProjectStore.save
    monkeypatch.setattr(ProjectStore, "save", lambda self: (saves.append(1), real(self))[1])
    return saves


def test_supply_and_rollback_write_state_once(ellora_dir, monkeypatch):
    p = Project(ellora_dir, ELLORA)
    run(ellora_dir)
    p.supply(HERO, png(ellora_dir), ref="r1")
    revise_hero(ellora_dir, "second take")
    run(ellora_dir)
    saves = count_saves(monkeypatch)
    assert p.supply(HERO, png(ellora_dir), ref="r2") == 2
    assert len(saves) == 1  # a crash cannot leave the node done without its external ref
    st = ProjectStore(ellora_dir).get(HERO)
    assert st.external["ref"] == "r2" and st.external_history["2"]["ref"] == "r2"
    saves.clear()
    assert p.rollback(HERO, 1) == 3
    assert len(saves) == 1


def test_commit_records_external_metadata(ellora_dir):
    store = ProjectStore(ellora_dir)
    hero = Project(ellora_dir, ELLORA).manifest().nodes[HERO]
    ext = {"provider": "ellora", "ref": "r", "id": None}
    assert store.commit(hero, png(ellora_dir), "fp", external=ext) == 1
    st = ProjectStore(ellora_dir).get(HERO)
    assert st.external == ext and st.external_history == {"1": ext}
