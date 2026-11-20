import pytest

from engine.config import (
    EXTERNAL_TYPES, AssemblyConfig, ConfigError, EngineConfig, Route, default_font, default_font_file, load_config,
)
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


def test_assembly_and_capcut_defaults():
    cfg = EngineConfig()
    assert (cfg.assembly.ffmpeg, cfg.assembly.ffprobe) == ("ffmpeg", "ffprobe")
    assert (cfg.assembly.font, cfg.assembly.font_file) == (default_font(), default_font_file())
    assert cfg.capcut.drafts_dir is None and cfg.capcut.media_root is None


def test_font_defaults_per_platform(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    assert (default_font(), default_font_file()) == ("Helvetica", "/System/Library/Fonts/Helvetica.ttc")
    monkeypatch.setattr("sys.platform", "linux")
    assert (default_font(), default_font_file()) == ("DejaVu Sans", None)
    assert AssemblyConfig().font == "DejaVu Sans"


def test_assembly_and_capcut_from_dict(tmp_path):
    cfg = EngineConfig.from_dict({
        "assembly": {"ffmpeg": "/opt/ff/ffmpeg", "font": "Inter"},
        "capcut": {"drafts_dir": str(tmp_path / "drafts"), "media_root": "C:/AdForge/projects/"},
    })
    assert (cfg.assembly.ffmpeg, cfg.assembly.ffprobe, cfg.assembly.font) == ("/opt/ff/ffmpeg", "ffprobe", "Inter")
    assert EngineConfig.from_dict({"assembly": {"font_file": "/fonts/Inter.ttf"}}).assembly.font_file == "/fonts/Inter.ttf"
    assert cfg.capcut.drafts_dir == tmp_path / "drafts"
    assert cfg.capcut.media_root == "C:/AdForge/projects"


def _ellora_cfg(**routing):
    return EngineConfig.from_dict({"external_providers": ["ellora"], "routing": routing})


def test_external_route_only_for_external_providers():
    cfg = _ellora_cfg(image={"provider": "ellora", "model": "img-1"})
    img = Node(id="refs.hero", type="image", inputs={}, depends_on=[])
    tts = Node(id="v1.vo.l01", type="tts", inputs={}, depends_on=[])
    assert cfg.external_providers == frozenset({"ellora"})
    assert cfg.external_route(img) == Route("ellora", "img-1")
    assert cfg.external_route(tts) is None


def test_external_route_none_when_routing_fails():
    cfg = _ellora_cfg()
    bad = Node(id="refs.hero", type="image", inputs={}, depends_on=[], provider="ellora")  # no model
    assert cfg.external_route(bad) is None


def test_external_provider_only_for_image_and_video():
    assert EXTERNAL_TYPES == frozenset({"image", "video"})
    with pytest.raises(ConfigError, match=r"routing\.tts"):
        _ellora_cfg(tts={"provider": "ellora", "model": "m"})


def test_external_providers_must_be_a_list_of_names():
    with pytest.raises(ConfigError, match="external_providers"):
        EngineConfig.from_dict({"external_providers": "ellora"})
    with pytest.raises(ConfigError, match="external_providers"):
        EngineConfig.from_dict({"external_providers": [""]})


def test_no_external_providers_by_default():
    assert EngineConfig().external_providers == frozenset()
