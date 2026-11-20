import asyncio
import json

import pytest

from engine.config import EngineConfig
from engine.core.graph import ManifestError
from engine.core.project import Project
from engine.core.store import ProjectStore
from engine.providers.mock import PNG_1X1
from tests.helpers import ELLORA, ELLORA_CONFIG, RecordingProvider, make_manifest, node


def project(d, config=ELLORA):
    return Project(d, config)


def run(p):
    return asyncio.run(p.run(providers={"mock": RecordingProvider()}))


def write_manifest(d, data):
    (d / "manifest.json").write_text(json.dumps(data))


def test_ellora_manifest_has_no_external_errors(ellora_dir):
    assert project(ellora_dir).external_errors() == []


def test_external_node_cannot_reference_a_local_render(ellora_dir):
    video_only = EngineConfig.from_dict({**ELLORA_CONFIG, "routing": {
        "video": {"provider": "ellora", "model": "ellora-video"}}})
    errors = project(ellora_dir, video_only).external_errors()
    assert len(errors) == 4
    assert errors[0] == (
        "v1.s01.clip: input @v1.s01.keyframe is rendered locally, but ellora cannot read local "
        "files; route v1.s01.keyframe to ellora too"
    )


def test_external_image_must_have_one_candidate(ellora_dir):
    write_manifest(ellora_dir, make_manifest())  # keyframes have inputs.n = 2
    errors = project(ellora_dir).external_errors()
    assert "v1.s01.keyframe: external image nodes render one candidate; remove inputs.n or set it to 1" in errors


def test_only_image_and_video_may_be_external(ellora_dir):
    data = json.loads((ellora_dir / "manifest.json").read_text())
    node(data, "v1.vo.l01").update(provider="ellora", model="ellora-tts")
    write_manifest(ellora_dir, data)
    assert project(ellora_dir).external_errors() == [
        "v1.vo.l01: external provider ellora can only render image or video nodes"
    ]


def test_dry_run_and_run_refuse_invalid_external_manifests(ellora_dir):
    write_manifest(ellora_dir, make_manifest())
    with pytest.raises(ManifestError):
        project(ellora_dir).dry_run()
    with pytest.raises(ManifestError):
        run(project(ellora_dir))


def test_dry_run_labels_external_nodes(ellora_dir):
    report = project(ellora_dir).dry_run(providers={"mock": RecordingProvider(cost_per_call=0.5)})
    by_id = {p.node_id: p for p in report.to_run}
    hero = by_id["refs.product_hero"]
    assert hero.external and hero.cost_usd == 0.0 and hero.provider == "ellora"
    assert not by_id["v1.vo.l01"].external and by_id["v1.vo.l01"].cost_usd == 0.5


def test_external_nodes_lists_awaiting_with_resolved_inputs(ellora_dir):
    p = project(ellora_dir)
    assert p.external_nodes() == []
    run(p)
    [hero] = p.external_nodes()
    assert hero == {
        "id": "refs.product_hero",
        "type": "image",
        "provider": "ellora",
        "model": "ellora-image",
        "prompt": "Hero shot of a matte ceramic mug on a wooden table",
        "inputs": {"size": "1024x1024"},
        "external_inputs": {"size": "1024x1024"},
        "fingerprint": ProjectStore(ellora_dir).get("refs.product_hero").expected_fingerprint,
    }


def test_external_inputs_use_the_supplied_ref(ellora_dir):
    p = project(ellora_dir)
    run(p)
    store = ProjectStore(ellora_dir)
    hero = p.manifest().nodes["refs.product_hero"]
    f = ellora_dir / "hero.png"
    f.write_bytes(PNG_1X1)
    store.commit(hero, f, store.get("refs.product_hero").expected_fingerprint)
    store.update("refs.product_hero", external={"provider": "ellora", "ref": "ellora://hero", "id": "g1"})
    run(p)
    kf = next(n for n in p.external_nodes() if n["id"] == "v1.s01.keyframe")
    assert kf["inputs"]["refs"] == [str(ellora_dir / "refs" / "product_hero.png")]
    assert kf["external_inputs"]["refs"] == ["ellora://hero"]


def test_external_nodes_rejects_a_node_changed_since_the_run(ellora_dir):
    p = project(ellora_dir)
    run(p)
    data = json.loads((ellora_dir / "manifest.json").read_text())
    node(data, "refs.product_hero").update(prompt="changed")
    write_manifest(ellora_dir, data)
    with pytest.raises(ValueError, match="refs.product_hero changed since the last run"):
        p.external_nodes()


def test_external_nodes_rejects_an_input_without_an_external_ref(ellora_dir):
    hero = "refs.product_hero"
    local = Project(ellora_dir, EngineConfig.from_dict({"retry": {"base_delay_s": 0}}))
    asyncio.run(local.run([hero], providers={"mock": RecordingProvider()}))
    data = json.loads((ellora_dir / "manifest.json").read_text())
    node(data, hero)["prompt"] = "second take"
    write_manifest(ellora_dir, data)
    asyncio.run(local.run([hero], providers={"mock": RecordingProvider()}))
    local.rollback(hero, 1)  # pinned, rendered locally: no external ref to hand on
    p = project(ellora_dir)
    assert p.external_errors() == []
    assert "v1.s01.keyframe" in run(p).awaiting
    with pytest.raises(ValueError) as e:
        p.external_nodes()
    assert str(e.value) == (
        "v1.s01.keyframe: input @refs.product_hero has no external ref; "
        "supply refs.product_hero again (revise it or run adengine run)"
    )
