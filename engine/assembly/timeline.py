"""Editor-independent timeline (spec §7).

`build_timeline` is a pure function: a timeline node's resolved inputs plus the
durations of the input files that exist → the content of timeline.json. Missing
inputs (failed/blocked upstream nodes) become placeholders so preview and draft
are always complete (spec §8). Output paths are project-relative POSIX strings."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from engine.providers.base import ProviderError

TIMELINE_VERSION = 1
ASPECTS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "4:5": (1080, 1350),
}
TRANSITIONS = ("cut", "crossfade")
DEFAULT_FPS = 30
CROSSFADE_S = 0.25
VO_LEAD_IN_S = 0.2
VO_GAP_S = 0.15
WORDS_PER_CAPTION = 3
SECONDS_PER_WORD = 0.4
MIN_VO_S = 0.8
DEFAULT_MUSIC_VOLUME = 0.25
DEFAULT_END_CARD_S = 2.0
HOLD_TOLERANCE_S = 0.05
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})


class TimelineError(ProviderError):
    """Invalid timeline inputs: the timeline node fails with this message."""


def _r(x: float) -> float:
    return round(float(x), 3)


def media_paths(inputs: dict[str, Any]) -> list[str]:
    """Every input path the builder may look up in `media`, existing or not, in order."""
    paths: list[Any] = []
    shots = inputs.get("shots")
    if isinstance(shots, list):
        for shot in shots:
            if isinstance(shot, dict):
                paths += [shot.get("clip"), shot.get("fallback")]
    for key in ("vo", "sfx"):
        items = inputs.get(key)
        if isinstance(items, list):
            paths += [item.get("audio") for item in items if isinstance(item, dict)]
    for key, name in (("music", "audio"), ("end_card", "image")):
        if isinstance(inputs.get(key), dict):
            paths.append(inputs[key].get(name))
    return [p for p in paths if isinstance(p, str)]


def caption_chunks(text: str, start: float, duration: float, words_per_chunk: int = WORDS_PER_CAPTION) -> list[dict]:
    """Split a VO line into short caption cues, timed in proportion to their length.
    (Word-level timestamps from the TTS provider replace this estimate in plan 3.)"""
    words = text.split()
    if not words:
        return []
    chunks = [" ".join(words[i:i + words_per_chunk]) for i in range(0, len(words), words_per_chunk)]
    total = sum(len(c) for c in chunks)
    cues, t = [], start
    for chunk in chunks:
        d = duration * len(chunk) / total
        cues.append({"start": _r(t), "end": _r(t + d), "text": chunk})
        t += d
    return cues


def build_timeline(
    node_id: str,
    inputs: dict[str, Any],
    *,
    sources: dict[str, str],
    project_dir: Path,
    media: dict[str, float],
) -> dict[str, Any]:
    """`sources` maps input path → node id. `media` maps each input path that exists
    to its duration in seconds (0.0 for images)."""

    def err(msg: str) -> TimelineError:
        return TimelineError(f"{node_id}: {msg}")

    def number(value: Any, where: str, *, positive: bool) -> float:
        if isinstance(value, bool):
            raise err(f"{where} must be a number")
        try:
            x = float(value)
        except (TypeError, ValueError):
            raise err(f"{where} must be a number") from None
        if not math.isfinite(x):
            raise err(f"{where} must be a finite number")
        if x < 0 or (positive and x == 0):
            raise err(f"{where} must be {'> 0' if positive else '>= 0'}")
        return x

    def ref(item: Any, key: str, where: str) -> str:
        if not isinstance(item, dict) or not isinstance(item.get(key), str):
            raise err(f"{where}.{key} must be a reference")
        return item[key]

    def rel(path: str) -> str:
        try:
            return Path(path).relative_to(project_dir).as_posix()
        except ValueError:
            raise err(f"{path} is outside the project directory") from None

    def ident(path: str) -> str:
        return sources.get(path, path)

    aspect = inputs.get("aspect", "9:16")
    if not isinstance(aspect, str) or aspect not in ASPECTS:
        raise err(f"inputs.aspect must be one of {', '.join(ASPECTS)}")
    width, height = ASPECTS[aspect]
    fps = number(inputs.get("fps", DEFAULT_FPS), "inputs.fps", positive=True)
    if fps != int(fps):
        raise err("inputs.fps must be a whole number")
    fps = int(fps)
    shots = inputs.get("shots")
    if not isinstance(shots, list) or not shots:
        raise err("inputs.shots must be a non-empty list")

    placeholders: list[str] = []

    def add_placeholder(node: str) -> None:
        if node not in placeholders:
            placeholders.append(node)

    warnings: list[str] = []

    video: list[dict] = []
    t = 0.0
    for i, shot in enumerate(shots):
        where = f"inputs.shots[{i}]"
        clip = ref(shot, "clip", where)
        duration = number(shot.get("duration"), f"{where}.duration", positive=True)
        transition = shot.get("transition", "cut")
        if transition not in TRANSITIONS:
            raise err(f"{where}.transition must be one of {', '.join(TRANSITIONS)}")
        if i == 0:
            transition = "cut"
        entry = {
            "node": None, "path": None, "kind": "slate", "start": _r(t), "duration": _r(duration),
            "transition": transition, "transition_s": CROSSFADE_S if transition == "crossfade" else 0.0,
            "hold": False, "placeholder_for": None,
        }
        if clip in media:
            entry.update(node=ident(clip), path=rel(clip), kind="video",
                         hold=media[clip] + HOLD_TOLERANCE_S < duration)
        else:
            add_placeholder(ident(clip))
            entry["placeholder_for"] = ident(clip)
            fallback = shot.get("fallback")
            if isinstance(fallback, str) and fallback in media:
                entry.update(node=ident(fallback), path=rel(fallback), kind="image")
            elif isinstance(fallback, str):
                warnings.append(f"{ident(clip)} and its fallback {ident(fallback)} are both missing")
        video.append(entry)
        t += duration
    video_end = t

    vo: list[dict] = []
    captions: list[dict] = []
    want_captions = True if inputs.get("captions") is None else inputs["captions"]
    if not isinstance(want_captions, bool):
        raise err("inputs.captions must be true or false")
    cursor = VO_LEAD_IN_S
    vo_items = [] if inputs.get("vo") is None else inputs["vo"]
    if not isinstance(vo_items, list):
        raise err("inputs.vo must be a list")
    for i, line in enumerate(vo_items):
        where = f"inputs.vo[{i}]"
        audio = ref(line, "audio", where)
        text = "" if line.get("text") is None else str(line["text"])
        start = cursor if line.get("start") is None else number(line["start"], f"{where}.start", positive=False)
        if audio in media:
            duration, path = media[audio], rel(audio)
        else:
            duration, path = max(MIN_VO_S, SECONDS_PER_WORD * len(text.split())), None
            add_placeholder(ident(audio))
        vo.append({"node": ident(audio), "path": path, "start": _r(start), "duration": _r(duration), "text": text})
        if want_captions:
            captions += caption_chunks(text, start, duration)
        if start + duration > video_end + 1e-6:
            warnings.append(f"{ident(audio)} ends at {_r(start + duration)}s, after the last shot at {_r(video_end)}s")
        cursor = start + duration + VO_GAP_S

    sfx: list[dict] = []
    sfx_items = [] if inputs.get("sfx") is None else inputs["sfx"]
    if not isinstance(sfx_items, list):
        raise err("inputs.sfx must be a list")
    for i, fx in enumerate(sfx_items):
        where = f"inputs.sfx[{i}]"
        audio = ref(fx, "audio", where)
        start = number(fx.get("start"), f"{where}.start", positive=False)
        volume = number(fx.get("volume", 1.0), f"{where}.volume", positive=False)
        if audio in media:
            sfx.append({"node": ident(audio), "path": rel(audio), "start": _r(start),
                        "duration": _r(media[audio]), "volume": volume})
        else:
            add_placeholder(ident(audio))

    end_card = None
    card = inputs.get("end_card")
    if card is not None:
        if not isinstance(card, dict):
            raise err("inputs.end_card must be an object")
        duration = number(card.get("duration", DEFAULT_END_CARD_S), "inputs.end_card.duration", positive=True)
        end_card = {"node": None, "path": None, "start": _r(video_end), "duration": _r(duration),
                    "text": str(card.get("text", ""))}
        image = card.get("image")
        if isinstance(image, str):
            if image in media:
                end_card.update(node=ident(image), path=rel(image))
            else:
                add_placeholder(ident(image))
    total = video_end + (end_card["duration"] if end_card else 0.0)

    music = None
    bed = inputs.get("music")
    if bed is not None:
        audio = ref(bed, "audio", "inputs.music")
        volume = number(bed.get("volume", DEFAULT_MUSIC_VOLUME), "inputs.music.volume", positive=False)
        if audio in media:
            music = {"node": ident(audio), "path": rel(audio), "start": 0.0, "duration": _r(total),
                     "source_duration": _r(media[audio]), "volume": volume, "duck": bool(bed.get("duck", True))}
        else:
            add_placeholder(ident(audio))

    return {
        "version": TIMELINE_VERSION,
        "node": node_id,
        "width": width,
        "height": height,
        "fps": fps,
        "duration": _r(total),
        "tracks": {"video": video, "vo": vo, "sfx": sfx, "music": music, "captions": captions, "end_card": end_card},
        "placeholders": placeholders,
        "warnings": warnings,
    }
