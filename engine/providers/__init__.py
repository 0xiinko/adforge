from engine.config import EngineConfig
from engine.providers.base import Provider
from engine.providers.mock import MockProvider


def build_providers(config: EngineConfig) -> dict[str, Provider]:
    """Provider instances keyed by the name used in routing. Plan 3 adds real providers."""
    return {"mock": MockProvider()}
