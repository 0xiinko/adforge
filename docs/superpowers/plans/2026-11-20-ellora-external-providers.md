# Ellora External Providers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let image and video nodes be routed to an "external" provider (Ellora Studio) that the engine never calls: such nodes wait as `awaiting_external` until Claude hands in the rendered file with `adengine supply`, after which the pipeline continues normally.

**Architecture:** Config gains `external_providers`. The scheduler marks ready, stale external nodes `awaiting_external` instead of launching them, and holds reported external failures. `Project` gains `external_errors`, `external_nodes`, `supply` and `supply_failure`; the CLI exposes them as `validate`/`dry-run` checks, `adengine external` and `adengine supply`, with exit code `3` meaning "waiting on external supply". No network code.

**Tech Stack:** Python ≥3.11, asyncio, jsonschema, pyyaml, pytest. ffmpeg (already used by assembly) for converting supplied JPG/WebP images to PNG.

**Spec:** `docs/superpowers/specs/2026-11-20-ellora-integration-design.md` (sections 3, 5, 6). This plan covers build order step 1 (engine). The brain/skills part (step 2) is out of scope.

## Global Constraints

- Branch `feat/ellora`. Run tests with `.venv/bin/python -m pytest -q` from the repo root. All 157 existing tests must keep passing.
- No new dependencies. No network code in the engine. No Ellora-specific names in engine code: the engine is generic over "external providers"; `ellora` appears only in config, tests and docs.
- Model names live in config, never in engine code.
- Only `image` and `video` nodes may be external.
- Existing output strings must not change when nothing is external (e.g. `ran 17, cached 0, failed 0, needs_review 0, blocked 0`).
- Old `state.json` files (without the new `NodeState` fields) must still load.
- Shell note: in this environment a plain `git` may fail with `_lc: command not found`; if so, prefix it: `command git ...`.

## File map

| File | Change |
|---|---|
| `engine/config.py` | `EXTERNAL_TYPES`, `EngineConfig.external_providers`, parsing/validation, `EngineConfig.external_route(node)` |
| `config.example.yaml` | commented `external_providers` example |
| `engine/core/store.py` | `NodeState.expected_fingerprint`, `.external`, `.external_history`; `commit` clears external fields; `rollback` restores the external metadata of the restored version |
| `engine/core/scheduler.py` | `awaiting_external` status, `RunReport.awaiting`, held external failures, shared `block_downstream` |
| `engine/schemas/manifest.schema.json` | add `awaiting_external` to the `status` enum |
| `engine/core/project.py` | `external_errors`, guards in `dry_run`/`run`, `PlannedNode.external`, `external_nodes`, `supply`, `supply_failure` |
| `engine/cli.py` | `validate` external checks, `dry-run` label, awaiting in report, exit code 3, `external` and `supply` commands |
| `tests/helpers.py`, `tests/conftest.py` | `ELLORA_CONFIG`, `ELLORA`, `make_ellora_manifest`, `ellora_dir` fixture |
| `tests/test_config.py` | config tests |
| `tests/test_external_scheduler.py` | scheduler + state tests |
| `tests/test_external_project.py` | validation, dry-run, listing tests |
| `tests/test_supply.py` | supply, failure, rollback tests |
| `tests/test_cli_external.py` | CLI tests incl. the full Claude loop |

---

### Task 1: Config — external providers

**Files:**
- Modify: `engine/config.py`
- Modify: `config.example.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `engine.config.EXTERNAL_TYPES: frozenset[str]` (= `{"image", "video"}`); `EngineConfig.external_providers: frozenset[str]` (default empty); `EngineConfig.external_route(node: Node) -> Route | None` — the node's route when its provider is external, else `None` (also `None` when `route()` raises `ConfigError`).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_config.py` (add the imports at the top if they are not already there):

```python
import pytest

from engine.config import ConfigError, EngineConfig, EXTERNAL_TYPES, Route
from engine.core.graph import Node


def _ellora_cfg(**routing):
    return EngineConfig.from_dict({"external_providers": ["ellora"], "routing": routing})


def test_external_route_only_for_external_providers():
    cfg = _ellora_cfg(image={"provider": "ellora", "model": "img-1"})
    img = Node(id="refs.hero", type="image", inputs={}, depends_on=[])
    tts = Node(id="v1.vo.l01", type="tts", inputs={}, depends_on=[])
    assert cfg.external_providers == frozenset({"ellora"})
    assert cfg.external_route(img) == Route("ellora", "img-1")
    assert cfg.external_route(tts) is None


def test_external_route_none_when_routing_fails():
    cfg = _ellora_cfg()
    bad = Node(id="refs.hero", type="image", inputs={}, depends_on=[], provider="ellora")  # no model
    assert cfg.external_route(bad) is None


def test_external_provider_only_for_image_and_video():
    assert EXTERNAL_TYPES == frozenset({"image", "video"})
    with pytest.raises(ConfigError, match=r"routing\.tts"):
        _ellora_cfg(tts={"provider": "ellora", "model": "m"})


def test_external_providers_must_be_a_list_of_names():
    with pytest.raises(ConfigError, match="external_providers"):
        EngineConfig.from_dict({"external_providers": "ellora"})
    with pytest.raises(ConfigError, match="external_providers"):
        EngineConfig.from_dict({"external_providers": [""]})


def test_no_external_providers_by_default():
    assert EngineConfig().external_providers == frozenset()
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_config.py -q`
Expected: FAIL — `ImportError: cannot import name 'EXTERNAL_TYPES'`.

- [ ] **Step 3: Implement** in `engine/config.py`.

After `NODE_TYPES = (...)` add:

```python
EXTERNAL_TYPES = frozenset({"image", "video"})  # node types an external provider may render
```

In `EngineConfig`, add a field after `capcut`:

```python
    external_providers: frozenset[str] = frozenset()  # never called; outputs are supplied (adengine supply)
```

In `from_dict`, just before `return cfg`, add:

```python
        ext = data.get("external_providers") or []
        if not isinstance(ext, list) or not all(isinstance(x, str) and x for x in ext):
            raise ConfigError("external_providers must be a list of provider names")
        cfg.external_providers = frozenset(ext)
        for node_type, route in cfg.routing.items():
            if route.provider in cfg.external_providers and node_type not in EXTERNAL_TYPES:
                raise ConfigError(
                    f"routing.{node_type}: external provider {route.provider!r} can only render image or video nodes"
                )
```

After the `route` method add:

```python
    def external_route(self, node: Node) -> Route | None:
        """The node's route if it goes to an external provider, else None. Also None when
        routing itself fails: the scheduler reports that error when it tries the node."""
        try:
            route = self.route(node)
        except ConfigError:
            return None
        return route if route.provider in self.external_providers else None
```

- [ ] **Step 4: Document it** — append to `config.example.yaml`:

```yaml

# Providers the engine never calls. Nodes routed to one wait as awaiting_external
# until Claude renders them (e.g. in Ellora Studio) and hands the file in with
# `adengine supply`. Image and video only. Example:
#   external_providers: [ellora]
#   routing:
#     image: {provider: ellora, model: <Ellora modelId from list_models>}
#     video: {provider: ellora, model: <Ellora modelId>}
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (157 + 5).

- [ ] **Step 6: Commit**

```bash
git add engine/config.py config.example.yaml tests/test_config.py
git commit -m "feat(config): external providers — routed nodes the engine never calls"
```

---

### Task 2: Scheduler — `awaiting_external` and held external failures

**Files:**
- Modify: `engine/core/store.py` (`NodeState`, `commit`)
- Modify: `engine/core/scheduler.py`
- Modify: `engine/schemas/manifest.schema.json`
- Modify: `tests/helpers.py`, `tests/conftest.py`
- Test: `tests/test_external_scheduler.py` (create)

**Interfaces:**
- Consumes: `EngineConfig.external_route(node)` (Task 1).
- Produces:
  - `NodeState.expected_fingerprint: str | None = None`, `NodeState.external: dict | None = None`, `NodeState.external_history: dict[str, dict] | None = None`. `ProjectStore.commit` sets `expected_fingerprint` and `external` to `None` (history is kept).
  - `RunReport.awaiting: list[str]`; `RunReport.ok` is false while `awaiting` is non-empty.
  - Store status `awaiting_external` with `reason="external"` and `expected_fingerprint` = the node's current fingerprint.
  - Held failure rule: a stale external node whose state is `(failed, external)` or `(needs_review, refused)` and whose `expected_fingerprint` equals its current fingerprint is reported in `report.failed` / `report.needs_review` again, is not re-listed as awaiting, and blocks its non-assembly descendants.
  - Test helpers: `tests.helpers.ELLORA_CONFIG: dict`, `tests.helpers.ELLORA: EngineConfig`, `tests.helpers.make_ellora_manifest(**kw) -> dict`; fixture `ellora_dir` (project dir with ellora manifest and `config.yaml`).

- [ ] **Step 1: Add test helpers.** Append to `tests/helpers.py`:

```python
ELLORA_CONFIG = {
    "retry": {"base_delay_s": 0},
    "default_concurrency": 8,
    "external_providers": ["ellora"],
    "routing": {
        "image": {"provider": "ellora", "model": "ellora-image"},
        "video": {"provider": "ellora", "model": "ellora-video"},
    },
}
ELLORA = EngineConfig.from_dict(ELLORA_CONFIG)


def make_ellora_manifest(**kw) -> dict:
    """make_manifest() with every image/video node fit for an external provider
    (one candidate per image: inputs.n removed)."""
    data = make_manifest(**kw)
    for n in data["nodes"]:
        n.get("inputs", {}).pop("n", None)
    return data
```

Append to `tests/conftest.py` (add `import yaml` and extend the helpers import to `from tests.helpers import ELLORA_CONFIG, make_ellora_manifest, make_manifest`):

```python
@pytest.fixture
def ellora_dir(tmp_path):
    d = tmp_path / "ellora-launch"
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps(make_ellora_manifest(), indent=2))
    (d / "config.yaml").write_text(yaml.safe_dump(ELLORA_CONFIG))
    return d
```

- [ ] **Step 2: Write the failing tests** — create `tests/test_external_scheduler.py`:

```python
import asyncio
import json

from engine.core.cache import compute_fingerprints
from engine.core.graph import load_manifest
from engine.core.ledger import Ledger
from engine.core.scheduler import Scheduler
from engine.core.store import ProjectStore
from engine.providers.mock import PNG_1X1
from tests.helpers import ELLORA, RecordingProvider, node

KEYFRAMES = {"v1.s01.keyframe", "v1.s02.keyframe", "v2.s01.keyframe", "v2.s02.keyframe"}


def run(project_dir, provider):
    sched = Scheduler(
        load_manifest(project_dir / "manifest.json"), ProjectStore(project_dir), ELLORA,
        {"mock": provider}, Ledger(project_dir / "ledger.jsonl"),
    )
    return asyncio.run(sched.run())


def edit_manifest(project_dir, fn):
    path = project_dir / "manifest.json"
    data = json.loads(path.read_text())
    fn(data)
    path.write_text(json.dumps(data))


def supply_directly(project_dir, node_id):
    """What `adengine supply` does at its core: commit a file against the expected fingerprint."""
    store = ProjectStore(project_dir)
    n = load_manifest(project_dir / "manifest.json").nodes[node_id]
    f = project_dir / f"{node_id}.supplied"
    f.write_bytes(PNG_1X1)
    store.commit(n, f, store.get(node_id).expected_fingerprint)


def test_external_node_waits_and_everything_else_runs(ellora_dir):
    p = RecordingProvider()
    report = run(ellora_dir, p)
    assert report.awaiting == ["refs.product_hero"]
    assert not report.ok
    assert sorted(p.calls) == ["v1.vo.l01", "v2.vo.l01"]
    assert report.blocked == [] and report.failed == []
    store = ProjectStore(ellora_dir)
    hero = store.get("refs.product_hero")
    fps = compute_fingerprints(load_manifest(ellora_dir / "manifest.json"), ELLORA, ellora_dir, {})
    assert hero.status == "awaiting_external" and hero.reason == "external"
    assert hero.expected_fingerprint == fps["refs.product_hero"]
    assert store.get("v1.s01.keyframe").status == "pending"
    assert store.get("v1.timeline").status == "pending"  # assembly waits: no placeholder
    assert not (ellora_dir / "v1" / "timeline.json").exists()


def test_rerun_without_supply_is_still_awaiting(ellora_dir):
    run(ellora_dir, RecordingProvider())
    p = RecordingProvider()
    report = run(ellora_dir, p)
    assert report.awaiting == ["refs.product_hero"] and p.calls == []


def test_supplied_node_is_cached_and_its_dependents_wait_next(ellora_dir):
    run(ellora_dir, RecordingProvider())
    supply_directly(ellora_dir, "refs.product_hero")
    report = run(ellora_dir, RecordingProvider())
    assert "refs.product_hero" in report.skipped
    assert set(report.awaiting) == KEYFRAMES
    store = ProjectStore(ellora_dir)
    assert store.get("refs.product_hero").expected_fingerprint is None  # commit clears it


def test_reported_external_failure_holds_until_revised(ellora_dir):
    run(ellora_dir, RecordingProvider())
    ProjectStore(ellora_dir).update("refs.product_hero", status="needs_review", reason="refused", message="policy")
    report = run(ellora_dir, RecordingProvider())
    assert report.needs_review == ["refs.product_hero"] and report.awaiting == []
    assert KEYFRAMES <= set(report.blocked)
    assert "v1.timeline" in report.ran  # assembly runs with placeholders, as for any failure
    edit_manifest(ellora_dir, lambda d: node(d, "refs.product_hero").update(prompt="a new hero"))
    report = run(ellora_dir, RecordingProvider())
    assert report.awaiting == ["refs.product_hero"] and report.needs_review == []


def test_reported_external_hard_failure_is_failed(ellora_dir):
    run(ellora_dir, RecordingProvider())
    ProjectStore(ellora_dir).update("refs.product_hero", status="failed", reason="external", message="timeout")
    report = run(ellora_dir, RecordingProvider())
    assert report.failed == ["refs.product_hero"] and report.awaiting == []


def test_old_state_file_loads(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"nodes": {"refs.hero": {
        "status": "done", "version": 1, "fingerprint": "x", "reason": None, "message": None,
        "pinned_version": None, "built_from": None,
    }}}))
    st = ProjectStore(tmp_path).get("refs.hero")
    assert st.expected_fingerprint is None and st.external is None and st.external_history is None
```

- [ ] **Step 3: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_external_scheduler.py -q`
Expected: FAIL — `AttributeError: 'RunReport' object has no attribute 'awaiting'` (and `NodeState` attribute errors).

- [ ] **Step 4: Implement `NodeState` fields** in `engine/core/store.py`. Add after `built_from`:

```python
    expected_fingerprint: str | None = None  # set while awaiting_external (spec: ellora §3.3)
    external: dict | None = None             # {"provider", "ref", "id"} of the current version, if supplied
    external_history: dict[str, dict] | None = None  # str(version) → external metadata, for rollback
```

In `commit`, next to `st.reason = None`, add:

```python
        st.expected_fingerprint = None
        st.external = None  # supply() sets it again for supplied files
```

- [ ] **Step 5: Implement the scheduler changes** in `engine/core/scheduler.py`.

Below `FINISHED = ...` add:

```python
HELD_EXTERNAL = frozenset({("failed", "external"), ("needs_review", "refused")})
```

In `RunReport` add the field and update `ok`:

```python
    awaiting: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.failed or self.needs_review or self.blocked or self.awaiting)
```

Replace the body of `Scheduler.run` with:

```python
    async def run(self, targets: Iterable[str] | None = None) -> RunReport:
        m = self.manifest
        self._sems = {}
        fps = compute_fingerprints(m, self.config, self.store.dir, self.store.pins())
        scope = m.scope(targets)
        order = [nid for nid in m.topo_order() if nid in scope]
        report = RunReport()
        status: dict[str, str] = {}

        def block_downstream(nid: str, outcome: str) -> None:
            downstream = m.descendants([nid])
            for d in order:
                if d in downstream and status.get(d) == "pending" and m.nodes[d].type not in ASSEMBLY_TYPES:
                    status[d] = "blocked"
                    self.store.update(d, status="blocked", reason=f"upstream {nid} {outcome}", message=None)
                    report.blocked.append(d)

        stale = self.store.stale_nodes(m, fps, order)
        held: list[str] = []
        for nid in order:
            if nid not in stale:
                status[nid] = "done"
                report.skipped.append(nid)
                if self.store.get(nid).status != "done":
                    self.store.update(nid, status="done", reason=None, message=None)
            elif self._held_external(m.nodes[nid], fps[nid]):
                st = self.store.get(nid)
                status[nid] = st.status
                (report.failed if st.status == "failed" else report.needs_review).append(nid)
                held.append(nid)
            else:
                status[nid] = "pending"
                self.store.update(nid, status="pending", reason=None, message=None)
        for nid in held:
            block_downstream(nid, status[nid])

        running: dict[asyncio.Task, str] = {}

        def ready(nid: str) -> bool:
            node = m.nodes[nid]
            if node.type in ASSEMBLY_TYPES:  # spec §8: assemble with placeholders
                return all(status[d] in FINISHED for d in node.depends_on)
            return all(status[d] == "done" for d in node.depends_on)

        def launch_ready() -> None:
            for nid in order:
                if status[nid] == "pending" and ready(nid):
                    route = self.config.external_route(m.nodes[nid])
                    if route is not None:  # rendered outside the engine; wait for `adengine supply`
                        status[nid] = "awaiting_external"
                        self.store.update(
                            nid, status="awaiting_external", reason="external",
                            message=f"render in {route.provider}, then adengine supply",
                            expected_fingerprint=fps[nid],
                        )
                        report.awaiting.append(nid)
                        continue
                    status[nid] = "running"
                    self.store.update(nid, status="running")
                    running[asyncio.create_task(self._run_node(nid, fps[nid]))] = nid

        launch_ready()
        while running:
            finished, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            for task in finished:
                nid = running.pop(task)
                exc = task.exception()
                if exc is not None:  # backstop: _run_node should never raise
                    outcome, reason, message = "failed", "error", f"{type(exc).__name__}: {exc}"
                else:
                    outcome, reason, message = task.result()
                status[nid] = outcome
                if outcome == "done":
                    report.ran.append(nid)
                    continue
                self.store.update(nid, status=outcome, reason=reason, message=message)
                (report.failed if outcome == "failed" else report.needs_review).append(nid)
                block_downstream(nid, outcome)
            launch_ready()
        return report

    def _held_external(self, node: Node, fingerprint: str) -> bool:
        """An external failure reported via `adengine supply --failed/--refused` stays put
        until the node changes (its fingerprint moves), instead of being re-listed as awaiting."""
        st = self.store.get(node.id)
        return (
            (st.status, st.reason) in HELD_EXTERNAL
            and st.expected_fingerprint == fingerprint
            and self.config.external_route(node) is not None
        )
```

`awaiting_external` is deliberately not in `FINISHED`, so dependents (assembly included) stay `pending`.

- [ ] **Step 6: Schema** — in `engine/schemas/manifest.schema.json` change the `status` enum to:

```json
"status": {"enum": ["pending", "running", "done", "failed", "blocked", "needs_review", "awaiting_external"]},
```

- [ ] **Step 7: Run tests**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (existing scheduler tests unchanged — the blocking logic moved into `block_downstream` with the same behaviour).

- [ ] **Step 8: Commit**

```bash
git add engine/core/store.py engine/core/scheduler.py engine/schemas/manifest.schema.json tests/helpers.py tests/conftest.py tests/test_external_scheduler.py
git commit -m "feat(engine): awaiting_external status — external nodes wait for supply, reported failures hold"
```

---

### Task 3: Project — external validation, dry-run label, listing

**Files:**
- Modify: `engine/core/project.py`
- Test: `tests/test_external_project.py` (create)

**Interfaces:**
- Consumes: `EXTERNAL_TYPES`, `EngineConfig.external_route` (Task 1); `NodeState.expected_fingerprint`, `.external`, status `awaiting_external` (Task 2).
- Produces:
  - `Project.external_errors(manifest: Manifest | None = None) -> list[str]`.
  - `Project.dry_run` and `Project.run` raise `ManifestError(errors)` when `external_errors()` is non-empty.
  - `PlannedNode.external: bool = False` (external nodes: `cost_usd=0.0`, `external=True`).
  - `Project.external_nodes() -> list[dict]`, each `{"id", "type", "provider", "model", "prompt", "inputs", "external_inputs", "fingerprint"}`. Raises `ValueError` if an awaiting node's fingerprint changed since the run that listed it.

- [ ] **Step 1: Write the failing tests** — create `tests/test_external_project.py`:

```python
import asyncio
import json

import pytest

from engine.config import EngineConfig
from engine.core.graph import ManifestError
from engine.core.project import Project
from engine.core.store import ProjectStore
from engine.providers.mock import PNG_1X1
from tests.helpers import ELLORA, ELLORA_CONFIG, RecordingProvider, make_manifest, node


def project(d, config=ELLORA):
    return Project(d, config)


def run(p):
    return asyncio.run(p.run(providers={"mock": RecordingProvider()}))


def write_manifest(d, data):
    (d / "manifest.json").write_text(json.dumps(data))


def test_ellora_manifest_has_no_external_errors(ellora_dir):
    assert project(ellora_dir).external_errors() == []


def test_external_node_cannot_reference_a_local_render(ellora_dir):
    video_only = EngineConfig.from_dict({**ELLORA_CONFIG, "routing": {
        "video": {"provider": "ellora", "model": "ellora-video"}}})
    errors = project(ellora_dir, video_only).external_errors()
    assert len(errors) == 4
    assert errors[0] == (
        "v1.s01.clip: input @v1.s01.keyframe is rendered locally, but ellora cannot read local "
        "files; route v1.s01.keyframe to ellora too"
    )


def test_external_image_must_have_one_candidate(ellora_dir):
    write_manifest(ellora_dir, make_manifest())  # keyframes have inputs.n = 2
    errors = project(ellora_dir).external_errors()
    assert "v1.s01.keyframe: external image nodes render one candidate; remove inputs.n or set it to 1" in errors


def test_only_image_and_video_may_be_external(ellora_dir):
    data = json.loads((ellora_dir / "manifest.json").read_text())
    node(data, "v1.vo.l01").update(provider="ellora", model="ellora-tts")
    write_manifest(ellora_dir, data)
    assert project(ellora_dir).external_errors() == [
        "v1.vo.l01: external provider ellora can only render image or video nodes"
    ]


def test_dry_run_and_run_refuse_invalid_external_manifests(ellora_dir):
    write_manifest(ellora_dir, make_manifest())
    with pytest.raises(ManifestError):
        project(ellora_dir).dry_run()
    with pytest.raises(ManifestError):
        run(project(ellora_dir))


def test_dry_run_labels_external_nodes(ellora_dir):
    report = project(ellora_dir).dry_run(providers={"mock": RecordingProvider(cost_per_call=0.5)})
    by_id = {p.node_id: p for p in report.to_run}
    hero = by_id["refs.product_hero"]
    assert hero.external and hero.cost_usd == 0.0 and hero.provider == "ellora"
    assert not by_id["v1.vo.l01"].external and by_id["v1.vo.l01"].cost_usd == 0.5


def test_external_nodes_lists_awaiting_with_resolved_inputs(ellora_dir):
    p = project(ellora_dir)
    assert p.external_nodes() == []
    run(p)
    [hero] = p.external_nodes()
    assert hero == {
        "id": "refs.product_hero",
        "type": "image",
        "provider": "ellora",
        "model": "ellora-image",
        "prompt": "Hero shot of a matte ceramic mug on a wooden table",
        "inputs": {"size": "1024x1024"},
        "external_inputs": {"size": "1024x1024"},
        "fingerprint": ProjectStore(ellora_dir).get("refs.product_hero").expected_fingerprint,
    }


def test_external_inputs_use_the_supplied_ref(ellora_dir):
    p = project(ellora_dir)
    run(p)
    store = ProjectStore(ellora_dir)
    hero = p.manifest().nodes["refs.product_hero"]
    f = ellora_dir / "hero.png"
    f.write_bytes(PNG_1X1)
    store.commit(hero, f, store.get("refs.product_hero").expected_fingerprint)
    store.update("refs.product_hero", external={"provider": "ellora", "ref": "ellora://hero", "id": "g1"})
    run(p)
    kf = next(n for n in p.external_nodes() if n["id"] == "v1.s01.keyframe")
    assert kf["inputs"]["refs"] == [str(ellora_dir / "refs" / "product_hero.png")]
    assert kf["external_inputs"]["refs"] == ["ellora://hero"]


def test_external_nodes_rejects_a_node_changed_since_the_run(ellora_dir):
    p = project(ellora_dir)
    run(p)
    data = json.loads((ellora_dir / "manifest.json").read_text())
    node(data, "refs.product_hero").update(prompt="changed")
    write_manifest(ellora_dir, data)
    with pytest.raises(ValueError, match="refs.product_hero changed since the last run"):
        p.external_nodes()
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_external_project.py -q`
Expected: FAIL — `AttributeError: 'Project' object has no attribute 'external_errors'`.

- [ ] **Step 3: Implement** in `engine/core/project.py`.

Imports — change/add:

```python
from engine.config import EXTERNAL_TYPES, EngineConfig, load_config
from engine.core.graph import Manifest, ManifestError, Node, find_refs, load_manifest, resolve_refs, save_manifest
```

`PlannedNode` — add a last field:

```python
    external: bool = False  # supplied by Claude via `adengine supply`; the engine never calls it
```

Add methods to `Project` (after `_providers`):

```python
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
```

In `run`, load the manifest once and check it:

```python
    async def run(self, targets: Iterable[str] | None = None, providers: dict[str, Provider] | None = None) -> RunReport:
        manifest = self.manifest()
        self._check_external(manifest)
        scheduler = Scheduler(manifest, self.store(), self.config, self._providers(providers), self.ledger())
        return await scheduler.run(targets)
```

In `dry_run`, after `manifest, store, provs = ...` add `self._check_external(manifest)`, and replace the body of the `for` loop after the cached branch with:

```python
            route = self.config.route(node)
            if self.config.external_route(node) is not None:
                report.to_run.append(PlannedNode(nid, route.provider, route.model, 0.0, False, external=True))
                continue
            provider = provs.get(route.provider)
            cost = provider.cost(node.type, cost_params(node, resolve_inputs(manifest, self.dir, node))) if provider else 0.0
            report.to_run.append(PlannedNode(nid, route.provider, route.model, cost, provider is not None))
```

Add `external_nodes` (after `status`):

```python
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
```

(`Node` is imported for Task 4; keep the import.)

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add engine/core/project.py tests/test_external_project.py
git commit -m "feat(engine): external validation, dry-run label and awaiting-node listing"
```

---

### Task 4: Project — `supply`, `supply_failure`, rollback of supplied files

**Files:**
- Modify: `engine/core/project.py`
- Modify: `engine/core/store.py` (`rollback`)
- Test: `tests/test_supply.py` (create)

**Interfaces:**
- Consumes: Tasks 1–3; `ProjectStore.commit/work_dir/update/get`; `Ledger.record`; `engine.assembly.ffmpeg.FFmpeg(config.assembly).run(args)`; `engine.core.paths.EXTENSIONS`.
- Produces:
  - `Project.supply(node_id: str, file: Path | str, *, ref: str, external_id: str | None = None, fingerprint: str | None = None) -> int` (new version).
  - `Project.supply_failure(node_id: str, *, refused: bool, message: str) -> None`.
  - Errors: `KeyError` unknown node; `ValueError` not external / not awaiting / changed / fingerprint mismatch / wrong extension; `FileNotFoundError` missing file; `ProviderError` from ffmpeg conversion.
  - `ProjectStore.rollback` restores `external` from `external_history[str(restored_version)]`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_supply.py`:

```python
import asyncio
import json

import pytest

from engine.core.ledger import Ledger
from engine.core.project import Project
from engine.core.store import ProjectStore
from engine.providers.mock import PNG_1X1
from tests.helpers import ELLORA, RecordingProvider, node

HERO = "refs.product_hero"


def run(d):
    return asyncio.run(Project(d, ELLORA).run(providers={"mock": RecordingProvider()}))


def png(d, name="hero.png"):
    f = d / name
    f.write_bytes(PNG_1X1)
    return f


def revise_hero(d, prompt):
    data = json.loads((d / "manifest.json").read_text())
    node(data, HERO).update(prompt=prompt)
    (d / "manifest.json").write_text(json.dumps(data))


def test_supply_commits_and_the_pipeline_continues(ellora_dir):
    run(ellora_dir)
    src = png(ellora_dir)
    version = Project(ellora_dir, ELLORA).supply(HERO, src, ref="ellora://hero", external_id="g1")
    assert version == 1
    assert src.exists()  # copied, not moved
    assert (ellora_dir / "refs" / "product_hero.png").read_bytes() == PNG_1X1
    st = ProjectStore(ellora_dir).get(HERO)
    assert st.status == "done" and st.expected_fingerprint is None
    assert st.external == {"provider": "ellora", "ref": "ellora://hero", "id": "g1"}
    assert st.external_history == {"1": st.external}
    [entry] = [e for e in Ledger(ellora_dir / "ledger.jsonl").entries() if e["node_id"] == HERO]
    assert entry["ok"] is True and entry["cost_usd"] == 0.0 and entry["external_id"] == "g1"
    assert entry["provider"] == "ellora" and entry["model"] == "ellora-image"
    report = run(ellora_dir)
    assert HERO in report.skipped and "v1.s01.keyframe" in report.awaiting


def test_resupply_after_revision_archives_the_old_version(ellora_dir):
    p = Project(ellora_dir, ELLORA)
    run(ellora_dir)
    p.supply(HERO, png(ellora_dir), ref="r1")
    revise_hero(ellora_dir, "second take")
    run(ellora_dir)
    assert p.supply(HERO, png(ellora_dir), ref="r2") == 2
    assert (ellora_dir / "refs" / "versions" / "refs.product_hero_v1.png").exists()


def test_supply_rejects_a_node_changed_since_listing(ellora_dir):
    run(ellora_dir)
    revise_hero(ellora_dir, "changed")
    with pytest.raises(ValueError, match="changed since it was listed"):
        Project(ellora_dir, ELLORA).supply(HERO, png(ellora_dir), ref="r")


def test_supply_rejects_a_fingerprint_mismatch(ellora_dir):
    run(ellora_dir)
    with pytest.raises(ValueError, match="--fingerprint does not match"):
        Project(ellora_dir, ELLORA).supply(HERO, png(ellora_dir), ref="r", fingerprint="nope")


def test_supply_rejects_nodes_that_are_not_awaiting_or_not_external(ellora_dir):
    p = Project(ellora_dir, ELLORA)
    with pytest.raises(ValueError, match="not awaiting_external"):
        p.supply(HERO, png(ellora_dir), ref="r")
    run(ellora_dir)
    with pytest.raises(ValueError, match="not routed to an external provider"):
        p.supply("v1.vo.l01", png(ellora_dir), ref="r")
    with pytest.raises(KeyError):
        p.supply("v9.nope", png(ellora_dir), ref="r")


def test_supply_rejects_wrong_extension_and_missing_file(ellora_dir):
    run(ellora_dir)
    p = Project(ellora_dir, ELLORA)
    clip = ellora_dir / "clip.mp4"
    clip.write_bytes(b"x")
    with pytest.raises(ValueError, match="image needs one of"):
        p.supply(HERO, clip, ref="r")
    with pytest.raises(FileNotFoundError):
        p.supply(HERO, ellora_dir / "missing.png", ref="r")
    assert ProjectStore(ellora_dir).get(HERO).status == "awaiting_external"


def test_jpg_is_converted_to_png(ellora_dir, ffmpeg):
    # JPG rather than WebP here: every ffmpeg build can encode it, so the test fixture is portable.
    run(ellora_dir)
    jpg = ellora_dir / "hero.jpg"
    asyncio.run(ffmpeg.run(["-f", "lavfi", "-i", "color=red:s=8x8", "-frames:v", "1", str(jpg)]))
    Project(ellora_dir, ELLORA).supply(HERO, jpg, ref="r")
    assert (ellora_dir / "refs" / "product_hero.png").read_bytes()[:4] == b"\x89PNG"


def test_refused_supply_holds_and_blocks_until_revised(ellora_dir):
    run(ellora_dir)
    Project(ellora_dir, ELLORA).supply_failure(HERO, refused=True, message="content policy")
    st = ProjectStore(ellora_dir).get(HERO)
    assert (st.status, st.reason, st.message) == ("needs_review", "refused", "content policy")
    [entry] = [e for e in Ledger(ellora_dir / "ledger.jsonl").entries() if e["node_id"] == HERO]
    assert entry["ok"] is False
    report = run(ellora_dir)
    assert report.needs_review == [HERO] and "v1.s01.keyframe" in report.blocked
    revise_hero(ellora_dir, "softer wording")
    assert run(ellora_dir).awaiting == [HERO]


def test_failed_supply_marks_failed(ellora_dir):
    run(ellora_dir)
    Project(ellora_dir, ELLORA).supply_failure(HERO, refused=False, message="timed out")
    assert ProjectStore(ellora_dir).get(HERO).status == "failed"
    assert run(ellora_dir).failed == [HERO]


def test_rollback_restores_the_external_ref(ellora_dir):
    p = Project(ellora_dir, ELLORA)
    run(ellora_dir)
    p.supply(HERO, png(ellora_dir), ref="r1")
    revise_hero(ellora_dir, "second take")
    run(ellora_dir)
    p.supply(HERO, png(ellora_dir), ref="r2")
    new_version = p.rollback(HERO, 1)
    st = ProjectStore(ellora_dir).get(HERO)
    assert st.external["ref"] == "r1"
    assert st.external_history[str(new_version)]["ref"] == "r1"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_supply.py -q`
Expected: FAIL — `AttributeError: 'Project' object has no attribute 'supply'`.

- [ ] **Step 3: Implement supply** in `engine/core/project.py`.

Imports — add:

```python
import asyncio
import shutil

from engine.assembly.ffmpeg import FFmpeg
from engine.config import Route
from engine.core.paths import EXTENSIONS, resolve_inputs
```

(`resolve_inputs` is already imported from `engine.core.paths`; extend that line rather than duplicating it.)

Module constant below `REVISABLE`:

```python
SUPPLY_SUFFIXES: dict[str, frozenset[str]] = {
    "image": frozenset({".png", ".jpg", ".jpeg", ".webp"}),
    "video": frozenset({".mp4"}),
}
```

Methods on `Project` (after `external_nodes`):

```python
    def _awaiting(self, node_id: str) -> tuple[Node, Route, str, ProjectStore]:
        """The awaiting external node, its route, its current fingerprint and the store.
        Raises if the node cannot be supplied right now."""
        manifest, store = self.manifest(), self.store()
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
        return node, route, current, store

    def supply(
        self, node_id: str, file: Path | str, *, ref: str,
        external_id: str | None = None, fingerprint: str | None = None,
    ) -> int:
        """Commit a file rendered outside the engine as the node's new version."""
        node, route, current, store = self._awaiting(node_id)
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
        version = store.commit(node, staged, current)
        ext = {"provider": route.provider, "ref": ref, "id": external_id}
        history = dict(store.get(node_id).external_history or {})
        history[str(version)] = ext
        store.update(node_id, external=ext, external_history=history)
        self.ledger().record(
            node_id=node_id, provider=route.provider, model=route.model, cost_usd=0.0,
            seconds=0.0, attempt=1, ok=True, external_id=external_id,
        )
        return version

    def supply_failure(self, node_id: str, *, refused: bool, message: str) -> None:
        """Record that the external render failed or was refused. The node keeps its
        expected fingerprint, so runs hold it (and block dependents) until it is revised."""
        node, route, _, store = self._awaiting(node_id)
        status, reason = ("needs_review", "refused") if refused else ("failed", "external")
        store.update(node_id, status=status, reason=reason, message=message)
        self.ledger().record(
            node_id=node_id, provider=route.provider, model=route.model, cost_usd=0.0,
            seconds=0.0, attempt=1, ok=False, external_id=None,
        )
```

- [ ] **Step 4: Rollback keeps the external ref** — in `engine/core/store.py`, replace the last line of `rollback` (`return self.commit(node, staged, pin=True)`) with:

```python
        new_version = self.commit(node, staged, pin=True)
        st = self.get(node.id)
        ext = (st.external_history or {}).get(str(version))
        if ext is not None:  # a supplied file: later external nodes need its provider-side ref
            st.external = ext
            st.external_history = {**(st.external_history or {}), str(new_version): ext}
            self.save()
        return new_version
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (`test_jpg_is_converted_to_png` is skipped if ffmpeg is missing).

- [ ] **Step 6: Commit**

```bash
git add engine/core/project.py engine/core/store.py tests/test_supply.py
git commit -m "feat(engine): adengine supply core — commit external renders, record failures, keep refs on rollback"
```

---

### Task 5: CLI — `external`, `supply`, exit code 3, validate/dry-run

**Files:**
- Modify: `engine/cli.py`
- Test: `tests/test_cli_external.py` (create)

**Interfaces:**
- Consumes: `Project.external_errors/external_nodes/supply/supply_failure`, `RunReport.awaiting`, `PlannedNode.external` (Tasks 2–4).
- Produces: commands `adengine external <project> [--json]`, `adengine supply <project> <node_id> [file] --ref R [--id I] [--fingerprint F] | --failed MSG | --refused MSG`. Exit codes for `run`/`revise`: `0` ok, `1` failed/needs_review/blocked, `3` only awaiting.

- [ ] **Step 1: Write the failing tests** — create `tests/test_cli_external.py`:

```python
import json

import yaml

from engine.cli import main
from engine.providers.mock import PNG_1X1
from tests.helpers import ELLORA_CONFIG

HERO = "refs.product_hero"


def supply_file(d, n):
    f = d / f"{n['id']}{'.png' if n['type'] == 'image' else '.mp4'}"
    f.write_bytes(PNG_1X1 if n["type"] == "image" else b"clip")
    return f


def test_run_exits_3_while_awaiting(ellora_dir, capsys):
    assert main(["run", str(ellora_dir)]) == 3
    out = capsys.readouterr().out
    assert "ran 2, cached 0, failed 0, needs_review 0, blocked 0, awaiting 1" in out
    assert f"AWAITING {HERO}" in out


def test_external_lists_awaiting_nodes(ellora_dir, capsys):
    main(["run", str(ellora_dir)])
    capsys.readouterr()
    assert main(["external", str(ellora_dir), "--json"]) == 0
    [hero] = json.loads(capsys.readouterr().out)
    assert hero["id"] == HERO and hero["model"] == "ellora-image"
    assert main(["external", str(ellora_dir)]) == 0
    assert capsys.readouterr().out.startswith(HERO)


def test_external_with_nothing_awaiting(ellora_dir, capsys):
    assert main(["external", str(ellora_dir)]) == 0
    assert capsys.readouterr().out.strip() == "nothing awaiting external supply"


def test_supply_and_refuse(ellora_dir, capsys):
    main(["run", str(ellora_dir)])
    f = supply_file(ellora_dir, {"id": HERO, "type": "image"})
    assert main(["supply", str(ellora_dir), HERO, str(f), "--ref", "ellora://hero", "--id", "g1"]) == 0
    assert capsys.readouterr().out.strip().endswith(f"supplied {HERO} as v1")
    assert main(["run", str(ellora_dir)]) == 3
    capsys.readouterr()
    assert main(["supply", str(ellora_dir), "v1.s01.keyframe", "--refused", "content policy"]) == 0
    assert "v1.s01.keyframe marked needs_review (refused)" in capsys.readouterr().out
    assert main(["run", str(ellora_dir)]) == 1  # 1 wins over 3
    assert "ATTENTION v1.s01.keyframe" in capsys.readouterr().out


def test_supply_argument_errors(ellora_dir, capsys):
    main(["run", str(ellora_dir)])
    capsys.readouterr()
    assert main(["supply", str(ellora_dir), HERO]) == 1
    assert "supply needs a file and --ref" in capsys.readouterr().err
    f = supply_file(ellora_dir, {"id": HERO, "type": "image"})
    assert main(["supply", str(ellora_dir), HERO, str(f), "--failed", "x"]) == 1
    assert "not both" in capsys.readouterr().err
    assert main(["supply", str(ellora_dir), "v1.vo.l01", str(f), "--ref", "r"]) == 1
    assert "not routed to an external provider" in capsys.readouterr().err


def test_validate_and_dry_run_report_external_problems(ellora_dir, capsys):
    cfg = {**ELLORA_CONFIG, "routing": {"video": {"provider": "ellora", "model": "ellora-video"}}}
    (ellora_dir / "config.yaml").write_text(yaml.safe_dump(cfg))
    assert main(["validate", str(ellora_dir)]) == 1
    assert "ERROR: v1.s01.clip: input @v1.s01.keyframe is rendered locally" in capsys.readouterr().err
    assert main(["dry-run", str(ellora_dir)]) == 1


def test_dry_run_labels_external_nodes(ellora_dir, capsys):
    assert main(["dry-run", str(ellora_dir)]) == 0
    assert f"RUN    {HERO}" in capsys.readouterr().out
    main(["dry-run", str(ellora_dir)])
    assert "(external: supplied by Claude)" in capsys.readouterr().out


def test_full_claude_loop_finishes(ellora_dir, capsys):
    passes = 0
    while (code := main(["run", str(ellora_dir)])) == 3:
        passes += 1
        assert passes <= 4
        capsys.readouterr()
        assert main(["external", str(ellora_dir), "--json"]) == 0
        for n in json.loads(capsys.readouterr().out):
            if n["id"].endswith(".clip"):
                assert n["external_inputs"]["first_frame"] == f"ellora://{n['id'].replace('.clip', '.keyframe')}"
            f = supply_file(ellora_dir, n)
            assert main([
                "supply", str(ellora_dir), n["id"], str(f),
                "--ref", f"ellora://{n['id']}", "--fingerprint", n["fingerprint"],
            ]) == 0
    assert code == 0 and passes == 3  # hero, keyframes, clips
    assert (ellora_dir / "v1" / "preview.mp4").exists()
    assert (ellora_dir / "v2" / "capcut_draft").is_dir()
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli_external.py -q`
Expected: FAIL — `run` returns `1` instead of `3`, and `external`/`supply` are unknown commands (argparse `SystemExit: 2`).

- [ ] **Step 3: Implement** in `engine/cli.py`.

Import `ProviderError`:

```python
from engine.providers.base import ProviderError
```

Replace `_print_report` and add `_exit_code`:

```python
def _print_report(report: RunReport) -> None:
    line = (
        f"ran {len(report.ran)}, cached {len(report.skipped)}, failed {len(report.failed)}, "
        f"needs_review {len(report.needs_review)}, blocked {len(report.blocked)}"
    )
    if report.awaiting:
        line += f", awaiting {len(report.awaiting)}"
    print(line)
    for nid in report.failed + report.needs_review:
        print(f"ATTENTION {nid}")
    for nid in report.awaiting:
        print(f"AWAITING {nid}")


def _exit_code(report: RunReport) -> int:
    """0 done; 1 something failed, needs review or is blocked; 3 only waiting for `adengine supply`."""
    if report.failed or report.needs_review or report.blocked:
        return 1
    return 3 if report.awaiting else 0
```

In `cmd_run` and `cmd_revise`, replace `return 0 if report.ok else 1` with `return _exit_code(report)`.

Replace `cmd_validate`:

```python
def cmd_validate(args: argparse.Namespace) -> int:
    try:
        manifest = load_manifest(Path(args.project) / "manifest.json")
    except ManifestError as e:
        for err in e.errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1
    errors = _project(args).external_errors(manifest)
    for err in errors:
        print(f"ERROR: {err}", file=sys.stderr)
    if errors:
        return 1
    print(f"OK: {len(manifest.nodes)} nodes")
    return 0
```

In `cmd_dry_run`, replace the `note = ...` line with:

```python
        if p.external:
            note = "  (external: supplied by Claude)"
        else:
            note = "" if p.provider_available else "  (provider not registered)"
```

Add the two commands (after `cmd_rollback`):

```python
def cmd_external(args: argparse.Namespace) -> int:
    nodes = _project(args).external_nodes()
    if args.json:
        print(json.dumps(nodes, indent=2))
        return 0
    if not nodes:
        print("nothing awaiting external supply")
    for n in nodes:
        print(f"{n['id']:<28} {n['type']:<6} {n['provider']}/{n['model']}")
    return 0


def cmd_supply(args: argparse.Namespace) -> int:
    project = _project(args)
    if args.failed is not None or args.refused is not None:
        if args.file is not None:
            print("ERROR: give a file or --failed/--refused, not both", file=sys.stderr)
            return 1
        refused = args.refused is not None
        project.supply_failure(args.node_id, refused=refused, message=args.refused if refused else args.failed)
        print(f"{args.node_id} marked {'needs_review (refused)' if refused else 'failed'}")
        return 0
    if args.file is None or not args.ref:
        print("ERROR: supply needs a file and --ref (or --failed/--refused)", file=sys.stderr)
        return 1
    version = project.supply(
        args.node_id, args.file, ref=args.ref, external_id=args.external_id, fingerprint=args.fingerprint,
    )
    print(f"supplied {args.node_id} as v{version}")
    return 0
```

In `_parser`, before `return p`, register them:

```python
    ex = add("external", cmd_external, "list nodes waiting for an external render (adengine supply)")
    ex.add_argument("--json", action="store_true", help="full details: prompt, inputs, external_inputs, fingerprint")
    sp = add("supply", cmd_supply, "hand in a file rendered outside the engine, or report that it failed")
    sp.add_argument("node_id")
    sp.add_argument("file", nargs="?", type=Path, default=None)
    sp.add_argument("--ref", help="the provider's own path/URL for this result; later external nodes use it as input")
    sp.add_argument("--id", dest="external_id", default=None, help="the provider's generation id")
    sp.add_argument("--fingerprint", default=None, help="from `adengine external`; rejects the file if the node changed")
    bad = sp.add_mutually_exclusive_group()
    bad.add_argument("--failed", metavar="MESSAGE", default=None, help="the external render failed")
    bad.add_argument("--refused", metavar="MESSAGE", default=None, help="the external provider refused the prompt")
```

In `main`, add `ProviderError` to the caught exception tuple:

```python
    except (ManifestError, ConfigError, ProviderError, ValueError, KeyError, FileNotFoundError, json.JSONDecodeError) as e:
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass, including the unchanged `tests/test_cli.py` (no external nodes → output identical to before).

- [ ] **Step 5: Commit**

```bash
git add engine/cli.py tests/test_cli_external.py
git commit -m "feat(cli): adengine external and supply; run exits 3 while awaiting external renders"
```

---

## Done when

- `.venv/bin/python -m pytest -q` passes (157 existing + the new tests; the JPG conversion test may skip without ffmpeg).
- `test_full_claude_loop_finishes` shows the whole loop: `run` → exit 3 → `external --json` → `supply` ×N → … → exit 0 with previews and CapCut drafts built.
- `git log` on `feat/ellora` shows the spec commit plus five task commits.
