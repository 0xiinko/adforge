import asyncio

import pytest

from engine.assembly.ffmpeg import FFmpeg
from engine.config import AssemblyConfig
from engine.providers.base import ProviderError


def test_missing_binary_is_a_provider_error():
    ff = FFmpeg(AssemblyConfig(ffmpeg="no-such-ffmpeg-binary", ffprobe="no-such-ffprobe-binary"))
    assert not ff.available()
    with pytest.raises(ProviderError, match="not found"):
        asyncio.run(ff.run(["-version"]))


def test_probe_audio(ffmpeg, tmp_path):
    asyncio.run(ffmpeg.run(["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1.5", "tone.wav"], cwd=tmp_path))
    info = asyncio.run(ffmpeg.probe(tmp_path / "tone.wav"))
    assert info.has_audio and not info.has_video
    assert info.duration == pytest.approx(1.5, abs=0.05)


def test_probe_video(ffmpeg, tmp_path):
    asyncio.run(ffmpeg.run([
        "-f", "lavfi", "-i", "color=c=red:s=64x36:r=24", "-t", "2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "clip.mp4",
    ], cwd=tmp_path))
    info = asyncio.run(ffmpeg.probe(tmp_path / "clip.mp4"))
    assert (info.width, info.height) == (64, 36)
    assert info.has_video and not info.has_audio
    assert info.duration == pytest.approx(2.0, abs=0.1)


def test_probe_image_dimensions(ffmpeg, tmp_path):
    asyncio.run(ffmpeg.run(["-f", "lavfi", "-i", "color=c=blue:s=64x112", "-frames:v", "1", "still.png"], cwd=tmp_path))
    info = asyncio.run(ffmpeg.probe(tmp_path / "still.png"))
    assert (info.width, info.height) == (64, 112)


def test_font_option_prefers_font_file():
    assert FFmpeg(AssemblyConfig(font="Inter", font_file=None)).font_option() == "font='Inter'"
    assert FFmpeg(AssemblyConfig(font="Helvetica", font_file="/System/Library/Fonts/Helvetica.ttc")).font_option() == (
        "fontfile='/System/Library/Fonts/Helvetica.ttc'"
    )


def test_ffmpeg_failure_reports_stderr(ffmpeg, tmp_path):
    with pytest.raises(ProviderError, match="ffmpeg failed"):
        asyncio.run(ffmpeg.run(["-i", "does-not-exist.mp4", "out.mp4"], cwd=tmp_path))


class _FakeProc:
    returncode = 0

    async def communicate(self):
        return b"{}", b""


def _capture_exec(monkeypatch):
    calls = []

    async def fake_exec(*args, **kwargs):
        calls.append((args, kwargs))
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return calls


def test_run_never_reads_stdin(monkeypatch, tmp_path):
    calls = _capture_exec(monkeypatch)
    ff = FFmpeg(AssemblyConfig(ffmpeg="ffmpeg-x", ffprobe="ffprobe-x"))
    asyncio.run(ff.run(["-i", "a.wav", "b.wav"]))
    asyncio.run(ff.probe(tmp_path / "a.wav"))
    (run_args, run_kwargs), (_, probe_kwargs) = calls
    assert run_args[:2] == ("ffmpeg-x", "-nostdin")
    assert run_kwargs["stdin"] == asyncio.subprocess.DEVNULL
    assert probe_kwargs["stdin"] == asyncio.subprocess.DEVNULL
