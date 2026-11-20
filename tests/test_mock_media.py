import asyncio

import pytest

from engine.assembly.ffmpeg import FFmpeg
from engine.providers.base import CallContext, ProviderError
from engine.providers.mock_media import MediaMockProvider


def ctx(tmp_path, node_id):
    d = tmp_path / node_id
    d.mkdir()
    return CallContext(node_id=node_id, model="mock", work_dir=d)


def test_image_candidates_have_requested_size(ffmpeg, tmp_path):
    mock = MediaMockProvider(ffmpeg)
    paths = asyncio.run(mock.generate_image(ctx(tmp_path, "refs.hero"), "mug", [], "64x112", 2))
    assert [p.name for p in paths] == ["candidate_0.png", "candidate_1.png"]
    info = asyncio.run(ffmpeg.probe(paths[0]))
    assert (info.width, info.height) == (64, 112)


def test_video_matches_duration_and_aspect(ffmpeg, tmp_path):
    mock = MediaMockProvider(ffmpeg)
    still = asyncio.run(mock.generate_image(ctx(tmp_path, "v1.s01.keyframe"), "p", [], "64x112", 1))[0]
    clip = asyncio.run(mock.generate_video(ctx(tmp_path, "v1.s01.clip"), "push in", still, None, 2.0, "9:16"))
    info = asyncio.run(ffmpeg.probe(clip))
    assert (info.width, info.height) == (270, 480)
    assert info.duration == pytest.approx(2.0, abs=0.1)
    wide = asyncio.run(mock.generate_video(ctx(tmp_path, "v1.s02.clip"), "p", None, None, 1.0, "16:9"))
    assert asyncio.run(ffmpeg.probe(wide)).width == 480


def test_audio_durations(ffmpeg, tmp_path):
    mock = MediaMockProvider(ffmpeg)
    vo = asyncio.run(mock.tts(ctx(tmp_path, "v1.vo.l01"), "one two three four five", "narrator", "neutral"))
    fx = asyncio.run(mock.sfx(ctx(tmp_path, "v1.sfx.whoosh"), "whoosh", 0.5))
    bed = asyncio.run(mock.music(ctx(tmp_path, "shared.music.bed"), "lofi", 3.0))
    assert [p.name for p in (vo, fx, bed)] == ["vo.wav", "sfx.wav", "music.wav"]
    durations = [asyncio.run(ffmpeg.probe(p)).duration for p in (vo, fx, bed)]
    assert durations == pytest.approx([1.9, 0.5, 3.0], abs=0.05)


def test_bad_size_is_a_provider_error(tmp_path):
    mock = MediaMockProvider(FFmpeg())
    with pytest.raises(ProviderError, match="size"):
        asyncio.run(mock.generate_image(ctx(tmp_path, "refs.hero"), "p", [], "big", 1))
