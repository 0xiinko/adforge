import re
from pathlib import Path

import pytest

from engine.assembly.timeline import TimelineError, build_timeline, caption_chunks, media_paths
from tests.helpers import assert_golden

P = Path("/proj")


def src(rel):
    return str(P / rel)


CLIP1, CLIP2 = src("v1/shots/s01/clip.mp4"), src("v1/shots/s02/clip.mp4")
KF1, KF2 = src("v1/shots/s01/keyframe.png"), src("v1/shots/s02/keyframe.png")
L01, L02 = src("v1/vo/l01.wav"), src("v1/vo/l02.wav")
WHOOSH, BED, END = src("v1/sfx/whoosh.wav"), src("shared/music/bed.wav"), src("v1/end.png")
SOURCES = {
    CLIP1: "v1.s01.clip", CLIP2: "v1.s02.clip", KF1: "v1.s01.keyframe", KF2: "v1.s02.keyframe",
    L01: "v1.vo.l01", L02: "v1.vo.l02", WHOOSH: "v1.sfx.whoosh", BED: "shared.music.bed", END: "v1.end",
}
MEDIA = {CLIP1: 3.0, CLIP2: 2.0, KF1: 0.0, KF2: 0.0, L01: 2.0, L02: 1.0, WHOOSH: 0.5, BED: 10.0}


def inputs(**overrides):
    base = {
        "aspect": "9:16",
        "shots": [
            {"clip": CLIP1, "duration": 3, "fallback": KF1},
            {"clip": CLIP2, "duration": 2.5, "transition": "crossfade", "fallback": KF2},
        ],
        "vo": [{"audio": L01, "text": "Fresh coffee every single morning"}, {"audio": L02, "text": "Try it today"}],
        "sfx": [{"audio": WHOOSH, "start": 2.9, "volume": 0.8}],
        "music": {"audio": BED, "volume": 0.3},
        "end_card": {"text": "Shop now", "duration": 1.5},
    }
    base.update(overrides)
    return base


def build(media=MEDIA, **overrides):
    return build_timeline("v1.timeline", inputs(**overrides), sources=SOURCES, project_dir=P, media=dict(media))


def test_basic_timeline_layout():
    t = build()
    assert (t["width"], t["height"], t["fps"], t["duration"]) == (1080, 1920, 30, 7.0)
    v = t["tracks"]["video"]
    assert [(e["node"], e["kind"], e["start"], e["duration"]) for e in v] == [
        ("v1.s01.clip", "video", 0.0, 3.0), ("v1.s02.clip", "video", 3.0, 2.5),
    ]
    assert v[0]["path"] == "v1/shots/s01/clip.mp4"
    assert [(e["transition"], e["transition_s"]) for e in v] == [("cut", 0.0), ("crossfade", 0.25)]
    assert [e["hold"] for e in v] == [False, True]
    vo = t["tracks"]["vo"]
    assert [(e["start"], e["duration"]) for e in vo] == [(0.2, 2.0), (2.35, 1.0)]
    assert t["tracks"]["captions"] == [
        {"start": 0.2, "end": 1.325, "text": "Fresh coffee every"},
        {"start": 1.325, "end": 2.2, "text": "single morning"},
        {"start": 2.35, "end": 3.35, "text": "Try it today"},
    ]
    assert t["tracks"]["sfx"] == [
        {"node": "v1.sfx.whoosh", "path": "v1/sfx/whoosh.wav", "start": 2.9, "duration": 0.5, "volume": 0.8},
    ]
    assert t["tracks"]["music"] == {
        "node": "shared.music.bed", "path": "shared/music/bed.wav", "start": 0.0, "duration": 7.0,
        "source_duration": 10.0, "volume": 0.3, "duck": True,
    }
    assert t["tracks"]["end_card"] == {"node": None, "path": None, "start": 5.5, "duration": 1.5, "text": "Shop now"}
    assert t["placeholders"] == [] and t["warnings"] == []


def test_golden_basic_timeline():
    assert_golden("timeline_basic.json", build())


def test_missing_media_becomes_placeholders():
    media = {KF1: 0.0, L01: 2.0, WHOOSH: 0.5}
    t = build(media=media)
    v = t["tracks"]["video"]
    assert (v[0]["kind"], v[0]["node"], v[0]["path"], v[0]["placeholder_for"]) == (
        "image", "v1.s01.keyframe", "v1/shots/s01/keyframe.png", "v1.s01.clip",
    )
    assert (v[1]["kind"], v[1]["node"], v[1]["path"], v[1]["placeholder_for"]) == ("slate", None, None, "v1.s02.clip")
    vo = t["tracks"]["vo"][1]
    assert (vo["path"], vo["duration"]) == (None, 1.2)
    assert t["tracks"]["captions"][-1]["text"] == "Try it today"
    assert t["tracks"]["music"] is None
    assert t["placeholders"] == ["v1.s01.clip", "v1.s02.clip", "v1.vo.l02", "shared.music.bed"]


def test_end_card_image_and_missing_end_card_image():
    t = build(media={**MEDIA, END: 0.0}, end_card={"text": "", "duration": 1, "image": END})
    assert t["tracks"]["end_card"] == {"node": "v1.end", "path": "v1/end.png", "start": 5.5, "duration": 1.0, "text": ""}
    t = build(end_card={"text": "Go", "image": END})
    assert t["tracks"]["end_card"]["path"] is None and "v1.end" in t["placeholders"]
    assert t["tracks"]["end_card"]["duration"] == 2.0


def test_first_shot_transition_is_always_a_cut():
    shots = [{"clip": CLIP1, "duration": 3, "transition": "crossfade"}]
    assert build(shots=shots)["tracks"]["video"][0]["transition"] == "cut"


def test_vo_explicit_start_and_overrun_warning():
    t = build(vo=[{"audio": L01, "text": "late line", "start": 5.0}])
    assert t["tracks"]["vo"][0]["start"] == 5.0
    assert t["warnings"] == ["v1.vo.l01 ends at 7.0s, after the last shot at 5.5s"]


def test_captions_can_be_disabled():
    assert build(captions=False)["tracks"]["captions"] == []


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"shots": []}, "inputs.shots must be a non-empty list"),
        ({"shots": [{"clip": CLIP1, "duration": 0}]}, "inputs.shots[0].duration must be > 0"),
        ({"aspect": "21:9"}, "inputs.aspect must be one of"),
        ({"shots": [{"clip": CLIP1, "duration": 1}, {"clip": CLIP2, "duration": 1, "transition": "wipe"}]},
         "inputs.shots[1].transition must be one of"),
        ({"sfx": [{"audio": WHOOSH}]}, "inputs.sfx[0].start must be a number"),
    ],
)
def test_invalid_inputs_fail_with_clear_message(overrides, message):
    with pytest.raises(TimelineError, match=re.escape(f"v1.timeline: {message}")):
        build(**overrides)


def test_caption_chunks_split_by_words_and_time_by_length():
    assert caption_chunks("", 0, 1) == []
    cues = caption_chunks("a bb ccc dddd", 1.0, 2.0, words_per_chunk=2)
    assert cues == [{"start": 1.0, "end": 1.667, "text": "a bb"}, {"start": 1.667, "end": 3.0, "text": "ccc dddd"}]


def test_media_paths_lists_every_referenced_file():
    assert media_paths(inputs(end_card={"text": "x", "image": END})) == [
        CLIP1, KF1, CLIP2, KF2, L01, L02, WHOOSH, BED, END,
    ]
