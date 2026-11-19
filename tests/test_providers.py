import asyncio
import json

import pytest

from engine.core.executors import cost_params, execute
from engine.core.graph import Node
from engine.core.ledger import Ledger
from engine.providers import build_providers
from engine.providers.base import CallContext, ProviderError
from engine.providers.mock import MockProvider
from engine.config import EngineConfig


def ctx(tmp_path, node_id="v1.s01.keyframe"):
    d = tmp_path / "work"
    d.mkdir(exist_ok=True)
    return CallContext(node_id=node_id, model="mock-x", work_dir=d)


def test_mock_image_returns_n_png_candidates(tmp_path):
    paths = asyncio.run(MockProvider().generate_image(ctx(tmp_path), "mug", [], "1024x1024", 2))
    assert len(paths) == 2
    assert all(p.read_bytes().startswith(b"\x89PNG") for p in paths)


def test_mock_video_stamps_its_parameters(tmp_path):
    p = asyncio.run(MockProvider().generate_video(ctx(tmp_path, "v1.s01.clip"), "push in", tmp_path / "k.png", None, 4.0, "9:16"))
    stamp = json.loads(p.read_bytes())
    assert stamp["node"] == "v1.s01.clip" and stamp["prompt"] == "push in" and stamp["duration"] == 4.0


def test_mock_capcut_draft_is_a_directory(tmp_path):
    p = asyncio.run(MockProvider().assemble(ctx(tmp_path, "v1.capcut_draft"), "capcut_draft", {"timeline": "t.json"}))
    assert p.is_dir() and (p / "draft_content.json").exists()


def test_mock_cost_only_for_generation(tmp_path):
    mock = MockProvider(cost_per_call=0.25)
    assert mock.cost("video", {}) == 0.25
    assert mock.cost("timeline", {}) == 0.0


def test_execute_image_picks_first_candidate(tmp_path):
    n = Node(id="v1.s01.keyframe", type="image", inputs={"refs": [], "n": 2}, depends_on=[], prompt="mug")
    out = asyncio.run(execute(n, MockProvider(), ctx(tmp_path), n.inputs))
    assert out.name == "candidate_0.png"


def test_execute_tts_requires_text(tmp_path):
    n = Node(id="v1.vo.l01", type="tts", inputs={}, depends_on=[])
    with pytest.raises(ProviderError, match="inputs.text"):
        asyncio.run(execute(n, MockProvider(), ctx(tmp_path, n.id), n.inputs))


def test_cost_params_merge_prompt_and_inputs():
    n = Node(id="v1.s01.clip", type="video", inputs={"duration": 4}, depends_on=[], prompt="p")
    assert cost_params(n, {"duration": 4}) == {"prompt": "p", "duration": 4}


def test_build_providers_has_mock():
    assert isinstance(build_providers(EngineConfig())["mock"], MockProvider)


def test_ledger_appends_and_totals(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    assert ledger.entries() == [] and ledger.total_cost() == 0
    ledger.record(node_id="a.b", provider="mock", model="m", cost_usd=0.5, seconds=1.0, attempt=1, ok=True)
    ledger.record(node_id="a.c", provider="mock", model="m", cost_usd=0.25, seconds=1.0, attempt=1, ok=False)
    entries = ledger.entries()
    assert [e["node_id"] for e in entries] == ["a.b", "a.c"]
    assert "ts" in entries[0]
    assert ledger.total_cost() == 0.75
