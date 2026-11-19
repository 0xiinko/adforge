"""Engine configuration: provider routing, concurrency caps, retry policy.
Model names live in config, never in engine code."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engine.core.graph import Node

NODE_TYPES: tuple[str, ...] = (
    "image", "video", "tts", "sfx", "music", "timeline", "preview", "capcut_draft",
)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Route:
    provider: str
    model: str


@dataclass
class RetryConfig:
    max_attempts: int = 3
    base_delay_s: float = 1.0
    max_delay_s: float = 30.0


def _default_routing() -> dict[str, Route]:
    return {t: Route("mock", f"mock-{t}") for t in NODE_TYPES}


@dataclass
class EngineConfig:
    routing: dict[str, Route] = field(default_factory=_default_routing)
    concurrency: dict[str, int] = field(default_factory=dict)
    default_concurrency: int = 4
    retry: RetryConfig = field(default_factory=RetryConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "EngineConfig":
        data = data or {}
        cfg = cls()
        for node_type, route in (data.get("routing") or {}).items():
            if node_type not in NODE_TYPES:
                raise ConfigError(f"routing: unknown node type {node_type!r}")
            try:
                cfg.routing[node_type] = Route(provider=str(route["provider"]), model=str(route["model"]))
            except (KeyError, TypeError):
                raise ConfigError(f"routing.{node_type} needs 'provider' and 'model'") from None
        cfg.concurrency = {str(k): int(v) for k, v in (data.get("concurrency") or {}).items()}
        cfg.default_concurrency = int(data.get("default_concurrency", cfg.default_concurrency))
        retry = data.get("retry") or {}
        cfg.retry = RetryConfig(
            max_attempts=int(retry.get("max_attempts", 3)),
            base_delay_s=float(retry.get("base_delay_s", 1.0)),
            max_delay_s=float(retry.get("max_delay_s", 30.0)),
        )
        if cfg.retry.max_attempts < 1:
            raise ConfigError("retry.max_attempts must be >= 1")
        if any(v < 1 for v in [*cfg.concurrency.values(), cfg.default_concurrency]):
            raise ConfigError("concurrency limits must be >= 1")
        return cfg

    def route(self, node: Node) -> Route:
        """Node-level provider/model override the per-type default. A node that names a
        different provider must also name its model, since we never guess model names."""
        default = self.routing[node.type]
        provider = node.provider or default.provider
        if node.model:
            return Route(provider, node.model)
        if provider != default.provider:
            raise ConfigError(
                f"{node.id}: provider {provider!r} is set without a model and is not the "
                f"routing default for {node.type}"
            )
        return Route(provider, default.model)

    def limit(self, provider: str) -> int:
        return self.concurrency.get(provider, self.default_concurrency)


def load_config(path: Path | None) -> EngineConfig:
    if path is None:
        return EngineConfig()
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    return EngineConfig.from_dict(yaml.safe_load(path.read_text()))
