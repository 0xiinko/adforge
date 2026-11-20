"""ffmpeg preview renderer (spec §7): timeline.json → preview.mp4 with cuts and
crossfades, mixed VO/SFX, ducked music, burned-in captions and an end card.

Rendering is several small ffmpeg calls inside the node's work dir, using relative
file names. User text reaches ffmpeg only via files (drawtext textfile=, .ass)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.assembly.ffmpeg import FFmpeg

SLATE_COLOR = "0x1e1e1e"
END_CARD_COLOR = "0x000000"
AUDIO_FORMAT = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
X264_FAST = ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]


def _fit(width: int, height: int) -> str:
    return f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1"


def drawtext(font_option: str, textfile: str, size: int) -> str:
    return (f"drawtext={font_option}:textfile={textfile}:expansion=none:fontcolor=white:fontsize={size}"
            f":borderw={max(2, size // 12)}:bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2")


def ass_time(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def ass_text(text: str) -> str:
    return text.replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def captions_ass(captions: list[dict[str, Any]], width: int, height: int, font: str) -> str:
    size = height // 22
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{font},{size},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,"
        f"{max(2, size // 12)},0,2,60,60,{int(height * 0.18)},1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    lines += [
        f"Dialogue: 0,{ass_time(c['start'])},{ass_time(c['end'])},Default,,0,0,0,,{ass_text(c['text'])}"
        for c in captions
    ]
    return "\n".join(lines) + "\n"


def build_concat_filter(lengths: list[float], transitions: list[tuple[str, float]], fps: int) -> tuple[str, str]:
    """Join inputs 0..n-1. lengths[k] already includes the crossfade overlap into input
    k+1. transitions[k] is (kind, seconds) joining input k-1 to k; transitions[0] is unused."""
    parts = [f"[{k}:v]fps={fps},settb=AVTB,setpts=PTS-STARTPTS[s{k}]" for k in range(len(lengths))]
    acc, acc_len = "[s0]", lengths[0]
    for k in range(1, len(lengths)):
        kind, seconds = transitions[k]
        label = f"[v{k}]"
        if kind == "crossfade":
            parts.append(f"{acc}[s{k}]xfade=transition=fade:duration={seconds:.3f}:offset={acc_len - seconds:.3f}{label}")
            acc_len += lengths[k] - seconds
        else:
            parts.append(f"{acc}[s{k}]concat=n=2:v=1:a=0{label}")
            acc_len += lengths[k]
        acc = label
    return ";".join(parts), acc


async def render_slate_image(ff: FFmpeg, work_dir: Path, name: str, width: int, height: int, text: str) -> Path:
    label = f"{Path(name).stem}.txt"
    (work_dir / label).write_text(text)
    await ff.run([
        "-f", "lavfi", "-i", f"color=c={SLATE_COLOR}:s={width}x{height}", "-frames:v", "1",
        "-vf", drawtext(ff.font_option(), label, height // 24), name,
    ], cwd=work_dir)
    return work_dir / name


async def _segment(ff: FFmpeg, entry: dict, length: float, project_dir: Path, work_dir: Path,
                   name: str, width: int, height: int, fps: int, index: int) -> None:
    out = ["-t", f"{length:.3f}", "-r", str(fps), *X264_FAST, "-an", name]
    if entry["kind"] == "video":
        vf = (f"{_fit(width, height)},fps={fps},tpad=stop_mode=clone:stop_duration={length:.3f},"
              f"trim=duration={length:.3f},setpts=PTS-STARTPTS")
        await ff.run(["-i", str(project_dir / entry["path"]), "-vf", vf, *out], cwd=work_dir)
    elif entry["kind"] == "image":
        frames = max(1, round(length * fps))
        vf = (f"{_fit(2 * width, 2 * height)},zoompan=z='min(zoom+0.0006,1.12)'"
              f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps={fps},setsar=1")
        await ff.run(["-i", str(project_dir / entry["path"]), "-vf", vf, *out], cwd=work_dir)
    else:
        slate = await render_slate_image(ff, work_dir, f"slate_{index:02d}.png", width, height,
                                         f"MISSING\n{entry['placeholder_for']}")
        await ff.run(["-loop", "1", "-i", slate.name, "-vf", f"fps={fps},setsar=1", *out], cwd=work_dir)


async def _end_card(ff: FFmpeg, card: dict, project_dir: Path, work_dir: Path, width: int, height: int, fps: int) -> str:
    if card["path"]:
        source = ["-loop", "1", "-i", str(project_dir / card["path"])]
        filters = [_fit(width, height)]
    else:
        source = ["-f", "lavfi", "-i", f"color=c={END_CARD_COLOR}:s={width}x{height}"]
        filters = ["setsar=1"]
    if card["text"]:
        (work_dir / "end_card.txt").write_text(card["text"])
        filters.append(drawtext(ff.font_option(), "end_card.txt", height // 14))
    filters.append(f"fps={fps}")
    await ff.run([*source, "-vf", ",".join(filters), "-t", f"{card['duration']:.3f}", "-r", str(fps),
                  *X264_FAST, "-an", "seg_end.mp4"], cwd=work_dir)
    return "seg_end.mp4"


async def _mix_audio(ff: FFmpeg, tracks: dict, project_dir: Path, work_dir: Path, total: float, name: str) -> None:
    args: list[str] = []
    filters: list[str] = []
    count = 0

    def add(path: str, loop: bool = False) -> int:
        nonlocal count
        if loop:
            args.extend(["-stream_loop", "-1"])
        args.extend(["-i", str(project_dir / path)])
        count += 1
        return count - 1

    vo_labels: list[str] = []
    for k, entry in enumerate(e for e in tracks["vo"] if e["path"]):
        i, ms = add(entry["path"]), round(entry["start"] * 1000)
        filters.append(f"[{i}:a]{AUDIO_FORMAT},adelay={ms}|{ms}[vo{k}]")
        vo_labels.append(f"[vo{k}]")
    if len(vo_labels) > 1:
        filters.append(f"{''.join(vo_labels)}amix=inputs={len(vo_labels)}:normalize=0[vo]")
    elif vo_labels:
        filters.append(f"{vo_labels[0]}anull[vo]")

    buses: list[str] = []
    music = tracks["music"]
    if music:
        i = add(music["path"], loop=True)
        filters.append(f"[{i}:a]{AUDIO_FORMAT},atrim=0:{total:.3f},volume={music['volume']}[mus]")
        if music["duck"] and vo_labels:
            filters.append("[vo]asplit=2[vomix][vokey]")
            filters.append("[mus][vokey]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[musd]")
            buses += ["[vomix]", "[musd]"]
        else:
            buses.append("[mus]")
            if vo_labels:
                buses.append("[vo]")
    elif vo_labels:
        buses.append("[vo]")
    for k, entry in enumerate(tracks["sfx"]):
        i, ms = add(entry["path"]), round(entry["start"] * 1000)
        filters.append(f"[{i}:a]{AUDIO_FORMAT},volume={entry['volume']},adelay={ms}|{ms}[fx{k}]")
        buses.append(f"[fx{k}]")

    if not buses:
        await ff.run(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{total:.3f}", name], cwd=work_dir)
        return
    head = f"{''.join(buses)}amix=inputs={len(buses)}:normalize=0," if len(buses) > 1 else buses[0]
    filters.append(f"{head}apad,atrim=0:{total:.3f}[out]")
    await ff.run([*args, "-filter_complex", ";".join(filters), "-map", "[out]", "-ac", "2", "-ar", "48000", name],
                 cwd=work_dir)


async def render_preview(timeline: dict[str, Any], project_dir: Path, work_dir: Path, ff: FFmpeg) -> Path:
    width, height, fps = timeline["width"], timeline["height"], timeline["fps"]
    tracks, total = timeline["tracks"], timeline["duration"]
    video = tracks["video"]
    names: list[str] = []
    lengths: list[float] = []
    transitions: list[tuple[str, float]] = []
    for i, entry in enumerate(video):
        overlap = video[i + 1]["transition_s"] if i + 1 < len(video) else 0.0
        length = entry["duration"] + overlap
        name = f"seg_{i:02d}.mp4"
        await _segment(ff, entry, length, project_dir, work_dir, name, width, height, fps, i)
        names.append(name)
        lengths.append(length)
        transitions.append((entry["transition"], entry["transition_s"]))
    if tracks["end_card"]:
        names.append(await _end_card(ff, tracks["end_card"], project_dir, work_dir, width, height, fps))
        lengths.append(tracks["end_card"]["duration"])
        transitions.append(("cut", 0.0))

    graph, label = build_concat_filter(lengths, transitions, fps)
    inputs = [arg for name in names for arg in ("-i", name)]
    await ff.run([*inputs, "-filter_complex", graph, "-map", label, *X264_FAST, "video.mp4"], cwd=work_dir)
    await _mix_audio(ff, tracks, project_dir, work_dir, total, "mix.wav")

    final = ["-i", "video.mp4", "-i", "mix.wav"]
    if tracks["captions"]:
        (work_dir / "captions.ass").write_text(captions_ass(tracks["captions"], width, height, ff.font))
        final += ["-vf", "subtitles=captions.ass"]
    final += ["-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "preview.mp4"]
    await ff.run(final, cwd=work_dir)
    return work_dir / "preview.mp4"
