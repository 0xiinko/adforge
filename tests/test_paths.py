import pytest

from engine.core.graph import Manifest
from engine.core.paths import output_path, resolve_inputs, version_path
from tests.helpers import make_manifest


@pytest.mark.parametrize(
    "node_id,node_type,expected",
    [
        ("refs.product_hero", "image", "refs/product_hero.png"),
        ("v2.s03.keyframe", "image", "v2/shots/s03/keyframe.png"),
        ("v2.s03.clip", "video", "v2/shots/s03/clip.mp4"),
        ("v2.vo.l04", "tts", "v2/vo/l04.wav"),
        ("v2.sfx.whoosh02", "sfx", "v2/sfx/whoosh02.wav"),
        ("shared.music.bed", "music", "shared/music/bed.mp3"),
        ("v2.timeline", "timeline", "v2/timeline.json"),
        ("v2.preview", "preview", "v2/preview.mp4"),
        ("v2.capcut_draft", "capcut_draft", "v2/capcut_draft"),
    ],
)
def test_output_path(tmp_path, node_id, node_type, expected):
    assert output_path(tmp_path, node_id, node_type) == tmp_path / expected


def test_version_path_for_file(tmp_path):
    out = tmp_path / "v2/shots/s03/clip.mp4"
    assert version_path(out, "v2.s03.clip", 2) == tmp_path / "v2/shots/s03/versions/v2.s03.clip_v2.mp4"


def test_version_path_for_directory(tmp_path):
    out = tmp_path / "v2/capcut_draft"
    assert version_path(out, "v2.capcut_draft", 1) == tmp_path / "v2/versions/v2.capcut_draft_v1"


def test_resolve_inputs_absolute_and_relative(tmp_path):
    m = Manifest.from_dict(make_manifest())
    clip = m.nodes["v1.s01.clip"]
    assert resolve_inputs(m, tmp_path, clip)["first_frame"] == str(tmp_path / "v1/shots/s01/keyframe.png")
    rel = resolve_inputs(m, tmp_path, clip, absolute=False)
    assert rel == {"first_frame": "v1/shots/s01/keyframe.png", "duration": 4, "aspect": "9:16"}
