import pytest

from engine.config import ConfigError, EngineConfig, Route, load_config
from engine.core.graph import Node


def _node(**kw):
    return Node(id="v1.s01.clip", type="video", inputs={}, depends_on=[], **kw)


def test_defaults_route_everything_to_mock():
    cfg = EngineConfig()
    assert cfg.route(_node()) == Route("mock", "mock-video")
    assert cfg.limit("anything") == 4
    assert cfg.retry.max_attempts == 3


def test_from_dict_overrides_routing_limits_and_retry():
    cfg = EngineConfig.from_dict({
        "routing": {"video": {"provider": "seedance", "model": "seedance-x"}},
        "concurrency": {"seedance": 2},
        "retry": {"max_attempts": 5, "base_delay_s": 0},
    })
    assert cfg.route(_node()) == Route("seedance", "seedance-x")
    assert cfg.route(Node(id="refs.a", type="image", inputs={}, depends_on=[])) == Route("mock", "mock-image")
    assert cfg.limit("seedance") == 2
    assert cfg.retry.max_attempts == 5 and cfg.retry.base_delay_s == 0


def test_node_level_provider_and_model_override():
    cfg = EngineConfig()
    assert cfg.route(_node(provider="higgsfield", model="hf-1")) == Route("higgsfield", "hf-1")
    assert cfg.route(_node(model="mock-video-2")) == Route("mock", "mock-video-2")


def test_node_provider_without_model_is_an_error():
    with pytest.raises(ConfigError, match="v1.s01.clip"):
        EngineConfig().route(_node(provider="higgsfield"))


def test_unknown_routing_type_rejected():
    with pytest.raises(ConfigError, match="gif"):
        EngineConfig.from_dict({"routing": {"gif": {"provider": "x", "model": "y"}}})


def test_invalid_retry_rejected():
    with pytest.raises(ConfigError):
        EngineConfig.from_dict({"retry": {"max_attempts": 0}})


def test_load_config(tmp_path):
    assert load_config(None).route(_node()) == Route("mock", "mock-video")
    path = tmp_path / "config.yaml"
    path.write_text("routing:\n  video: {provider: seedance, model: seedance-x}\n")
    assert load_config(path).route(_node()) == Route("seedance", "seedance-x")
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.yaml")
