import asyncio

import pytest

from engine.assembly.ffmpeg_preview import ass_text, ass_time, build_concat_filter, captions_ass, render_preview
from engine.assembly.timeline import build_timeline


def test_concat_filter_offsets_put_each_shot_at_its_start():
    graph, label = build_concat_filter([3.25, 2.5, 1.5], [("cut", 0.0), ("crossfade", 0.25), ("cut", 0.0)], 30)
    assert graph.split(";") == [
        "[0:v]fps=30,settb=AVTB,setpts=PTS-STARTPTS[s0]",
        "[1:v]fps=30,settb=AVTB,setpts=PTS-STARTPTS[s1]",
        "[2:v]fps=30,settb=AVTB,setpts=PTS-STARTPTS[s2]",
        "[s0][s1]xfade=transition=fade:duration=0.250:offset=3.000[v1]",
        "[v1][s2]concat=n=2:v=1:a=0[v2]",
    ]
    assert label == "[v2]"
    assert build_concat_filter([2.0], [("cut", 0.0)], 24) == ("[0:v]fps=24,settb=AVTB,setpts=PTS-STARTPTS[s0]", "[s0]")


def test_ass_helpers():
    assert ass_time(3725.456) == "1:02:05.46"
    assert ass_time(0.2) == "0:00:00.20"
    assert ass_text("a {b}\nc") == "a \\{b\\}\\Nc"
    assert ass_text("a\\b") == "a＼b"
    doc = captions_ass([{"start": 0.2, "end": 1.325, "text": "Fresh coffee every"}], 1080, 1920, "DejaVu Sans")
    assert "PlayResX: 1080" in doc and "PlayResY: 1920" in doc
    assert "Style: Default,DejaVu Sans,87," in doc
    assert doc.rstrip().endswith("Dialogue: 0,0:00:00.20,0:00:01.32,Default,,0,0,0,,Fresh coffee every")


async def _make(ff, project, rel, args):
    path = project / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    await ff.run([*args, str(path)])
    return str(path)


def _tone(seconds, freq=440):
    return ["-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={seconds}"]


def _clip(seconds, color="red"):
    return ["-f", "lavfi", "-i", f"color=c={color}:s=320x240:r=24", "-t", str(seconds),
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]


STILL = ["-f", "lavfi", "-i", "color=c=blue:s=320x240", "-frames:v", "1"]


async def _probe_all(ff, paths):
    return {p: (0.0 if p.endswith(".png") else (await ff.probe(p)).duration) for p in paths}


def test_full_preview_matches_timeline(ffmpeg, tmp_path):
    async def scenario():
        project = tmp_path / "proj"
        files = {
            "c1": await _make(ffmpeg, project, "v1/shots/s01/clip.mp4", _clip(1.5)),
            "c2": await _make(ffmpeg, project, "v1/shots/s02/clip.mp4", _clip(0.8, "green")),
            "vo": await _make(ffmpeg, project, "v1/vo/l01.wav", _tone(1.0, 220)),
            "fx": await _make(ffmpeg, project, "v1/sfx/hit.wav", _tone(0.3, 880)),
            "bed": await _make(ffmpeg, project, "shared/music/bed.wav", _tone(3.0, 110)),
        }
        sources = {files["c1"]: "v1.s01.clip", files["c2"]: "v1.s02.clip", files["vo"]: "v1.vo.l01",
                   files["fx"]: "v1.sfx.hit", files["bed"]: "shared.music.bed"}
        inputs = {
            "aspect": "1:1",
            "shots": [{"clip": files["c1"], "duration": 1.5},
                      {"clip": files["c2"], "duration": 1.2, "transition": "crossfade"}],
            "vo": [{"audio": files["vo"], "text": "Fresh coffee {daily}"}],
            "sfx": [{"audio": files["fx"], "start": 1.4}],
            "music": {"audio": files["bed"], "volume": 0.3},
            "end_card": {"text": "Shop now: 20% off", "duration": 1.0},
        }
        timeline = build_timeline("v1.timeline", inputs, sources=sources, project_dir=project,
                                  media=await _probe_all(ffmpeg, list(sources)))
        work = tmp_path / "work"
        work.mkdir()
        out = await render_preview(timeline, project, work, ffmpeg)
        return timeline, await ffmpeg.probe(out)

    timeline, info = asyncio.run(scenario())
    assert timeline["duration"] == 3.7
    assert (info.width, info.height) == (1080, 1080)
    assert info.has_video and info.has_audio
    assert info.duration == pytest.approx(3.7, abs=0.15)


def test_placeholder_only_preview_without_audio(ffmpeg, tmp_path):
    async def scenario():
        project = tmp_path / "proj"
        kf = await _make(ffmpeg, project, "v1/shots/s01/keyframe.png", STILL)
        missing = str(project / "v1/shots/s01/clip.mp4")
        inputs = {
            "aspect": "1:1", "captions": False,
            "shots": [{"clip": missing, "duration": 1.0, "fallback": kf},
                      {"clip": str(project / "v1/shots/s02/clip.mp4"), "duration": 1.0}],
        }
        sources = {missing: "v1.s01.clip", kf: "v1.s01.keyframe",
                   str(project / "v1/shots/s02/clip.mp4"): "v1.s02.clip"}
        timeline = build_timeline("v1.timeline", inputs, sources=sources, project_dir=project, media={kf: 0.0})
        work = tmp_path / "work"
        work.mkdir()
        out = await render_preview(timeline, project, work, ffmpeg)
        return timeline, await ffmpeg.probe(out)

    timeline, info = asyncio.run(scenario())
    assert [e["kind"] for e in timeline["tracks"]["video"]] == ["image", "slate"]
    assert info.has_audio and (info.width, info.height) == (1080, 1080)
    assert info.duration == pytest.approx(2.0, abs=0.15)


async def _mean_volume(ff, path, start, length):
    proc = await asyncio.create_subprocess_exec(
        ff.ffmpeg, "-hide_banner", "-nostdin", "-ss", str(start), "-t", str(length), "-i", str(path),
        "-af", "volumedetect", "-f", "null", "-", stderr=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    for line in err.decode().splitlines():
        if "mean_volume:" in line:
            return float(line.split("mean_volume:")[1].split("dB")[0])
    raise AssertionError(err.decode()[-500:])


def test_ducked_music_stays_audible_after_vo_ends(ffmpeg, tmp_path):
    async def scenario():
        project = tmp_path / "proj"
        files = {
            "c1": await _make(ffmpeg, project, "v1/shots/s01/clip.mp4", _clip(4.0)),
            "vo": await _make(ffmpeg, project, "v1/vo/l01.wav", _tone(1.0, 220)),
            "bed": await _make(ffmpeg, project, "shared/music/bed.wav", _tone(1.0, 110)),
        }
        sources = {files["c1"]: "v1.s01.clip", files["vo"]: "v1.vo.l01", files["bed"]: "shared.music.bed"}
        inputs = {"aspect": "1:1", "captions": False,
                  "shots": [{"clip": files["c1"], "duration": 4.0}],
                  "vo": [{"audio": files["vo"], "text": "Hi"}],
                  "music": {"audio": files["bed"], "volume": 0.5}}
        timeline = build_timeline("v1.timeline", inputs, sources=sources, project_dir=project,
                                  media=await _probe_all(ffmpeg, list(sources)))
        work = tmp_path / "work"
        work.mkdir()
        out = await render_preview(timeline, project, work, ffmpeg)
        return await _mean_volume(ffmpeg, out, 2.0, 1.4)

    assert asyncio.run(scenario()) > -60


def test_concat_filter_clamps_crossfade_to_short_shot():
    graph, _ = build_concat_filter([1.25, 0.2, 1.0], [("cut", 0.0), ("crossfade", 0.25), ("cut", 0.0)], 30)
    parts = graph.split(";")
    assert "[s0][s1]xfade=transition=fade:duration=0.200:offset=1.000[v1]" in parts
    assert "[v1][s2]concat=n=2:v=1:a=0[v2]" in parts


def _clip_with_audio(seconds, color, freq):
    return ["-f", "lavfi", "-i", f"color=c={color}:s=320x240:r=24",
            "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000",
            "-t", str(seconds), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac"]


def _clip_audio_timeline_inputs(files, **extra):
    return {"aspect": "1:1", "captions": False,
            "shots": [{"clip": files["c1"], "duration": 1.5, "audio": True, "text": "Hello"},
                      {"clip": files["c2"], "duration": 1.2, "audio": True, "transition": "crossfade"}],
            "end_card": {"text": "Shop", "duration": 0.8}, **extra}


def test_clip_audio_alone_makes_a_full_length_mix(ffmpeg, tmp_path):
    async def scenario():
        project = tmp_path / "proj"
        files = {
            "c1": await _make(ffmpeg, project, "v1/shots/s01/clip.mp4", _clip_with_audio(1.5, "red", 330)),
            "c2": await _make(ffmpeg, project, "v1/shots/s02/clip.mp4", _clip_with_audio(1.2, "green", 660)),
        }
        sources = {files["c1"]: "v1.s01.clip", files["c2"]: "v1.s02.clip"}
        timeline = build_timeline("v1.timeline", _clip_audio_timeline_inputs(files), sources=sources,
                                  project_dir=project, media=await _probe_all(ffmpeg, list(sources)),
                                  audio_paths=frozenset(sources))
        work = tmp_path / "work"
        work.mkdir()
        out = await render_preview(timeline, project, work, ffmpeg)
        return timeline, await ffmpeg.probe(out), await _mean_volume(ffmpeg, out, 0.1, 1.2), \
            await _mean_volume(ffmpeg, work / "mix.wav", 2.8, 0.6)

    timeline, info, first_shot, end_card = asyncio.run(scenario())
    assert [e["audio"] for e in timeline["tracks"]["video"]] == [True, True]
    assert info.has_audio and first_shot > -60
    assert end_card < -80
    assert info.duration == pytest.approx(timeline["duration"], abs=0.15)


def test_music_ducks_under_clip_audio(ffmpeg, tmp_path):
    async def scenario():
        project = tmp_path / "proj"
        files = {
            "c1": await _make(ffmpeg, project, "v1/shots/s01/clip.mp4", _clip_with_audio(1.5, "red", 330)),
            "c2": await _make(ffmpeg, project, "v1/shots/s02/clip.mp4", _clip_with_audio(1.2, "green", 660)),
            "bed": await _make(ffmpeg, project, "shared/music/bed.wav", _tone(1.0, 110)),
        }
        sources = {files["c1"]: "v1.s01.clip", files["c2"]: "v1.s02.clip", files["bed"]: "shared.music.bed"}
        inputs = _clip_audio_timeline_inputs(files, music={"audio": files["bed"], "volume": 0.5})
        timeline = build_timeline("v1.timeline", inputs, sources=sources, project_dir=project,
                                  media=await _probe_all(ffmpeg, list(sources)), audio_paths=frozenset(sources))
        work = tmp_path / "work"
        work.mkdir()
        calls = []
        run = ffmpeg.run

        async def spy(args, **kw):
            calls.append(args)
            return await run(args, **kw)

        ffmpeg.run = spy
        out = await render_preview(timeline, project, work, ffmpeg)
        mix = next(a for a in calls if a[-1] == "mix.wav")
        graph = mix[mix.index("-filter_complex") + 1]
        return await ffmpeg.probe(out), await _mean_volume(ffmpeg, work / "mix.wav", 2.9, 0.5), graph

    info, after_clips, graph = asyncio.run(scenario())
    assert info.has_audio and info.duration == pytest.approx(3.5, abs=0.15)
    assert "sidechaincompress" in graph and "[ca0]" in graph and "[ca1]" in graph
    assert after_clips > -60   # the key is padded, so the ducked bed keeps playing after the clips end
