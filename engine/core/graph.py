"""Manifest model: loading, validation, reference handling, graph queries."""
from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable

import jsonschema

from engine.core.jsonio import write_json_atomic

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "manifest.schema.json"


class ManifestError(ValueError):
    """Manifest failed schema or graph validation. `.errors` lists every problem."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@lru_cache(maxsize=1)
def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def find_refs(value: Any) -> list[str]:
    """All `@id` references inside a nested inputs value, in order."""
    if isinstance(value, str):
        return [value[1:]] if value.startswith("@") else []
    if isinstance(value, list):
        return [r for item in value for r in find_refs(item)]
    if isinstance(value, dict):
        return [r for item in value.values() for r in find_refs(item)]
    return []


def resolve_refs(value: Any, lookup: Callable[[str], str]) -> Any:
    """Copy of `value` with every `@id` string replaced by `lookup(id)`."""
    if isinstance(value, str):
        return lookup(value[1:]) if value.startswith("@") else value
    if isinstance(value, list):
        return [resolve_refs(item, lookup) for item in value]
    if isinstance(value, dict):
        return {k: resolve_refs(v, lookup) for k, v in value.items()}
    return value


def _topo(order: list[str], deps: dict[str, list[str]]) -> list[str]:
    """Stable topological sort (manifest order breaks ties).
    Returns fewer ids than given when there is a cycle."""
    done: set[str] = set()
    result: list[str] = []
    progressed = True
    while progressed:
        progressed = False
        for nid in order:
            if nid not in done and set(deps[nid]) <= done:
                result.append(nid)
                done.add(nid)
                progressed = True
    return result


def validate_dict(data: Any) -> None:
    """Raise ManifestError listing every schema and graph problem."""
    validator = jsonschema.Draft202012Validator(_schema())
    errors = [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in validator.iter_errors(data)
    ]
    if errors:
        raise ManifestError(errors)

    ids: list[str] = []
    seen: set[str] = set()
    for n in data["nodes"]:
        if n["id"] in seen:
            errors.append(f"duplicate node id: {n['id']}")
        seen.add(n["id"])
        ids.append(n["id"])

    for n in data["nodes"]:
        deps = set(n["depends_on"])
        if n["id"] in deps:
            errors.append(f"{n['id']}: depends on itself")
        for dep in n["depends_on"]:
            if dep not in seen:
                errors.append(f"{n['id']}: depends_on unknown node {dep}")
        for ref in find_refs(n["inputs"]):
            if ref not in deps:
                errors.append(f"{n['id']}: input references @{ref} but it is not in depends_on")
    if errors:
        raise ManifestError(errors)

    unique = list(dict.fromkeys(ids))
    sorted_ids = _topo(unique, {n["id"]: n["depends_on"] for n in data["nodes"]})
    if len(sorted_ids) < len(unique):
        stuck = [i for i in unique if i not in set(sorted_ids)]
        raise ManifestError([f"dependency cycle among: {', '.join(stuck)}"])


@dataclass
class Node:
    id: str
    type: str
    inputs: dict[str, Any]
    depends_on: list[str]
    provider: str | None = None
    model: str | None = None
    prompt: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Node":
        return cls(
            id=d["id"],
            type=d["type"],
            inputs=dict(d.get("inputs", {})),
            depends_on=list(d.get("depends_on", [])),
            provider=d.get("provider"),
            model=d.get("model"),
            prompt=d.get("prompt"),
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"id": self.id, "type": self.type}
        for key in ("provider", "model", "prompt"):
            value = getattr(self, key)
            if value is not None:
                d[key] = value
        d["inputs"] = self.inputs
        d["depends_on"] = self.depends_on
        return d


@dataclass
class Manifest:
    project: str
    nodes: dict[str, Node]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Manifest":
        validate_dict(data)
        return cls(
            project=data["project"],
            nodes={n["id"]: Node.from_dict(n) for n in data["nodes"]},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": 1,
            "project": self.project,
            "nodes": [n.to_dict() for n in self.nodes.values()],
        }

    def topo_order(self) -> list[str]:
        return _topo(list(self.nodes), {nid: n.depends_on for nid, n in self.nodes.items()})

    def dependents(self, node_id: str) -> list[str]:
        return [nid for nid, n in self.nodes.items() if node_id in n.depends_on]

    def descendants(self, ids: Iterable[str]) -> set[str]:
        result: set[str] = set()
        stack = list(ids)
        while stack:
            for child in self.dependents(stack.pop()):
                if child not in result:
                    result.add(child)
                    stack.append(child)
        return result

    def ancestors(self, ids: Iterable[str]) -> set[str]:
        result: set[str] = set()
        stack = list(ids)
        while stack:
            for parent in self.nodes[stack.pop()].depends_on:
                if parent not in result:
                    result.add(parent)
                    stack.append(parent)
        return result

    def match(self, patterns: Iterable[str]) -> set[str]:
        pats = list(patterns)
        return {nid for nid in self.nodes if any(fnmatch.fnmatchcase(nid, p) for p in pats)}

    def scope(self, targets: Iterable[str] | None) -> set[str]:
        """Nodes a run must consider: targets (glob patterns) plus all their ancestors.
        None or empty means the whole manifest."""
        pats = list(targets) if targets is not None else []
        if not pats:
            return set(self.nodes)
        matched = self.match(pats)
        if not matched:
            raise ValueError(f"no nodes match {pats}")
        return matched | self.ancestors(matched)


def load_manifest(path: Path) -> Manifest:
    return Manifest.from_dict(json.loads(Path(path).read_text()))


def save_manifest(manifest: Manifest, path: Path) -> None:
    write_json_atomic(Path(path), manifest.to_dict())
