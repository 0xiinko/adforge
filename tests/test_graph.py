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


def test_schema_ships_inside_the_engine_package():
    from importlib.resources import files

    from engine.core import graph

    resource = files("engine.schemas") / "manifest.schema.json"
    assert resource.is_file()
    assert graph._schema()["title"] == "AdForge manifest"


def test_at_sign_in_ad_copy_is_literal():
    data = make_manifest()
    node(data, "v1.vo.l01")["inputs"]["text"] = "@acme has a sale"
    m = Manifest.from_dict(data)
    assert find_refs(m.nodes["v1.vo.l01"].inputs) == []
    assert resolve_refs("@acme has a sale", lambda r: "X") == "@acme has a sale"


def test_double_at_escapes_a_ref_shaped_literal():
    data = make_manifest()
    node(data, "v1.vo.l01")["inputs"]["text"] = "@@acme.sale"
    m = Manifest.from_dict(data)
    assert find_refs(m.nodes["v1.vo.l01"].inputs) == []
    assert resolve_refs(m.nodes["v1.vo.l01"].inputs, lambda r: "X")["text"] == "@acme.sale"


def test_nested_refs_found_and_resolved():
    value = {"a": {"b": ["@x.y", {"c": "@x.y.z"}]}, "d": "@@x.y", "e": "plain @x.y", "f": 3}
    assert find_refs(value) == ["x.y", "x.y.z"]
    assert resolve_refs(value, lambda r: f"<{r}>") == {
        "a": {"b": ["<x.y>", {"c": "<x.y.z>"}]}, "d": "@x.y", "e": "plain @x.y", "f": 3,
    }


def _add(data, node_id, node_type="image"):
    data["nodes"].append({"id": node_id, "type": node_type, "inputs": {}, "depends_on": []})


def test_directory_output_cannot_contain_another_nodes_output():
    data = make_manifest()
    _add(data, "v1.draft", "capcut_draft")
    _add(data, "v1.draft.x")
    with pytest.raises(ManifestError) as exc:
        Manifest.from_dict(data)
    msg = str(exc.value)
    assert "v1.draft" in msg and "v1.draft.x" in msg


@pytest.mark.parametrize("bad_id", ["v1.versions", "v1.shots", "v1.versions.x"])
def test_reserved_layout_names_rejected(bad_id):
    data = make_manifest()
    _add(data, bad_id)
    with pytest.raises(ManifestError, match="reserved"):
        Manifest.from_dict(data)


def test_id_with_trailing_newline_rejected():
    data = make_manifest()
    node(data, "refs.product_hero")["id"] = "refs.hero\n"
    for n in data["nodes"]:
        n["depends_on"] = []
        n["inputs"] = {}
    with pytest.raises(ManifestError, match="invalid node id"):
        Manifest.from_dict(data)


def test_default_manifest_layout_is_valid():
    Manifest.from_dict(make_manifest(variants=("v1", "v2", "v3"), shots=4))
