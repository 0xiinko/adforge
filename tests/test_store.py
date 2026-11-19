import pytest

from engine.core.cache import pinned_fingerprint
from engine.core.graph import Node
from engine.core.store import ProjectStore

VO = Node(id="v1.vo.l01", type="tts", inputs={}, depends_on=[])
DRAFT = Node(id="v1.capcut_draft", type="capcut_draft", inputs={}, depends_on=[])


def produce(tmp_path, name, text):
    path = tmp_path / "work" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_new_store_is_empty(tmp_path):
    store = ProjectStore(tmp_path)
    assert store.nodes == {}
    assert store.get("x.y").status == "pending"
    assert not store.state_path.exists()


def test_commit_moves_output_and_versions_the_previous_one(tmp_path):
    store = ProjectStore(tmp_path)
    out = tmp_path / "v1/vo/l01.wav"
    assert store.commit(VO, produce(tmp_path, "a.wav", "one"), "fp1") == 1
    assert out.read_text() == "one"
    assert store.commit(VO, produce(tmp_path, "b.wav", "two"), "fp2") == 2
    assert out.read_text() == "two"
    assert (tmp_path / "v1/vo/versions/v1.vo.l01_v1.wav").read_text() == "one"
    assert store.versions(VO) == [1]
    st = store.get(VO.id)
    assert (st.status, st.version, st.fingerprint) == ("done", 2, "fp2")


def test_state_persists_across_instances(tmp_path):
    ProjectStore(tmp_path).commit(VO, produce(tmp_path, "a.wav", "one"), "fp1")
    st = ProjectStore(tmp_path).get(VO.id)
    assert (st.status, st.version, st.fingerprint) == ("done", 1, "fp1")


def test_is_fresh_requires_matching_fingerprint_and_existing_output(tmp_path):
    store = ProjectStore(tmp_path)
    store.commit(VO, produce(tmp_path, "a.wav", "one"), "fp1")
    assert store.is_fresh(VO, "fp1")
    assert not store.is_fresh(VO, "fp2")
    store.output(VO).unlink()
    assert not store.is_fresh(VO, "fp1")


def test_directory_outputs_commit_and_version(tmp_path):
    store = ProjectStore(tmp_path)
    for i in (1, 2):
        d = tmp_path / "work" / f"draft{i}"
        d.mkdir(parents=True)
        (d / "draft_content.json").write_text(str(i))
        store.commit(DRAFT, d, f"fp{i}")
    assert (tmp_path / "v1/capcut_draft/draft_content.json").read_text() == "2"
    assert (tmp_path / "v1/versions/v1.capcut_draft_v1/draft_content.json").read_text() == "1"
    assert store.versions(DRAFT) == [1]


def test_rollback_restores_content_and_pins(tmp_path):
    store = ProjectStore(tmp_path)
    store.commit(VO, produce(tmp_path, "a.wav", "one"), "fp1")
    store.commit(VO, produce(tmp_path, "b.wav", "two"), "fp2")
    assert store.rollback(VO, 1) == 3
    assert store.output(VO).read_text() == "one"
    st = store.get(VO.id)
    assert st.pinned_version == 3
    assert st.fingerprint == pinned_fingerprint(VO.id, 3)
    assert store.pins() == {VO.id: 3}
    assert store.versions(VO) == [1, 2]
    store.unpin(VO.id)
    assert store.pins() == {}


def test_rollback_to_missing_version_raises(tmp_path):
    store = ProjectStore(tmp_path)
    store.commit(VO, produce(tmp_path, "a.wav", "one"), "fp1")
    with pytest.raises(ValueError, match="no version 7"):
        store.rollback(VO, 7)


def test_work_dir_is_fresh_each_time(tmp_path):
    store = ProjectStore(tmp_path)
    d = store.work_dir("v1.s01.clip")
    (d / "junk").write_text("x")
    d2 = store.work_dir("v1.s01.clip")
    assert d2 == d and d2.is_dir() and not (d2 / "junk").exists()
