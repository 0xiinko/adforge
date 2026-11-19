"""Node fingerprints (spec §4). A node is fresh when its stored fingerprint
matches and its output exists. Dependency fingerprints are hashed in, so any
change invalidates exactly the node and its descendants."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from engine.config import EngineConfig, Route
from engine.core.graph import Manifest, Node
from engine.core.paths import resolve_inputs


def _sha256(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def node_fingerprint(node: Node, route: Route, resolved_inputs: dict, dep_fps: dict[str, str]) -> str:
    return _sha256({
        "type": node.type,
        "provider": route.provider,
        "model": route.model,
        "prompt": node.prompt,
        "inputs": resolved_inputs,
        "deps": {d: dep_fps[d] for d in sorted(node.depends_on)},
    })


def pinned_fingerprint(node_id: str, version: int) -> str:
    """Fingerprint of a node restored by rollback. It stays fresh until revised,
    and it differs from the normal fingerprint so dependents rebuild."""
    return _sha256({"pinned": node_id, "version": version})


def compute_fingerprints(
    manifest: Manifest, config: EngineConfig, project_dir: Path, pins: dict[str, int]
) -> dict[str, str]:
    fps: dict[str, str] = {}
    for nid in manifest.topo_order():
        node = manifest.nodes[nid]
        if nid in pins:
            fps[nid] = pinned_fingerprint(nid, pins[nid])
            continue
        resolved = resolve_inputs(manifest, project_dir, node, absolute=False)
        fps[nid] = node_fingerprint(node, config.route(node), resolved, fps)
    return fps
