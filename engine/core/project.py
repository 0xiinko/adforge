"""Library API over one project folder. The CLI and (plan 6) the MCP server are thin layers on this."""
from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from engine.assembly.ffmpeg import FFmpeg
from engine.config import EXTERNAL_TYPES, EngineConfig, Route, load_config
from engine.core.cache import compute_fingerprints
from engine.core.executors import cost_params
from engine.core.graph import Manifest, ManifestError, Node, find_refs, load_manifest, resolve_refs, save_manifest
from engine.core.ledger import Ledger
from engine.core.paths import EXTENSIONS, resolve_inputs
from engine.core.scheduler import RunReport, Scheduler
from engine.core.store import NodeState, ProjectStore
from engine.providers import build_providers
from engine.providers.base import Provider

REVISABLE = frozenset({"prompt", "inputs", "provider", "model", "depends_on"})
SUPPLY_SUFFIXES: dict[str, frozenset[str]] = {
    "image": frozenset({".png", ".jpg", ".jpeg", ".webp"}),
    "video": frozenset({".mp4"}),
}


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
        manifest = manifest if manifest is not None else self.manifest()
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

        def external_ref(nid: str, ref_id: str) -> str:
            ext = store.nodes[ref_id].external if ref_id in store.nodes else None
            ref = ext.get("ref") if ext else None
            if ref is None:
                raise ValueError(
                    f"{nid}: input @{ref_id} has no external ref; supply {ref_id} again (revise it or run adengine run)"
                )
            return ref

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
                "external_inputs": resolve_refs(node.inputs, lambda ref_id: external_ref(nid, ref_id)),
                "fingerprint": st.expected_fingerprint,
            })
        return out

    def _awaiting(self, node_id: str, store: ProjectStore) -> tuple[Node, Route, str]:
        """The awaiting external node, its route and its current fingerprint.
        Raises if the node cannot be supplied right now. Call with store.lock() held."""
        manifest = self.manifest()
        if node_id not in manifest.nodes:
            raise KeyError(f"unknown node {node_id}")
        node = manifest.nodes[node_id]
        route = self.config.external_route(node)
        if route is None:
            raise ValueError(f"{node_id} is not routed to an external provider")
        st = store.get(node_id)
        if st.status != "awaiting_external":
            raise ValueError(f"{node_id} is {st.status}, not awaiting_external; run adengine run first")
        current = compute_fingerprints(manifest, self.config, self.dir, store.pins())[node_id]
        if st.expected_fingerprint != current:
            raise ValueError(f"{node_id} changed since it was listed; run adengine run, then adengine external again")
        return node, route, current

    def supply(
        self, node_id: str, file: Path | str, *, ref: str,
        external_id: str | None = None, fingerprint: str | None = None,
    ) -> int:
        """Commit a file rendered outside the engine as the node's new version. Holds the
        state lock throughout, so parallel supplies of one node cannot both pass the check."""
        store = self.store()
        with store.lock():
            node, route, current = self._awaiting(node_id, store)
            if fingerprint is not None and fingerprint != current:
                raise ValueError(f"{node_id}: --fingerprint does not match the current fingerprint; list again with adengine external")
            src = Path(file)
            if not src.is_file():
                raise FileNotFoundError(f"{src} does not exist")
            allowed = SUPPLY_SUFFIXES[node.type]
            if src.suffix.lower() not in allowed:
                raise ValueError(f"{node_id}: {node.type} needs one of {sorted(allowed)}, got {src.name}")
            staged = store.work_dir(node_id) / f"supplied{EXTENSIONS[node.type]}"
            if node.type == "image" and src.suffix.lower() != ".png":
                asyncio.run(FFmpeg(self.config.assembly).run(["-i", str(src), "-frames:v", "1", str(staged)]))
            else:
                shutil.copy2(src, staged)
            ext = {"provider": route.provider, "ref": ref, "id": external_id}
            version = store.commit(node, staged, current, external=ext)
            self.ledger().record(
                node_id=node_id, provider=route.provider, model=route.model, cost_usd=0.0,
                seconds=0.0, attempt=1, ok=True, external_id=external_id,
            )
            return version

    def supply_failure(self, node_id: str, *, refused: bool, message: str) -> None:
        """Record that the external render failed or was refused. A refused node keeps its
        expected fingerprint, so runs hold it (and block dependents) until it is revised;
        a failed one is listed as awaiting again by the next run."""
        store = self.store()
        with store.lock():
            node, route, _ = self._awaiting(node_id, store)
            status, reason = ("needs_review", "refused") if refused else ("failed", "external")
            store.update(node_id, status=status, reason=reason, message=message)
            self.ledger().record(
                node_id=node_id, provider=route.provider, model=route.model, cost_usd=0.0,
                seconds=0.0, attempt=1, ok=False, external_id=None,
            )

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
