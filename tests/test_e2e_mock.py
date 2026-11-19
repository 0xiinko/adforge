"""Spec §10 mock end-to-end, engine half: manifest → parallel run → every
variant's timeline, preview and CapCut draft exist. Plan 2 extends this with
real assembly; plan 5 extends it back to the brief."""
import json

from engine.cli import main
from engine.core.ledger import Ledger


def test_mock_end_to_end(project_dir):
    assert main(["run", str(project_dir)]) == 0
    for rel in [
        "refs/product_hero.png",
        "v1/shots/s01/keyframe.png", "v1/shots/s02/clip.mp4", "v1/vo/l01.wav",
        "v1/timeline.json", "v1/preview.mp4", "v1/capcut_draft/draft_content.json",
        "v2/shots/s02/clip.mp4", "v2/timeline.json", "v2/preview.mp4", "v2/capcut_draft/draft_content.json",
    ]:
        assert (project_dir / rel).exists(), rel
    state = json.loads((project_dir / "state.json").read_text())["nodes"]
    assert len(state) == 17 and {s["status"] for s in state.values()} == {"done"}
    assert len(Ledger(project_dir / "ledger.jsonl").entries()) == 11
    assert main(["run", str(project_dir)]) == 0  # resumable / idempotent
