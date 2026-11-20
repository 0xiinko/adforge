"""Library API over one project folder. The CLI and (plan 6) the MCP server are thin layers on this."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from engine.config import EXTERNAL_TYPES, EngineConfig, load_config
from engine.core.cache import compute_fingerprints
from engine.core.executors import cost_params
from engine.core.graph import Manifest, ManifestError, Node, find_refs, load_manifest, resolve_refs, save_manifest
from engine.core.ledger import Ledger
from engine.core.paths import resolve_inputs
from engine.core.scheduler import RunReport, Scheduler
from engine.core.store import NodeState, ProjectStore
from engine.providers import build_providers
from engine.providers.base import Provider

REVISABLE = frozenset({"prompt", "inputs", "provider", "model", "depends_on"})


@dataclass
class PlannedNode:
    node_id: str
    provider: str
    model: str
    cost_usd: float
    provider_available: bool
    external: bool = False  # supplied by Claude via `adengine supply`; the engine never calls it


@dataclass
class DryRunReport:
    to_run: list[PlannedNode] = field(default_factory=list)
    cached: list[str] = field(default_factory=list)

    @property
    def total_cost(self) -> float:
        return sum(p.cost_usd for p in self.to_run)


class Project:
    def __init__(self, project_dir: Path, config: EngineConfig | None = None):
        self.dir = Path(project_dir)
        self.config = config or EngineConfig()
        self.manifest_path = self.dir / "manifest.json"

    @classmethod
    def open(cls, project_dir: Path, config_path: Path | None = None) -> "Project":
        project_dir = Path(project_dir)
        if config_path is None and (project_dir / "config.yaml").exists():
            config_path = project_dir / "config.yaml"
        return cls(project_dir, load_config(config_path))

    def manifest(self) -> Manifest:
        return load_manifest(self.manifest_path)

    def store(self) -> ProjectStore:
        return ProjectStore(self.dir)

    def ledger(self) -> Ledger:
        return Ledger(self.dir / "ledger.jsonl")

    def _providers(self, providers: dict[str, Provider] | None) -> dict[str, Provider]:
        return providers if providers is not None else build_providers(self.config)

    def external_errors(self, manifest: Manifest | None = None) -> list[str]:
        """Manifest problems that would leave external nodes impossible to supply."""
        manifest = manifest or self.manifest()
        routes = {nid: self.config.external_route(n) for nid, n in manifest.nodes.items()}
        errors: list[str] = []
        for nid in manifest.topo_order():
            route = routes[nid]
            if route is None:
                continue
            node = manifest.nodes[nid]
            if node.type not in EXTERNAL_TYPES:
                errors.append(f"{nid}: external provider {route.provider} can only render image or video nodes")
                continue
            for ref in dict.fromkeys(find_refs(node.inputs)):
                if routes.get(ref) is None:
                    errors.append(
                        f"{nid}: input @{ref} is rendered locally, but {route.provider} cannot read local "
                        f"files; route {ref} to {route.provider} too"
                    )
            if node.type == "image" and node.inputs.get("n", 1) != 1:
                errors.append(f"{nid}: external image nodes render one candidate; remove inputs.n or set it to 1")
        return errors

    def _check_external(self, manifest: Manifest) -> None:
        errors = self.external_errors(manifest)
        if errors:
            raise ManifestError(errors)

    async def run(self, targets: Iterable[str] | None = None, providers: dict[str, Provider] | None = None) -> RunReport:
        manifest = self.manifest()
        self._check_external(manifest)
        scheduler = Scheduler(manifest, self.store(), self.config, self._providers(providers), self.ledger())
        return await scheduler.run(targets)

    def dry_run(self, targets: Iterable[str] | None = None, providers: dict[str, Provider] | None = None) -> DryRunReport:
        manifest, store, provs = self.manifest(), self.store(), self._providers(providers)
        self._check_external(manifest)
        fps = compute_fingerprints(manifest, self.config, self.dir, store.pins())
        scope = manifest.scope(targets)
        order = [nid for nid in manifest.topo_order() if nid in scope]
        stale = store.stale_nodes(manifest, fps, order)
        report = DryRunReport()
        for nid in order:
            node = manifest.nodes[nid]
            if nid not in stale:
                report.cached.append(nid)
                continue
            route = self.config.route(node)
            if self.config.external_route(node) is not None:
                report.to_run.append(PlannedNode(nid, route.provider, route.model, 0.0, False, external=True))
                continue
            provider = provs.get(route.provider)
            cost = provider.cost(node.type, cost_params(node, resolve_inputs(manifest, self.dir, node))) if provider else 0.0
            report.to_run.append(PlannedNode(nid, route.provider, route.model, cost, provider is not None))
        return report

    def status(self) -> list[tuple[str, NodeState]]:
        store = self.store()
        return [(nid, store.nodes.get(nid, NodeState())) for nid in self.manifest().topo_order()]

    def external_nodes(self) -> list[dict[str, Any]]:
        """Nodes waiting for `adengine supply`, with everything needed to render them outside
        the engine. `external_inputs` swaps each @ref for the referenced node's provider-side
        ref (stored at supply), which is what an external provider can actually read."""
        manifest, store = self.manifest(), self.store()
        fps = compute_fingerprints(manifest, self.config, self.dir, store.pins())

        def external_ref(ref_id: str) -> str | None:
            ext = store.nodes[ref_id].external if ref_id in store.nodes else None
            return ext.get("ref") if ext else None

        out: list[dict[str, Any]] = []
        for nid in manifest.topo_order():
            st = store.nodes.get(nid)
            if st is None or st.status != "awaiting_external":
                continue
            if st.expected_fingerprint != fps[nid]:
                raise ValueError(f"{nid} changed since the last run; run adengine run first")
            node = manifest.nodes[nid]
            route = self.config.route(node)
            out.append({
                "id": nid,
                "type": node.type,
                "provider": route.provider,
                "model": route.model,
                "prompt": node.prompt,
                "inputs": resolve_inputs(manifest, self.dir, node),
                "external_inputs": resolve_refs(node.inputs, external_ref),
                "fingerprint": st.expected_fingerprint,
            })
        return out

    def revise(self, node_id: str, changes: dict[str, Any]) -> None:
        unknown = set(changes) - REVISABLE
        if unknown:
            raise ValueError(f"cannot revise fields: {sorted(unknown)} (allowed: {sorted(REVISABLE)})")
        data = self.manifest().to_dict()
        target = next((n for n in data["nodes"] if n["id"] == node_id), None)
        if target is None:
            raise KeyError(f"unknown node {node_id}")
        for key, value in changes.items():
            if key == "inputs":
                if not isinstance(value, dict):
                    raise ValueError("inputs change must be an object of input name -> value (null removes)")
                merged = dict(target.get("inputs", {}))
                for ik, iv in value.items():
                    if iv is None:
                        merged.pop(ik, None)
                    else:
                        merged[ik] = iv
                target["inputs"] = merged
            elif value is None:
                target.pop(key, None)
            else:
                target[key] = value
        manifest = Manifest.from_dict(data)  # validates; raises before anything is written
        self.store().unpin(node_id)  # before saving: a crash in between leaves it unpinned, never stale-pinned
        save_manifest(manifest, self.manifest_path)

    def rollback(self, node_id: str, version: int) -> int:
        manifest = self.manifest()
        if node_id not in manifest.nodes:
            raise KeyError(f"unknown node {node_id}")
        return self.store().rollback(manifest.nodes[node_id], version)
