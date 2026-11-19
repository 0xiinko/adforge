import json

import pytest

from tests.helpers import make_manifest


@pytest.fixture
def project_dir(tmp_path):
    d = tmp_path / "mug-launch"
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps(make_manifest(), indent=2))
    return d
