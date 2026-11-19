"""Deterministic on-disk layout derived from node ids (spec §4)."""
from __future__ import annotations

import re
from pathlib import Path

from engine.core.graph import Manifest, Node, resolve_refs

EXTENSIONS: dict[str, str] = {
    "image": ".png",
    "video": ".mp4",
    "tts": ".wav",
    "sfx": ".wav",
    "music": ".mp3",
    "timeline": ".json",
    "preview": ".mp4",
    "capcut_draft": "",  # a directory
}

_SHOT_UNIT = re.compile(r"^s\d+$")


def output_path(project_dir: Path, node_id: str, node_type: str) -> Path:
    """refs.product_hero → refs/product_hero.png
    v2.s03.keyframe   → v2/shots/s03/keyframe.png
    v2.vo.l04         → v2/vo/l04.wav
    v2.timeline       → v2/timeline.json"""
    ext = EXTENSIONS[node_type]
    parts = node_id.split(".")
    if len(parts) == 2:
        scope, name = parts
        return project_dir / scope / f"{name}{ext}"
    scope, unit, kind = parts
    if _SHOT_UNIT.match(unit):
        return project_dir / scope / "shots" / unit / f"{kind}{ext}"
    return project_dir / scope / unit / f"{kind}{ext}"


def version_path(output: Path, node_id: str, version: int) -> Path:
    """Where an earlier output is archived: <dir>/versions/<node_id>_v<N><ext>."""
    return output.parent / "versions" / f"{node_id}_v{version}{output.suffix}"


def resolve_inputs(manifest: Manifest, project_dir: Path, node: Node, *, absolute: bool = True) -> dict:
    """Node inputs with every @ref replaced by the referenced node's output path.
    absolute=False gives project-relative paths (used for portable fingerprints)."""

    def lookup(ref_id: str) -> str:
        dep = manifest.nodes[ref_id]
        path = output_path(project_dir, dep.id, dep.type)
        return str(path if absolute else path.relative_to(project_dir))

    return resolve_refs(node.inputs, lookup)
