import json
from pathlib import Path

from engine.assembly.capcut_draft import CAPTION_Y, build_draft, write_draft
from tests.helpers import assert_golden

P = Path("/home/me/projects/mug-launch")
SLATES = {2: P / "v1/capcut_draft/placeholders/slate_02.png"}


def entry(node, path, kind, start, duration, transition="cut", ts=0.0, placeholder_for=None, audio=False):
    return {"node": node, "path": path, "kind": kind, "start": start, "duration": duration,
            "transition": transition, "transition_s": ts, "hold": False, "placeholder_for": placeholder_for,
            "audio": audio}


TIMELINE = {
    "version": 1, "node": "v1.timeline", "width": 1080, "height": 1920, "fps": 30, "duration": 7.0,
    "tracks": {
        "video": [
            entry("v1.s01.clip", "v1/shots/s01/clip.mp4", "video", 0.0, 3.0),
            entry("v1.s02.keyframe", "v1/shots/s02/keyframe.png", "image", 3.0, 2.5, "crossfade", 0.25, "v1.s02.clip"),
            entry(None, None, "slate", 5.5, 0.5, placeholder_for="v1.s03.clip"),
        ],
        "vo": [
            {"node": "v1.vo.l01", "path": "v1/vo/l01.wav", "start": 0.2, "duration": 2.0,
             "text": "Fresh coffee every single morning"},
            {"node": "v1.vo.l02", "path": None, "start": 2.35, "duration": 1.2, "text": "Try it today"},
        ],
        "sfx": [{"node": "v1.sfx.whoosh", "path": "v1/sfx/whoosh.wav", "start": 2.9, "duration": 0.5, "volume": 0.8}],
        "music": {"node": "shared.music.bed", "path": "shared/music/bed.wav", "start": 0.0, "duration": 7.0,
                  "source_duration": 3.0, "volume": 0.3, "duck": True},
        "captions": [{"start": 0.2, "end": 1.325, "text": "Fresh coffee every"},
                     {"start": 1.325, "end": 2.2, "text": "single morning"}],
        "end_card": {"node": None, "path": None, "start": 6.0, "duration": 1.0, "text": "Shop now"},
    },
    "placeholders": ["v1.s02.clip", "v1.s03.clip", "v1.vo.l02"],
    "warnings": [],
}


def build(**kw):
    args = dict(project_dir=P, draft_dir=P / "v1/capcut_draft", draft_name="mug-launch_v1",
                media_root=None, now_us=1_700_000_000_000_000, slates=SLATES)
    args.update(kw)
    return build_draft(TIMELINE, **args)


def track(draft, name):
    return next(t for t in draft["tracks"] if t["name"] == name)


def material(draft, kind, material_id):
    return next(m for m in draft["materials"][kind] if m["id"] == material_id)


def test_track_layout():
    draft, _ = build()
    assert [(t["type"], t["name"]) for t in draft["tracks"]] == [
        ("video", "main"), ("audio", "vo"), ("audio", "sfx"), ("audio", "music"),
        ("text", "captions"), ("text", "end_card"),
    ]
    assert draft["duration"] == 7_000_000 and draft["fps"] == 30.0
    assert draft["canvas_config"] == {"height": 1920, "ratio": "original", "width": 1080}
    assert draft["name"] == "mug-launch_v1"


def test_video_segments_are_named_by_node_id():
    draft, _ = build()
    segs = track(draft, "main")["segments"]
    assert [s["target_timerange"] for s in segs] == [
        {"start": 0, "duration": 3_000_000}, {"start": 3_000_000, "duration": 2_500_000},
        {"start": 5_500_000, "duration": 500_000},
    ]
    mats = [material(draft, "videos", s["material_id"]) for s in segs]
    assert [m["material_name"] for m in mats] == ["v1.s01.clip", "v1.s02.keyframe", "v1.s03.clip"]
    assert [m["type"] for m in mats] == ["video", "photo", "photo"]
    assert [m["path"] for m in mats] == [
        str(P / "v1/shots/s01/clip.mp4"), str(P / "v1/shots/s02/keyframe.png"), str(SLATES[2]),
    ]


def test_audio_tracks_skip_missing_vo_and_loop_music():
    draft, _ = build()
    vo = track(draft, "vo")["segments"]
    assert [s["target_timerange"] for s in vo] == [{"start": 200_000, "duration": 2_000_000}]
    music = track(draft, "music")["segments"]
    assert [s["target_timerange"] for s in music] == [
        {"start": 0, "duration": 3_000_000}, {"start": 3_000_000, "duration": 3_000_000},
        {"start": 6_000_000, "duration": 1_000_000},
    ]
    assert {s["volume"] for s in music} == {0.3}
    assert len({s["material_id"] for s in music}) == 1
    assert sorted(m["name"] for m in draft["materials"]["audios"]) == ["shared.music.bed", "v1.sfx.whoosh", "v1.vo.l01"]
    assert track(draft, "sfx")["segments"][0]["volume"] == 0.8


def test_caption_and_end_card_text():
    draft, _ = build()
    caps = track(draft, "captions")["segments"]
    texts = [json.loads(material(draft, "texts", s["material_id"])["content"])["text"] for s in caps]
    assert texts == ["Fresh coffee every", "single morning"]
    assert all(s["clip"]["transform"]["y"] == CAPTION_Y and s["source_timerange"] is None for s in caps)
    end = track(draft, "end_card")["segments"][0]
    assert end["target_timerange"] == {"start": 6_000_000, "duration": 1_000_000}
    assert json.loads(material(draft, "texts", end["material_id"])["content"])["text"] == "Shop now"


def test_media_root_rewrites_paths_for_the_capcut_machine():
    draft, _ = build(media_root="C:/AdForge/projects")
    first = material(draft, "videos", track(draft, "main")["segments"][0]["material_id"])
    assert first["path"] == "C:/AdForge/projects/mug-launch/v1/shots/s01/clip.mp4"


def test_references_resolve_ids_are_unique_and_output_is_deterministic():
    draft, meta = build()
    assert build() == (draft, meta)
    material_ids = {m["id"] for kind in ("videos", "audios", "texts", "speeds") for m in draft["materials"][kind]}
    segments = [s for t in draft["tracks"] for s in t["segments"]]
    for s in segments:
        assert s["material_id"] in material_ids
        assert set(s["extra_material_refs"]) <= material_ids
    all_ids = [m["id"] for kind in ("videos", "audios", "texts", "speeds") for m in draft["materials"][kind]]
    all_ids += [t["id"] for t in draft["tracks"]] + [s["id"] for s in segments]
    assert len(all_ids) == len(set(all_ids))
    assert meta["draft_id"] == draft["id"] and meta["tm_duration"] == 7_000_000
    assert meta["draft_fold_path"] == str(P / "v1/capcut_draft")


def test_write_draft_creates_both_files(tmp_path):
    draft, meta = build()
    write_draft(tmp_path / "capcut_draft", draft, meta)
    assert json.loads((tmp_path / "capcut_draft/draft_content.json").read_text()) == draft
    assert json.loads((tmp_path / "capcut_draft/draft_meta_info.json").read_text()) == meta


def test_golden_basic_draft():
    assert_golden("capcut_basic.json", build()[0])


def test_video_segment_volume_follows_clip_audio():
    draft, _ = build()
    assert [s["volume"] for s in track(draft, "main")["segments"]] == [0.0, 0.0, 0.0]
    video = [dict(e) for e in TIMELINE["tracks"]["video"]]
    video[0]["audio"] = True
    timeline = {**TIMELINE, "tracks": {**TIMELINE["tracks"], "video": video}}
    draft, _ = build_draft(timeline, project_dir=P, draft_dir=P / "v1/capcut_draft", draft_name="mug-launch_v1",
                           media_root=None, now_us=1_700_000_000_000_000, slates=SLATES)
    assert [s["volume"] for s in track(draft, "main")["segments"]] == [1.0, 0.0, 0.0]
