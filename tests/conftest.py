import json

import pytest
import yaml

from engine.assembly.ffmpeg import FFmpeg
from tests.helpers import ELLORA_CONFIG, make_ellora_manifest, make_manifest


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


@pytest.fixture
def ellora_dir(tmp_path):
    d = tmp_path / "ellora-launch"
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps(make_ellora_manifest(), indent=2))
    (d / "config.yaml").write_text(yaml.safe_dump(ELLORA_CONFIG))
    return d
