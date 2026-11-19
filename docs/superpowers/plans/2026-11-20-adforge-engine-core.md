# AdForge Engine Core Implementation Plan (Plan 1 of 6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the AdForge engine core: a validated `manifest.json` contract, a fingerprint-cached asyncio DAG scheduler with per-provider concurrency caps, versioned outputs with rollback, a cost ledger, a mock provider, and an `adengine` CLI. Together these render a whole multi-variant ad manifest end to end with zero API calls.

**Architecture:** The engine is a Python library (`engine/core`). The CLI is a thin layer on top, and so is the MCP server in a later plan. The brain (the Claude plugin, also a later plan) writes `projects/<slug>/manifest.json`. The engine validates it, computes a fingerprint per node, and runs every node whose fingerprint or output is stale, in dependency order, as soon as its dependencies finish. Each node is routed to a provider by config. Outputs land at deterministic paths derived from node IDs, and earlier outputs move to `versions/`.

**Tech Stack:** Python 3.11+ (3.12 on this machine), `uv` for env and packaging, `jsonschema`, `pyyaml`, `pytest`. No other runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-11-20-adforge-design.md`

**Plan series** (each plan produces working, tested software on its own):
1. **Engine core + mock providers (this plan).** Spec §4, §6 scheduler/routing/errors, §8, §11.1.
2. Assembly: timeline + ffmpeg preview + CapCut draft (§7). Upgrades the mock to emit real media. Needs `ffmpeg`, which is **not installed** on this machine yet.
3. Real providers: openai_image, seedance, fishaudio, then mcp_bridge plus fallback chains (§6 Providers).
4. QC vision judge (§6 Automatic QC).
5. Brain: plugin skeleton, `/ad`, skills, variant-writer subagent, gate UX (§5).
6. MCP server, cost estimation polish, budget enforcement (§6 Interfaces, §9).

## Global Constraints

- Python `>=3.11`. Packaged with `uv`. Runtime deps limited to `jsonschema` and `pyyaml`.
- The engine makes **no creative decisions** and **never rewrites prompts** (spec §3, §8).
- Model names are config values, never hard-coded in engine logic (`provider` + `model`). The only built-in names are the mock defaults `mock` / `mock-<type>`.
- Secrets come only from env / `.env` and are never written to manifests, state, or ledgers. This plan needs none.
- Node IDs: `<scope>.<unit>.<kind>` or `<scope>.<name>`, lowercase `[a-z0-9_]`, stable forever within a project.
- Node types are exactly: `image`, `video`, `tts`, `sfx`, `music`, `timeline`, `preview`, `capcut_draft`.
- Status values are exactly: `pending | running | done | failed | blocked | needs_review`.
- References: `@<id>` inside `inputs` resolves to that node's output path. `depends_on` must list every referenced ID.
- Fingerprint = `sha256(type, provider, model, prompt, resolved inputs, fingerprints of dependencies)`.
- Before overwriting, the previous output moves to `versions/<node_id>_v<N>.<ext>`.
- `state.json` is saved after every node status change. Re-running resumes.
- Temporary failures retry with exponential backoff. Refusals become `needs_review` with `reason: "refused"`. Hard failures become `failed` and their dependents `blocked`, while everything unrelated continues.
- **Deviation from spec, recorded deliberately:** run status and version live in `state.json` only. The engine never writes them back into `manifest.json`, so the brain's file is never rewritten underneath it. The schema still *allows* `status`/`version` in the manifest, and the engine ignores them.

---

## File Structure

```
adforge/
  pyproject.toml                    # package "engine", console script adengine
  .gitignore
  config.example.yaml               # routing, concurrency, retry
  schemas/manifest.schema.json      # the brain↔engine contract
  engine/
    __init__.py
    config.py                       # EngineConfig, Route, routing + limits
    cli.py                          # adengine validate|dry-run|estimate|run|status|revise|rollback
    core/
      __init__.py
      jsonio.py                     # atomic JSON write
      graph.py                      # Manifest/Node, validation, refs, topo, scope
      paths.py                      # node id → output path, version path, input resolution
      cache.py                      # fingerprints (incl. pinned-after-rollback)
      store.py                      # state.json, commit/versioning, rollback, work dirs
      ledger.py                     # ledger.jsonl
      executors.py                  # node type → provider method dispatch
      scheduler.py                  # asyncio DAG executor
      project.py                    # library API: run, dry_run, status, revise, rollback
    providers/
      __init__.py                   # build_providers(config)
      base.py                       # Provider base, errors, CallContext, type sets
      mock.py                       # MockProvider
  tests/
    __init__.py
    conftest.py                     # project_dir fixture
    helpers.py                      # make_manifest, node(), RecordingProvider, FAST
    test_graph.py  test_paths.py  test_config.py  test_cache.py  test_store.py
    test_providers.py  test_scheduler.py  test_project.py  test_cli.py  test_e2e_mock.py
```

---

### Task 1: Project scaffold, manifest schema and graph validation

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `schemas/manifest.schema.json`
- Create: `engine/__init__.py`, `engine/core/__init__.py`, `engine/core/jsonio.py`, `engine/core/graph.py`
- Create: `tests/__init__.py`, `tests/helpers.py`, `tests/conftest.py`
- Test: `tests/test_graph.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `engine.core.jsonio.write_json_atomic(path: Path, data: Any) -> None`
  - `engine.core.graph.ManifestError(ValueError)` with `.errors: list[str]`
  - `engine.core.graph.Node` dataclass: `id: str, type: str, inputs: dict, depends_on: list[str], provider: str|None, model: str|None, prompt: str|None`; `Node.from_dict(d)`, `Node.to_dict()`
  - `engine.core.graph.Manifest` dataclass: `project: str, nodes: dict[str, Node]` (manifest order); `Manifest.from_dict(data)` (validates), `.to_dict()`, `.topo_order() -> list[str]`, `.dependents(id) -> list[str]`, `.descendants(ids) -> set[str]`, `.ancestors(ids) -> set[str]`, `.match(patterns) -> set[str]`, `.scope(targets: Iterable[str]|None) -> set[str]` (matched plus ancestors; raises `ValueError` if nothing matches)
  - `engine.core.graph.find_refs(value) -> list[str]`, `resolve_refs(value, lookup: Callable[[str], str]) -> Any`
  - `engine.core.graph.load_manifest(path) -> Manifest`, `save_manifest(manifest, path) -> None`, `validate_dict(data) -> None`
  - `tests.helpers.make_manifest(variants=("v1","v2"), shots=2) -> dict` (17 nodes by default), `tests.helpers.node(data, node_id) -> dict`
  - `tests/conftest.py` fixture `project_dir` (a `tmp_path/"mug-launch"` folder containing `manifest.json` from `make_manifest()`)

- [ ] **Step 1: Initialize the repo and packaging**

```bash
cd /home/iinko/PROJECT_AUTOMATION/adforge
git init
mkdir -p engine/core engine/providers schemas tests
touch engine/__init__.py engine/core/__init__.py tests/__init__.py
```

Create `pyproject.toml`:

```toml
[project]
name = "adforge"
version = "0.1.0"
description = "AdForge engine: manifest-driven parallel ad asset rendering"
requires-python = ">=3.11"
dependencies = ["jsonschema>=4.21", "pyyaml>=6.0"]

[project.scripts]
adengine = "engine.cli:main"

[dependency-groups]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["engine"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

Create `.gitignore`:

```
.venv/
__pycache__/
.pytest_cache/
*.egg-info/
.env
projects/
```

Run: `uv sync`
Expected: creates `.venv`, installs `jsonschema`, `pyyaml`, `pytest`, and `adforge` (editable). Ends without errors.

- [ ] **Step 2: Write the manifest schema**

Create `schemas/manifest.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://adforge.local/manifest.schema.json",
  "title": "AdForge manifest",
  "type": "object",
  "required": ["manifest_version", "project", "nodes"],
  "additionalProperties": false,
  "properties": {
    "manifest_version": {"const": 1},
    "project": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*$"},
    "nodes": {"type": "array", "items": {"$ref": "#/$defs/node"}}
  },
  "$defs": {
    "node": {
      "type": "object",
      "required": ["id", "type", "inputs", "depends_on"],
      "additionalProperties": false,
      "properties": {
        "id": {"type": "string", "pattern": "^[a-z0-9_]+(\\.[a-z0-9_]+){1,2}$"},
        "type": {"enum": ["image", "video", "tts", "sfx", "music", "timeline", "preview", "capcut_draft"]},
        "provider": {"type": "string", "minLength": 1},
        "model": {"type": "string", "minLength": 1},
        "prompt": {"type": "string"},
        "inputs": {"type": "object"},
        "depends_on": {"type": "array", "items": {"type": "string"}, "uniqueItems": true},
        "status": {"enum": ["pending", "running", "done", "failed", "blocked", "needs_review"]},
        "version": {"type": "integer", "minimum": 1}
      }
    }
  }
}
```

- [ ] **Step 3: Write test helpers and fixture**

Create `tests/helpers.py`:

```python
"""Shared test builders. Imported as `from tests.helpers import ...`."""
from __future__ import annotations


def make_manifest(variants: tuple[str, ...] = ("v1", "v2"), shots: int = 2) -> dict:
    """A realistic manifest: one shared product hero, then per variant
    `shots` keyframe→clip pairs, one VO line, timeline, preview, CapCut draft.
    Default size: 1 + 2 * 8 = 17 nodes, 11 of them generation nodes."""
    nodes: list[dict] = [
        {
            "id": "refs.product_hero",
            "type": "image",
            "prompt": "Hero shot of a matte ceramic mug on a wooden table",
            "inputs": {"size": "1024x1024"},
            "depends_on": [],
        }
    ]
    for v in variants:
        clips: list[str] = []
        for s in range(1, shots + 1):
            sid = f"s{s:02d}"
            nodes.append({
                "id": f"{v}.{sid}.keyframe",
                "type": "image",
                "prompt": f"{v} shot {s} keyframe",
                "inputs": {"refs": ["@refs.product_hero"], "n": 2},
                "depends_on": ["refs.product_hero"],
            })
            nodes.append({
                "id": f"{v}.{sid}.clip",
                "type": "video",
                "prompt": f"{v} shot {s} slow push-in",
                "inputs": {"first_frame": f"@{v}.{sid}.keyframe", "duration": 4, "aspect": "9:16"},
                "depends_on": [f"{v}.{sid}.keyframe"],
            })
            clips.append(f"{v}.{sid}.clip")
        nodes.append({
            "id": f"{v}.vo.l01",
            "type": "tts",
            "inputs": {"text": f"Line for {v}", "voice": "narrator"},
            "depends_on": [],
        })
        nodes.append({
            "id": f"{v}.timeline",
            "type": "timeline",
            "inputs": {"clips": [f"@{c}" for c in clips], "vo": [f"@{v}.vo.l01"]},
            "depends_on": clips + [f"{v}.vo.l01"],
        })
        nodes.append({
            "id": f"{v}.preview",
            "type": "preview",
            "inputs": {"timeline": f"@{v}.timeline"},
            "depends_on": [f"{v}.timeline"],
        })
        nodes.append({
            "id": f"{v}.capcut_draft",
            "type": "capcut_draft",
            "inputs": {"timeline": f"@{v}.timeline"},
            "depends_on": [f"{v}.timeline"],
        })
    return {"manifest_version": 1, "project": "mug-launch", "nodes": nodes}


def node(data: dict, node_id: str) -> dict:
    """Return the node dict with this id from a manifest dict (mutable)."""
    return next(n for n in data["nodes"] if n["id"] == node_id)
```

Create `tests/conftest.py`:

```python
import json

import pytest

from tests.helpers import make_manifest


@pytest.fixture
def project_dir(tmp_path):
    d = tmp_path / "mug-launch"
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps(make_manifest(), indent=2))
    return d
```

- [ ] **Step 4: Write the failing graph tests**

Create `tests/test_graph.py`:

```python
import pytest

from engine.core.graph import (
    Manifest,
    ManifestError,
    find_refs,
    load_manifest,
    resolve_refs,
    save_manifest,
)
from tests.helpers import make_manifest, node


def test_valid_manifest_loads():
    m = Manifest.from_dict(make_manifest())
    assert m.project == "mug-launch"
    assert len(m.nodes) == 17
    assert m.nodes["v1.s01.clip"].inputs["first_frame"] == "@v1.s01.keyframe"


def test_schema_rejects_bad_id():
    data = make_manifest()
    data["nodes"][0]["id"] = "Refs.Hero"
    with pytest.raises(ManifestError) as exc:
        Manifest.from_dict(data)
    assert "nodes/0/id" in str(exc.value)


def test_schema_rejects_unknown_type():
    data = make_manifest()
    data["nodes"][0]["type"] = "gif"
    with pytest.raises(ManifestError) as exc:
        Manifest.from_dict(data)
    assert "nodes/0/type" in str(exc.value)


def test_ref_must_be_listed_in_depends_on():
    data = make_manifest()
    node(data, "v1.s01.clip")["depends_on"] = []
    with pytest.raises(ManifestError) as exc:
        Manifest.from_dict(data)
    assert "v1.s01.clip: input references @v1.s01.keyframe but it is not in depends_on" in exc.value.errors


def test_unknown_dependency_rejected():
    data = make_manifest()
    node(data, "v1.s01.clip")["depends_on"].append("v9.s01.keyframe")
    with pytest.raises(ManifestError) as exc:
        Manifest.from_dict(data)
    assert "v1.s01.clip: depends_on unknown node v9.s01.keyframe" in exc.value.errors


def test_duplicate_id_rejected():
    data = make_manifest()
    data["nodes"].append(dict(data["nodes"][0]))
    with pytest.raises(ManifestError) as exc:
        Manifest.from_dict(data)
    assert "duplicate node id: refs.product_hero" in exc.value.errors


def test_cycle_rejected():
    data = make_manifest()
    node(data, "refs.product_hero")["depends_on"] = ["v1.s01.keyframe"]
    with pytest.raises(ManifestError) as exc:
        Manifest.from_dict(data)
    assert "dependency cycle" in str(exc.value)


def test_topo_order_puts_dependencies_first():
    m = Manifest.from_dict(make_manifest())
    order = m.topo_order()
    assert sorted(order) == sorted(m.nodes)
    for nid, n in m.nodes.items():
        for dep in n.depends_on:
            assert order.index(dep) < order.index(nid)


def test_descendants_and_ancestors():
    m = Manifest.from_dict(make_manifest())
    assert m.descendants(["v1.s01.keyframe"]) == {
        "v1.s01.clip", "v1.timeline", "v1.preview", "v1.capcut_draft",
    }
    assert m.ancestors(["v1.preview"]) == {
        "v1.timeline", "v1.s01.clip", "v1.s02.clip", "v1.s01.keyframe",
        "v1.s02.keyframe", "v1.vo.l01", "refs.product_hero",
    }


def test_scope_with_globs():
    m = Manifest.from_dict(make_manifest())
    assert m.scope(None) == set(m.nodes)
    assert m.scope(["refs.*"]) == {"refs.product_hero"}
    assert m.scope(["v2.s02.clip"]) == {"v2.s02.clip", "v2.s02.keyframe", "refs.product_hero"}
    with pytest.raises(ValueError, match="no nodes match"):
        m.scope(["nope.*"])


def test_find_and_resolve_refs():
    inputs = {"clips": ["@a.b", "x"], "first": "@c.d", "n": 2}
    assert find_refs(inputs) == ["a.b", "c.d"]
    assert resolve_refs(inputs, lambda r: f"/out/{r}") == {
        "clips": ["/out/a.b", "x"], "first": "/out/c.d", "n": 2,
    }


def test_save_and_load_roundtrip(tmp_path):
    m = Manifest.from_dict(make_manifest())
    path = tmp_path / "manifest.json"
    save_manifest(m, path)
    assert load_manifest(path).to_dict() == m.to_dict()
    assert m.to_dict() == make_manifest()
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `uv run pytest tests/test_graph.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'engine.core.graph'`.

- [ ] **Step 6: Implement jsonio and graph**

Create `engine/core/jsonio.py`:

```python
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path, data: Any) -> None:
    """Write JSON so readers never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)
```

Create `engine/core/graph.py`:

```python
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
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_graph.py -v`
Expected: 12 passed.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock .gitignore schemas engine tests docs
git commit -m "feat(engine): manifest schema, graph validation and queries"
```

---

### Task 2: Output paths and input resolution

**Files:**
- Create: `engine/core/paths.py`
- Test: `tests/test_paths.py`

**Interfaces:**
- Consumes: `Manifest`, `Node`, `resolve_refs` from Task 1.
- Produces:
  - `engine.core.paths.EXTENSIONS: dict[str, str]` (node type → extension; `capcut_draft` → `""`, meaning a directory)
  - `engine.core.paths.output_path(project_dir: Path, node_id: str, node_type: str) -> Path`
  - `engine.core.paths.version_path(output: Path, node_id: str, version: int) -> Path`
  - `engine.core.paths.resolve_inputs(manifest: Manifest, project_dir: Path, node: Node, *, absolute: bool = True) -> dict`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_paths.py`:

```python
import pytest

from engine.core.graph import Manifest
from engine.core.paths import output_path, resolve_inputs, version_path
from tests.helpers import make_manifest


@pytest.mark.parametrize(
    "node_id,node_type,expected",
    [
        ("refs.product_hero", "image", "refs/product_hero.png"),
        ("v2.s03.keyframe", "image", "v2/shots/s03/keyframe.png"),
        ("v2.s03.clip", "video", "v2/shots/s03/clip.mp4"),
        ("v2.vo.l04", "tts", "v2/vo/l04.wav"),
        ("v2.sfx.whoosh02", "sfx", "v2/sfx/whoosh02.wav"),
        ("shared.music.bed", "music", "shared/music/bed.mp3"),
        ("v2.timeline", "timeline", "v2/timeline.json"),
        ("v2.preview", "preview", "v2/preview.mp4"),
        ("v2.capcut_draft", "capcut_draft", "v2/capcut_draft"),
    ],
)
def test_output_path(tmp_path, node_id, node_type, expected):
    assert output_path(tmp_path, node_id, node_type) == tmp_path / expected


def test_version_path_for_file(tmp_path):
    out = tmp_path / "v2/shots/s03/clip.mp4"
    assert version_path(out, "v2.s03.clip", 2) == tmp_path / "v2/shots/s03/versions/v2.s03.clip_v2.mp4"


def test_version_path_for_directory(tmp_path):
    out = tmp_path / "v2/capcut_draft"
    assert version_path(out, "v2.capcut_draft", 1) == tmp_path / "v2/versions/v2.capcut_draft_v1"


def test_resolve_inputs_absolute_and_relative(tmp_path):
    m = Manifest.from_dict(make_manifest())
    clip = m.nodes["v1.s01.clip"]
    assert resolve_inputs(m, tmp_path, clip)["first_frame"] == str(tmp_path / "v1/shots/s01/keyframe.png")
    rel = resolve_inputs(m, tmp_path, clip, absolute=False)
    assert rel == {"first_frame": "v1/shots/s01/keyframe.png", "duration": 4, "aspect": "9:16"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_paths.py -v`
Expected: `ModuleNotFoundError: No module named 'engine.core.paths'`.

- [ ] **Step 3: Implement paths**

Create `engine/core/paths.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_paths.py -v`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/core/paths.py tests/test_paths.py
git commit -m "feat(engine): node id to output path layout and input resolution"
```

---

### Task 3: Engine config and fingerprints

**Files:**
- Create: `engine/config.py`, `engine/core/cache.py`
- Test: `tests/test_config.py`, `tests/test_cache.py`

**Interfaces:**
- Consumes: `Manifest`, `Node` (Task 1), `resolve_inputs` (Task 2).
- Produces:
  - `engine.config.NODE_TYPES: tuple[str, ...]`
  - `engine.config.ConfigError(ValueError)`
  - `engine.config.Route(provider: str, model: str)` (frozen dataclass)
  - `engine.config.RetryConfig(max_attempts=3, base_delay_s=1.0, max_delay_s=30.0)`
  - `engine.config.EngineConfig(routing: dict[str, Route], concurrency: dict[str, int], default_concurrency: int = 4, retry: RetryConfig)`; `EngineConfig.from_dict(data) -> EngineConfig`, `.route(node: Node) -> Route` (raises `ConfigError`), `.limit(provider: str) -> int`
  - `engine.config.load_config(path: Path | None) -> EngineConfig`
  - `engine.core.cache.node_fingerprint(node, route, resolved_inputs, dep_fps) -> str`
  - `engine.core.cache.pinned_fingerprint(node_id: str, version: int) -> str`
  - `engine.core.cache.compute_fingerprints(manifest, config, project_dir, pins: dict[str, int]) -> dict[str, str]`

- [ ] **Step 1: Write the failing config tests**

Create `tests/test_config.py`:

```python
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
```

- [ ] **Step 2: Write the failing fingerprint tests**

Create `tests/test_cache.py`:

```python
from pathlib import Path

from engine.config import EngineConfig
from engine.core.cache import compute_fingerprints, pinned_fingerprint
from engine.core.graph import Manifest
from tests.helpers import make_manifest, node


def fps_for(data, config=None, pins=None, project_dir=Path("/proj")):
    return compute_fingerprints(Manifest.from_dict(data), config or EngineConfig(), project_dir, pins or {})


def changed(a, b):
    return {k for k in a if a[k] != b[k]}


def test_fingerprints_are_deterministic_sha256():
    a, b = fps_for(make_manifest()), fps_for(make_manifest())
    assert a == b
    assert all(len(v) == 64 for v in a.values())
    assert len(set(a.values())) == len(a)


def test_prompt_change_invalidates_node_and_descendants_only():
    base = fps_for(make_manifest())
    data = make_manifest()
    node(data, "v1.s01.keyframe")["prompt"] = "darker, moodier"
    assert changed(base, fps_for(data)) == {
        "v1.s01.keyframe", "v1.s01.clip", "v1.timeline", "v1.preview", "v1.capcut_draft",
    }


def test_routing_change_invalidates_that_type_and_downstream():
    base = fps_for(make_manifest())
    cfg = EngineConfig.from_dict({"routing": {"video": {"provider": "mock", "model": "mock-video-2"}}})
    assert changed(base, fps_for(make_manifest(), config=cfg)) == {
        "v1.s01.clip", "v1.s02.clip", "v2.s01.clip", "v2.s02.clip",
        "v1.timeline", "v1.preview", "v1.capcut_draft",
        "v2.timeline", "v2.preview", "v2.capcut_draft",
    }


def test_pin_replaces_node_fingerprint_and_invalidates_descendants():
    base = fps_for(make_manifest())
    pinned = fps_for(make_manifest(), pins={"v1.vo.l01": 3})
    assert pinned["v1.vo.l01"] == pinned_fingerprint("v1.vo.l01", 3)
    assert changed(base, pinned) == {"v1.vo.l01", "v1.timeline", "v1.preview", "v1.capcut_draft"}


def test_project_location_does_not_affect_fingerprints():
    assert fps_for(make_manifest(), project_dir=Path("/a")) == fps_for(make_manifest(), project_dir=Path("/b"))
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_config.py tests/test_cache.py -v`
Expected: `ModuleNotFoundError: No module named 'engine.config'`.

- [ ] **Step 4: Implement config**

Create `engine/config.py`:

```python
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
```

- [ ] **Step 5: Implement fingerprints**

Create `engine/core/cache.py`:

```python
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
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_config.py tests/test_cache.py -v`
Expected: 12 passed.

- [ ] **Step 7: Commit**

```bash
git add engine/config.py engine/core/cache.py tests/test_config.py tests/test_cache.py
git commit -m "feat(engine): config routing and dependency-aware fingerprints"
```

---

### Task 4: Project store (state.json, versioning, rollback)

**Files:**
- Create: `engine/core/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `Node` (Task 1), `output_path`, `version_path` (Task 2), `pinned_fingerprint` (Task 3), `write_json_atomic` (Task 1).
- Produces:
  - `engine.core.store.NodeState` dataclass: `status="pending", version=0, fingerprint: str|None, reason: str|None, message: str|None, pinned_version: int|None`
  - `engine.core.store.ProjectStore(project_dir: Path)` with attributes `.dir`, `.state_path`, `.nodes: dict[str, NodeState]` and methods:
    - `get(node_id) -> NodeState` (creates a pending entry if missing, not saved)
    - `update(node_id, **fields) -> None` (saves)
    - `save() -> None`
    - `output(node: Node) -> Path`
    - `is_fresh(node: Node, fingerprint: str) -> bool`
    - `commit(node: Node, produced: Path, fingerprint: str) -> int` (returns new version, sets status `done`)
    - `versions(node: Node) -> list[int]`
    - `rollback(node: Node, version: int) -> int` (raises `ValueError`; pins the node)
    - `pins() -> dict[str, int]`, `unpin(node_id) -> None`
    - `work_dir(node_id) -> Path` (fresh empty dir under `<project>/.tmp/`)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_store.py`:

```python
import pytest

from engine.core.cache import pinned_fingerprint
from engine.core.graph import Node
from engine.core.store import ProjectStore

VO = Node(id="v1.vo.l01", type="tts", inputs={}, depends_on=[])
DRAFT = Node(id="v1.capcut_draft", type="capcut_draft", inputs={}, depends_on=[])


def produce(tmp_path, name, text):
    path = tmp_path / "work" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_new_store_is_empty(tmp_path):
    store = ProjectStore(tmp_path)
    assert store.nodes == {}
    assert store.get("x.y").status == "pending"
    assert not store.state_path.exists()


def test_commit_moves_output_and_versions_the_previous_one(tmp_path):
    store = ProjectStore(tmp_path)
    out = tmp_path / "v1/vo/l01.wav"
    assert store.commit(VO, produce(tmp_path, "a.wav", "one"), "fp1") == 1
    assert out.read_text() == "one"
    assert store.commit(VO, produce(tmp_path, "b.wav", "two"), "fp2") == 2
    assert out.read_text() == "two"
    assert (tmp_path / "v1/vo/versions/v1.vo.l01_v1.wav").read_text() == "one"
    assert store.versions(VO) == [1]
    st = store.get(VO.id)
    assert (st.status, st.version, st.fingerprint) == ("done", 2, "fp2")


def test_state_persists_across_instances(tmp_path):
    ProjectStore(tmp_path).commit(VO, produce(tmp_path, "a.wav", "one"), "fp1")
    st = ProjectStore(tmp_path).get(VO.id)
    assert (st.status, st.version, st.fingerprint) == ("done", 1, "fp1")


def test_is_fresh_requires_matching_fingerprint_and_existing_output(tmp_path):
    store = ProjectStore(tmp_path)
    store.commit(VO, produce(tmp_path, "a.wav", "one"), "fp1")
    assert store.is_fresh(VO, "fp1")
    assert not store.is_fresh(VO, "fp2")
    store.output(VO).unlink()
    assert not store.is_fresh(VO, "fp1")


def test_directory_outputs_commit_and_version(tmp_path):
    store = ProjectStore(tmp_path)
    for i in (1, 2):
        d = tmp_path / "work" / f"draft{i}"
        d.mkdir(parents=True)
        (d / "draft_content.json").write_text(str(i))
        store.commit(DRAFT, d, f"fp{i}")
    assert (tmp_path / "v1/capcut_draft/draft_content.json").read_text() == "2"
    assert (tmp_path / "v1/versions/v1.capcut_draft_v1/draft_content.json").read_text() == "1"
    assert store.versions(DRAFT) == [1]


def test_rollback_restores_content_and_pins(tmp_path):
    store = ProjectStore(tmp_path)
    store.commit(VO, produce(tmp_path, "a.wav", "one"), "fp1")
    store.commit(VO, produce(tmp_path, "b.wav", "two"), "fp2")
    assert store.rollback(VO, 1) == 3
    assert store.output(VO).read_text() == "one"
    st = store.get(VO.id)
    assert st.pinned_version == 3
    assert st.fingerprint == pinned_fingerprint(VO.id, 3)
    assert store.pins() == {VO.id: 3}
    assert store.versions(VO) == [1, 2]
    store.unpin(VO.id)
    assert store.pins() == {}


def test_rollback_to_missing_version_raises(tmp_path):
    store = ProjectStore(tmp_path)
    store.commit(VO, produce(tmp_path, "a.wav", "one"), "fp1")
    with pytest.raises(ValueError, match="no version 7"):
        store.rollback(VO, 7)


def test_work_dir_is_fresh_each_time(tmp_path):
    store = ProjectStore(tmp_path)
    d = store.work_dir("v1.s01.clip")
    (d / "junk").write_text("x")
    d2 = store.work_dir("v1.s01.clip")
    assert d2 == d and d2.is_dir() and not (d2 / "junk").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_store.py -v`
Expected: `ModuleNotFoundError: No module named 'engine.core.store'`.

- [ ] **Step 3: Implement the store**

Create `engine/core/store.py`:

```python
"""Per-project run state (state.json), versioned outputs, rollback."""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from engine.core.cache import pinned_fingerprint
from engine.core.graph import Node
from engine.core.jsonio import write_json_atomic
from engine.core.paths import output_path, version_path


@dataclass
class NodeState:
    status: str = "pending"
    version: int = 0
    fingerprint: str | None = None
    reason: str | None = None
    message: str | None = None
    pinned_version: int | None = None


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


class ProjectStore:
    def __init__(self, project_dir: Path):
        self.dir = Path(project_dir)
        self.state_path = self.dir / "state.json"
        self.nodes: dict[str, NodeState] = {}
        if self.state_path.exists():
            data = json.loads(self.state_path.read_text())
            self.nodes = {k: NodeState(**v) for k, v in data.get("nodes", {}).items()}

    def save(self) -> None:
        write_json_atomic(self.state_path, {"nodes": {k: asdict(v) for k, v in self.nodes.items()}})

    def get(self, node_id: str) -> NodeState:
        return self.nodes.setdefault(node_id, NodeState())

    def update(self, node_id: str, **fields) -> None:
        st = self.get(node_id)
        for key, value in fields.items():
            setattr(st, key, value)
        self.save()

    def output(self, node: Node) -> Path:
        return output_path(self.dir, node.id, node.type)

    def is_fresh(self, node: Node, fingerprint: str) -> bool:
        st = self.nodes.get(node.id)
        return st is not None and st.fingerprint == fingerprint and self.output(node).exists()

    def commit(self, node: Node, produced: Path, fingerprint: str) -> int:
        """Archive the current output (if any) to versions/, move `produced` into place."""
        out = self.output(node)
        st = self.get(node.id)
        if out.exists():
            archived = version_path(out, node.id, st.version)
            archived.parent.mkdir(parents=True, exist_ok=True)
            _remove(archived)
            shutil.move(str(out), str(archived))
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(produced), str(out))
        st.version += 1
        st.status = "done"
        st.fingerprint = fingerprint
        st.reason = None
        st.message = None
        self.save()
        return st.version

    def versions(self, node: Node) -> list[int]:
        out = self.output(node)
        vdir = out.parent / "versions"
        if not vdir.exists():
            return []
        prefix, suffix = f"{node.id}_v", out.suffix
        nums: list[int] = []
        for p in vdir.iterdir():
            name = p.name
            if suffix:
                if not name.endswith(suffix):
                    continue
                name = name[: -len(suffix)]
            tail = name[len(prefix):]
            if name.startswith(prefix) and tail.isdigit():
                nums.append(int(tail))
        return sorted(nums)

    def rollback(self, node: Node, version: int) -> int:
        """Restore versions/<id>_v<version> as a new current version and pin it, so
        re-runs keep it until the node is revised. Dependents rebuild against it."""
        out = self.output(node)
        src = version_path(out, node.id, version)
        if not src.exists():
            raise ValueError(f"{node.id} has no version {version} (archived: {self.versions(node)})")
        staged = self.work_dir(node.id) / f"rollback{out.suffix}"
        if src.is_dir():
            shutil.copytree(src, staged)
        else:
            shutil.copy2(src, staged)
        new_version = self.get(node.id).version + 1
        self.commit(node, staged, pinned_fingerprint(node.id, new_version))
        self.update(node.id, pinned_version=new_version)
        return new_version

    def pins(self) -> dict[str, int]:
        return {k: v.pinned_version for k, v in self.nodes.items() if v.pinned_version is not None}

    def unpin(self, node_id: str) -> None:
        if node_id in self.nodes and self.nodes[node_id].pinned_version is not None:
            self.update(node_id, pinned_version=None)

    def work_dir(self, node_id: str) -> Path:
        d = self.dir / ".tmp" / node_id
        _remove(d)
        d.mkdir(parents=True)
        return d
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_store.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/core/store.py tests/test_store.py
git commit -m "feat(engine): state store with versioned outputs and rollback"
```

---

### Task 5: Provider interface, mock provider, executors, ledger

**Files:**
- Create: `engine/providers/base.py`, `engine/providers/mock.py`, `engine/providers/__init__.py`
- Create: `engine/core/executors.py`, `engine/core/ledger.py`
- Modify: `tests/helpers.py` (append `RecordingProvider`)
- Test: `tests/test_providers.py`

**Interfaces:**
- Consumes: `Node` (Task 1), `EngineConfig` (Task 3).
- Produces:
  - `engine.providers.base.GENERATION_TYPES = frozenset({"image","video","tts","sfx","music"})`, `ASSEMBLY_TYPES = frozenset({"timeline","preview","capcut_draft"})`
  - `engine.providers.base.ProviderError(Exception)`, `TransientProviderError(ProviderError)`, `ProviderRefusal(ProviderError)`
  - `engine.providers.base.CallContext(node_id: str, model: str, work_dir: Path)`
  - `engine.providers.base.Provider` with `name: str` and async methods. All of them write into `ctx.work_dir` and return the produced path:
    - `generate_image(ctx, prompt: str, refs: list[Path], size: str, n: int) -> list[Path]`
    - `generate_video(ctx, prompt: str, first_frame: Path|None, last_frame: Path|None, duration: float, aspect: str) -> Path`
    - `tts(ctx, text: str, voice: str, emotion: str) -> Path`
    - `sfx(ctx, prompt: str, duration: float) -> Path`
    - `music(ctx, prompt: str, duration: float) -> Path`
    - `assemble(ctx, node_type: str, inputs: dict) -> Path`
    - sync `cost(node_type: str, params: dict) -> float` (USD)
  - `engine.providers.mock.MockProvider(cost_per_call: float = 0.0, delay_s: float = 0.0)`, with an overridable hook `async _before(ctx)`. `PNG_1X1: bytes`.
  - `engine.providers.build_providers(config: EngineConfig) -> dict[str, Provider]` (currently `{"mock": MockProvider()}`)
  - `engine.core.executors.execute(node, provider, ctx, inputs: dict) -> Path`, `cost_params(node, inputs) -> dict`
  - `engine.core.ledger.Ledger(path)` with `.record(**fields)`, `.entries() -> list[dict]`, `.total_cost() -> float`
  - `tests.helpers.RecordingProvider(*, delays=None, default_delay=0.0, fail=(), transient=None, refuse=(), cost_per_call=0.0)` with `.calls: list[str]`, `.events: list[tuple[str, str]]`, `.max_active: int`

Note: the spec's provider signatures (§6) omit an output location. This plan adds `ctx: CallContext` so that the engine, not the provider, decides where files land.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_providers.py`:

```python
import asyncio
import json

import pytest

from engine.core.executors import cost_params, execute
from engine.core.graph import Node
from engine.core.ledger import Ledger
from engine.providers import build_providers
from engine.providers.base import CallContext, ProviderError
from engine.providers.mock import MockProvider
from engine.config import EngineConfig


def ctx(tmp_path, node_id="v1.s01.keyframe"):
    d = tmp_path / "work"
    d.mkdir(exist_ok=True)
    return CallContext(node_id=node_id, model="mock-x", work_dir=d)


def test_mock_image_returns_n_png_candidates(tmp_path):
    paths = asyncio.run(MockProvider().generate_image(ctx(tmp_path), "mug", [], "1024x1024", 2))
    assert len(paths) == 2
    assert all(p.read_bytes().startswith(b"\x89PNG") for p in paths)


def test_mock_video_stamps_its_parameters(tmp_path):
    p = asyncio.run(MockProvider().generate_video(ctx(tmp_path, "v1.s01.clip"), "push in", tmp_path / "k.png", None, 4.0, "9:16"))
    stamp = json.loads(p.read_bytes())
    assert stamp["node"] == "v1.s01.clip" and stamp["prompt"] == "push in" and stamp["duration"] == 4.0


def test_mock_capcut_draft_is_a_directory(tmp_path):
    p = asyncio.run(MockProvider().assemble(ctx(tmp_path, "v1.capcut_draft"), "capcut_draft", {"timeline": "t.json"}))
    assert p.is_dir() and (p / "draft_content.json").exists()


def test_mock_cost_only_for_generation(tmp_path):
    mock = MockProvider(cost_per_call=0.25)
    assert mock.cost("video", {}) == 0.25
    assert mock.cost("timeline", {}) == 0.0


def test_execute_image_picks_first_candidate(tmp_path):
    n = Node(id="v1.s01.keyframe", type="image", inputs={"refs": [], "n": 2}, depends_on=[], prompt="mug")
    out = asyncio.run(execute(n, MockProvider(), ctx(tmp_path), n.inputs))
    assert out.name == "candidate_0.png"


def test_execute_tts_requires_text(tmp_path):
    n = Node(id="v1.vo.l01", type="tts", inputs={}, depends_on=[])
    with pytest.raises(ProviderError, match="inputs.text"):
        asyncio.run(execute(n, MockProvider(), ctx(tmp_path, n.id), n.inputs))


def test_cost_params_merge_prompt_and_inputs():
    n = Node(id="v1.s01.clip", type="video", inputs={"duration": 4}, depends_on=[], prompt="p")
    assert cost_params(n, {"duration": 4}) == {"prompt": "p", "duration": 4}


def test_build_providers_has_mock():
    assert isinstance(build_providers(EngineConfig())["mock"], MockProvider)


def test_ledger_appends_and_totals(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    assert ledger.entries() == [] and ledger.total_cost() == 0
    ledger.record(node_id="a.b", provider="mock", model="m", cost_usd=0.5, seconds=1.0, attempt=1, ok=True)
    ledger.record(node_id="a.c", provider="mock", model="m", cost_usd=0.25, seconds=1.0, attempt=1, ok=False)
    entries = ledger.entries()
    assert [e["node_id"] for e in entries] == ["a.b", "a.c"]
    assert "ts" in entries[0]
    assert ledger.total_cost() == 0.75
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_providers.py -v`
Expected: `ModuleNotFoundError: No module named 'engine.core.executors'`.

- [ ] **Step 3: Implement the provider base**

Create `engine/providers/base.py`:

```python
"""Provider interface. Providers execute; they make no creative decisions."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

GENERATION_TYPES = frozenset({"image", "video", "tts", "sfx", "music"})
ASSEMBLY_TYPES = frozenset({"timeline", "preview", "capcut_draft"})


class ProviderError(Exception):
    """Hard failure: node → failed, dependents → blocked."""


class TransientProviderError(ProviderError):
    """429 / 5xx / timeout: the scheduler retries with exponential backoff."""


class ProviderRefusal(ProviderError):
    """Content refusal: node → needs_review with reason 'refused'. Never auto-rewritten."""


@dataclass
class CallContext:
    node_id: str
    model: str
    work_dir: Path  # empty directory; write outputs here and return their paths


class Provider:
    name = "base"

    async def generate_image(self, ctx: CallContext, prompt: str, refs: list[Path], size: str, n: int) -> list[Path]:
        raise NotImplementedError(f"{self.name} does not support image generation")

    async def generate_video(
        self, ctx: CallContext, prompt: str, first_frame: Path | None, last_frame: Path | None,
        duration: float, aspect: str,
    ) -> Path:
        raise NotImplementedError(f"{self.name} does not support video generation")

    async def tts(self, ctx: CallContext, text: str, voice: str, emotion: str) -> Path:
        raise NotImplementedError(f"{self.name} does not support tts")

    async def sfx(self, ctx: CallContext, prompt: str, duration: float) -> Path:
        raise NotImplementedError(f"{self.name} does not support sfx")

    async def music(self, ctx: CallContext, prompt: str, duration: float) -> Path:
        raise NotImplementedError(f"{self.name} does not support music")

    async def assemble(self, ctx: CallContext, node_type: str, inputs: dict[str, Any]) -> Path:
        raise NotImplementedError(f"{self.name} does not support {node_type}")

    def cost(self, node_type: str, params: dict[str, Any]) -> float:
        return 0.0
```

- [ ] **Step 4: Implement the mock provider and registry**

Create `engine/providers/mock.py`:

```python
"""Instant placeholder outputs for tests and dry runs. No network.
Video/audio files are JSON stamps with media extensions; plan 2 upgrades
them to real media so assembly can be tested end to end."""
from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any

from engine.providers.base import ASSEMBLY_TYPES, CallContext, Provider

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


class MockProvider(Provider):
    name = "mock"

    def __init__(self, cost_per_call: float = 0.0, delay_s: float = 0.0):
        self.cost_per_call = cost_per_call
        self.delay_s = delay_s

    async def _before(self, ctx: CallContext) -> None:
        """Runs at the start of every call. Tests override it to inject delays/failures."""
        if self.delay_s:
            await asyncio.sleep(self.delay_s)

    def _stamp(self, ctx: CallContext, **fields: Any) -> bytes:
        return json.dumps(
            {"mock": True, "node": ctx.node_id, "model": ctx.model, **fields}, sort_keys=True, default=str
        ).encode()

    def _write(self, ctx: CallContext, filename: str, payload: bytes) -> Path:
        path = ctx.work_dir / filename
        path.write_bytes(payload)
        return path

    async def generate_image(self, ctx, prompt, refs, size, n):
        await self._before(ctx)
        return [self._write(ctx, f"candidate_{i}.png", PNG_1X1) for i in range(n)]

    async def generate_video(self, ctx, prompt, first_frame, last_frame, duration, aspect):
        await self._before(ctx)
        return self._write(ctx, "clip.mp4", self._stamp(
            ctx, prompt=prompt, first_frame=first_frame, last_frame=last_frame, duration=duration, aspect=aspect,
        ))

    async def tts(self, ctx, text, voice, emotion):
        await self._before(ctx)
        return self._write(ctx, "vo.wav", self._stamp(ctx, text=text, voice=voice, emotion=emotion))

    async def sfx(self, ctx, prompt, duration):
        await self._before(ctx)
        return self._write(ctx, "sfx.wav", self._stamp(ctx, prompt=prompt, duration=duration))

    async def music(self, ctx, prompt, duration):
        await self._before(ctx)
        return self._write(ctx, "music.mp3", self._stamp(ctx, prompt=prompt, duration=duration))

    async def assemble(self, ctx, node_type, inputs):
        await self._before(ctx)
        if node_type == "capcut_draft":
            d = ctx.work_dir / "capcut_draft"
            d.mkdir()
            (d / "draft_content.json").write_bytes(self._stamp(ctx, inputs=inputs))
            return d
        ext = {"timeline": ".json", "preview": ".mp4"}[node_type]
        return self._write(ctx, f"{node_type}{ext}", self._stamp(ctx, node_type=node_type, inputs=inputs))

    def cost(self, node_type, params):
        return 0.0 if node_type in ASSEMBLY_TYPES else self.cost_per_call
```

Create `engine/providers/__init__.py`:

```python
from engine.config import EngineConfig
from engine.providers.base import Provider
from engine.providers.mock import MockProvider


def build_providers(config: EngineConfig) -> dict[str, Provider]:
    """Provider instances keyed by the name used in routing. Plan 3 adds real providers."""
    return {"mock": MockProvider()}
```

- [ ] **Step 5: Implement executors and the ledger**

Create `engine/core/executors.py`:

```python
"""Dispatch a node to the right provider method based on its type."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.core.graph import Node
from engine.providers.base import ASSEMBLY_TYPES, CallContext, Provider, ProviderError


def _path_or_none(value: Any) -> Path | None:
    return Path(value) if value else None


def cost_params(node: Node, inputs: dict[str, Any]) -> dict[str, Any]:
    return {"prompt": node.prompt, **inputs}


async def execute(node: Node, provider: Provider, ctx: CallContext, inputs: dict[str, Any]) -> Path:
    """`inputs` are already resolved (refs → absolute paths). Returns the produced path."""
    t, prompt = node.type, node.prompt or ""
    if t == "image":
        candidates = await provider.generate_image(
            ctx, prompt, [Path(p) for p in inputs.get("refs", [])],
            str(inputs.get("size", "1024x1792")), int(inputs.get("n", 1)),
        )
        if not candidates:
            raise ProviderError(f"{node.id}: image provider returned no candidates")
        return candidates[0]  # plan 4 replaces this with the vision judge's pick
    if t == "video":
        return await provider.generate_video(
            ctx, prompt, _path_or_none(inputs.get("first_frame")), _path_or_none(inputs.get("last_frame")),
            float(inputs.get("duration", 4)), str(inputs.get("aspect", "9:16")),
        )
    if t == "tts":
        if "text" not in inputs:
            raise ProviderError(f"{node.id}: tts node needs inputs.text")
        return await provider.tts(
            ctx, str(inputs["text"]), str(inputs.get("voice", "default")), str(inputs.get("emotion", "neutral")),
        )
    if t == "sfx":
        return await provider.sfx(ctx, prompt, float(inputs.get("duration", 1.0)))
    if t == "music":
        return await provider.music(ctx, prompt, float(inputs.get("duration", 30.0)))
    if t in ASSEMBLY_TYPES:
        return await provider.assemble(ctx, t, inputs)
    raise ProviderError(f"{node.id}: unknown node type {t}")
```

Create `engine/core/ledger.py`:

```python
"""Append-only ledger of provider calls (spec §9). One JSON object per line."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)

    def record(self, **fields: Any) -> None:
        entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **fields}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def total_cost(self) -> float:
        return sum(float(e.get("cost_usd", 0)) for e in self.entries())
```

- [ ] **Step 6: Add RecordingProvider to the test helpers**

Append to `tests/helpers.py`:

```python
import asyncio

from engine.providers.base import ProviderRefusal, TransientProviderError
from engine.providers.mock import MockProvider


class RecordingProvider(MockProvider):
    """MockProvider that records every call and injects per-node behaviour:
    delays (seconds), fail (hard error), transient {id: failures before success},
    refuse (content refusal)."""

    def __init__(self, *, delays=None, default_delay=0.0, fail=(), transient=None, refuse=(), cost_per_call=0.0):
        super().__init__(cost_per_call=cost_per_call)
        self.delays = dict(delays or {})
        self.default_delay = default_delay
        self.fail = set(fail)
        self.transient = dict(transient or {})
        self.refuse = set(refuse)
        self.calls: list[str] = []
        self.events: list[tuple[str, str]] = []
        self.active = 0
        self.max_active = 0

    async def _before(self, ctx):
        nid = ctx.node_id
        self.calls.append(nid)
        self.events.append(("start", nid))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delays.get(nid, self.default_delay))
            if nid in self.fail:
                raise RuntimeError("boom")
            if self.transient.get(nid, 0) > 0:
                self.transient[nid] -= 1
                raise TransientProviderError("429 rate limited")
            if nid in self.refuse:
                raise ProviderRefusal("content policy")
        finally:
            self.active -= 1
            self.events.append(("end", nid))
```

Move the new `import asyncio` and `from engine...` lines to the top of `tests/helpers.py`, next to `from __future__ import annotations`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_providers.py -v`
Expected: 9 passed.

- [ ] **Step 8: Commit**

```bash
git add engine/providers engine/core/executors.py engine/core/ledger.py tests/helpers.py tests/test_providers.py
git commit -m "feat(engine): provider interface, mock provider, executors, ledger"
```

---

### Task 6: Async DAG scheduler

**Files:**
- Create: `engine/core/scheduler.py`
- Modify: `tests/helpers.py` (append `FAST`)
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `Manifest`, `load_manifest` (Task 1), `resolve_inputs` (Task 2), `EngineConfig`, `compute_fingerprints` (Task 3), `ProjectStore` (Task 4), `Provider`, the error classes, `CallContext`, `GENERATION_TYPES`, `execute`, `cost_params`, `Ledger` (Task 5).
- Produces:
  - `engine.core.scheduler.RunReport` dataclass with lists `ran, skipped, failed, needs_review, blocked` and property `ok: bool`
  - `engine.core.scheduler.Scheduler(manifest, store, config, providers: dict[str, Provider], ledger, sleep=asyncio.sleep)` and `async run(targets: Iterable[str] | None = None) -> RunReport`
  - `tests.helpers.FAST: EngineConfig` (zero backoff delay, concurrency 8)

Behaviour contract:
- Fingerprints are computed once at run start. In-scope nodes that are fresh are `skipped` (status `done`), and the rest become `pending`.
- Every pending node whose dependencies are all `done` starts immediately. Each completion triggers another launch pass, which gives pipelining.
- The provider call runs inside a per-provider `asyncio.Semaphore(config.limit(name))`.
- `TransientProviderError` retries up to `retry.max_attempts`, sleeping `min(base * 2**(attempt-1), max)` between attempts. If every attempt fails, the node is `failed` with reason `transient`.
- `ProviderRefusal` makes the node `needs_review` with reason `refused`. Any other exception (or an unknown provider) makes it `failed` with reason `error`/`config`.
- When a node fails or needs review, its pending in-scope descendants become `blocked` with reason `upstream <id> <status>`.
- Every generation-type call attempt, failed attempts included, appends a ledger entry.
- `state.json` is saved on every status change (via `ProjectStore.update`/`commit`).

- [ ] **Step 1: Add the FAST config helper**

Append to `tests/helpers.py`, putting the import at the top with the others:

```python
from engine.config import EngineConfig

FAST = EngineConfig.from_dict({"retry": {"base_delay_s": 0}, "default_concurrency": 8})
```

- [ ] **Step 2: Write the failing scheduler tests**

Create `tests/test_scheduler.py`:

```python
import asyncio
import json

from engine.config import EngineConfig
from engine.core.graph import load_manifest
from engine.core.ledger import Ledger
from engine.core.scheduler import Scheduler
from engine.core.store import ProjectStore
from tests.helpers import FAST, RecordingProvider, node

V1_S01_CHAIN = {"v1.s01.keyframe", "v1.s01.clip", "v1.timeline", "v1.preview", "v1.capcut_draft"}


def run(project_dir, provider, *, config=FAST, targets=None, sleep=None):
    sched = Scheduler(
        load_manifest(project_dir / "manifest.json"),
        ProjectStore(project_dir),
        config,
        {"mock": provider},
        Ledger(project_dir / "ledger.jsonl"),
        **({"sleep": sleep} if sleep else {}),
    )
    return asyncio.run(sched.run(targets))


def edit_manifest(project_dir, fn):
    path = project_dir / "manifest.json"
    data = json.loads(path.read_text())
    fn(data)
    path.write_text(json.dumps(data))


def test_full_run_renders_every_node(project_dir):
    p = RecordingProvider()
    report = run(project_dir, p)
    assert report.ok
    assert len(report.ran) == 17 and report.skipped == []
    assert len(p.calls) == 17
    store = ProjectStore(project_dir)
    assert all(store.get(n).status == "done" for n in report.ran)
    assert (project_dir / "v1/shots/s01/clip.mp4").exists()


def test_second_run_is_fully_cached(project_dir):
    run(project_dir, RecordingProvider())
    p = RecordingProvider()
    report = run(project_dir, p)
    assert p.calls == [] and len(report.skipped) == 17 and report.ran == []


def test_revision_rerenders_exactly_node_and_dependents(project_dir):
    run(project_dir, RecordingProvider())
    edit_manifest(project_dir, lambda d: node(d, "v1.s01.keyframe").update(prompt="darker"))
    p = RecordingProvider()
    run(project_dir, p)
    assert set(p.calls) == V1_S01_CHAIN
    assert (project_dir / "v1/shots/s01/versions/v1.s01.keyframe_v1.png").exists()


def test_concurrency_cap_is_respected(project_dir):
    p = RecordingProvider(default_delay=0.02)
    cfg = EngineConfig.from_dict({"retry": {"base_delay_s": 0}, "concurrency": {"mock": 2}})
    run(project_dir, p, config=cfg)
    assert p.max_active == 2


def test_dependents_start_as_soon_as_their_inputs_finish(project_dir):
    p = RecordingProvider(delays={"v2.s02.keyframe": 0.3})
    run(project_dir, p)
    assert p.events.index(("start", "v1.s01.clip")) < p.events.index(("end", "v2.s02.keyframe"))


def test_hard_failure_blocks_only_dependents(project_dir):
    report = run(project_dir, RecordingProvider(fail={"v1.s01.keyframe"}))
    assert not report.ok
    assert report.failed == ["v1.s01.keyframe"]
    assert set(report.blocked) == V1_S01_CHAIN - {"v1.s01.keyframe"}
    store = ProjectStore(project_dir)
    st = store.get("v1.s01.keyframe")
    assert (st.status, st.reason) == ("failed", "error") and "boom" in st.message
    assert store.get("v1.timeline").reason == "upstream v1.s01.keyframe failed"
    assert all(store.get(n).status == "done" for n in ("v2.preview", "v2.capcut_draft", "v1.s02.clip"))


def test_resume_after_failure_runs_only_unfinished_nodes(project_dir):
    run(project_dir, RecordingProvider(fail={"v1.s01.keyframe"}))
    p = RecordingProvider()
    report = run(project_dir, p)
    assert report.ok
    assert set(p.calls) == V1_S01_CHAIN


def test_transient_errors_retry_with_exponential_backoff(project_dir):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    cfg = EngineConfig.from_dict({"retry": {"max_attempts": 3, "base_delay_s": 1.0}})
    p = RecordingProvider(transient={"refs.product_hero": 2})
    report = run(project_dir, p, config=cfg, sleep=fake_sleep)
    assert report.ok
    assert p.calls.count("refs.product_hero") == 3
    assert sleeps == [1.0, 2.0]
    hero = [e for e in Ledger(project_dir / "ledger.jsonl").entries() if e["node_id"] == "refs.product_hero"]
    assert [e["ok"] for e in hero] == [False, False, True]
    assert [e["attempt"] for e in hero] == [1, 2, 3]


def test_transient_errors_give_up_after_max_attempts(project_dir):
    report = run(project_dir, RecordingProvider(transient={"v2.vo.l01": 5}))
    assert report.failed == ["v2.vo.l01"]
    assert ProjectStore(project_dir).get("v2.vo.l01").reason == "transient"


def test_refusal_goes_to_needs_review(project_dir):
    report = run(project_dir, RecordingProvider(refuse={"v2.s01.clip"}))
    assert report.needs_review == ["v2.s01.clip"]
    assert set(report.blocked) == {"v2.timeline", "v2.preview", "v2.capcut_draft"}
    st = ProjectStore(project_dir).get("v2.s01.clip")
    assert (st.status, st.reason, st.message) == ("needs_review", "refused", "content policy")


def test_unknown_provider_fails_the_node(project_dir):
    edit_manifest(project_dir, lambda d: node(d, "v1.vo.l01").update(provider="nope", model="x"))
    report = run(project_dir, RecordingProvider())
    assert report.failed == ["v1.vo.l01"]
    assert ProjectStore(project_dir).get("v1.vo.l01").reason == "config"


def test_targets_run_only_matches_and_their_ancestors(project_dir):
    p = RecordingProvider()
    run(project_dir, p, targets=["refs.*"])
    assert p.calls == ["refs.product_hero"]
    p = RecordingProvider()
    run(project_dir, p, targets=["v1.s01.clip"])
    assert set(p.calls) == {"v1.s01.keyframe", "v1.s01.clip"}


def test_ledger_logs_generation_calls_only(project_dir):
    run(project_dir, RecordingProvider(cost_per_call=0.1))
    entries = Ledger(project_dir / "ledger.jsonl").entries()
    assert len(entries) == 11
    assert {"node_id", "provider", "model", "cost_usd", "seconds", "attempt", "ok", "ts"} <= set(entries[0])
    assert round(Ledger(project_dir / "ledger.jsonl").total_cost(), 2) == 1.1
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: `ModuleNotFoundError: No module named 'engine.core.scheduler'`.

- [ ] **Step 4: Implement the scheduler**

Create `engine/core/scheduler.py`:

```python
"""asyncio DAG executor (spec §6 Scheduler, §8 Error handling)."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterable

from engine.config import ConfigError, EngineConfig, Route
from engine.core.cache import compute_fingerprints
from engine.core.executors import cost_params, execute
from engine.core.graph import Manifest, Node
from engine.core.ledger import Ledger
from engine.core.paths import resolve_inputs
from engine.core.store import ProjectStore
from engine.providers.base import (
    GENERATION_TYPES,
    CallContext,
    Provider,
    ProviderRefusal,
    TransientProviderError,
)

Outcome = tuple[str, str | None, str | None]  # (status, reason, message)


@dataclass
class RunReport:
    ran: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    needs_review: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.failed or self.needs_review or self.blocked)


class Scheduler:
    def __init__(
        self,
        manifest: Manifest,
        store: ProjectStore,
        config: EngineConfig,
        providers: dict[str, Provider],
        ledger: Ledger,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.manifest = manifest
        self.store = store
        self.config = config
        self.providers = providers
        self.ledger = ledger
        self.sleep = sleep
        self._sems: dict[str, asyncio.Semaphore] = {}

    def _sem(self, provider: str) -> asyncio.Semaphore:
        if provider not in self._sems:
            self._sems[provider] = asyncio.Semaphore(self.config.limit(provider))
        return self._sems[provider]

    async def run(self, targets: Iterable[str] | None = None) -> RunReport:
        m = self.manifest
        self._sems = {}
        fps = compute_fingerprints(m, self.config, self.store.dir, self.store.pins())
        scope = m.scope(targets)
        order = [nid for nid in m.topo_order() if nid in scope]
        report = RunReport()
        status: dict[str, str] = {}

        for nid in order:
            if self.store.is_fresh(m.nodes[nid], fps[nid]):
                status[nid] = "done"
                report.skipped.append(nid)
                if self.store.get(nid).status != "done":
                    self.store.update(nid, status="done", reason=None, message=None)
            else:
                status[nid] = "pending"
                self.store.update(nid, status="pending", reason=None, message=None)

        running: dict[asyncio.Task, str] = {}

        def launch_ready() -> None:
            for nid in order:
                if status[nid] == "pending" and all(status[d] == "done" for d in m.nodes[nid].depends_on):
                    status[nid] = "running"
                    self.store.update(nid, status="running")
                    running[asyncio.create_task(self._run_node(nid, fps[nid]))] = nid

        launch_ready()
        while running:
            finished, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            for task in finished:
                nid = running.pop(task)
                outcome, reason, message = task.result()
                status[nid] = outcome
                if outcome == "done":
                    report.ran.append(nid)
                    continue
                self.store.update(nid, status=outcome, reason=reason, message=message)
                (report.failed if outcome == "failed" else report.needs_review).append(nid)
                downstream = m.descendants([nid])
                for d in order:
                    if d in downstream and status[d] == "pending":
                        status[d] = "blocked"
                        self.store.update(d, status="blocked", reason=f"upstream {nid} {outcome}", message=None)
                        report.blocked.append(d)
            launch_ready()
        return report

    async def _run_node(self, nid: str, fingerprint: str) -> Outcome:
        node = self.manifest.nodes[nid]
        try:
            route = self.config.route(node)
            provider = self.providers[route.provider]
        except ConfigError as e:
            return ("failed", "config", str(e))
        except KeyError:
            return ("failed", "config", f"no provider registered as {route.provider!r}")
        inputs = resolve_inputs(self.manifest, self.store.dir, node)
        retry = self.config.retry
        for attempt in range(1, retry.max_attempts + 1):
            ctx = CallContext(node_id=nid, model=route.model, work_dir=self.store.work_dir(nid))
            started = time.monotonic()
            try:
                async with self._sem(route.provider):
                    produced = await execute(node, provider, ctx, inputs)
            except TransientProviderError as e:
                self._log(node, route, provider, inputs, started, attempt, ok=False)
                if attempt == retry.max_attempts:
                    return ("failed", "transient", str(e))
                await self.sleep(min(retry.base_delay_s * 2 ** (attempt - 1), retry.max_delay_s))
                continue
            except ProviderRefusal as e:
                self._log(node, route, provider, inputs, started, attempt, ok=False)
                return ("needs_review", "refused", str(e))
            except Exception as e:  # hard failure: isolate it to this node
                self._log(node, route, provider, inputs, started, attempt, ok=False)
                return ("failed", "error", f"{type(e).__name__}: {e}")
            self._log(node, route, provider, inputs, started, attempt, ok=True)
            self.store.commit(node, produced, fingerprint)
            return ("done", None, None)
        raise AssertionError("unreachable")

    def _log(self, node: Node, route: Route, provider: Provider, inputs: dict, started: float, attempt: int, ok: bool) -> None:
        if node.type not in GENERATION_TYPES:
            return
        self.ledger.record(
            node_id=node.id,
            provider=route.provider,
            model=route.model,
            cost_usd=provider.cost(node.type, cost_params(node, inputs)),
            seconds=round(time.monotonic() - started, 3),
            attempt=attempt,
            ok=ok,
        )
```

Note: `test_unknown_provider_fails_the_node` expects reason `config`. The `KeyError` branch covers a provider name that is configured but has no registered instance.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: 13 passed.

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -q`
Expected: all tests pass (66 so far).

- [ ] **Step 7: Commit**

```bash
git add engine/core/scheduler.py tests/helpers.py tests/test_scheduler.py
git commit -m "feat(engine): pipelined async DAG scheduler with retries and isolation"
```

---

### Task 7: Project library API (run, dry-run, status, revise, rollback)

**Files:**
- Create: `engine/core/project.py`
- Test: `tests/test_project.py`

**Interfaces:**
- Consumes: everything from Tasks 1–6, plus `build_providers` (Task 5).
- Produces (the API the CLI uses here and the MCP server uses in plan 6):
  - `engine.core.project.PlannedNode(node_id: str, provider: str, model: str, cost_usd: float, provider_available: bool)`
  - `engine.core.project.DryRunReport(to_run: list[PlannedNode], cached: list[str])` with property `total_cost: float`
  - `engine.core.project.REVISABLE = frozenset({"prompt","inputs","provider","model","depends_on"})`
  - `engine.core.project.Project(project_dir: Path, config: EngineConfig | None = None)`:
    - `Project.open(project_dir, config_path: Path | None = None) -> Project`. Uses `<project>/config.yaml` when present and no path is given.
    - `.dir`, `.config`, `.manifest_path`
    - `.manifest() -> Manifest`, `.store() -> ProjectStore`, `.ledger() -> Ledger`
    - `async .run(targets=None, providers=None) -> RunReport`
    - `.dry_run(targets=None, providers=None) -> DryRunReport` (zero provider calls)
    - `.status() -> list[tuple[str, NodeState]]` (topological order)
    - `.revise(node_id: str, changes: dict) -> None`. `inputs` is merged key-by-key (a `None` value deletes the key). Other keys replace, and `None` deletes. The result is validated, saved, and the node unpinned. Raises `ValueError`/`KeyError`/`ManifestError`, and the manifest is untouched on error.
    - `.rollback(node_id: str, version: int) -> int`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_project.py`:

```python
import asyncio

import pytest

from engine.core.graph import ManifestError
from engine.core.project import Project
from tests.helpers import FAST, RecordingProvider


def run(project, provider=None):
    provider = provider or RecordingProvider()
    report = asyncio.run(project.run(providers={"mock": provider}))
    return report, provider


def test_dry_run_on_fresh_project_plans_everything(project_dir):
    report = Project(project_dir, FAST).dry_run(providers={"mock": RecordingProvider(cost_per_call=0.5)})
    assert len(report.to_run) == 17 and report.cached == []
    assert report.total_cost == pytest.approx(11 * 0.5)
    first = report.to_run[0]
    assert (first.node_id, first.provider, first.model) == ("refs.product_hero", "mock", "mock-image")
    assert not (project_dir / "state.json").exists()


def test_dry_run_makes_no_provider_calls(project_dir):
    p = RecordingProvider()
    Project(project_dir, FAST).dry_run(providers={"mock": p})
    assert p.calls == []


def test_dry_run_after_run_is_all_cached(project_dir):
    project = Project(project_dir, FAST)
    run(project)
    report = project.dry_run(providers={"mock": RecordingProvider()})
    assert report.to_run == [] and len(report.cached) == 17


def test_dry_run_flags_unregistered_provider(project_dir):
    project = Project(project_dir, FAST)
    project.revise("v1.vo.l01", {"provider": "fishaudio", "model": "s1"})
    planned = {p.node_id: p for p in project.dry_run(providers={"mock": RecordingProvider()}).to_run}
    assert planned["v1.vo.l01"].provider_available is False


def test_status_lists_nodes_in_topological_order(project_dir):
    project = Project(project_dir, FAST)
    run(project)
    rows = project.status()
    assert rows[0][0] == "refs.product_hero"
    assert len(rows) == 17 and all(st.status == "done" and st.version == 1 for _, st in rows)


def test_revise_prompt_rerenders_chain(project_dir):
    project = Project(project_dir, FAST)
    run(project)
    project.revise("v1.s01.keyframe", {"prompt": "darker"})
    assert project.manifest().nodes["v1.s01.keyframe"].prompt == "darker"
    assert {p.node_id for p in project.dry_run(providers={"mock": RecordingProvider()}).to_run} == {
        "v1.s01.keyframe", "v1.s01.clip", "v1.timeline", "v1.preview", "v1.capcut_draft",
    }


def test_revise_merges_inputs(project_dir):
    project = Project(project_dir, FAST)
    project.revise("v1.s01.clip", {"inputs": {"duration": 5, "aspect": None}})
    assert project.manifest().nodes["v1.s01.clip"].inputs == {"first_frame": "@v1.s01.keyframe", "duration": 5}


def test_revise_rejects_unknown_fields_and_nodes(project_dir):
    project = Project(project_dir, FAST)
    with pytest.raises(ValueError, match="cannot revise"):
        project.revise("v1.s01.clip", {"type": "image"})
    with pytest.raises(KeyError):
        project.revise("v9.s01.clip", {"prompt": "x"})


def test_invalid_revision_leaves_manifest_untouched(project_dir):
    project = Project(project_dir, FAST)
    before = (project_dir / "manifest.json").read_text()
    with pytest.raises(ManifestError):
        project.revise("v1.s01.clip", {"inputs": {"first_frame": "@v9.s01.keyframe"}})
    assert (project_dir / "manifest.json").read_text() == before


def test_rollback_pins_until_next_revise(project_dir):
    project = Project(project_dir, FAST)
    run(project)
    project.revise("v1.vo.l01", {"inputs": {"text": "Second take"}})
    run(project)
    out = project_dir / "v1/vo/l01.wav"
    assert b"Second take" in out.read_bytes()

    assert project.rollback("v1.vo.l01", 1) == 3
    assert b"Line for v1" in out.read_bytes()

    _, p = run(project)
    assert set(p.calls) == {"v1.timeline", "v1.preview", "v1.capcut_draft"}
    _, p = run(project)
    assert p.calls == []

    project.revise("v1.vo.l01", {"inputs": {"text": "Third take"}})
    _, p = run(project)
    assert set(p.calls) == {"v1.vo.l01", "v1.timeline", "v1.preview", "v1.capcut_draft"}


def test_open_uses_project_config_yaml(project_dir):
    (project_dir / "config.yaml").write_text("concurrency: {mock: 3}\n")
    assert Project.open(project_dir).config.limit("mock") == 3
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_project.py -v`
Expected: `ModuleNotFoundError: No module named 'engine.core.project'`.

- [ ] **Step 3: Implement the project API**

Create `engine/core/project.py`:

```python
"""Library API over one project folder. The CLI and (plan 6) the MCP server are thin layers on this."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from engine.config import EngineConfig, load_config
from engine.core.cache import compute_fingerprints
from engine.core.executors import cost_params
from engine.core.graph import Manifest, load_manifest, save_manifest
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

    async def run(self, targets: Iterable[str] | None = None, providers: dict[str, Provider] | None = None) -> RunReport:
        scheduler = Scheduler(self.manifest(), self.store(), self.config, self._providers(providers), self.ledger())
        return await scheduler.run(targets)

    def dry_run(self, targets: Iterable[str] | None = None, providers: dict[str, Provider] | None = None) -> DryRunReport:
        manifest, store, provs = self.manifest(), self.store(), self._providers(providers)
        fps = compute_fingerprints(manifest, self.config, self.dir, store.pins())
        scope = manifest.scope(targets)
        report = DryRunReport()
        for nid in manifest.topo_order():
            if nid not in scope:
                continue
            node = manifest.nodes[nid]
            if store.is_fresh(node, fps[nid]):
                report.cached.append(nid)
                continue
            route = self.config.route(node)
            provider = provs.get(route.provider)
            cost = provider.cost(node.type, cost_params(node, resolve_inputs(manifest, self.dir, node))) if provider else 0.0
            report.to_run.append(PlannedNode(nid, route.provider, route.model, cost, provider is not None))
        return report

    def status(self) -> list[tuple[str, NodeState]]:
        store = self.store()
        return [(nid, store.nodes.get(nid, NodeState())) for nid in self.manifest().topo_order()]

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
        save_manifest(manifest, self.manifest_path)
        self.store().unpin(node_id)

    def rollback(self, node_id: str, version: int) -> int:
        manifest = self.manifest()
        if node_id not in manifest.nodes:
            raise KeyError(f"unknown node {node_id}")
        return self.store().rollback(manifest.nodes[node_id], version)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_project.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/core/project.py tests/test_project.py
git commit -m "feat(engine): project API for run, dry-run, status, revise, rollback"
```

---

### Task 8: `adengine` CLI, example config, mock end-to-end test

**Files:**
- Create: `engine/cli.py`, `config.example.yaml`
- Test: `tests/test_cli.py`, `tests/test_e2e_mock.py`

**Interfaces:**
- Consumes: `Project`, `DryRunReport`, `RunReport` (Task 7), `load_manifest`, `ManifestError` (Task 1), `ConfigError`, `load_config` (Task 3), `Ledger` (Task 5).
- Produces: `engine.cli.main(argv: list[str] | None = None) -> int` and the `adengine` console script with these subcommands:
  - `validate <project>` prints `OK: <n> nodes`, or one `ERROR: ...` line per problem on stderr (exit 1)
  - `dry-run <project> [--only PATTERN]...` prints one `RUN`/`CACHED` line per node, then `<a> to run, <b> cached, estimated cost: $X.XX`
  - `estimate <project> [--only PATTERN]...` prints `estimated cost: $X.XX for <a> nodes`
  - `run <project> [--only PATTERN]...` prints `ran A, cached B, failed C, needs_review D, blocked E` plus an `ATTENTION <id>` line for each failed or needs_review node. Exits 0 only if the report is ok.
  - `status <project>`
  - `revise <project> <node_id> --json '<changes>' [--no-run]`
  - `rollback <project> <node_id> <version>`
  - The global option `--config PATH` comes before the subcommand.

- [ ] **Step 1: Write the failing CLI and end-to-end tests**

Create `tests/test_cli.py`:

```python
import json
from pathlib import Path

from engine.cli import main
from engine.config import load_config


def test_validate_ok(project_dir, capsys):
    assert main(["validate", str(project_dir)]) == 0
    assert capsys.readouterr().out.strip() == "OK: 17 nodes"


def test_validate_reports_every_error(project_dir, capsys):
    data = json.loads((project_dir / "manifest.json").read_text())
    data["nodes"][1]["depends_on"] = []
    (project_dir / "manifest.json").write_text(json.dumps(data))
    assert main(["validate", str(project_dir)]) == 1
    assert "ERROR: v1.s01.keyframe: input references @refs.product_hero" in capsys.readouterr().err


def test_dry_run_and_estimate(project_dir, capsys):
    assert main(["dry-run", str(project_dir)]) == 0
    out = capsys.readouterr().out
    assert "RUN    refs.product_hero" in out
    assert out.strip().endswith("17 to run, 0 cached, estimated cost: $0.00")
    assert main(["estimate", str(project_dir), "--only", "refs.*"]) == 0
    assert capsys.readouterr().out.strip() == "estimated cost: $0.00 for 1 nodes"


def test_run_status_revise_rollback(project_dir, capsys):
    assert main(["run", str(project_dir)]) == 0
    assert capsys.readouterr().out.strip() == "ran 17, cached 0, failed 0, needs_review 0, blocked 0"

    assert main(["status", str(project_dir)]) == 0
    status = capsys.readouterr().out
    assert "refs.product_hero" in status and "done" in status and "v1" in status

    assert main(["revise", str(project_dir), "v1.vo.l01", "--json", '{"inputs": {"text": "Take two"}}']) == 0
    out = capsys.readouterr().out
    assert "revised v1.vo.l01" in out
    assert "ran 4, cached 13" in out

    assert main(["rollback", str(project_dir), "v1.vo.l01", "1"]) == 0
    assert "restored from v1 as v3" in capsys.readouterr().out


def test_errors_exit_nonzero_with_message(project_dir, capsys):
    assert main(["rollback", str(project_dir), "v1.vo.l01", "9"]) == 1
    assert "ERROR:" in capsys.readouterr().err
    assert main(["revise", str(project_dir), "v1.vo.l01", "--json", '{"type": "image"}']) == 1
    assert "cannot revise" in capsys.readouterr().err


def test_example_config_loads():
    cfg = load_config(Path(__file__).resolve().parents[1] / "config.example.yaml")
    assert cfg.routing["video"].provider == "mock"
```

Create `tests/test_e2e_mock.py`:

```python
"""Spec §10 mock end-to-end, engine half: manifest → parallel run → every
variant's timeline, preview and CapCut draft exist. Plan 2 extends this with
real assembly; plan 5 extends it back to the brief."""
import json

from engine.cli import main
from engine.core.ledger import Ledger


def test_mock_end_to_end(project_dir):
    assert main(["run", str(project_dir)]) == 0
    for rel in [
        "refs/product_hero.png",
        "v1/shots/s01/keyframe.png", "v1/shots/s02/clip.mp4", "v1/vo/l01.wav",
        "v1/timeline.json", "v1/preview.mp4", "v1/capcut_draft/draft_content.json",
        "v2/shots/s02/clip.mp4", "v2/timeline.json", "v2/preview.mp4", "v2/capcut_draft/draft_content.json",
    ]:
        assert (project_dir / rel).exists(), rel
    state = json.loads((project_dir / "state.json").read_text())["nodes"]
    assert len(state) == 17 and {s["status"] for s in state.values()} == {"done"}
    assert len(Ledger(project_dir / "ledger.jsonl").entries()) == 11
    assert main(["run", str(project_dir)]) == 0  # resumable / idempotent
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py tests/test_e2e_mock.py -v`
Expected: `ModuleNotFoundError: No module named 'engine.cli'`.

- [ ] **Step 3: Write the example config**

Create `config.example.yaml`:

```yaml
# AdForge engine config. Copy to projects/<slug>/config.yaml or pass --config.
# Model names live here, never in engine code. Secrets come from env / .env only.
routing:
  image:        {provider: mock, model: mock-image}
  video:        {provider: mock, model: mock-video}
  tts:          {provider: mock, model: mock-tts}
  sfx:          {provider: mock, model: mock-sfx}
  music:        {provider: mock, model: mock-music}
  timeline:     {provider: mock, model: mock-timeline}
  preview:      {provider: mock, model: mock-preview}
  capcut_draft: {provider: mock, model: mock-capcut_draft}

# Max simultaneous calls per provider. Real providers arrive in plan 3, e.g.
#   openai_image: 8
#   seedance: 4
#   fishaudio: 10
concurrency:
  mock: 8
default_concurrency: 4

# Temporary failures (429/5xx/timeouts) retry with exponential backoff.
retry:
  max_attempts: 3
  base_delay_s: 1.0
  max_delay_s: 30.0
```

- [ ] **Step 4: Implement the CLI**

Create `engine/cli.py`:

```python
"""adengine: run AdForge manifests without Claude attached."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from engine.config import ConfigError
from engine.core.graph import ManifestError, load_manifest
from engine.core.project import Project
from engine.core.scheduler import RunReport


def _project(args: argparse.Namespace) -> Project:
    return Project.open(args.project, args.config)


def _print_report(report: RunReport) -> None:
    print(
        f"ran {len(report.ran)}, cached {len(report.skipped)}, failed {len(report.failed)}, "
        f"needs_review {len(report.needs_review)}, blocked {len(report.blocked)}"
    )
    for nid in report.failed + report.needs_review:
        print(f"ATTENTION {nid}")


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        manifest = load_manifest(Path(args.project) / "manifest.json")
    except ManifestError as e:
        for err in e.errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1
    print(f"OK: {len(manifest.nodes)} nodes")
    return 0


def cmd_dry_run(args: argparse.Namespace) -> int:
    report = _project(args).dry_run(args.only)
    for p in report.to_run:
        note = "" if p.provider_available else "  (provider not registered)"
        print(f"RUN    {p.node_id:<28} {p.provider}/{p.model}  ${p.cost_usd:.2f}{note}")
    for nid in report.cached:
        print(f"CACHED {nid}")
    print(f"{len(report.to_run)} to run, {len(report.cached)} cached, estimated cost: ${report.total_cost:.2f}")
    return 0


def cmd_estimate(args: argparse.Namespace) -> int:
    report = _project(args).dry_run(args.only)
    print(f"estimated cost: ${report.total_cost:.2f} for {len(report.to_run)} nodes")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    report = asyncio.run(_project(args).run(args.only))
    _print_report(report)
    return 0 if report.ok else 1


def cmd_status(args: argparse.Namespace) -> int:
    for nid, st in _project(args).status():
        line = f"{nid:<28} {st.status:<13} v{st.version}"
        if st.pinned_version is not None:
            line += " (pinned)"
        if st.reason:
            line += f"  {st.reason}: {st.message or ''}"
        print(line)
    return 0


def cmd_revise(args: argparse.Namespace) -> int:
    project = _project(args)
    project.revise(args.node_id, json.loads(args.json))
    print(f"revised {args.node_id}")
    if args.no_run:
        return 0
    report = asyncio.run(project.run())
    _print_report(report)
    return 0 if report.ok else 1


def cmd_rollback(args: argparse.Namespace) -> int:
    new_version = _project(args).rollback(args.node_id, args.version)
    print(f"{args.node_id} restored from v{args.version} as v{new_version} (pinned until next revise)")
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="adengine", description="AdForge render engine")
    p.add_argument("--config", type=Path, default=None, help="config YAML (default: <project>/config.yaml)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name: str, fn, help_text: str, targets: bool = False) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("project", type=Path)
        if targets:
            sp.add_argument("--only", action="append", default=None, metavar="PATTERN",
                            help="node id glob; repeatable (ancestors are included)")
        sp.set_defaults(fn=fn)
        return sp

    add("validate", cmd_validate, "validate manifest.json")
    add("dry-run", cmd_dry_run, "show what would run and the estimated cost; no API calls", targets=True)
    add("estimate", cmd_estimate, "estimated cost of what would run", targets=True)
    add("run", cmd_run, "render stale nodes", targets=True)
    add("status", cmd_status, "per-node status")
    rv = add("revise", cmd_revise, "change one node, then re-render what it affects")
    rv.add_argument("node_id")
    rv.add_argument("--json", required=True, help='changes, e.g. \'{"prompt": "..."}\'')
    rv.add_argument("--no-run", action="store_true")
    rb = add("rollback", cmd_rollback, "restore an earlier version of a node")
    rb.add_argument("node_id")
    rb.add_argument("version", type=int)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.fn(args)
    except (ManifestError, ConfigError, ValueError, KeyError, FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli.py tests/test_e2e_mock.py -v`
Expected: 7 passed.

- [ ] **Step 6: Run the full suite and a manual smoke test**

Run: `uv run pytest -q`
Expected: all tests pass (84 total).

Run:

```bash
SMOKE=$(mktemp -d)/demo && mkdir -p "$SMOKE"
uv run python -c "import json; from tests.helpers import make_manifest; print(json.dumps(make_manifest(), indent=2))" > "$SMOKE/manifest.json"
uv run adengine validate "$SMOKE"
uv run adengine run "$SMOKE"
uv run adengine status "$SMOKE" | head -5
```

Expected: `OK: 17 nodes`, then `ran 17, cached 0, failed 0, needs_review 0, blocked 0`, then status lines showing `done   v1`.

- [ ] **Step 7: Commit**

```bash
git add engine/cli.py config.example.yaml tests/test_cli.py tests/test_e2e_mock.py
git commit -m "feat(engine): adengine CLI, example config, mock end-to-end test"
```

---

## Spec coverage (Plan 1)

| Spec item | Task |
|---|---|
| §3 manifest.json is the contract; schema file | 1 |
| §4 node schema, types, ID format, `@ref` + `depends_on` rule, status values | 1, 6 |
| §4 project folder layout (`refs/`, `vN/shots/sNN/`, `vo/`, `sfx/`, `music/`, `timeline.json`, `preview.mp4`, `capcut_draft/`) | 2 |
| §4 fingerprint + downstream invalidation | 3, 6 |
| §4 versioning + rollback | 4, 7, 8 |
| §4 shared vs per-variant (shared nodes render once) | 1 (fixture), 6 |
| §6 CLI `run/status/revise/rollback/estimate/dry-run` | 8 |
| §6 core as library, CLI thin | 7, 8 |
| §6 scheduler: pipelining, per-provider caps, state.json resume | 6 |
| §6 provider interface, routing defaults, node override, `cost()` | 3, 5 |
| §6 mock provider | 5 |
| §8 transient retry/backoff, refusal → needs_review, hard failure isolation | 6 |
| §9 ledger.jsonl, dry-run with zero API calls | 5, 6, 7 |
| §10 unit tests listed + mock end-to-end (engine half) | all |

Deferred by design: assembly (plan 2), real providers, fallback chains, and secrets (plan 3), QC best-of-n (plan 4), brain (plan 5), MCP server and `budget.max_usd` enforcement (plan 6).
