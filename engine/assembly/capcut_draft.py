"""CapCut draft writer (spec §7). Deliberately isolated: if CapCut changes its draft
format, only this module and capcut_template.json change; preview and raw assets
keep working.

Builds draft_content.json + draft_meta_info.json from timeline.json. Every clip is
named by its node id. Times are microseconds. IDs are deterministic (uuid5), so a
rebuilt draft is byte-for-byte stable and overwrites the old one in place."""
from __future__ import annotations

import copy
import json
import uuid
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

US = 1_000_000
ID_NAMESPACE = uuid.UUID("6f1c8a52-1f0e-4b7a-9d3e-0a5d2c7b9e41")
PHOTO_DURATION_US = 10_800 * US   # CapCut's material length for stills
CAPTION_Y = -0.62                 # CapCut transform space: -1 bottom … 1 top
CAPTION_SIZE = 8.0
END_CARD_SIZE = 12.0


def us(seconds: float) -> int:
    return int(round(seconds * US))


def draft_id(*parts: str) -> str:
    return str(uuid.uuid5(ID_NAMESPACE, "/".join(parts))).upper()


@lru_cache(maxsize=1)
def _template() -> dict[str, Any]:
    return json.loads(resources.files("engine.assembly").joinpath("capcut_template.json").read_text())


def _timerange(start: float, duration: float) -> dict[str, int]:
    return {"start": us(start), "duration": us(duration)}


def _track(name: str, kind: str, track_id: str) -> dict[str, Any]:
    return {"attribute": 0, "flag": 0, "id": track_id, "is_default_name": False,
            "name": name, "segments": [], "type": kind}


def _speed(speed_id: str) -> dict[str, Any]:
    return {"curve_speed": None, "id": speed_id, "mode": 0, "speed": 1.0, "type": "speed"}


def _segment(segment_id: str, material_id: str, start: float, duration: float, *, volume: float = 1.0,
             extra_refs: list[str] | None = None, transform_y: float = 0.0, has_source: bool = True) -> dict[str, Any]:
    return {
        "caption_info": None, "cartoon": False,
        "clip": {"alpha": 1.0, "flip": {"horizontal": False, "vertical": False}, "rotation": 0.0,
                 "scale": {"x": 1.0, "y": 1.0}, "transform": {"x": 0.0, "y": transform_y}},
        "common_keyframes": [], "enable_adjust": True, "enable_color_curves": True, "enable_color_wheels": True,
        "enable_lut": True, "extra_material_refs": list(extra_refs or []), "group_id": "",
        "hdr_settings": {"intensity": 1.0, "mode": 1, "nits": 1000}, "id": segment_id,
        "intensifies_audio": False, "is_placeholder": False, "is_tone_modify": False, "keyframe_refs": [],
        "last_nonzero_volume": 1.0, "material_id": material_id, "render_index": 0, "reverse": False,
        "source_timerange": _timerange(0.0, duration) if has_source else None,
        "speed": 1.0, "target_timerange": _timerange(start, duration), "template_id": "",
        "template_scene": "default", "track_attribute": 0, "track_render_index": 0,
        "uniform_scale": {"on": True, "value": 1.0}, "visible": True, "volume": volume,
    }


def _video_material(material_id: str, path: str, name: str, kind: str, duration: float,
                    width: int, height: int) -> dict[str, Any]:
    return {
        "audio_fade": None, "category_id": "", "category_name": "local", "check_flag": 63487,
        "crop": {"lower_left_x": 0.0, "lower_left_y": 1.0, "lower_right_x": 1.0, "lower_right_y": 1.0,
                 "upper_left_x": 0.0, "upper_left_y": 0.0, "upper_right_x": 1.0, "upper_right_y": 0.0},
        "crop_ratio": "free", "crop_scale": 1.0,
        "duration": PHOTO_DURATION_US if kind == "photo" else us(duration),
        "extra_type_option": 0, "height": height, "id": material_id, "local_material_id": "",
        "material_id": "", "material_name": name, "media_path": "", "path": path, "source_platform": 0,
        "type": kind, "width": width,
    }


def _audio_material(material_id: str, path: str, name: str, duration: float) -> dict[str, Any]:
    return {
        "app_id": 0, "category_id": "", "category_name": "local", "check_flag": 1, "duration": us(duration),
        "effect_id": "", "formula_id": "", "id": material_id, "intensifies_path": "",
        "local_material_id": material_id, "music_id": material_id, "name": name, "path": path,
        "source_platform": 0, "team_id": "", "text_id": "", "tone_category_id": "", "tone_category_name": "",
        "tone_effect_id": "", "tone_effect_name": "", "tone_speaker": "", "tone_type": "",
        "type": "extract_music", "video_id": "", "wave_points": [],
    }


def _text_material(material_id: str, text: str, size: float) -> dict[str, Any]:
    length = len(text.encode("utf-16-le")) // 2
    solid = lambda rgb: {"render_type": "solid", "solid": {"alpha": 1.0, "color": rgb}}  # noqa: E731
    content = {
        "styles": [{"fill": {"alpha": 1.0, "content": solid([1.0, 1.0, 1.0])}, "range": [0, length],
                    "size": size, "bold": True, "font": {"id": "", "path": ""},
                    "strokes": [{"content": solid([0.0, 0.0, 0.0]), "width": 0.08}]}],
        "text": text,
    }
    return {
        "add_type": 0, "alignment": 1, "background_alpha": 1.0, "background_color": "", "check_flag": 7,
        "content": json.dumps(content, ensure_ascii=False), "fixed_height": -1.0, "fixed_width": -1.0,
        "font_size": size, "global_alpha": 1.0, "id": material_id, "line_max_width": 0.82,
        "line_spacing": 0.02, "name": "", "text_alpha": 1.0, "text_color": "#FFFFFF", "type": "text",
        "typesetting": 0,
    }


def build_draft(
    timeline: dict[str, Any],
    *,
    project_dir: Path,
    draft_dir: Path,
    draft_name: str,
    media_root: str | None,
    now_us: int,
    slates: dict[int, Path],
) -> tuple[dict[str, Any], dict[str, Any]]:
    def mid(*parts: str) -> str:
        return draft_id(draft_name, *parts)

    def media_path(path: Path) -> str:
        if media_root:
            return f"{media_root}/{path.relative_to(project_dir.parent).as_posix()}"
        return str(path)

    width, height, fps = timeline["width"], timeline["height"], timeline["fps"]
    tracks = timeline["tracks"]
    draft = copy.deepcopy(_template())
    mats = draft["materials"]
    draft.update(
        id=mid("draft"), name=draft_name, fps=float(fps), duration=us(timeline["duration"]),
        create_time=now_us // US, update_time=now_us // US,
        canvas_config={"height": height, "ratio": "original", "width": width},
    )

    main = _track("main", "video", mid("track", "main"))

    def add_visual(key: str, path: Path, name: str, kind: str, start: float, duration: float,
                   volume: float = 0.0) -> None:
        material_id, speed_id = mid("video", key), mid("speed", "video", key)
        mats["videos"].append(_video_material(material_id, media_path(path), name, kind, duration, width, height))
        mats["speeds"].append(_speed(speed_id))
        main["segments"].append(_segment(mid("segment", "video", key), material_id, start, duration,
                                         volume=volume, extra_refs=[speed_id]))

    for i, e in enumerate(tracks["video"]):
        if e["kind"] == "slate":
            add_visual(str(i), slates[i], e["placeholder_for"], "photo", e["start"], e["duration"])
        else:
            # A clip's own sound plays only when the timeline uses it; otherwise it is muted.
            add_visual(str(i), project_dir / e["path"], e["node"], "video" if e["kind"] == "video" else "photo",
                       e["start"], e["duration"], volume=1.0 if e.get("audio") else 0.0)
    card = tracks["end_card"]
    if card and card["path"]:
        add_visual("end_card", project_dir / card["path"], card["node"], "photo", card["start"], card["duration"])
    out_tracks = [main]

    audio_materials: dict[str, str] = {}

    def audio_material(e: dict[str, Any]) -> str:
        if e["path"] not in audio_materials:
            material_id = mid("audio", e["node"])
            mats["audios"].append(_audio_material(material_id, media_path(project_dir / e["path"]), e["node"],
                                                  e.get("source_duration", e["duration"])))
            audio_materials[e["path"]] = material_id
        return audio_materials[e["path"]]

    def audio_track(name: str, pieces: list[tuple[dict[str, Any], float, float, float]]) -> None:
        if not pieces:
            return
        track = _track(name, "audio", mid("track", name))
        for k, (e, start, duration, volume) in enumerate(pieces):
            speed_id = mid("speed", name, str(k))
            mats["speeds"].append(_speed(speed_id))
            track["segments"].append(_segment(mid("segment", name, str(k)), audio_material(e), start, duration,
                                              volume=volume, extra_refs=[speed_id]))
        out_tracks.append(track)

    audio_track("vo", [(e, e["start"], e["duration"], 1.0) for e in tracks["vo"] if e["path"]])
    audio_track("sfx", [(e, e["start"], e["duration"], e["volume"]) for e in tracks["sfx"]])
    music = tracks["music"]
    if music:
        step = music["source_duration"] if music["source_duration"] > 0 else music["duration"]
        pieces, t = [], 0.0
        while t < music["duration"] - 1e-6:
            d = min(step, music["duration"] - t)
            pieces.append((music, round(t, 3), round(d, 3), music["volume"]))
            t += d
        audio_track("music", pieces)

    def text_track(name: str, cues: list[tuple[str, float, float]], size: float, y: float) -> None:
        if not cues:
            return
        track = _track(name, "text", mid("track", name))
        for k, (text, start, end) in enumerate(cues):
            material_id = mid("text", name, str(k))
            mats["texts"].append(_text_material(material_id, text, size))
            track["segments"].append(_segment(mid("segment", name, str(k)), material_id, start, end - start,
                                              transform_y=y, has_source=False))
        out_tracks.append(track)

    text_track("captions", [(c["text"], c["start"], c["end"]) for c in tracks["captions"]], CAPTION_SIZE, CAPTION_Y)
    if card and card["text"]:
        text_track("end_card", [(card["text"], card["start"], card["start"] + card["duration"])], END_CARD_SIZE, 0.0)

    draft["tracks"] = out_tracks
    meta = {
        "draft_cover": "", "draft_fold_path": str(draft_dir), "draft_id": draft["id"], "draft_name": draft_name,
        "draft_root_path": str(draft_dir.parent), "tm_draft_create": now_us, "tm_draft_modified": now_us,
        "tm_duration": draft["duration"],
    }
    return draft, meta


def write_draft(out_dir: Path, draft: dict[str, Any], meta: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "draft_content.json").write_text(json.dumps(draft, ensure_ascii=False))
    (out_dir / "draft_meta_info.json").write_text(json.dumps(meta, ensure_ascii=False))
