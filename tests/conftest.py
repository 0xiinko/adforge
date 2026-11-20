import json

import pytest

from engine.assembly.ffmpeg import FFmpeg
from tests.helpers import make_manifest


@pytest.fixture
def project_dir(tmp_path):
    d = tmp_path / "mug-launch"
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps(make_manifest(), indent=2))
    return d


@pytest.fixture
def ffmpeg():
    ff = FFmpeg()
    if not ff.available():
        pytest.skip("ffmpeg/ffprobe not installed (sudo apt install ffmpeg)")
    return ff
