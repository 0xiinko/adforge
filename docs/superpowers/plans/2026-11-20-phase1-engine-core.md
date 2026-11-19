# AdForge Phase 1 — Engine Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the AdForge execution engine core: manifest contract, dependency graph, fingerprint-based caching, parallel scheduler with per-provider concurrency caps, retries/fallbacks/budget guardrails, per-node revise/rollback, cost estimation and a CLI — all running end-to-end against a mock provider.

**Architecture:** `manifest.json` (brain-authored, pydantic-validated) describes a DAG of asset nodes with stable IDs. The engine computes a fingerprint per node (spec + upstream fingerprints), skips nodes whose fingerprint and output are unchanged, and renders the rest with asyncio, starting each node as soon as its dependencies finish. Runtime state (status, version, fingerprint, output path) lives in `state.json`; paid calls go to `ledger.jsonl`; replaced outputs move to `versions/`.

**Tech Stack:** Python 3.12, uv, pydantic v2, PyYAML, pytest + pytest-asyncio, stdlib argparse/asyncio.

**Spec:** `docs/superpowers/specs/2026-11-20-adforge-design.md` (this plan = build-order step 1, plus the CLI part of step 7).

## Global Constraints

- Repo root: `/home/iinko/PROJECT_AUTOMATION/adforge`. All paths below are relative to it.
- Python `>=3.11`; dependencies limited to `pydantic>=2.6`, `pyyaml>=6.0`; dev: `pytest>=8.0`, `pytest-asyncio>=0.23`.
- Run everything through uv: `uv run pytest ...`, `uv run adengine ...`.
- In this machine's shell `git` is aliased to a broken wrapper — invoke it as `command git ...`.
- Node ID regex: `^[a-z0-9_]+(\.[a-z0-9_]+){1,2}$`. References in `inputs` are strings starting with `@`.
- Node types in Phase 1: `image, video, lipsync, tts, sfx, music, timeline, preview, capcut_draft` (`creator_asset` arrives in Phase 5).
- Engine never makes creative decisions and never rewrites prompts.
- Secrets never appear in manifests, state, or ledger.
- **Spec refinements locked by this plan:** node `status`/`version` live in `state.json` (not in `manifest.json`); all audio outputs are `.wav`; providers implement one generic `render(RenderRequest) -> Path` + `cost(node) -> float` (the typed per-kind methods in the spec become internals of concrete adapters).

## File Structure

```
pyproject.toml                    # package + adengine script + pytest config
.gitignore
engine/__init__.py
engine/config.py                  # EngineConfig (providers, routing defaults, retry, budget) + load_config
engine/core/__init__.py
engine/core/manifest.py           # Node, Manifest, NodeType, find_refs, load/save, export_schema
engine/core/graph.py              # topo_order, ancestors, descendants, select (pure functions on {id: deps})
engine/core/fingerprint.py        # fingerprint, fingerprint_all
engine/core/store.py              # ProjectStore (paths, state.json, versions/, ref resolution), NodeState
engine/core/ledger.py             # Ledger (append-only jsonl cost log)
engine/core/scheduler.py          # Scheduler, RunReport
engine/core/revise.py             # revise, rollback
engine/core/estimate.py           # estimate, Estimate
engine/core/status.py             # project_status
engine/providers/__init__.py
engine/providers/base.py          # Provider ABC, RenderRequest, TransientError, RefusalError
engine/providers/mock.py          # MockProvider (delays, failure injection, call log)
engine/providers/registry.py      # ADAPTERS, ProviderRegistry (routing + fallback chains)
engine/cli.py                     # adengine CLI
schemas/manifest.schema.json      # generated from Manifest
tests/__init__.py
tests/helpers.py                  # SAMPLE_NODES, write_manifest, mock_config, make_scheduler
tests/fixtures/sample_project/manifest.json
tests/test_*.py
README.md
```

---

### Task 1: Repo scaffold + manifest contract

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `engine/__init__.py`, `engine/core/__init__.py`, `engine/core/graph.py` (cycle check only needed here; full graph API in Task 2 — create the complete file now), `engine/core/manifest.py`, `tests/__init__.py`, `tests/test_manifest.py`, `schemas/manifest.schema.json` (generated)

**Interfaces:**
- Produces:
  - `engine.core.manifest.NodeType` (str Enum: `image video lipsync tts sfx music timeline preview capcut_draft`)
  - `engine.core.manifest.REF_PREFIX = "@"`, `ID_PATTERN: str`
  - `class Node(BaseModel)`: `id: str, type: NodeType, provider: str|None, model: str|None, prompt: str = "", inputs: dict[str, Any], depends_on: list[str]` (extra fields forbidden)
  - `class Manifest(BaseModel)`: `project: str, nodes: list[Node]`; methods `by_id() -> dict[str, Node]`, `get(node_id) -> Node` (raises `KeyError`), `deps() -> dict[str, list[str]]`
  - `find_refs(value: Any) -> set[str]`, `load_manifest(path: Path) -> Manifest`, `save_manifest(manifest, path) -> None`, `export_schema(path: Path) -> None`
  - `engine.core.graph`: `CycleError(ValueError)`, `topo_order(deps) -> list[str]`, `ancestors(deps, node_id) -> set[str]`, `descendants(deps, node_id) -> set[str]`, `select(deps, patterns: list[str]) -> set[str]`

- [ ] **Step 1: Initialise repo and project files**

```bash
cd /home/iinko/PROJECT_AUTOMATION/adforge
command git init
mkdir -p engine/core engine/providers schemas tests/fixtures/sample_project
```

`pyproject.toml`:
```toml
[project]
name = "adforge"
version = "0.1.0"
description = "AdForge: brief-to-CapCut AI ad engine"
requires-python = ">=3.11"
dependencies = ["pydantic>=2.6", "pyyaml>=6.0"]

[project.scripts]
adengine = "engine.cli:main"

[dependency-groups]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["engine"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
.pytest_cache/
projects/
.env
```

Create empty files: `engine/__init__.py`, `engine/core/__init__.py`, `engine/providers/__init__.py`, `tests/__init__.py`.

Note: `engine/cli.py` does not exist yet; `uv sync` only installs the script stub, which is fine.

Run: `uv sync`
Expected: creates `.venv`, installs pydantic, pyyaml, pytest, pytest-asyncio, and the `adforge` package in editable mode.

- [ ] **Step 2: Write `engine/core/graph.py`** (pure functions; manifest validation depends on `topo_order`)

```python
from __future__ import annotations

from collections import deque
from fnmatch import fnmatchcase

Deps = dict[str, list[str]]


class CycleError(ValueError):
    pass


def topo_order(deps: Deps) -> list[str]:
    """Deterministic topological order (dependencies first)."""
    indegree = {node: len(set(parents)) for node, parents in deps.items()}
    children: dict[str, list[str]] = {node: [] for node in deps}
    for node, parents in deps.items():
        for parent in set(parents):
            children[parent].append(node)
    queue = deque(sorted(node for node, count in indegree.items() if count == 0))
    order: list[str] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for child in sorted(children[node]):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if len(order) != len(deps):
        stuck = sorted(set(deps) - set(order))
        raise CycleError(f"dependency cycle among: {stuck}")
    return order


def ancestors(deps: Deps, node_id: str) -> set[str]:
    seen: set[str] = set()
    stack = list(deps[node_id])
    while stack:
        node = stack.pop()
        if node not in seen:
            seen.add(node)
            stack.extend(deps[node])
    return seen


def descendants(deps: Deps, node_id: str) -> set[str]:
    children: dict[str, list[str]] = {node: [] for node in deps}
    for node, parents in deps.items():
        for parent in parents:
            children[parent].append(node)
    seen: set[str] = set()
    stack = list(children[node_id])
    while stack:
        node = stack.pop()
        if node not in seen:
            seen.add(node)
            stack.extend(children[node])
    return seen


def select(deps: Deps, patterns: list[str]) -> set[str]:
    """Nodes matching any glob pattern, plus all their ancestors."""
    matched = {node for node in deps if any(fnmatchcase(node, p) for p in patterns)}
    if not matched:
        raise KeyError(f"no nodes match {patterns}")
    result = set(matched)
    for node in matched:
        result |= ancestors(deps, node)
    return result
```

- [ ] **Step 3: Write the failing manifest tests** — `tests/test_manifest.py`

```python
import json

import pytest
from pydantic import ValidationError

from engine.core.manifest import (
    Manifest,
    NodeType,
    export_schema,
    find_refs,
    load_manifest,
    save_manifest,
)


def mk(nodes):
    return Manifest.model_validate({"project": "demo", "nodes": nodes})


def test_valid_manifest_parses():
    m = mk([
        {"id": "refs.hero", "type": "image", "prompt": "a mug"},
        {"id": "v1.s01.keyframe", "type": "image",
         "inputs": {"refs": ["@refs.hero"]}, "depends_on": ["refs.hero"]},
    ])
    assert m.get("v1.s01.keyframe").type is NodeType.image
    assert m.deps() == {"refs.hero": [], "v1.s01.keyframe": ["refs.hero"]}
    assert set(m.by_id()) == {"refs.hero", "v1.s01.keyframe"}


def test_get_unknown_raises_keyerror():
    with pytest.raises(KeyError):
        mk([{"id": "refs.hero", "type": "image"}]).get("nope.nope")


@pytest.mark.parametrize("bad_id", ["V1.s01", "single", "a.b.c.d", "v1..x", "v1.s-1.clip"])
def test_rejects_bad_ids(bad_id):
    with pytest.raises(ValidationError):
        mk([{"id": bad_id, "type": "image"}])


def test_rejects_duplicate_ids():
    with pytest.raises(ValidationError, match="duplicate"):
        mk([{"id": "refs.hero", "type": "image"}, {"id": "refs.hero", "type": "image"}])


def test_rejects_unknown_dependency():
    with pytest.raises(ValidationError, match="unknown node"):
        mk([{"id": "v1.s01.clip", "type": "video", "depends_on": ["v1.s01.keyframe"]}])


def test_rejects_ref_not_in_depends_on():
    with pytest.raises(ValidationError, match="not listed in depends_on"):
        mk([
            {"id": "v1.s01.keyframe", "type": "image"},
            {"id": "v1.s01.clip", "type": "video", "inputs": {"first_frame": "@v1.s01.keyframe"}},
        ])


def test_rejects_cycle():
    with pytest.raises(ValidationError, match="cycle"):
        mk([
            {"id": "a.b", "type": "image", "depends_on": ["c.d"]},
            {"id": "c.d", "type": "image", "depends_on": ["a.b"]},
        ])


def test_rejects_unknown_field():
    with pytest.raises(ValidationError):
        mk([{"id": "refs.hero", "type": "image", "status": "done"}])


def test_find_refs_nested():
    value = {"a": "@x.y", "b": ["@p.q", {"c": "@r.s"}], "d": "plain", "e": 3}
    assert find_refs(value) == {"x.y", "p.q", "r.s"}


def test_save_load_roundtrip(tmp_path):
    m = mk([{"id": "refs.hero", "type": "image", "prompt": "a mug"}])
    path = tmp_path / "manifest.json"
    save_manifest(m, path)
    assert load_manifest(path) == m


def test_export_schema(tmp_path):
    path = tmp_path / "schema.json"
    export_schema(path)
    data = json.loads(path.read_text())
    assert "nodes" in data["properties"]
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/test_manifest.py -v`
Expected: FAIL / collection error `ModuleNotFoundError: No module named 'engine.core.manifest'`

- [ ] **Step 5: Implement `engine/core/manifest.py`**

```python
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from engine.core.graph import topo_order

ID_PATTERN = r"^[a-z0-9_]+(\.[a-z0-9_]+){1,2}$"
REF_PREFIX = "@"


class NodeType(str, Enum):
    image = "image"
    video = "video"
    lipsync = "lipsync"
    tts = "tts"
    sfx = "sfx"
    music = "music"
    timeline = "timeline"
    preview = "preview"
    capcut_draft = "capcut_draft"


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ID_PATTERN)
    type: NodeType
    provider: str | None = None
    model: str | None = None
    prompt: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)


def find_refs(value: Any) -> set[str]:
    """All node IDs referenced as '@id' anywhere inside value."""
    if isinstance(value, str):
        return {value[len(REF_PREFIX):]} if value.startswith(REF_PREFIX) else set()
    if isinstance(value, dict):
        return set().union(*(find_refs(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(find_refs(v) for v in value))
    return set()


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str
    nodes: list[Node]

    @model_validator(mode="after")
    def _check_graph(self) -> "Manifest":
        ids = [n.id for n in self.nodes]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate node ids: {dupes}")
        known = set(ids)
        for node in self.nodes:
            for dep in node.depends_on:
                if dep not in known:
                    raise ValueError(f"{node.id}: depends_on unknown node '{dep}'")
            missing = find_refs(node.inputs) - set(node.depends_on)
            if missing:
                raise ValueError(f"{node.id}: inputs reference {sorted(missing)} not listed in depends_on")
        topo_order(self.deps())  # raises CycleError (a ValueError) on cycles
        return self

    def by_id(self) -> dict[str, Node]:
        return {n.id: n for n in self.nodes}

    def get(self, node_id: str) -> Node:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise KeyError(f"unknown node '{node_id}'")

    def deps(self) -> dict[str, list[str]]:
        return {n.id: list(n.depends_on) for n in self.nodes}


def load_manifest(path: Path) -> Manifest:
    return Manifest.model_validate_json(Path(path).read_text(encoding="utf-8"))


def save_manifest(manifest: Manifest, path: Path) -> None:
    Path(path).write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def export_schema(path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(Manifest.model_json_schema(), indent=2) + "\n", encoding="utf-8")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_manifest.py -v`
Expected: 15 passed

- [ ] **Step 7: Generate the committed schema file**

Run: `uv run python -c "from engine.core.manifest import export_schema; export_schema('schemas/manifest.schema.json')"`
Expected: `schemas/manifest.schema.json` exists and contains `"nodes"`.

- [ ] **Step 8: Commit**

```bash
command git add .gitignore pyproject.toml uv.lock engine tests schemas docs
command git commit -m "feat: scaffold adforge engine and manifest contract"
```

---

### Task 2: Graph utilities tests

**Files:**
- Test: `tests/test_graph.py` (implementation already written in Task 1 Step 2)

**Interfaces:**
- Consumes: `engine.core.graph.{topo_order, ancestors, descendants, select, CycleError}`
- Produces: verified graph API used by Tasks 3, 6, 8, 9.

- [ ] **Step 1: Write the tests** — `tests/test_graph.py`

```python
import pytest

from engine.core.graph import CycleError, ancestors, descendants, select, topo_order

DEPS = {
    "refs.hero": [],
    "v1.s01.keyframe": ["refs.hero"],
    "v1.s01.clip": ["v1.s01.keyframe"],
    "v1.vo.l01": [],
    "v1.timeline": ["v1.s01.clip", "v1.vo.l01"],
}


def test_topo_order_respects_dependencies():
    order = topo_order(DEPS)
    assert sorted(order) == sorted(DEPS)
    for node, parents in DEPS.items():
        for parent in parents:
            assert order.index(parent) < order.index(node)


def test_topo_order_is_deterministic_regardless_of_insertion_order():
    reversed_deps = dict(reversed(list(DEPS.items())))
    assert topo_order(DEPS) == topo_order(reversed_deps)


def test_cycle_raises():
    with pytest.raises(CycleError, match="cycle"):
        topo_order({"a.b": ["c.d"], "c.d": ["a.b"]})


def test_ancestors():
    assert ancestors(DEPS, "v1.timeline") == {"v1.s01.clip", "v1.s01.keyframe", "refs.hero", "v1.vo.l01"}
    assert ancestors(DEPS, "refs.hero") == set()


def test_descendants():
    assert descendants(DEPS, "refs.hero") == {"v1.s01.keyframe", "v1.s01.clip", "v1.timeline"}
    assert descendants(DEPS, "v1.timeline") == set()


def test_select_glob_includes_ancestors():
    assert select(DEPS, ["v1.s01.*"]) == {"v1.s01.keyframe", "v1.s01.clip", "refs.hero"}


def test_select_exact_id():
    assert select(DEPS, ["v1.vo.l01"]) == {"v1.vo.l01"}


def test_select_no_match_raises():
    with pytest.raises(KeyError):
        select(DEPS, ["v9.*"])
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_graph.py -v`
Expected: 8 passed. (If any fail, fix `engine/core/graph.py`, not the test.)

- [ ] **Step 3: Commit**

```bash
command git add tests/test_graph.py
command git commit -m "test: cover dependency graph utilities"
```

---

### Task 3: Fingerprints

**Files:**
- Create: `engine/core/fingerprint.py`
- Test: `tests/test_fingerprint.py`

**Interfaces:**
- Consumes: `Node`, `Manifest`, `topo_order`
- Produces:
  - `fingerprint(node: Node, dep_fingerprints: dict[str, str], provider: str | None = None) -> str` (sha256 hex)
  - `fingerprint_all(manifest: Manifest, provider_for: Callable[[Node], str] | None = None) -> dict[str, str]` — when `provider_for` is given, its result replaces `node.provider` in the hash (so changing a routing default re-renders).

- [ ] **Step 1: Write the failing tests** — `tests/test_fingerprint.py`

```python
from engine.core.fingerprint import fingerprint_all
from engine.core.manifest import Manifest


def manifest(hero_prompt="a mug", vo_prompt="hello"):
    return Manifest.model_validate({"project": "demo", "nodes": [
        {"id": "refs.hero", "type": "image", "prompt": hero_prompt},
        {"id": "v1.s01.keyframe", "type": "image", "prompt": "kitchen",
         "inputs": {"refs": ["@refs.hero"]}, "depends_on": ["refs.hero"]},
        {"id": "v1.s01.clip", "type": "video", "prompt": "push in",
         "inputs": {"first_frame": "@v1.s01.keyframe"}, "depends_on": ["v1.s01.keyframe"]},
        {"id": "v1.vo.l01", "type": "tts", "prompt": vo_prompt},
    ]})


def test_same_spec_same_fingerprints():
    assert fingerprint_all(manifest()) == fingerprint_all(manifest())


def test_change_propagates_downstream():
    a, b = fingerprint_all(manifest()), fingerprint_all(manifest(hero_prompt="a cup"))
    for nid in ("refs.hero", "v1.s01.keyframe", "v1.s01.clip"):
        assert a[nid] != b[nid]
    assert a["v1.vo.l01"] == b["v1.vo.l01"]


def test_unrelated_change_is_isolated():
    a, b = fingerprint_all(manifest()), fingerprint_all(manifest(vo_prompt="bye"))
    assert a["v1.vo.l01"] != b["v1.vo.l01"]
    for nid in ("refs.hero", "v1.s01.keyframe", "v1.s01.clip"):
        assert a[nid] == b[nid]


def test_effective_provider_affects_fingerprint():
    m = manifest()
    a = fingerprint_all(m, provider_for=lambda n: "mock")
    b = fingerprint_all(m, provider_for=lambda n: "other")
    assert a["refs.hero"] != b["refs.hero"]


def test_fingerprint_is_sha256_hex():
    fp = fingerprint_all(manifest())["refs.hero"]
    assert len(fp) == 64 and all(c in "0123456789abcdef" for c in fp)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_fingerprint.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'engine.core.fingerprint'`

- [ ] **Step 3: Implement `engine/core/fingerprint.py`**

```python
from __future__ import annotations

import hashlib
import json
from typing import Callable

from engine.core.graph import topo_order
from engine.core.manifest import Manifest, Node


def fingerprint(node: Node, dep_fingerprints: dict[str, str], provider: str | None = None) -> str:
    payload = {
        "type": node.type.value,
        "provider": provider if provider is not None else node.provider,
        "model": node.model,
        "prompt": node.prompt,
        "inputs": node.inputs,
        "deps": {dep: dep_fingerprints[dep] for dep in sorted(node.depends_on)},
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def fingerprint_all(
    manifest: Manifest,
    provider_for: Callable[[Node], str] | None = None,
) -> dict[str, str]:
    nodes = manifest.by_id()
    result: dict[str, str] = {}
    for node_id in topo_order(manifest.deps()):
        node = nodes[node_id]
        provider = provider_for(node) if provider_for else None
        result[node_id] = fingerprint(node, result, provider)
    return result
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_fingerprint.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
command git add engine/core/fingerprint.py tests/test_fingerprint.py
command git commit -m "feat: content fingerprints with downstream propagation"
```

---

### Task 4: Project store (paths, state, versions, ref resolution)

**Files:**
- Create: `engine/core/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `Node`, `NodeType`, `REF_PREFIX`
- Produces:
  - `EXTENSIONS: dict[NodeType, str]` (`capcut_draft` → `""`, i.e. a directory)
  - `class NodeState(BaseModel)`: `status: Literal["pending","running","done","failed","blocked","needs_review"] = "pending"`, `fingerprint: str|None`, `version: int = 0`, `output: str|None` (posix path relative to project root), `spec: dict|None` (node spec that produced `output`), `reason: str|None`, `message: str|None`
  - `class ProjectStore(root: Path)` with attributes `root, manifest_path, state_path, ledger_path` and methods:
    - `output_path(node) -> Path`
    - `load_state() -> dict[str, NodeState]`, `save_state(state) -> None` (atomic)
    - `is_fresh(state, node_id, fingerprint) -> bool`
    - `archive(node, ns) -> Path | None` — moves current output to `versions/<stem>_v<ns.version><suffix>` + sidecar `<stem>_v<N>.json` = `{"fingerprint": ns.fingerprint, "node": ns.spec}`; no-op if `ns.version == 0` or output missing
    - `restore(node, ns, version) -> dict` — archives current output, copies version file back to `output_path`, returns sidecar dict; `FileNotFoundError` if version missing
    - `resolve_inputs(value, state) -> Any` — replaces `"@id"` strings (recursively) with absolute output paths

- [ ] **Step 1: Write the failing tests** — `tests/test_store.py`

```python
import json

import pytest

from engine.core.manifest import Node
from engine.core.store import NodeState, ProjectStore


@pytest.mark.parametrize("nid,ntype,rel", [
    ("v2.s03.keyframe", "image", "v2/shots/s03/keyframe.png"),
    ("v2.s03.clip", "video", "v2/shots/s03/clip.mp4"),
    ("v2.s02.talk", "lipsync", "v2/shots/s02/talk.mp4"),
    ("v2.vo.l04", "tts", "v2/vo/l04.wav"),
    ("v2.sfx.whoosh02", "sfx", "v2/sfx/whoosh02.wav"),
    ("refs.product_hero", "image", "refs/product_hero.png"),
    ("refs.music_bed", "music", "refs/music_bed.wav"),
    ("v2.timeline", "timeline", "v2/timeline.json"),
    ("v2.capcut_draft", "capcut_draft", "v2/capcut_draft"),
])
def test_output_path(tmp_path, nid, ntype, rel):
    store = ProjectStore(tmp_path)
    assert store.output_path(Node(id=nid, type=ntype)) == tmp_path / rel


def test_state_roundtrip_and_missing_file(tmp_path):
    store = ProjectStore(tmp_path)
    assert store.load_state() == {}
    state = {"refs.hero": NodeState(status="done", fingerprint="abc", version=2, output="refs/hero.png")}
    store.save_state(state)
    assert store.load_state() == state


def _render(store, node, ns, content, fp):
    out = store.output_path(node)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content)
    ns.status, ns.fingerprint, ns.version = "done", fp, ns.version + 1
    ns.output = out.relative_to(store.root).as_posix()
    ns.spec = node.model_dump(mode="json")


def test_is_fresh(tmp_path):
    store = ProjectStore(tmp_path)
    node = Node(id="refs.hero", type="image")
    ns = NodeState()
    state = {"refs.hero": ns}
    assert not store.is_fresh(state, "refs.hero", "fp1")
    _render(store, node, ns, "v1", "fp1")
    assert store.is_fresh(state, "refs.hero", "fp1")
    assert not store.is_fresh(state, "refs.hero", "fp2")
    store.output_path(node).unlink()
    assert not store.is_fresh(state, "refs.hero", "fp1")


def test_archive_noop_when_never_rendered(tmp_path):
    store = ProjectStore(tmp_path)
    assert store.archive(Node(id="refs.hero", type="image"), NodeState()) is None


def test_archive_moves_output_and_writes_sidecar(tmp_path):
    store = ProjectStore(tmp_path)
    node = Node(id="v1.s01.keyframe", type="image", prompt="old")
    ns = NodeState()
    _render(store, node, ns, "first", "fp1")
    dest = store.archive(node, ns)
    assert dest == tmp_path / "v1/shots/s01/versions/keyframe_v1.png"
    assert dest.read_text() == "first"
    assert not store.output_path(node).exists()
    sidecar = json.loads((tmp_path / "v1/shots/s01/versions/keyframe_v1.json").read_text())
    assert sidecar == {"fingerprint": "fp1", "node": node.model_dump(mode="json")}


def test_restore_copies_version_back_and_archives_current(tmp_path):
    store = ProjectStore(tmp_path)
    node = Node(id="v1.s01.keyframe", type="image")
    ns = NodeState()
    _render(store, node, ns, "first", "fp1")
    store.archive(node, ns)
    _render(store, node, ns, "second", "fp2")  # version 2
    sidecar = store.restore(node, ns, 1)
    assert sidecar["fingerprint"] == "fp1"
    assert store.output_path(node).read_text() == "first"
    assert (tmp_path / "v1/shots/s01/versions/keyframe_v2.png").read_text() == "second"
    assert (tmp_path / "v1/shots/s01/versions/keyframe_v1.png").exists()  # copy, not move


def test_restore_missing_version_raises(tmp_path):
    store = ProjectStore(tmp_path)
    with pytest.raises(FileNotFoundError):
        store.restore(Node(id="refs.hero", type="image"), NodeState(), 7)


def test_archive_and_restore_directory_outputs(tmp_path):
    store = ProjectStore(tmp_path)
    node = Node(id="v1.capcut_draft", type="capcut_draft")
    ns = NodeState(status="done", fingerprint="fp1", version=1, output="v1/capcut_draft", spec={})
    out = store.output_path(node)
    out.mkdir(parents=True)
    (out / "draft_content.json").write_text("{}")
    store.archive(node, ns)
    assert (tmp_path / "v1/versions/capcut_draft_v1/draft_content.json").exists()
    ns.version = 2
    out.mkdir()
    store.restore(node, ns, 1)
    assert (out / "draft_content.json").exists()


def test_resolve_inputs(tmp_path):
    store = ProjectStore(tmp_path)
    state = {"refs.hero": NodeState(status="done", output="refs/hero.png")}
    resolved = store.resolve_inputs({"refs": ["@refs.hero"], "duration": 4, "note": "plain"}, state)
    assert resolved == {"refs": [str(tmp_path / "refs/hero.png")], "duration": 4, "note": "plain"}


def test_resolve_inputs_missing_output_raises(tmp_path):
    with pytest.raises(ValueError, match="no output"):
        ProjectStore(tmp_path).resolve_inputs({"x": "@refs.hero"}, {})
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'engine.core.store'`

- [ ] **Step 3: Implement `engine/core/store.py`**

```python
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from engine.core.manifest import REF_PREFIX, Node, NodeType

EXTENSIONS: dict[NodeType, str] = {
    NodeType.image: ".png",
    NodeType.video: ".mp4",
    NodeType.lipsync: ".mp4",
    NodeType.tts: ".wav",
    NodeType.sfx: ".wav",
    NodeType.music: ".wav",
    NodeType.timeline: ".json",
    NodeType.preview: ".mp4",
    NodeType.capcut_draft: "",  # directory output
}
SHOT_UNIT = re.compile(r"^s\d+$")

Status = Literal["pending", "running", "done", "failed", "blocked", "needs_review"]


class NodeState(BaseModel):
    status: Status = "pending"
    fingerprint: str | None = None
    version: int = 0
    output: str | None = None
    spec: dict[str, Any] | None = None
    reason: str | None = None
    message: str | None = None


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


class ProjectStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.manifest_path = self.root / "manifest.json"
        self.state_path = self.root / "state.json"
        self.ledger_path = self.root / "ledger.jsonl"

    # ---- paths -------------------------------------------------------------
    def output_path(self, node: Node) -> Path:
        parts = node.id.split(".")
        if len(parts) == 3 and SHOT_UNIT.match(parts[1]):
            rel = Path(parts[0], "shots", parts[1], parts[2])
        else:
            rel = Path(*parts)
        return self.root / (str(rel) + EXTENSIONS[node.type])

    def _version_paths(self, node: Node, version: int) -> tuple[Path, Path]:
        out = self.output_path(node)
        base = f"{out.stem}_v{version}"
        vdir = out.parent / "versions"
        return vdir / f"{base}{out.suffix}", vdir / f"{base}.json"

    # ---- state -------------------------------------------------------------
    def load_state(self) -> dict[str, NodeState]:
        if not self.state_path.exists():
            return {}
        raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        return {k: NodeState.model_validate(v) for k, v in raw.items()}

    def save_state(self, state: dict[str, NodeState]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".json.tmp")
        data = {k: v.model_dump(mode="json") for k, v in sorted(state.items())}
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def is_fresh(self, state: dict[str, NodeState], node_id: str, fingerprint: str) -> bool:
        ns = state.get(node_id)
        return bool(
            ns
            and ns.status == "done"
            and ns.fingerprint == fingerprint
            and ns.output
            and (self.root / ns.output).exists()
        )

    # ---- versions ----------------------------------------------------------
    def archive(self, node: Node, ns: NodeState) -> Path | None:
        out = self.output_path(node)
        if ns.version == 0 or not out.exists():
            return None
        dest, meta = self._version_paths(node, ns.version)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            _remove(dest)
        shutil.move(str(out), str(dest))
        meta.write_text(json.dumps({"fingerprint": ns.fingerprint, "node": ns.spec}, indent=2), encoding="utf-8")
        return dest

    def restore(self, node: Node, ns: NodeState, version: int) -> dict[str, Any]:
        src, meta = self._version_paths(node, version)
        if not src.exists() or not meta.exists():
            raise FileNotFoundError(f"{node.id}: no archived version {version}")
        sidecar = json.loads(meta.read_text(encoding="utf-8"))
        self.archive(node, ns)
        out = self.output_path(node)
        if out.exists():
            _remove(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, out)
        else:
            shutil.copy2(src, out)
        return sidecar

    # ---- references --------------------------------------------------------
    def resolve_inputs(self, value: Any, state: dict[str, NodeState]) -> Any:
        if isinstance(value, str) and value.startswith(REF_PREFIX):
            ref = value[len(REF_PREFIX):]
            ns = state.get(ref)
            if ns is None or ns.output is None:
                raise ValueError(f"reference {value} has no output yet")
            return str(self.root / ns.output)
        if isinstance(value, dict):
            return {k: self.resolve_inputs(v, state) for k, v in value.items()}
        if isinstance(value, list):
            return [self.resolve_inputs(v, state) for v in value]
        return value
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_store.py -v`
Expected: 18 passed

- [ ] **Step 5: Commit**

```bash
command git add engine/core/store.py tests/test_store.py
command git commit -m "feat: project store with state, versioning and ref resolution"
```

---

### Task 5: Config + cost ledger

**Files:**
- Create: `engine/config.py`, `engine/core/ledger.py`
- Test: `tests/test_config.py`, `tests/test_ledger.py`

**Interfaces:**
- Consumes: `NodeType`
- Produces:
  - `ProviderSpec(BaseModel, extra="allow")`: `kind: str`, `concurrency: int = 4` (≥1), property `options -> dict[str, Any]` (all extra keys)
  - `RetryConfig`: `max_attempts: int = 3`, `base_delay_s: float = 2.0`
  - `BudgetConfig`: `max_usd: float | None = None`
  - `EngineConfig`: `providers: dict[str, ProviderSpec]` (default `{"mock": kind=mock, concurrency=8}`), `defaults: dict[NodeType, list[str]]` (default every type → `["mock"]`; a bare string is wrapped into a list), `retry`, `budget`
  - `load_config(path: Path | None) -> EngineConfig`
  - `Ledger(path)`: `record(node_id, provider, model, cost_usd, seconds) -> None`, `total() -> float`

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:
```python
import pytest
from pydantic import ValidationError

from engine.config import EngineConfig, load_config
from engine.core.manifest import NodeType


def test_defaults_route_everything_to_mock():
    cfg = load_config(None)
    assert set(cfg.providers) == {"mock"}
    assert cfg.providers["mock"].concurrency == 8
    assert all(cfg.defaults[t] == ["mock"] for t in NodeType)
    assert cfg.budget.max_usd is None


def test_load_yaml_wraps_single_default_and_keeps_options(tmp_path):
    path = tmp_path / "adforge.yaml"
    path.write_text(
        "providers:\n"
        "  seed:\n"
        "    kind: mock\n"
        "    concurrency: 2\n"
        "    base_url: https://example.invalid\n"
        "defaults:\n"
        "  video: seed\n"
        "  image: [seed, seed]\n"
        "budget:\n"
        "  max_usd: 12.5\n"
    )
    cfg = load_config(path)
    assert cfg.defaults[NodeType.video] == ["seed"]
    assert cfg.defaults[NodeType.image] == ["seed", "seed"]
    assert cfg.providers["seed"].options == {"base_url": "https://example.invalid"}
    assert cfg.budget.max_usd == 12.5


def test_unknown_top_level_key_rejected():
    with pytest.raises(ValidationError):
        EngineConfig.model_validate({"bogus": 1})


def test_concurrency_must_be_positive():
    with pytest.raises(ValidationError):
        EngineConfig.model_validate({"providers": {"m": {"kind": "mock", "concurrency": 0}}})
```

`tests/test_ledger.py`:
```python
import json

from engine.core.ledger import Ledger


def test_record_and_total(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    assert ledger.total() == 0.0
    ledger.record("refs.hero", "mock", None, 0.04, 1.2)
    ledger.record("v1.s01.clip", "seedance", "seedance-2.5", 0.5, 30.0)
    assert round(ledger.total(), 6) == 0.54
    lines = [json.loads(l) for l in path.read_text().splitlines()]
    assert lines[1]["node_id"] == "v1.s01.clip" and lines[1]["model"] == "seedance-2.5"
    assert set(lines[0]) == {"ts", "node_id", "provider", "model", "cost_usd", "seconds"}


def test_total_reads_existing_file(tmp_path):
    path = tmp_path / "ledger.jsonl"
    Ledger(path).record("refs.hero", "mock", None, 1.5, 0.1)
    assert Ledger(path).total() == 1.5
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_config.py tests/test_ledger.py -v`
Expected: FAIL `ModuleNotFoundError`

- [ ] **Step 3: Implement `engine/config.py`**

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from engine.core.manifest import NodeType


class ProviderSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: str
    concurrency: int = Field(default=4, ge=1)

    @property
    def options(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class RetryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=3, ge=1)
    base_delay_s: float = Field(default=2.0, ge=0)


class BudgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_usd: float | None = None


def _default_providers() -> dict[str, ProviderSpec]:
    return {"mock": ProviderSpec(kind="mock", concurrency=8)}


def _default_routes() -> dict[NodeType, list[str]]:
    return {t: ["mock"] for t in NodeType}


class EngineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: dict[str, ProviderSpec] = Field(default_factory=_default_providers)
    defaults: dict[NodeType, list[str]] = Field(default_factory=_default_routes)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)

    @field_validator("defaults", mode="before")
    @classmethod
    def _wrap_single_provider(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: [v] if isinstance(v, str) else v for k, v in value.items()}
        return value


def load_config(path: Path | None) -> EngineConfig:
    if path is None:
        return EngineConfig()
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return EngineConfig.model_validate(data)
```

- [ ] **Step 4: Implement `engine/core/ledger.py`**

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class Ledger:
    """Append-only log of paid provider calls."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._total: float | None = None

    def total(self) -> float:
        if self._total is None:
            self._total = 0.0
            if self.path.exists():
                for line in self.path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        self._total += float(json.loads(line)["cost_usd"])
        return self._total

    def record(self, node_id: str, provider: str, model: str | None, cost_usd: float, seconds: float) -> None:
        self.total()  # make sure the running total includes prior entries
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "node_id": node_id,
            "provider": provider,
            "model": model,
            "cost_usd": round(cost_usd, 6),
            "seconds": round(seconds, 3),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        self._total += cost_usd
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_config.py tests/test_ledger.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
command git add engine/config.py engine/core/ledger.py tests/test_config.py tests/test_ledger.py
command git commit -m "feat: engine config and cost ledger"
```

---

### Task 6: Provider interface, mock provider, registry

**Files:**
- Create: `engine/providers/base.py`, `engine/providers/mock.py`, `engine/providers/registry.py`
- Test: `tests/test_providers.py`

**Interfaces:**
- Consumes: `Node`, `NodeType`, `ProviderSpec`, `EngineConfig`
- Produces:
  - `TransientError(Exception)` (retryable: rate limits, timeouts, 5xx), `RefusalError(Exception)` (content refusal)
  - `@dataclass RenderRequest(node: Node, inputs: dict[str, Any], out_path: Path)`
  - `class Provider(ABC)`: `__init__(name: str, spec: ProviderSpec)`, attrs `name`, `spec`, class attr `supports: frozenset[NodeType]`, `async render(req) -> Path`, `cost(node) -> float`
  - `MockProvider(Provider)`: options `delay_s: float = 0`, `delays: {node_id: seconds}`, `cost_usd: float = 0`, `fail: {node_id: ["transient"|"refusal"|"error", ...]}` (one entry consumed per attempt); records `calls: list[str]`, `log: list[str]` (`"start:<id>"`, `"end:<id>"`), `max_active: int`. Writes a JSON payload `{"mock", "id", "prompt", "inputs"}` to `out_path` (for `capcut_draft`, a directory containing `draft_content.json`).
  - `ADAPTERS: dict[str, type[Provider]] = {"mock": MockProvider}`
  - `ProviderRegistry(config)`: `providers: dict[str, Provider]`, `chain_for(node) -> list[Provider]` (node.provider override, else `config.defaults[node.type]`), `primary_name(node) -> str`. Raises `ValueError` for unknown adapter kind, unknown provider name, unsupported node type, or no route.

- [ ] **Step 1: Write the failing tests** — `tests/test_providers.py`

```python
import json

import pytest

from engine.config import EngineConfig
from engine.core.manifest import Node, NodeType
from engine.providers import registry as registry_mod
from engine.providers.base import RefusalError, RenderRequest, TransientError
from engine.providers.mock import MockProvider
from engine.providers.registry import ProviderRegistry


def cfg(**data):
    return EngineConfig.model_validate(data)


async def test_mock_writes_payload(tmp_path):
    reg = ProviderRegistry(cfg())
    mock = reg.providers["mock"]
    node = Node(id="refs.hero", type="image", prompt="a mug")
    out = tmp_path / "refs" / "hero.png"
    path = await mock.render(RenderRequest(node=node, inputs={"a": 1}, out_path=out))
    assert path == out
    assert json.loads(out.read_text()) == {"mock": True, "id": "refs.hero", "prompt": "a mug", "inputs": {"a": 1}}
    assert mock.calls == ["refs.hero"]
    assert mock.log == ["start:refs.hero", "end:refs.hero"]


async def test_mock_capcut_draft_is_directory(tmp_path):
    mock = ProviderRegistry(cfg()).providers["mock"]
    out = tmp_path / "v1" / "capcut_draft"
    await mock.render(RenderRequest(node=Node(id="v1.capcut_draft", type="capcut_draft"), inputs={}, out_path=out))
    assert (out / "draft_content.json").exists()


@pytest.mark.parametrize("kind,exc", [("transient", TransientError), ("refusal", RefusalError), ("error", RuntimeError)])
async def test_mock_failure_injection_consumed_per_attempt(tmp_path, kind, exc):
    reg = ProviderRegistry(cfg(providers={"mock": {"kind": "mock", "fail": {"refs.hero": [kind]}}}))
    mock = reg.providers["mock"]
    req = RenderRequest(node=Node(id="refs.hero", type="image"), inputs={}, out_path=tmp_path / "h.png")
    with pytest.raises(exc):
        await mock.render(req)
    await mock.render(req)  # second attempt succeeds
    assert mock.calls == ["refs.hero", "refs.hero"]


def test_mock_cost_option():
    mock = ProviderRegistry(cfg(providers={"mock": {"kind": "mock", "cost_usd": 0.25}})).providers["mock"]
    assert mock.cost(Node(id="refs.hero", type="image")) == 0.25


def test_chain_uses_defaults_and_node_override():
    reg = ProviderRegistry(cfg(
        providers={"a": {"kind": "mock"}, "b": {"kind": "mock"}},
        defaults={"tts": ["a", "b"], "image": "a"},
    ))
    assert [p.name for p in reg.chain_for(Node(id="v1.vo.l01", type="tts"))] == ["a", "b"]
    assert [p.name for p in reg.chain_for(Node(id="refs.hero", type="image", provider="b"))] == ["b"]
    assert reg.primary_name(Node(id="v1.vo.l01", type="tts")) == "a"


def test_unknown_adapter_kind():
    with pytest.raises(ValueError, match="unknown adapter kind"):
        ProviderRegistry(cfg(providers={"x": {"kind": "nope"}}))


def test_unknown_provider_name():
    reg = ProviderRegistry(cfg())
    with pytest.raises(ValueError, match="unknown provider"):
        reg.chain_for(Node(id="refs.hero", type="image", provider="ghost"))


def test_no_route_for_type():
    reg = ProviderRegistry(cfg(defaults={"image": "mock"}))
    with pytest.raises(ValueError, match="no provider configured"):
        reg.chain_for(Node(id="v1.vo.l01", type="tts"))


class ImageOnly(MockProvider):
    supports = frozenset({NodeType.image})


def test_unsupported_type(monkeypatch):
    monkeypatch.setitem(registry_mod.ADAPTERS, "imgonly", ImageOnly)
    reg = ProviderRegistry(cfg(providers={"p": {"kind": "imgonly"}}, defaults={"tts": "p"}))
    with pytest.raises(ValueError, match="does not support"):
        reg.chain_for(Node(id="v1.vo.l01", type="tts"))
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_providers.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'engine.providers.base'`

- [ ] **Step 3: Implement `engine/providers/base.py`**

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.config import ProviderSpec
from engine.core.manifest import Node, NodeType


class TransientError(Exception):
    """Retryable failure: rate limit, timeout, 5xx, provider temporarily down."""


class RefusalError(Exception):
    """Provider refused the content (moderation / policy)."""


@dataclass
class RenderRequest:
    node: Node
    inputs: dict[str, Any]  # '@refs' already resolved to absolute path strings
    out_path: Path


class Provider(ABC):
    supports: frozenset[NodeType] = frozenset()

    def __init__(self, name: str, spec: ProviderSpec):
        self.name = name
        self.spec = spec

    @abstractmethod
    async def render(self, req: RenderRequest) -> Path:
        """Produce the node output at req.out_path and return the path."""

    @abstractmethod
    def cost(self, node: Node) -> float:
        """Estimated USD cost of one successful render of node."""
```

- [ ] **Step 4: Implement `engine/providers/mock.py`**

```python
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from engine.config import ProviderSpec
from engine.core.manifest import Node, NodeType
from engine.providers.base import Provider, RefusalError, RenderRequest, TransientError


class MockProvider(Provider):
    """Instant fake provider for tests and dry runs. Writes JSON payloads."""

    supports = frozenset(NodeType)

    def __init__(self, name: str, spec: ProviderSpec):
        super().__init__(name, spec)
        opts = spec.options
        self.delay_s = float(opts.get("delay_s", 0.0))
        self.delays = {k: float(v) for k, v in opts.get("delays", {}).items()}
        self.cost_usd = float(opts.get("cost_usd", 0.0))
        self.fail = {k: list(v) for k, v in opts.get("fail", {}).items()}
        self.calls: list[str] = []
        self.log: list[str] = []
        self.active = 0
        self.max_active = 0

    def cost(self, node: Node) -> float:
        return self.cost_usd

    async def render(self, req: RenderRequest) -> Path:
        node_id = req.node.id
        self.calls.append(node_id)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            self.log.append(f"start:{node_id}")
            await asyncio.sleep(self.delays.get(node_id, self.delay_s))
            queue = self.fail.get(node_id)
            if queue:
                kind = queue.pop(0)
                if kind == "transient":
                    raise TransientError(f"mock transient failure for {node_id}")
                if kind == "refusal":
                    raise RefusalError(f"mock refusal for {node_id}")
                raise RuntimeError(f"mock hard failure for {node_id}")
            payload = json.dumps(
                {"mock": True, "id": node_id, "prompt": req.node.prompt, "inputs": req.inputs},
                sort_keys=True,
            )
            if req.node.type is NodeType.capcut_draft:
                req.out_path.mkdir(parents=True, exist_ok=True)
                (req.out_path / "draft_content.json").write_text(payload, encoding="utf-8")
            else:
                req.out_path.parent.mkdir(parents=True, exist_ok=True)
                req.out_path.write_text(payload, encoding="utf-8")
            self.log.append(f"end:{node_id}")
            return req.out_path
        finally:
            self.active -= 1
```

- [ ] **Step 5: Implement `engine/providers/registry.py`**

```python
from __future__ import annotations

from engine.config import EngineConfig
from engine.core.manifest import Node
from engine.providers.base import Provider
from engine.providers.mock import MockProvider

ADAPTERS: dict[str, type[Provider]] = {"mock": MockProvider}


class ProviderRegistry:
    def __init__(self, config: EngineConfig):
        self.config = config
        self.providers: dict[str, Provider] = {}
        for name, spec in config.providers.items():
            adapter = ADAPTERS.get(spec.kind)
            if adapter is None:
                raise ValueError(f"provider '{name}': unknown adapter kind '{spec.kind}' (known: {sorted(ADAPTERS)})")
            self.providers[name] = adapter(name, spec)

    def chain_for(self, node: Node) -> list[Provider]:
        names = [node.provider] if node.provider else self.config.defaults.get(node.type, [])
        if not names:
            raise ValueError(f"{node.id}: no provider configured for type '{node.type.value}'")
        chain: list[Provider] = []
        for name in names:
            provider = self.providers.get(name)
            if provider is None:
                raise ValueError(f"{node.id}: unknown provider '{name}'")
            if node.type not in provider.supports:
                raise ValueError(f"{node.id}: provider '{name}' does not support type '{node.type.value}'")
            chain.append(provider)
        return chain

    def primary_name(self, node: Node) -> str:
        return self.chain_for(node)[0].name
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_providers.py -v`
Expected: 11 passed

- [ ] **Step 7: Commit**

```bash
command git add engine/providers tests/test_providers.py
command git commit -m "feat: provider interface, mock provider and routing registry"
```

---

### Task 7: Parallel scheduler

**Files:**
- Create: `engine/core/scheduler.py`, `tests/helpers.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `load_manifest`, `select`, `fingerprint_all`, `ProjectStore`, `NodeState`, `Ledger`, `EngineConfig`, `ProviderRegistry`, `Provider`, `RenderRequest`, `TransientError`, `RefusalError`
- Produces:
  - `@dataclass RunReport`: `rendered: list[str]`, `skipped: list[str]`, `failed: dict[str, str]`, `blocked: list[str]`, `needs_review: dict[str, str]`, `budget_held: list[str]`; property `ok: bool`; `to_dict() -> dict` (includes `"ok"`)
  - `Scheduler(store: ProjectStore, config: EngineConfig, registry: ProviderRegistry | None = None, ledger: Ledger | None = None, sleep=asyncio.sleep)`; attrs `store, config, registry, ledger`; `async run(only: list[str] | None = None) -> RunReport`
  - Behaviour: fresh nodes skipped; others rendered as soon as deps are done; per-provider `asyncio.Semaphore(spec.concurrency)` held only during a single attempt; `TransientError` retried with `base_delay_s * 2**(attempt-1)` up to `max_attempts`, then next provider in chain; `RefusalError` → `needs_review` (reason `refused`); any other exception → `failed` (reason `error`); dependents of non-done nodes → `blocked` (reason `dependency`); budget check (`ledger.total() + reserved + cost > max_usd`) → status `pending`, reason `budget`, listed in `budget_held`; previous output archived before re-render; `state.json` saved after every status change.
- `tests/helpers.py` produces: `SAMPLE_NODES`, `write_manifest(root, nodes=None) -> Path`, `mock_config(concurrency=8, budget=None, max_attempts=3, **options) -> EngineConfig`, `nosleep`, `make_scheduler(root, config) -> Scheduler`

- [ ] **Step 1: Write `tests/helpers.py`**

```python
from __future__ import annotations

from pathlib import Path

from engine.config import EngineConfig
from engine.core.manifest import Manifest, save_manifest
from engine.core.scheduler import Scheduler
from engine.core.store import ProjectStore

SAMPLE_NODES = [
    {"id": "refs.hero", "type": "image", "prompt": "hero"},
    {"id": "v1.s01.keyframe", "type": "image", "prompt": "k1",
     "inputs": {"refs": ["@refs.hero"]}, "depends_on": ["refs.hero"]},
    {"id": "v1.s01.clip", "type": "video", "prompt": "c1",
     "inputs": {"first_frame": "@v1.s01.keyframe", "duration": 4}, "depends_on": ["v1.s01.keyframe"]},
    {"id": "v1.s02.keyframe", "type": "image", "prompt": "k2",
     "inputs": {"refs": ["@refs.hero"]}, "depends_on": ["refs.hero"]},
    {"id": "v1.s02.clip", "type": "video", "prompt": "c2",
     "inputs": {"first_frame": "@v1.s02.keyframe", "duration": 4}, "depends_on": ["v1.s02.keyframe"]},
    {"id": "v1.vo.l01", "type": "tts", "prompt": "Hello there"},
]
ALL_IDS = {n["id"] for n in SAMPLE_NODES}


def write_manifest(root: Path, nodes: list[dict] | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    manifest = Manifest.model_validate({"project": "demo", "nodes": nodes or SAMPLE_NODES})
    save_manifest(manifest, root / "manifest.json")
    return root


def mock_config(concurrency: int = 8, budget: float | None = None, max_attempts: int = 3, **options) -> EngineConfig:
    return EngineConfig.model_validate({
        "providers": {"mock": {"kind": "mock", "concurrency": concurrency, **options}},
        "retry": {"max_attempts": max_attempts, "base_delay_s": 0},
        "budget": {"max_usd": budget},
    })


async def nosleep(_seconds: float) -> None:
    return None


def make_scheduler(root: Path, config: EngineConfig) -> Scheduler:
    return Scheduler(ProjectStore(root), config, sleep=nosleep)
```

- [ ] **Step 2: Write the failing tests** — `tests/test_scheduler.py`

```python
import json
import time

from engine.config import EngineConfig
from engine.core.manifest import load_manifest, save_manifest
from tests.helpers import ALL_IDS, make_scheduler, mock_config, write_manifest


def mock_of(scheduler, name="mock"):
    return scheduler.registry.providers[name]


async def test_renders_all_nodes(tmp_path):
    root = write_manifest(tmp_path / "p")
    s = make_scheduler(root, mock_config())
    report = await s.run()
    assert set(report.rendered) == ALL_IDS and report.ok
    state = s.store.load_state()
    assert all(state[n].status == "done" and state[n].version == 1 for n in ALL_IDS)
    assert (root / "v1/shots/s01/clip.mp4").exists()
    clip_inputs = json.loads((root / "v1/shots/s01/clip.mp4").read_text())["inputs"]
    assert clip_inputs["first_frame"] == str(root / "v1/shots/s01/keyframe.png")


async def test_second_run_skips_everything(tmp_path):
    root = write_manifest(tmp_path / "p")
    await make_scheduler(root, mock_config()).run()
    s2 = make_scheduler(root, mock_config())
    report = await s2.run()
    assert report.rendered == [] and set(report.skipped) == ALL_IDS
    assert mock_of(s2).calls == []


async def test_dependencies_finish_before_dependents_start(tmp_path):
    root = write_manifest(tmp_path / "p")
    s = make_scheduler(root, mock_config(delay_s=0.01))
    await s.run()
    log = mock_of(s).log
    assert log.index("end:refs.hero") < log.index("start:v1.s01.keyframe")
    assert log.index("end:v1.s01.keyframe") < log.index("start:v1.s01.clip")


async def test_independent_nodes_run_in_parallel(tmp_path):
    nodes = [{"id": f"v1.vo.l0{i}", "type": "tts", "prompt": str(i)} for i in range(5)]
    root = write_manifest(tmp_path / "p", nodes)
    s = make_scheduler(root, mock_config(delay_s=0.1))
    started = time.monotonic()
    await s.run()
    assert time.monotonic() - started < 0.35
    assert mock_of(s).max_active == 5


async def test_concurrency_cap(tmp_path):
    nodes = [{"id": f"v1.vo.l0{i}", "type": "tts", "prompt": str(i)} for i in range(6)]
    root = write_manifest(tmp_path / "p", nodes)
    s = make_scheduler(root, mock_config(concurrency=2, delay_s=0.03))
    await s.run()
    assert mock_of(s).max_active == 2


async def test_pipelining_starts_clip_before_slow_sibling_keyframe_finishes(tmp_path):
    root = write_manifest(tmp_path / "p")
    s = make_scheduler(root, mock_config(delays={"v1.s01.keyframe": 0.2}))
    await s.run()
    log = mock_of(s).log
    assert log.index("start:v1.s02.clip") < log.index("end:v1.s01.keyframe")


async def test_transient_errors_are_retried(tmp_path):
    root = write_manifest(tmp_path / "p")
    s = make_scheduler(root, mock_config(fail={"v1.vo.l01": ["transient", "transient"]}))
    report = await s.run()
    assert "v1.vo.l01" in report.rendered
    assert mock_of(s).calls.count("v1.vo.l01") == 3


async def test_transient_retries_exhausted_fails_node(tmp_path):
    root = write_manifest(tmp_path / "p")
    s = make_scheduler(root, mock_config(fail={"v1.vo.l01": ["transient"] * 3}))
    report = await s.run()
    assert "v1.vo.l01" in report.failed and not report.ok
    assert s.store.load_state()["v1.vo.l01"].status == "failed"


async def test_fallback_chain_used_after_transient_exhaustion(tmp_path):
    root = write_manifest(tmp_path / "p")
    cfg = EngineConfig.model_validate({
        "providers": {"a": {"kind": "mock", "fail": {"v1.vo.l01": ["transient"] * 3}}, "b": {"kind": "mock"}},
        "defaults": {"tts": ["a", "b"], "image": "a", "video": "a"},
        "retry": {"max_attempts": 3, "base_delay_s": 0},
    })
    s = make_scheduler(root, cfg)
    report = await s.run()
    assert "v1.vo.l01" in report.rendered
    assert mock_of(s, "b").calls == ["v1.vo.l01"]


async def test_refusal_needs_review_and_blocks_dependents_only(tmp_path):
    root = write_manifest(tmp_path / "p")
    s = make_scheduler(root, mock_config(fail={"v1.s01.keyframe": ["refusal"]}))
    report = await s.run()
    assert "v1.s01.keyframe" in report.needs_review
    assert report.blocked == ["v1.s01.clip"]
    assert {"refs.hero", "v1.s02.keyframe", "v1.s02.clip", "v1.vo.l01"} <= set(report.rendered)
    state = s.store.load_state()
    assert state["v1.s01.keyframe"].reason == "refused"
    assert state["v1.s01.clip"].status == "blocked"


async def test_hard_failure_is_isolated(tmp_path):
    root = write_manifest(tmp_path / "p")
    s = make_scheduler(root, mock_config(fail={"v1.s02.keyframe": ["error"]}))
    report = await s.run()
    assert "RuntimeError" in report.failed["v1.s02.keyframe"]
    assert report.blocked == ["v1.s02.clip"]
    assert "v1.s01.clip" in report.rendered


async def test_budget_holds_nodes_once_limit_reached(tmp_path):
    root = write_manifest(tmp_path / "p")
    s = make_scheduler(root, mock_config(cost_usd=1.0, budget=3.0))
    report = await s.run()
    assert len(report.rendered) == 3
    assert s.ledger.total() == 3.0
    assert report.budget_held and not report.ok
    held = report.budget_held[0]
    assert s.store.load_state()[held].reason == "budget"


async def test_only_runs_selected_and_ancestors(tmp_path):
    root = write_manifest(tmp_path / "p")
    report = await make_scheduler(root, mock_config()).run(only=["v1.s01.*"])
    assert set(report.rendered) == {"refs.hero", "v1.s01.keyframe", "v1.s01.clip"}


async def test_rerender_archives_previous_version(tmp_path):
    root = write_manifest(tmp_path / "p")
    await make_scheduler(root, mock_config()).run()
    manifest = load_manifest(root / "manifest.json")
    manifest.get("v1.s01.keyframe").prompt = "k1 brighter"
    save_manifest(manifest, root / "manifest.json")
    s = make_scheduler(root, mock_config())
    report = await s.run()
    assert sorted(report.rendered) == ["v1.s01.clip", "v1.s01.keyframe"]
    assert (root / "v1/shots/s01/versions/keyframe_v1.png").exists()
    assert s.store.load_state()["v1.s01.keyframe"].version == 2
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'engine.core.scheduler'`

- [ ] **Step 4: Implement `engine/core/scheduler.py`**

```python
from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from engine.config import EngineConfig
from engine.core.fingerprint import fingerprint_all
from engine.core.graph import select
from engine.core.ledger import Ledger
from engine.core.manifest import Node, load_manifest
from engine.core.store import NodeState, ProjectStore
from engine.providers.base import Provider, RefusalError, RenderRequest, TransientError
from engine.providers.registry import ProviderRegistry

Sleep = Callable[[float], Awaitable[None]]


@dataclass
class RunReport:
    rendered: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    blocked: list[str] = field(default_factory=list)
    needs_review: dict[str, str] = field(default_factory=dict)
    budget_held: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.failed or self.blocked or self.needs_review or self.budget_held)

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "ok": self.ok}


class Scheduler:
    def __init__(
        self,
        store: ProjectStore,
        config: EngineConfig,
        registry: ProviderRegistry | None = None,
        ledger: Ledger | None = None,
        sleep: Sleep = asyncio.sleep,
    ):
        self.store = store
        self.config = config
        self.registry = registry or ProviderRegistry(config)
        self.ledger = ledger or Ledger(store.ledger_path)
        self._sleep = sleep
        self._reserved = 0.0

    async def run(self, only: list[str] | None = None) -> RunReport:
        manifest = load_manifest(self.store.manifest_path)
        nodes = manifest.by_id()
        deps = manifest.deps()
        selected = select(deps, only) if only else set(nodes)
        fps = fingerprint_all(manifest, provider_for=self.registry.primary_name)
        state = self.store.load_state()
        report = RunReport()
        sems = {name: asyncio.Semaphore(p.spec.concurrency) for name, p in self.registry.providers.items()}
        finished = {nid: asyncio.Event() for nid in selected}
        outcome: dict[str, str] = {}

        def persist() -> None:
            self.store.save_state(state)

        async def run_node(nid: str) -> None:
            node = nodes[nid]
            try:
                for dep in node.depends_on:
                    await finished[dep].wait()
                ns = state.setdefault(nid, NodeState())
                bad = sorted(d for d in node.depends_on if outcome.get(d) != "done")
                if bad:
                    ns.status, ns.reason, ns.message = "blocked", "dependency", f"blocked by {', '.join(bad)}"
                    report.blocked.append(nid)
                    persist()
                    return
                if self.store.is_fresh(state, nid, fps[nid]):
                    report.skipped.append(nid)
                    outcome[nid] = "done"
                    return
                if await self._render(node, ns, fps[nid], state, sems, report, persist):
                    outcome[nid] = "done"
            finally:
                finished[nid].set()

        await asyncio.gather(*(run_node(nid) for nid in sorted(selected)))
        return report

    async def _render(
        self,
        node: Node,
        ns: NodeState,
        fp: str,
        state: dict[str, NodeState],
        sems: dict[str, asyncio.Semaphore],
        report: RunReport,
        persist: Callable[[], None],
    ) -> bool:
        cost = 0.0
        reserved = False
        try:
            chain = self.registry.chain_for(node)
            cost = chain[0].cost(node)
            budget = self.config.budget.max_usd
            if budget is not None and self.ledger.total() + self._reserved + cost > budget + 1e-9:
                ns.status, ns.reason = "pending", "budget"
                ns.message = f"budget ${budget:.2f} would be exceeded"
                report.budget_held.append(node.id)
                persist()
                return False
            self._reserved += cost
            reserved = True

            self.store.archive(node, ns)
            ns.status, ns.reason, ns.message = "running", None, None
            persist()

            inputs = self.store.resolve_inputs(node.inputs, state)
            out = self.store.output_path(node)
            path = await self._render_with_fallback(chain, node, inputs, out, sems)

            ns.status = "done"
            ns.fingerprint = fp
            ns.version += 1
            ns.output = path.relative_to(self.store.root).as_posix()
            ns.spec = node.model_dump(mode="json")
            report.rendered.append(node.id)
            persist()
            return True
        except RefusalError as exc:
            ns.status, ns.reason, ns.message = "needs_review", "refused", str(exc)
            report.needs_review[node.id] = str(exc)
            persist()
            return False
        except Exception as exc:  # noqa: BLE001 — isolate any provider/engine failure to this node
            ns.status, ns.reason, ns.message = "failed", "error", f"{type(exc).__name__}: {exc}"
            report.failed[node.id] = ns.message
            persist()
            return False
        finally:
            if reserved:
                self._reserved -= cost

    async def _render_with_fallback(
        self,
        chain: list[Provider],
        node: Node,
        inputs: dict[str, Any],
        out: Path,
        sems: dict[str, asyncio.Semaphore],
    ) -> Path:
        for index, provider in enumerate(chain):
            try:
                return await self._call_with_retry(provider, node, inputs, out, sems[provider.name])
            except TransientError:
                if index == len(chain) - 1:
                    raise
        raise AssertionError("unreachable: empty provider chain")

    async def _call_with_retry(
        self,
        provider: Provider,
        node: Node,
        inputs: dict[str, Any],
        out: Path,
        sem: asyncio.Semaphore,
    ) -> Path:
        attempts = self.config.retry.max_attempts
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                async with sem:
                    path = await provider.render(RenderRequest(node=node, inputs=inputs, out_path=out))
            except TransientError:
                if attempt == attempts:
                    raise
                await self._sleep(self.config.retry.base_delay_s * 2 ** (attempt - 1))
                continue
            self.ledger.record(node.id, provider.name, node.model, provider.cost(node), time.monotonic() - started)
            return path
        raise AssertionError("unreachable: retry loop exited")
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: 14 passed

- [ ] **Step 6: Run full suite**

Run: `uv run pytest -q`
Expected: all passed

- [ ] **Step 7: Commit**

```bash
command git add engine/core/scheduler.py tests/helpers.py tests/test_scheduler.py
command git commit -m "feat: parallel DAG scheduler with retries, fallbacks and budget"
```

---

### Task 8: Revise + rollback

**Files:**
- Create: `engine/core/revise.py`
- Test: `tests/test_revise.py`

**Interfaces:**
- Consumes: `load_manifest`, `save_manifest`, `Manifest`, `Node`, `descendants`, `topo_order`, `ProjectStore`, `NodeState`
- Produces:
  - `EDITABLE_FIELDS = frozenset({"prompt", "inputs", "provider", "model", "depends_on"})`
  - `revise(store, node_id: str, changes: dict) -> list[str]` — `inputs` is merged key-by-key (a `None` value deletes a key); other fields replace. Re-validates the whole manifest, saves it, returns `[node_id] + descendants` in topological order. Raises `ValueError` (bad field / invalid manifest) or `KeyError` (unknown node).
  - `rollback(store, node_id: str, version: int) -> None` — restores the archived output and its node spec, sets state `done` with the archived fingerprint, `version += 1`. Raises `FileNotFoundError` if the version doesn't exist.

- [ ] **Step 1: Write the failing tests** — `tests/test_revise.py`

```python
import json

import pytest

from engine.core.manifest import load_manifest
from engine.core.revise import revise, rollback
from engine.core.store import ProjectStore
from tests.helpers import make_scheduler, mock_config, write_manifest


def store_for(tmp_path):
    return ProjectStore(write_manifest(tmp_path / "p"))


def test_revise_prompt_returns_affected_in_topo_order(tmp_path):
    store = store_for(tmp_path)
    affected = revise(store, "v1.s01.keyframe", {"prompt": "k1 warmer"})
    assert affected == ["v1.s01.keyframe", "v1.s01.clip"]
    assert load_manifest(store.manifest_path).get("v1.s01.keyframe").prompt == "k1 warmer"


def test_revise_root_affects_all_descendants(tmp_path):
    affected = revise(store_for(tmp_path), "refs.hero", {"prompt": "matte black"})
    assert affected[0] == "refs.hero"
    assert set(affected) == {"refs.hero", "v1.s01.keyframe", "v1.s01.clip", "v1.s02.keyframe", "v1.s02.clip"}


def test_revise_inputs_merge_and_delete(tmp_path):
    store = store_for(tmp_path)
    revise(store, "v1.s01.clip", {"inputs": {"duration": 6, "camera": "dolly"}})
    inputs = load_manifest(store.manifest_path).get("v1.s01.clip").inputs
    assert inputs == {"first_frame": "@v1.s01.keyframe", "duration": 6, "camera": "dolly"}
    revise(store, "v1.s01.clip", {"inputs": {"camera": None}})
    assert "camera" not in load_manifest(store.manifest_path).get("v1.s01.clip").inputs


def test_revise_rejects_unknown_field(tmp_path):
    with pytest.raises(ValueError, match="cannot revise"):
        revise(store_for(tmp_path), "refs.hero", {"status": "done"})


def test_revise_rejects_invalid_reference(tmp_path):
    store = store_for(tmp_path)
    with pytest.raises(ValueError):
        revise(store, "v1.s01.clip", {"inputs": {"audio": "@v1.vo.l01"}})
    assert "audio" not in load_manifest(store.manifest_path).get("v1.s01.clip").inputs  # unchanged on error


def test_revise_unknown_node(tmp_path):
    with pytest.raises(KeyError):
        revise(store_for(tmp_path), "v9.s01.clip", {"prompt": "x"})


async def test_rollback_restores_output_and_spec(tmp_path):
    store = store_for(tmp_path)
    await make_scheduler(store.root, mock_config()).run()
    revise(store, "v1.s01.keyframe", {"prompt": "k1 v2"})
    await make_scheduler(store.root, mock_config()).run()

    rollback(store, "v1.s01.keyframe", 1)

    assert load_manifest(store.manifest_path).get("v1.s01.keyframe").prompt == "k1"
    payload = json.loads((store.root / "v1/shots/s01/keyframe.png").read_text())
    assert payload["prompt"] == "k1"
    ns = store.load_state()["v1.s01.keyframe"]
    assert ns.status == "done" and ns.version == 3
    assert (store.root / "v1/shots/s01/versions/keyframe_v2.png").exists()

    report = await make_scheduler(store.root, mock_config()).run()
    assert report.rendered == ["v1.s01.clip"]  # keyframe fresh again, clip follows it


def test_rollback_missing_version(tmp_path):
    with pytest.raises(FileNotFoundError):
        rollback(store_for(tmp_path), "refs.hero", 4)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_revise.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'engine.core.revise'`

- [ ] **Step 3: Implement `engine/core/revise.py`**

```python
from __future__ import annotations

from typing import Any

from engine.core.graph import descendants, topo_order
from engine.core.manifest import Manifest, Node, load_manifest, save_manifest
from engine.core.store import NodeState, ProjectStore

EDITABLE_FIELDS = frozenset({"prompt", "inputs", "provider", "model", "depends_on"})


def _replace_node(manifest: Manifest, node: Node) -> Manifest:
    data = manifest.model_dump(mode="json")
    data["nodes"] = [node.model_dump(mode="json") if n["id"] == node.id else n for n in data["nodes"]]
    return Manifest.model_validate(data)


def revise(store: ProjectStore, node_id: str, changes: dict[str, Any]) -> list[str]:
    unknown = set(changes) - EDITABLE_FIELDS
    if unknown:
        raise ValueError(f"cannot revise fields {sorted(unknown)}; editable: {sorted(EDITABLE_FIELDS)}")
    manifest = load_manifest(store.manifest_path)
    data = manifest.get(node_id).model_dump(mode="json")
    for key, value in changes.items():
        if key == "inputs":
            merged = {**data["inputs"], **value}
            data["inputs"] = {k: v for k, v in merged.items() if v is not None}
        else:
            data[key] = value
    updated = _replace_node(manifest, Node.model_validate(data))
    save_manifest(updated, store.manifest_path)
    deps = updated.deps()
    affected = {node_id} | descendants(deps, node_id)
    return [nid for nid in topo_order(deps) if nid in affected]


def rollback(store: ProjectStore, node_id: str, version: int) -> None:
    manifest = load_manifest(store.manifest_path)
    node = manifest.get(node_id)
    state = store.load_state()
    ns = state.get(node_id) or NodeState()
    sidecar = store.restore(node, ns, version)
    restored = Node.model_validate(sidecar["node"])
    save_manifest(_replace_node(manifest, restored), store.manifest_path)
    ns.status, ns.reason, ns.message = "done", None, None
    ns.fingerprint = sidecar["fingerprint"]
    ns.spec = sidecar["node"]
    ns.version += 1
    ns.output = store.output_path(restored).relative_to(store.root).as_posix()
    state[node_id] = ns
    store.save_state(state)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_revise.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
command git add engine/core/revise.py tests/test_revise.py
command git commit -m "feat: per-node revise and rollback"
```

---

### Task 9: Cost estimate + status report

**Files:**
- Create: `engine/core/estimate.py`, `engine/core/status.py`
- Test: `tests/test_estimate_status.py`

**Interfaces:**
- Consumes: `load_manifest`, `select`, `topo_order`, `fingerprint_all`, `ProjectStore`, `NodeState`, `Ledger`, `EngineConfig`, `ProviderRegistry`
- Produces:
  - `@dataclass Estimate(to_render: list[str], per_scope: dict[str, float], total_usd: float)` with `to_dict()`; scope = first ID segment (`refs`, `v1`, …)
  - `estimate(store, config, registry=None, only=None) -> Estimate` — zero API calls; nodes in topological order that are not fresh
  - `project_status(store, registry) -> dict` with keys `project`, `counts` (status → n), `spent_usd`, `nodes` (`id → {status, stale, version, output, reason, message}`); `stale` = done but fingerprint changed

- [ ] **Step 1: Write the failing tests** — `tests/test_estimate_status.py`

```python
from engine.core.estimate import estimate
from engine.core.revise import revise
from engine.core.status import project_status
from engine.core.store import ProjectStore
from engine.providers.registry import ProviderRegistry
from tests.helpers import make_scheduler, mock_config, write_manifest


def test_estimate_fresh_project(tmp_path):
    store = ProjectStore(write_manifest(tmp_path / "p"))
    est = estimate(store, mock_config(cost_usd=0.5))
    assert len(est.to_render) == 6 and est.to_render[0] in {"refs.hero", "v1.vo.l01"}
    assert est.per_scope == {"refs": 0.5, "v1": 2.5}
    assert est.total_usd == 3.0
    assert not store.ledger_path.exists()  # no paid calls


async def test_estimate_after_run_is_zero_and_after_revise_only_affected(tmp_path):
    store = ProjectStore(write_manifest(tmp_path / "p"))
    await make_scheduler(store.root, mock_config()).run()
    assert estimate(store, mock_config(cost_usd=0.5)).to_render == []
    revise(store, "v1.s02.keyframe", {"prompt": "k2 closer"})
    est = estimate(store, mock_config(cost_usd=0.5))
    assert est.to_render == ["v1.s02.keyframe", "v1.s02.clip"]
    assert est.total_usd == 1.0


def test_estimate_only(tmp_path):
    store = ProjectStore(write_manifest(tmp_path / "p"))
    assert estimate(store, mock_config(), only=["refs.*"]).to_render == ["refs.hero"]


async def test_status_counts_and_stale(tmp_path):
    store = ProjectStore(write_manifest(tmp_path / "p"))
    cfg = mock_config(cost_usd=0.1)
    status = project_status(store, ProviderRegistry(cfg))
    assert status["counts"] == {"pending": 6} and status["spent_usd"] == 0.0

    await make_scheduler(store.root, cfg).run()
    revise(store, "v1.vo.l01", {"prompt": "Hi!"})
    status = project_status(store, ProviderRegistry(cfg))
    assert status["project"] == "demo"
    assert status["counts"] == {"done": 6}
    assert round(status["spent_usd"], 6) == 0.6
    assert status["nodes"]["v1.vo.l01"]["stale"] is True
    assert status["nodes"]["refs.hero"]["stale"] is False
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_estimate_status.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'engine.core.estimate'`

- [ ] **Step 3: Implement `engine/core/estimate.py`**

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from engine.config import EngineConfig
from engine.core.fingerprint import fingerprint_all
from engine.core.graph import select, topo_order
from engine.core.manifest import load_manifest
from engine.core.store import ProjectStore
from engine.providers.registry import ProviderRegistry


@dataclass
class Estimate:
    to_render: list[str]
    per_scope: dict[str, float]
    total_usd: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate(
    store: ProjectStore,
    config: EngineConfig,
    registry: ProviderRegistry | None = None,
    only: list[str] | None = None,
) -> Estimate:
    registry = registry or ProviderRegistry(config)
    manifest = load_manifest(store.manifest_path)
    nodes = manifest.by_id()
    deps = manifest.deps()
    selected = select(deps, only) if only else set(nodes)
    fps = fingerprint_all(manifest, provider_for=registry.primary_name)
    state = store.load_state()
    to_render: list[str] = []
    per_scope: dict[str, float] = {}
    for nid in topo_order(deps):
        if nid not in selected or store.is_fresh(state, nid, fps[nid]):
            continue
        to_render.append(nid)
        node = nodes[nid]
        scope = nid.split(".")[0]
        per_scope[scope] = round(per_scope.get(scope, 0.0) + registry.chain_for(node)[0].cost(node), 6)
    return Estimate(to_render=to_render, per_scope=per_scope, total_usd=round(sum(per_scope.values()), 6))
```

- [ ] **Step 4: Implement `engine/core/status.py`**

```python
from __future__ import annotations

from collections import Counter
from typing import Any

from engine.core.fingerprint import fingerprint_all
from engine.core.ledger import Ledger
from engine.core.manifest import load_manifest
from engine.core.store import NodeState, ProjectStore
from engine.providers.registry import ProviderRegistry


def project_status(store: ProjectStore, registry: ProviderRegistry) -> dict[str, Any]:
    manifest = load_manifest(store.manifest_path)
    fps = fingerprint_all(manifest, provider_for=registry.primary_name)
    state = store.load_state()
    counts: Counter[str] = Counter()
    nodes: dict[str, dict[str, Any]] = {}
    for node in manifest.nodes:
        ns = state.get(node.id) or NodeState()
        counts[ns.status] += 1
        nodes[node.id] = {
            "status": ns.status,
            "stale": ns.status == "done" and not store.is_fresh(state, node.id, fps[node.id]),
            "version": ns.version,
            "output": ns.output,
            "reason": ns.reason,
            "message": ns.message,
        }
    return {
        "project": manifest.project,
        "counts": dict(counts),
        "spent_usd": round(Ledger(store.ledger_path).total(), 6),
        "nodes": nodes,
    }
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_estimate_status.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
command git add engine/core/estimate.py engine/core/status.py tests/test_estimate_status.py
command git commit -m "feat: zero-cost estimate and project status"
```

---

### Task 10: `adengine` CLI + end-to-end test + README

**Files:**
- Create: `engine/cli.py`, `tests/fixtures/sample_project/manifest.json`, `tests/test_cli_e2e.py`, `README.md`, `config.example.yaml`

**Interfaces:**
- Consumes: everything above.
- Produces: console script `adengine` with subcommands `validate`, `run [--only GLOB...]`, `status`, `estimate|dry-run [--only GLOB...]`, `revise NODE [--prompt] [--provider] [--model] [--set-input KEY=VALUE]...`, `rollback NODE VERSION`, `schema OUT`; global `--config PATH` (default `<project>/adforge.yaml` if present, else all-mock). Output is JSON on stdout. Exit codes: `0` ok, `1` user/validation error (JSON `{"error": ...}` on stderr), `2` run finished with failed/blocked/needs_review/budget-held nodes. `main(argv: list[str] | None = None) -> int`.

- [ ] **Step 1: Create the fixture** — `tests/fixtures/sample_project/manifest.json`

```json
{
  "project": "sample-mug-ad",
  "nodes": [
    {"id": "refs.product_hero", "type": "image", "prompt": "Matte ceramic travel mug, studio light"},
    {"id": "refs.music_bed", "type": "music", "prompt": "Upbeat lo-fi, 30s"},
    {"id": "v1.s01.keyframe", "type": "image", "prompt": "Mug on kitchen counter at sunrise",
     "inputs": {"refs": ["@refs.product_hero"]}, "depends_on": ["refs.product_hero"]},
    {"id": "v1.s01.clip", "type": "video", "prompt": "Slow push-in, steam rising",
     "inputs": {"first_frame": "@v1.s01.keyframe", "duration": 4, "aspect": "9:16"}, "depends_on": ["v1.s01.keyframe"]},
    {"id": "v1.s02.keyframe", "type": "image", "prompt": "Hand grabs mug, commuter backpack",
     "inputs": {"refs": ["@refs.product_hero"]}, "depends_on": ["refs.product_hero"]},
    {"id": "v1.s02.clip", "type": "video", "prompt": "Handheld follow shot out the door",
     "inputs": {"first_frame": "@v1.s02.keyframe", "duration": 4, "aspect": "9:16"}, "depends_on": ["v1.s02.keyframe"]},
    {"id": "v1.vo.l01", "type": "tts", "prompt": "Your coffee, still hot at 3pm."},
    {"id": "v1.sfx.whoosh01", "type": "sfx", "prompt": "Soft whoosh transition, 0.5s"},
    {"id": "v2.s01.keyframe", "type": "image", "prompt": "Mug next to laptop, rainy window",
     "inputs": {"refs": ["@refs.product_hero"]}, "depends_on": ["refs.product_hero"]},
    {"id": "v2.s01.clip", "type": "video", "prompt": "Rack focus from rain to mug",
     "inputs": {"first_frame": "@v2.s01.keyframe", "duration": 5, "aspect": "9:16"}, "depends_on": ["v2.s01.keyframe"]},
    {"id": "v2.vo.l01", "type": "tts", "prompt": "Built for long days."}
  ]
}
```

- [ ] **Step 2: Write the failing tests** — `tests/test_cli_e2e.py`

```python
import json
import shutil
from pathlib import Path

import pytest

from engine.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "sample_project"


@pytest.fixture
def project(tmp_path):
    dest = tmp_path / "sample"
    shutil.copytree(FIXTURE, dest)
    return dest


def run(capsys, *argv):
    code = main([str(a) for a in argv])
    out = capsys.readouterr()
    return code, (json.loads(out.out) if out.out.strip() else None), out.err


def test_full_flow(project, capsys):
    code, data, _ = run(capsys, "validate", project)
    assert code == 0 and data["nodes"] == 11

    code, data, _ = run(capsys, "estimate", project)
    assert code == 0 and len(data["to_render"]) == 11 and data["total_usd"] == 0.0

    code, data, _ = run(capsys, "run", project)
    assert code == 0 and data["ok"] and len(data["rendered"]) == 11

    code, data, _ = run(capsys, "run", project)
    assert data["rendered"] == [] and len(data["skipped"]) == 11

    code, data, _ = run(capsys, "revise", project, "v1.s01.keyframe", "--prompt", "Mug on counter, golden hour")
    assert code == 0 and data["affected"] == ["v1.s01.keyframe", "v1.s01.clip"]

    code, data, _ = run(capsys, "dry-run", project)
    assert data["to_render"] == ["v1.s01.keyframe", "v1.s01.clip"]

    code, data, _ = run(capsys, "run", project)
    assert sorted(data["rendered"]) == ["v1.s01.clip", "v1.s01.keyframe"]
    assert (project / "v1/shots/s01/versions/keyframe_v1.png").exists()

    code, data, _ = run(capsys, "rollback", project, "v1.s01.keyframe", 1)
    assert code == 0
    code, data, _ = run(capsys, "run", project)
    assert data["rendered"] == ["v1.s01.clip"]

    code, data, _ = run(capsys, "status", project)
    assert data["counts"] == {"done": 11}
    assert not any(n["stale"] for n in data["nodes"].values())


def test_revise_set_input_parses_json_and_raw(project, capsys):
    code, data, _ = run(capsys, "revise", project, "v1.s01.clip",
                        "--set-input", "duration=6", "--set-input", "camera=dolly in")
    assert code == 0
    manifest = json.loads((project / "manifest.json").read_text())
    clip = next(n for n in manifest["nodes"] if n["id"] == "v1.s01.clip")
    assert clip["inputs"]["duration"] == 6 and clip["inputs"]["camera"] == "dolly in"


def test_revise_without_changes_is_error(project, capsys):
    code, _, err = run(capsys, "revise", project, "v1.s01.clip")
    assert code == 1 and "error" in json.loads(err)


def test_invalid_manifest_exit_1(project, capsys):
    (project / "manifest.json").write_text('{"project": "x", "nodes": [{"id": "BAD", "type": "image"}]}')
    code, _, err = run(capsys, "validate", project)
    assert code == 1 and "ValidationError" in json.loads(err)["error"]


def test_run_with_project_config_failure_exit_2(project, capsys):
    (project / "adforge.yaml").write_text(
        "providers:\n  mock:\n    kind: mock\n    fail:\n      v2.vo.l01: [refusal]\n"
    )
    code, data, _ = run(capsys, "run", project)
    assert code == 2 and "v2.vo.l01" in data["needs_review"]


def test_schema_command(tmp_path, capsys):
    out = tmp_path / "schema.json"
    code, data, _ = run(capsys, "schema", out)
    assert code == 0 and "nodes" in json.loads(out.read_text())["properties"]
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_cli_e2e.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'engine.cli'`

- [ ] **Step 4: Implement `engine/cli.py`**

```python
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from engine.config import EngineConfig, load_config
from engine.core.estimate import estimate
from engine.core.manifest import export_schema, load_manifest
from engine.core.revise import revise, rollback
from engine.core.scheduler import Scheduler
from engine.core.status import project_status
from engine.core.store import ProjectStore
from engine.providers.registry import ProviderRegistry


def _emit(data: Any) -> None:
    print(json.dumps(data, indent=2))


def _config(args: argparse.Namespace) -> EngineConfig:
    if args.config is not None:
        return load_config(args.config)
    local = args.project / "adforge.yaml"
    return load_config(local if local.exists() else None)


def _parse_input(pair: str) -> tuple[str, Any]:
    if "=" not in pair:
        raise ValueError(f"--set-input expects KEY=VALUE, got '{pair}'")
    key, raw = pair.split("=", 1)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = raw
    return key, value


def cmd_validate(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.project / "manifest.json")
    _emit({"valid": True, "project": manifest.project, "nodes": len(manifest.nodes)})
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    report = asyncio.run(Scheduler(ProjectStore(args.project), _config(args)).run(args.only or None))
    _emit(report.to_dict())
    return 0 if report.ok else 2


def cmd_status(args: argparse.Namespace) -> int:
    _emit(project_status(ProjectStore(args.project), ProviderRegistry(_config(args))))
    return 0


def cmd_estimate(args: argparse.Namespace) -> int:
    _emit(estimate(ProjectStore(args.project), _config(args), only=args.only or None).to_dict())
    return 0


def cmd_revise(args: argparse.Namespace) -> int:
    changes: dict[str, Any] = {}
    if args.prompt is not None:
        changes["prompt"] = args.prompt
    if args.provider is not None:
        changes["provider"] = args.provider
    if args.model is not None:
        changes["model"] = args.model
    if args.set_input:
        changes["inputs"] = dict(_parse_input(p) for p in args.set_input)
    if not changes:
        raise ValueError("revise needs at least one of --prompt, --provider, --model, --set-input")
    affected = revise(ProjectStore(args.project), args.node_id, changes)
    _emit({"revised": args.node_id, "affected": affected})
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    rollback(ProjectStore(args.project), args.node_id, args.version)
    _emit({"rolled_back": args.node_id, "to_version": args.version})
    return 0


def cmd_schema(args: argparse.Namespace) -> int:
    export_schema(args.out)
    _emit({"schema": str(args.out)})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="adengine", description="AdForge execution engine")
    parser.add_argument("--config", type=Path, default=None,
                        help="engine config YAML (default: <project>/adforge.yaml, else all-mock)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def project_cmd(name: str, func, help_text: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("project", type=Path)
        sp.set_defaults(func=func)
        return sp

    project_cmd("validate", cmd_validate, "validate manifest.json")
    sp = project_cmd("run", cmd_run, "render every stale node in parallel")
    sp.add_argument("--only", nargs="*", default=None, help="node id globs (ancestors included)")
    project_cmd("status", cmd_status, "per-node status, staleness and spend")
    for name in ("estimate", "dry-run"):
        sp = project_cmd(name, cmd_estimate, "list nodes to render and estimated cost; no API calls")
        sp.add_argument("--only", nargs="*", default=None, help="node id globs (ancestors included)")
    sp = project_cmd("revise", cmd_revise, "edit one node; prints affected nodes")
    sp.add_argument("node_id")
    sp.add_argument("--prompt")
    sp.add_argument("--provider")
    sp.add_argument("--model")
    sp.add_argument("--set-input", action="append", metavar="KEY=VALUE",
                    help="VALUE parsed as JSON when possible; JSON null deletes the key")
    sp = project_cmd("rollback", cmd_rollback, "restore an archived version of a node")
    sp.add_argument("node_id")
    sp.add_argument("version", type=int)
    sp = sub.add_parser("schema", help="write manifest JSON schema")
    sp.add_argument("out", type=Path)
    sp.set_defaults(func=cmd_schema)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, KeyError, FileNotFoundError) as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_cli_e2e.py -v`
Expected: 6 passed

- [ ] **Step 6: Write `config.example.yaml`**

```yaml
# Copy to <project>/adforge.yaml (or pass --config). Phase 1 ships only the `mock` adapter;
# real adapters (openai_image, seedance, fishaudio, mcp_bridge) arrive in Phase 3.
providers:
  mock:
    kind: mock
    concurrency: 8
    cost_usd: 0.0
defaults:
  image: mock
  video: mock
  lipsync: mock
  tts: mock
  sfx: mock
  music: mock
  timeline: mock
  preview: mock
  capcut_draft: mock
retry:
  max_attempts: 3
  base_delay_s: 2.0
budget:
  max_usd: null
```

- [ ] **Step 7: Write `README.md`**

````markdown
# AdForge

Paste a short-form ad brief into Claude, get N finished ad variants as preview MP4s + editable CapCut drafts.
Design: `docs/superpowers/specs/2026-11-20-adforge-design.md`.

**Status:** Phase 1 — execution engine core (mock provider only).

## Quickstart

```bash
uv sync
uv run pytest -q
cp -r tests/fixtures/sample_project projects/demo
uv run adengine validate projects/demo
uv run adengine estimate projects/demo
uv run adengine run projects/demo
uv run adengine revise projects/demo v1.s01.keyframe --prompt "golden hour"
uv run adengine run projects/demo        # re-renders only v1.s01.keyframe and v1.s01.clip
uv run adengine rollback projects/demo v1.s01.keyframe 1
uv run adengine status projects/demo
```

## Concepts

- `manifest.json` — written by the brain; every asset is a node with a stable ID (`v2.s03.keyframe`).
- `state.json` — engine-owned status/version/fingerprint per node.
- `ledger.jsonl` — every paid provider call.
- `versions/` — previous outputs, restorable with `adengine rollback`.
````

- [ ] **Step 8: Full suite**

Run: `uv run pytest -q`
Expected: all tests pass (≈90)

- [ ] **Step 9: Smoke-test the installed script**

```bash
rm -rf projects/demo && mkdir -p projects && cp -r tests/fixtures/sample_project projects/demo
uv run adengine run projects/demo
```
Expected: JSON with `"ok": true` and 11 entries in `"rendered"`; exit code 0.

- [ ] **Step 10: Commit**

```bash
command git add engine/cli.py tests/fixtures tests/test_cli_e2e.py README.md config.example.yaml
command git commit -m "feat: adengine CLI with end-to-end mock flow"
```

---

## Next plans (not in this plan)

- Phase 2: assembly — `timeline` builder, ffmpeg preview, CapCut draft writer (mock upgraded to emit real media via ffmpeg).
- Phase 3: real providers — openai_image, seedance, fishaudio, mcp_bridge (Higgsfield).
- Phase 4: QC vision judge (candidate selection, retries → needs_review).
- Phase 5: creator library, `creator_asset` nodes, `lipsync` via Higgsfield, face-consistency QC.
- Phase 6: brain — plugin manifest, `/ad` command, skills, variant-writer subagent, gate UX.
- Phase 7: MCP server exposing engine tools; `--refresh-creators`.
