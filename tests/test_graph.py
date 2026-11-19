import pytest

from engine.core.graph import (
    Manifest,
    ManifestError,
    find_refs,
    load_manifest,
    resolve_refs,
    save_manifest,
)
from tests.helpers import make_manifest, node


def test_valid_manifest_loads():
    m = Manifest.from_dict(make_manifest())
    assert m.project == "mug-launch"
    assert len(m.nodes) == 17
    assert m.nodes["v1.s01.clip"].inputs["first_frame"] == "@v1.s01.keyframe"


def test_schema_rejects_bad_id():
    data = make_manifest()
    data["nodes"][0]["id"] = "Refs.Hero"
    with pytest.raises(ManifestError) as exc:
        Manifest.from_dict(data)
    assert "nodes/0/id" in str(exc.value)


def test_schema_rejects_unknown_type():
    data = make_manifest()
    data["nodes"][0]["type"] = "gif"
    with pytest.raises(ManifestError) as exc:
        Manifest.from_dict(data)
    assert "nodes/0/type" in str(exc.value)


def test_ref_must_be_listed_in_depends_on():
    data = make_manifest()
    node(data, "v1.s01.clip")["depends_on"] = []
    with pytest.raises(ManifestError) as exc:
        Manifest.from_dict(data)
    assert "v1.s01.clip: input references @v1.s01.keyframe but it is not in depends_on" in exc.value.errors


def test_unknown_dependency_rejected():
    data = make_manifest()
    node(data, "v1.s01.clip")["depends_on"].append("v9.s01.keyframe")
    with pytest.raises(ManifestError) as exc:
        Manifest.from_dict(data)
    assert "v1.s01.clip: depends_on unknown node v9.s01.keyframe" in exc.value.errors


def test_duplicate_id_rejected():
    data = make_manifest()
    data["nodes"].append(dict(data["nodes"][0]))
    with pytest.raises(ManifestError) as exc:
        Manifest.from_dict(data)
    assert "duplicate node id: refs.product_hero" in exc.value.errors


def test_cycle_rejected():
    data = make_manifest()
    node(data, "refs.product_hero")["depends_on"] = ["v1.s01.keyframe"]
    with pytest.raises(ManifestError) as exc:
        Manifest.from_dict(data)
    assert "dependency cycle" in str(exc.value)


def test_topo_order_puts_dependencies_first():
    m = Manifest.from_dict(make_manifest())
    order = m.topo_order()
    assert sorted(order) == sorted(m.nodes)
    for nid, n in m.nodes.items():
        for dep in n.depends_on:
            assert order.index(dep) < order.index(nid)


def test_descendants_and_ancestors():
    m = Manifest.from_dict(make_manifest())
    assert m.descendants(["v1.s01.keyframe"]) == {
        "v1.s01.clip", "v1.timeline", "v1.preview", "v1.capcut_draft",
    }
    assert m.ancestors(["v1.preview"]) == {
        "v1.timeline", "v1.s01.clip", "v1.s02.clip", "v1.s01.keyframe",
        "v1.s02.keyframe", "v1.vo.l01", "refs.product_hero",
    }


def test_scope_with_globs():
    m = Manifest.from_dict(make_manifest())
    assert m.scope(None) == set(m.nodes)
    assert m.scope(["refs.*"]) == {"refs.product_hero"}
    assert m.scope(["v2.s02.clip"]) == {"v2.s02.clip", "v2.s02.keyframe", "refs.product_hero"}
    with pytest.raises(ValueError, match="no nodes match"):
        m.scope(["nope.*"])


def test_find_and_resolve_refs():
    inputs = {"clips": ["@a.b", "x"], "first": "@c.d", "n": 2}
    assert find_refs(inputs) == ["a.b", "c.d"]
    assert resolve_refs(inputs, lambda r: f"/out/{r}") == {
        "clips": ["/out/a.b", "x"], "first": "/out/c.d", "n": 2,
    }


def test_save_and_load_roundtrip(tmp_path):
    m = Manifest.from_dict(make_manifest())
    path = tmp_path / "manifest.json"
    save_manifest(m, path)
    assert load_manifest(path).to_dict() == m.to_dict()
    assert m.to_dict() == make_manifest()
