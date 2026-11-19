from pathlib import Path

from engine.config import EngineConfig
from engine.core.cache import compute_fingerprints, pinned_fingerprint
from engine.core.graph import Manifest
from tests.helpers import make_manifest, node


def fps_for(data, config=None, pins=None, project_dir=Path("/proj")):
    return compute_fingerprints(Manifest.from_dict(data), config or EngineConfig(), project_dir, pins or {})


def changed(a, b):
    return {k for k in a if a[k] != b[k]}


def test_fingerprints_are_deterministic_sha256():
    a, b = fps_for(make_manifest()), fps_for(make_manifest())
    assert a == b
    assert all(len(v) == 64 for v in a.values())
    assert len(set(a.values())) == len(a)


def test_prompt_change_invalidates_node_and_descendants_only():
    base = fps_for(make_manifest())
    data = make_manifest()
    node(data, "v1.s01.keyframe")["prompt"] = "darker, moodier"
    assert changed(base, fps_for(data)) == {
        "v1.s01.keyframe", "v1.s01.clip", "v1.timeline", "v1.preview", "v1.capcut_draft",
    }


def test_routing_change_invalidates_that_type_and_downstream():
    base = fps_for(make_manifest())
    cfg = EngineConfig.from_dict({"routing": {"video": {"provider": "mock", "model": "mock-video-2"}}})
    assert changed(base, fps_for(make_manifest(), config=cfg)) == {
        "v1.s01.clip", "v1.s02.clip", "v2.s01.clip", "v2.s02.clip",
        "v1.timeline", "v1.preview", "v1.capcut_draft",
        "v2.timeline", "v2.preview", "v2.capcut_draft",
    }


def test_pin_replaces_node_fingerprint_and_invalidates_descendants():
    base = fps_for(make_manifest())
    pinned = fps_for(make_manifest(), pins={"v1.vo.l01": 3})
    assert pinned["v1.vo.l01"] == pinned_fingerprint("v1.vo.l01", 3)
    assert changed(base, pinned) == {"v1.vo.l01", "v1.timeline", "v1.preview", "v1.capcut_draft"}


def test_project_location_does_not_affect_fingerprints():
    assert fps_for(make_manifest(), project_dir=Path("/a")) == fps_for(make_manifest(), project_dir=Path("/b"))
