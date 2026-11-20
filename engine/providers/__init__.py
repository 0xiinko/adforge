from engine.config import EngineConfig
from engine.providers.base import Provider
from engine.providers.mock import MockProvider


def build_providers(config: EngineConfig) -> dict[str, Provider]:
    """Provider instances keyed by the name used in routing. Plan 3 adds real providers."""
    # Imported here: engine.assembly.ffmpeg imports engine.providers.base, so importing
    # it at package level would be circular.
    from engine.assembly.ffmpeg import FFmpeg
    from engine.providers.assembly import AssemblyProvider
    from engine.providers.mock_media import MediaMockProvider

    ff = FFmpeg(config.assembly)
    return {
        "mock": MockProvider(),
        "mock_media": MediaMockProvider(ff),
        "assembly": AssemblyProvider(ff, config.capcut),
    }
