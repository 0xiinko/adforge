# AdForge Assembly Implementation Plan (Plan 2 of 7)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn each variant's rendered shots and audio into a `timeline.json`, a reviewable `preview.mp4` (cuts and crossfades, mixed VO and SFX, ducked music, burned-in captions, end card) and an editable CapCut draft. Missing inputs become placeholders, so the preview and the draft are always complete. A media-producing mock makes the whole pipeline testable with zero API cost.

**Architecture:** Assembly is an engine-internal provider named `assembly`. It handles the three assembly node types through the existing `Provider.assemble` hook:
- `timeline` is a pure function of the node's inputs plus probed media durations.
- `preview` drives system `ffmpeg` through small subprocess calls inside the node's work dir.
- `capcut_draft` is an isolated, template-driven JSON writer.

The scheduler starts assembly nodes once every dependency has *finished*, whether or not it succeeded, which implements spec §8's placeholders. A new `mock_media` provider emits tiny real PNG/MP4/WAV files via ffmpeg.

**Tech Stack:** Python 3.12, system `ffmpeg` + `ffprobe` (subprocess, never a shell), pytest. No new Python dependencies.

**Spec:** `docs/superpowers/specs/2026-11-20-adforge-design.md`: §7 Assembly, §8 placeholders, §10 golden tests, §11 step 2.
**Builds on:** Plan 1 (`docs/superpowers/plans/2026-11-20-adforge-engine-core.md`), which is merged on `main`. Read `engine/core/scheduler.py`, `engine/providers/base.py` and `engine/core/paths.py` before starting.

## Prerequisite (human, once)

```bash
sudo apt install -y ffmpeg fonts-dejavu-core
ffmpeg -hide_banner -filters | grep -E " (xfade|sidechaincompress|subtitles|drawtext|zoompan) "
```

On macOS (the production machine): `brew install ffmpeg`. Captions and slates use Helvetica from `/System/Library/Fonts/Helvetica.ttc` by default (see `AssemblyConfig.font_file`), so no extra fonts are needed.

Expected: five matching filter lines. Ubuntu's ffmpeg build includes libass, freetype and fontconfig, which these filters need. Tests that need ffmpeg use the `ffmpeg` fixture and **skip** when it is missing, so the rest of the suite stays green. Plan 2 isn't finished until those tests actually run and pass.

## Global Constraints

- Python `>=3.11`. Runtime Python deps stay exactly `jsonschema` and `pyyaml`. ffmpeg/ffprobe are external binaries whose paths come from config (`assembly.ffmpeg`, `assembly.ffprobe`).
- ffmpeg is always invoked with an argument list (`asyncio.create_subprocess_exec`), never through a shell. User text such as captions and end-card copy reaches ffmpeg only through files (`textfile=`, `.ass`), never by interpolating it into filter strings.
- The engine makes no creative decisions. Shot order, slot durations, transitions, VO text, SFX timing, music volume and end-card copy all come from the timeline node's `inputs`, which the brain writes. The engine only fills mechanical defaults (named constants in `engine/assembly/timeline.py`).
- Runs on Linux (development) and macOS (production). Platform differences live only in `AssemblyConfig` defaults: the font, an optional font file, and the CapCut drafts folder example. Never branch on the platform anywhere else.
- All audio outputs are `.wav` (spec §4). This changes `music` from `.mp3` to `.wav`.
- Every CapCut clip is named by its node ID. CapCut-format knowledge lives only in `engine/assembly/capcut_draft.py` and `engine/assembly/capcut_template.json`.
- Assembly nodes (`timeline`, `preview`, `capcut_draft`) are free. They are routed like any node but never write ledger entries (the scheduler already logs only `GENERATION_TYPES`).
- Missing upstream media never fails assembly. A missing clip becomes its `fallback` keyframe with a slow zoom, or a slate showing the node ID if there is no fallback. Missing audio is skipped. Every substitution is listed in `timeline.json` under `placeholders`.
- The plain `mock` provider (JSON stamps) stays the default routing, so all existing tests keep running without ffmpeg. `config.example.yaml` switches to `mock_media` + `assembly`.
- **Known risk, recorded deliberately:** the CapCut draft format is undocumented. The writer follows the open-source pyJianYingDraft-style layout, but newer CapCut desktop releases may refuse unencrypted or older-format drafts. Task 7 ends with a manual acceptance check in CapCut. If it fails, only `capcut_template.json` and `capcut_draft.py` change.

---

## File Structure

```
engine/
  config.py                     # + AssemblyConfig, CapcutConfig
  core/paths.py                 # music → .wav
  core/scheduler.py             # ctx.project_dir/sources; assembly nodes run on finished (not only done) deps
  providers/
    base.py                     # CallContext.project_dir, CallContext.sources
    mock.py                     # music.wav
    mock_media.py               # NEW: MediaMockProvider ("mock_media"): real tiny media via ffmpeg
    assembly.py                 # NEW: AssemblyProvider ("assembly"): timeline / preview / capcut_draft
    __init__.py                 # registers mock, mock_media, assembly
  assembly/
    __init__.py                 # NEW (package marker)
    ffmpeg.py                   # NEW: FFmpeg wrapper (run, probe, available) + MediaInfo
    timeline.py                 # NEW: build_timeline (pure), media_paths, caption_chunks
    ffmpeg_preview.py           # NEW: render_preview, render_slate_image, build_concat_filter, captions_ass
    capcut_draft.py             # NEW: build_draft (pure), write_draft
    capcut_template.json        # NEW: draft_content.json skeleton
config.example.yaml             # mock_media + assembly routing, assembly/capcut sections
tests/
  helpers.py                    # make_manifest timeline contract, assert_golden
  conftest.py                   # + ffmpeg fixture (skips without ffmpeg)
  golden/timeline_basic.json    # NEW (generated, reviewed, committed)
  golden/capcut_basic.json      # NEW (generated, reviewed, committed)
  test_ffmpeg.py  test_mock_media.py  test_timeline.py  test_preview.py
  test_capcut_draft.py  test_assembly_provider.py  test_e2e_media.py      # NEW
```

### Timeline node contract (what the brain writes; validated by `build_timeline`)

```json
{
  "id": "v1.timeline", "type": "timeline",
  "inputs": {
    "aspect": "9:16",
    "fps": 30,
    "shots": [
      {"clip": "@v1.s01.clip", "duration": 4, "fallback": "@v1.s01.keyframe"},
      {"clip": "@v1.s02.clip", "duration": 3.5, "transition": "crossfade", "fallback": "@v1.s02.keyframe"}
    ],
    "vo": [{"audio": "@v1.vo.l01", "text": "Fresh coffee every single morning"},
           {"audio": "@v1.vo.l02", "text": "Try it today", "start": 4.0}],
    "sfx": [{"audio": "@v1.sfx.whoosh", "start": 3.9, "volume": 0.8}],
    "music": {"audio": "@shared.music.bed", "volume": 0.25, "duck": true},
    "captions": true,
    "end_card": {"text": "Shop now", "duration": 2, "image": "@v1.end_card_bg"}
  },
  "depends_on": ["v1.s01.clip", "v1.s02.clip", "v1.s01.keyframe", "v1.s02.keyframe", "v1.vo.l01", "v1.vo.l02",
                 "v1.sfx.whoosh", "shared.music.bed", "v1.end_card_bg"]
}
```

`preview` and `capcut_draft` nodes take `{"timeline": "@vX.timeline"}`.

---

### Task 1: Plumbing (config sections, .wav music, call context, fixture contract)

**Files:**
- Modify: `engine/config.py`, `engine/core/paths.py`, `engine/providers/base.py`, `engine/providers/mock.py`, `engine/core/scheduler.py`
- Modify: `tests/helpers.py`, `tests/test_paths.py`, `tests/test_config.py`, `tests/test_scheduler.py`

**Interfaces:**
- Consumes: Plan 1's `EngineConfig`, `CallContext`, `Scheduler._run_node`, `make_manifest`.
- Produces:
  - `engine.config.AssemblyConfig(ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe", font: str = default_font(), font_file: str | None = default_font_file())`. On macOS (`sys.platform == "darwin"`) the defaults are `"Helvetica"` and `"/System/Library/Fonts/Helvetica.ttc"`. Elsewhere they are `"DejaVu Sans"` and `None`. `font` is the family name used by captions (libass). `font_file`, when set, is passed to ffmpeg drawtext as `fontfile=` instead of `font=`.
  - `engine.config.CapcutConfig(drafts_dir: Path | None = None, media_root: str | None = None)`
  - `EngineConfig.assembly: AssemblyConfig` and `EngineConfig.capcut: CapcutConfig`, both parsed by `from_dict` from the `assembly:` and `capcut:` sections. `media_root` has trailing `/` and `\` stripped, and `drafts_dir` has `~` expanded.
  - `engine.providers.base.CallContext` gains `project_dir: Path | None = None` and `sources: dict[str, str]` (default `{}`). For assembly nodes, the scheduler sets `project_dir = store.dir` and `sources = {str(absolute output path of dep): dep_id for every dep}`. Other nodes get `project_dir` and an empty `sources`.
  - `EXTENSIONS["music"] == ".wav"`
  - `tests.helpers.make_manifest()` timeline nodes use the timeline contract above: shots with `duration: 4` and a keyframe `fallback`, one VO line with `text`, and an end card `{"text": "Shop now", "duration": 2}`. Keyframes are added to the timeline's `depends_on`. Still 17 nodes.
  - `tests.helpers.assert_golden(name: str, data) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`, and add `from engine.config import AssemblyConfig, default_font, default_font_file` to its imports:

```python
def test_assembly_and_capcut_defaults():
    cfg = EngineConfig()
    assert (cfg.assembly.ffmpeg, cfg.assembly.ffprobe) == ("ffmpeg", "ffprobe")
    assert (cfg.assembly.font, cfg.assembly.font_file) == (default_font(), default_font_file())
    assert cfg.capcut.drafts_dir is None and cfg.capcut.media_root is None


def test_font_defaults_per_platform(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    assert (default_font(), default_font_file()) == ("Helvetica", "/System/Library/Fonts/Helvetica.ttc")
    monkeypatch.setattr("sys.platform", "linux")
    assert (default_font(), default_font_file()) == ("DejaVu Sans", None)
    assert AssemblyConfig().font == "DejaVu Sans"


def test_assembly_and_capcut_from_dict(tmp_path):
    cfg = EngineConfig.from_dict({
        "assembly": {"ffmpeg": "/opt/ff/ffmpeg", "font": "Inter"},
        "capcut": {"drafts_dir": str(tmp_path / "drafts"), "media_root": "C:/AdForge/projects/"},
    })
    assert (cfg.assembly.ffmpeg, cfg.assembly.ffprobe, cfg.assembly.font) == ("/opt/ff/ffmpeg", "ffprobe", "Inter")
    assert EngineConfig.from_dict({"assembly": {"font_file": "/fonts/Inter.ttf"}}).assembly.font_file == "/fonts/Inter.ttf"
    assert cfg.capcut.drafts_dir == tmp_path / "drafts"
    assert cfg.capcut.media_root == "C:/AdForge/projects"
```

In `tests/test_paths.py`, change the music row of the parametrize list to:

```python
        ("shared.music.bed", "music", "shared/music/bed.wav"),
```

Append to `tests/test_scheduler.py`:

```python
class ContextRecorder(RecordingProvider):
    def __init__(self):
        super().__init__()
        self.contexts = {}

    async def _before(self, ctx):
        self.contexts[ctx.node_id] = ctx
        await super()._before(ctx)


def test_assembly_nodes_get_project_dir_and_sources(project_dir):
    p = ContextRecorder()
    run(project_dir, p)
    ctx = p.contexts["v1.timeline"]
    assert ctx.project_dir == project_dir
    assert ctx.sources == {
        str(project_dir / "v1/shots/s01/clip.mp4"): "v1.s01.clip",
        str(project_dir / "v1/shots/s02/clip.mp4"): "v1.s02.clip",
        str(project_dir / "v1/shots/s01/keyframe.png"): "v1.s01.keyframe",
        str(project_dir / "v1/shots/s02/keyframe.png"): "v1.s02.keyframe",
        str(project_dir / "v1/vo/l01.wav"): "v1.vo.l01",
    }
    assert p.contexts["v1.s01.clip"].sources == {}
    assert p.contexts["v1.s01.clip"].project_dir == project_dir
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_config.py tests/test_paths.py tests/test_scheduler.py -q`
Expected: 5 failures (the platform-font test also fails, with `ImportError`):
- `test_assembly_and_capcut_defaults` and `test_assembly_and_capcut_from_dict`: `AttributeError: 'EngineConfig' object has no attribute 'assembly'`.
- The music path row: `bed.mp3 != bed.wav`.
- `test_assembly_nodes_get_project_dir_and_sources`: `AttributeError: ... 'project_dir'`.

- [ ] **Step 3: Implement config sections**

In `engine/config.py`, add `import sys` to the imports, then add after `RetryConfig`:

```python
def default_font() -> str:
    return "Helvetica" if sys.platform == "darwin" else "DejaVu Sans"


def default_font_file() -> str | None:
    return "/System/Library/Fonts/Helvetica.ttc" if sys.platform == "darwin" else None


@dataclass
class AssemblyConfig:
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    font: str = field(default_factory=default_font)            # family name for captions (libass)
    font_file: str | None = field(default_factory=default_font_file)  # drawtext fontfile=; None → font=


@dataclass
class CapcutConfig:
    drafts_dir: Path | None = None   # folder CapCut scans for drafts; None = keep the draft in the project only
    media_root: str | None = None    # how the projects/ folder is seen from the CapCut machine
```

Add two fields to `EngineConfig`, after `retry`:

```python
    assembly: AssemblyConfig = field(default_factory=AssemblyConfig)
    capcut: CapcutConfig = field(default_factory=CapcutConfig)
```

In `EngineConfig.from_dict`, insert before the final `return cfg`:

```python
        asm = data.get("assembly") or {}
        cfg.assembly = AssemblyConfig(
            ffmpeg=str(asm.get("ffmpeg", "ffmpeg")),
            ffprobe=str(asm.get("ffprobe", "ffprobe")),
            font=str(asm.get("font", default_font())),
            font_file=str(asm["font_file"]) if asm.get("font_file") else default_font_file(),
        )
        cap = data.get("capcut") or {}
        cfg.capcut = CapcutConfig(
            drafts_dir=Path(str(cap["drafts_dir"])).expanduser() if cap.get("drafts_dir") else None,
            media_root=str(cap["media_root"]).rstrip("/\\") if cap.get("media_root") else None,
        )
```

- [ ] **Step 4: Music becomes .wav**

In `engine/core/paths.py`, change the `EXTENSIONS` entry to `"music": ".wav",`. In `engine/providers/mock.py`, change the `music` method's filename from `"music.mp3"` to `"music.wav"`.

- [ ] **Step 5: Extend CallContext and pass it from the scheduler**

Replace the `CallContext` dataclass in `engine/providers/base.py`, and change its import line to `from dataclasses import dataclass, field`:

```python
@dataclass
class CallContext:
    node_id: str
    model: str
    work_dir: Path  # empty directory; write outputs here and return their paths
    project_dir: Path | None = None
    sources: dict[str, str] = field(default_factory=dict)  # assembly only: absolute input path → node id
```

In `engine/core/scheduler.py`, add `ASSEMBLY_TYPES` to the `from engine.providers.base import (...)` list. In `_run_node`, directly after `inputs = resolve_inputs(self.manifest, self.store.dir, node)`, add:

```python
            sources = (
                {str(self.store.output(self.manifest.nodes[d])): d for d in node.depends_on}
                if node.type in ASSEMBLY_TYPES
                else {}
            )
```

Then replace the `ctx = CallContext(...)` line with:

```python
                ctx = CallContext(
                    node_id=nid, model=route.model, work_dir=self.store.work_dir(nid),
                    project_dir=self.store.dir, sources=sources,
                )
```

- [ ] **Step 6: Update the fixture manifest to the timeline contract and add `assert_golden`**

In `tests/helpers.py`, replace the `nodes.append({... "id": f"{v}.timeline" ...})` block inside `make_manifest` with:

```python
        keyframes = [f"{v}.s{s:02d}.keyframe" for s in range(1, shots + 1)]
        nodes.append({
            "id": f"{v}.timeline",
            "type": "timeline",
            "inputs": {
                "aspect": "9:16",
                "shots": [
                    {"clip": f"@{c}", "duration": 4, "fallback": f"@{k}"} for c, k in zip(clips, keyframes)
                ],
                "vo": [{"audio": f"@{v}.vo.l01", "text": f"Line for {v}"}],
                "end_card": {"text": "Shop now", "duration": 2},
            },
            "depends_on": clips + keyframes + [f"{v}.vo.l01"],
        })
```

Add to the imports at the top of `tests/helpers.py`:

```python
import json
import os
from pathlib import Path
```

Append to `tests/helpers.py`:

```python
GOLDEN_DIR = Path(__file__).parent / "golden"


def assert_golden(name: str, data) -> None:
    """Compare JSON-able `data` with tests/golden/<name>. Run once with
    ADFORGE_UPDATE_GOLDEN=1 to (re)write the file, then review it before committing."""
    path = GOLDEN_DIR / name
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if os.environ.get("ADFORGE_UPDATE_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    assert path.exists(), f"missing golden file {path}; run with ADFORGE_UPDATE_GOLDEN=1 and review it"
    assert json.loads(path.read_text()) == json.loads(text)
```

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -q -W error`
Expected: everything passes, including the 4 new or changed tests. The node count, invalidation sets and CLI expectations are unchanged, because keyframes were already ancestors of each timeline.

- [ ] **Step 8: Commit**

```bash
command git add engine tests
command git commit -m "feat(engine): assembly plumbing — config sections, wav music, call context sources"
```

---

### Task 2: Assembly nodes run once their inputs have finished (spec §8 placeholders)

**Files:**
- Modify: `engine/core/scheduler.py`
- Modify: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: Task 1's scheduler.
- Produces: new scheduler semantics.
  - A non-assembly node is ready when all its deps are `done`. That is unchanged.
  - An **assembly** node (`ASSEMBLY_TYPES`) is ready when every dep is in `{"done", "failed", "needs_review", "blocked"}`.
  - When a node fails or needs review, only its pending **non-assembly** descendants become `blocked`. Assembly descendants stay pending and run with placeholders.
  - Re-running after the failed input recovers rebuilds the assembly nodes. This needs no new code: the failed dep is stale and its version changes, so Plan 1's freshness rule covers it.

- [ ] **Step 1: Update the existing tests whose expectations change, and add new tests**

In `tests/test_scheduler.py`, replace `test_hard_failure_blocks_only_dependents` with:

```python
def test_hard_failure_blocks_generation_dependents_only(project_dir):
    report = run(project_dir, RecordingProvider(fail={"v1.s01.keyframe"}))
    assert not report.ok
    assert report.failed == ["v1.s01.keyframe"]
    assert report.blocked == ["v1.s01.clip"]
    store = ProjectStore(project_dir)
    st = store.get("v1.s01.keyframe")
    assert (st.status, st.reason) == ("failed", "error") and "boom" in st.message
    assert store.get("v1.s01.clip").reason == "upstream v1.s01.keyframe failed"
    for n in ("v1.timeline", "v1.preview", "v1.capcut_draft", "v2.preview", "v1.s02.clip"):
        assert store.get(n).status == "done", n
```

Replace `test_refusal_goes_to_needs_review` with:

```python
def test_refusal_goes_to_needs_review(project_dir):
    report = run(project_dir, RecordingProvider(refuse={"v2.s01.clip"}))
    assert report.needs_review == ["v2.s01.clip"]
    assert report.blocked == []
    assert {"v2.timeline", "v2.preview", "v2.capcut_draft"} <= set(report.ran)
    st = ProjectStore(project_dir).get("v2.s01.clip")
    assert (st.status, st.reason, st.message) == ("needs_review", "refused", "content policy")
```

In `test_commit_failure_is_isolated_to_the_node`, replace the line
`assert {"v1.timeline", "v2.timeline"} <= set(report.blocked)` with:

```python
    assert {"v1.timeline", "v2.timeline"} <= set(report.ran)
```

Append:

```python
def test_assembly_waits_until_every_input_has_finished(project_dir):
    p = RecordingProvider(fail={"v1.s01.keyframe"}, delays={"v1.s02.clip": 0.2})
    run(project_dir, p)
    assert p.events.index(("start", "v1.timeline")) > p.events.index(("end", "v1.s02.clip"))


def test_assembly_rebuilds_when_a_failed_input_recovers(project_dir):
    run(project_dir, RecordingProvider(fail={"v1.s01.keyframe"}))
    p = RecordingProvider()
    assert run(project_dir, p).ok
    assert {"v1.timeline", "v1.preview", "v1.capcut_draft"} <= set(p.calls)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_scheduler.py -q`
Expected: failures in the hard-failure, refusal, commit-failure and wait-until-finished tests (assembly nodes are still blocked). `test_assembly_rebuilds_when_a_failed_input_recovers` may already pass.

- [ ] **Step 3: Implement**

In `engine/core/scheduler.py`, add a module constant below `Outcome`:

```python
FINISHED = frozenset({"done", "failed", "needs_review", "blocked"})
```

Replace `launch_ready` inside `run()` with:

```python
        def ready(nid: str) -> bool:
            node = m.nodes[nid]
            if node.type in ASSEMBLY_TYPES:  # spec §8: assemble with placeholders
                return all(status[d] in FINISHED for d in node.depends_on)
            return all(status[d] == "done" for d in node.depends_on)

        def launch_ready() -> None:
            for nid in order:
                if status[nid] == "pending" and ready(nid):
                    status[nid] = "running"
                    self.store.update(nid, status="running")
                    running[asyncio.create_task(self._run_node(nid, fps[nid]))] = nid
```

In the blocking loop, replace `if d in downstream and status[d] == "pending":` with:

```python
                    if d in downstream and status[d] == "pending" and m.nodes[d].type not in ASSEMBLY_TYPES:
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_scheduler.py -q`, then `uv run pytest -q -W error`.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
command git add engine/core/scheduler.py tests/test_scheduler.py
command git commit -m "feat(engine): assembly nodes run once inputs finish, enabling placeholders"
```

---

### Task 3: ffmpeg wrapper

**Files:**
- Create: `engine/assembly/__init__.py` (empty), `engine/assembly/ffmpeg.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_ffmpeg.py`

**Interfaces:**
- Consumes: `AssemblyConfig` (Task 1), `ProviderError` (Plan 1).
- Produces:
  - `engine.assembly.ffmpeg.MediaInfo(duration: float, width: int|None, height: int|None, has_video: bool, has_audio: bool)` (frozen)
  - `engine.assembly.ffmpeg.FFmpeg(config: AssemblyConfig | None = None)` with attributes `.ffmpeg`, `.ffprobe`, `.font`, `.font_file` and methods:
    - `font_option() -> str` returns `"fontfile='<font_file>'"` when `font_file` is set, else `"font='<font>'"`. Every drawtext call uses it.
    - `available() -> bool`
    - `async run(args: list[str], cwd: Path | None = None) -> None`. It prepends `ffmpeg -hide_banner -loglevel error -y`.
    - `async probe(path: Path) -> MediaInfo`
  - Errors: a missing binary raises `ProviderError("… not found; install ffmpeg or set assembly.ffmpeg/ffprobe in config")`. A non-zero exit raises `ProviderError("<binary> failed (exit N): <last stderr lines>")`.
  - `tests/conftest.py` fixture `ffmpeg` returns `FFmpeg()`, or skips with the reason `ffmpeg/ffprobe not installed (sudo apt install ffmpeg)`.

- [ ] **Step 1: Add the fixture and write the failing tests**

Append to `tests/conftest.py`, and add `from engine.assembly.ffmpeg import FFmpeg` to its imports:

```python
@pytest.fixture
def ffmpeg():
    ff = FFmpeg()
    if not ff.available():
        pytest.skip("ffmpeg/ffprobe not installed (sudo apt install ffmpeg)")
    return ff
```

Create `tests/test_ffmpeg.py`:

```python
import asyncio

import pytest

from engine.assembly.ffmpeg import FFmpeg
from engine.config import AssemblyConfig
from engine.providers.base import ProviderError


def test_missing_binary_is_a_provider_error():
    ff = FFmpeg(AssemblyConfig(ffmpeg="no-such-ffmpeg-binary", ffprobe="no-such-ffprobe-binary"))
    assert not ff.available()
    with pytest.raises(ProviderError, match="not found"):
        asyncio.run(ff.run(["-version"]))


def test_probe_audio(ffmpeg, tmp_path):
    asyncio.run(ffmpeg.run(["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1.5", "tone.wav"], cwd=tmp_path))
    info = asyncio.run(ffmpeg.probe(tmp_path / "tone.wav"))
    assert info.has_audio and not info.has_video
    assert info.duration == pytest.approx(1.5, abs=0.05)


def test_probe_video(ffmpeg, tmp_path):
    asyncio.run(ffmpeg.run([
        "-f", "lavfi", "-i", "color=c=red:s=64x36:r=24", "-t", "2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "clip.mp4",
    ], cwd=tmp_path))
    info = asyncio.run(ffmpeg.probe(tmp_path / "clip.mp4"))
    assert (info.width, info.height) == (64, 36)
    assert info.has_video and not info.has_audio
    assert info.duration == pytest.approx(2.0, abs=0.1)


def test_probe_image_dimensions(ffmpeg, tmp_path):
    asyncio.run(ffmpeg.run(["-f", "lavfi", "-i", "color=c=blue:s=64x112", "-frames:v", "1", "still.png"], cwd=tmp_path))
    info = asyncio.run(ffmpeg.probe(tmp_path / "still.png"))
    assert (info.width, info.height) == (64, 112)


def test_font_option_prefers_font_file():
    assert FFmpeg(AssemblyConfig(font="Inter", font_file=None)).font_option() == "font='Inter'"
    assert FFmpeg(AssemblyConfig(font="Helvetica", font_file="/System/Library/Fonts/Helvetica.ttc")).font_option() == (
        "fontfile='/System/Library/Fonts/Helvetica.ttc'"
    )


def test_ffmpeg_failure_reports_stderr(ffmpeg, tmp_path):
    with pytest.raises(ProviderError, match="ffmpeg failed"):
        asyncio.run(ffmpeg.run(["-i", "does-not-exist.mp4", "out.mp4"], cwd=tmp_path))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_ffmpeg.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'engine.assembly'`.

- [ ] **Step 3: Implement**

Create the empty `engine/assembly/__init__.py`. Create `engine/assembly/ffmpeg.py`:

```python
"""Thin async wrapper around the ffmpeg/ffprobe binaries. Always argument lists,
never a shell."""
from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from engine.config import AssemblyConfig
from engine.providers.base import ProviderError


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    width: int | None
    height: int | None
    has_video: bool
    has_audio: bool


def _float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


class FFmpeg:
    def __init__(self, config: AssemblyConfig | None = None):
        cfg = config or AssemblyConfig()
        self.ffmpeg = cfg.ffmpeg
        self.ffprobe = cfg.ffprobe
        self.font = cfg.font
        self.font_file = cfg.font_file

    def font_option(self) -> str:
        """drawtext font selector: an explicit file (macOS default) or a fontconfig family name."""
        return f"fontfile='{self.font_file}'" if self.font_file else f"font='{self.font}'"

    def available(self) -> bool:
        return shutil.which(self.ffmpeg) is not None and shutil.which(self.ffprobe) is not None

    async def _exec(self, args: list[str], cwd: Path | None) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                *args, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            raise ProviderError(
                f"{args[0]} not found; install ffmpeg or set assembly.ffmpeg/ffprobe in config"
            ) from None
        out, err = await proc.communicate()
        if proc.returncode != 0:
            tail = err.decode(errors="replace").strip().splitlines()[-8:]
            raise ProviderError(f"{Path(args[0]).name} failed (exit {proc.returncode}): " + " | ".join(tail))
        return out.decode(errors="replace")

    async def run(self, args: list[str], cwd: Path | None = None) -> None:
        await self._exec([self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *args], cwd)

    async def probe(self, path: Path) -> MediaInfo:
        out = await self._exec([
            self.ffprobe, "-v", "error",
            "-show_entries", "format=duration:stream=codec_type,width,height",
            "-of", "json", str(path),
        ], None)
        data = json.loads(out or "{}")
        streams = data.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        return MediaInfo(
            duration=_float(data.get("format", {}).get("duration")),
            width=video.get("width") if video else None,
            height=video.get("height") if video else None,
            has_video=video is not None,
            has_audio=any(s.get("codec_type") == "audio" for s in streams),
        )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_ffmpeg.py -v`
Expected: 6 passed with ffmpeg installed. Without it, the two tests that don't need ffmpeg pass and the other 4 are skipped.

- [ ] **Step 5: Commit**

```bash
command git add engine/assembly tests/conftest.py tests/test_ffmpeg.py
command git commit -m "feat(assembly): async ffmpeg/ffprobe wrapper"
```

---

### Task 4: Media-producing mock provider (`mock_media`)

**Files:**
- Create: `engine/providers/mock_media.py`
- Test: `tests/test_mock_media.py`

**Interfaces:**
- Consumes: `FFmpeg` (Task 3), `Provider`, `CallContext`, `ProviderError` (Plan 1).
- Produces: `engine.providers.mock_media.MediaMockProvider(ffmpeg: FFmpeg | None = None)` with `name = "mock_media"`, plus `ASPECT_SIZES`. It writes real files into `ctx.work_dir`:
  - `generate_image` writes `candidate_<i>.png` at the requested `size` (`"WxH"`; anything else raises `ProviderError` mentioning `size`). Each image is a solid colour derived from the node ID, labelled with the ID.
  - `generate_video` writes `clip.mp4` of exactly `duration` seconds at a small resolution for its aspect (`9:16` → 270x480, `16:9` → 480x270, `1:1` → 360x360, `4:5` → 320x400). It uses the first frame when one exists, otherwise a solid colour. No audio.
  - `tts` writes `vo.wav` lasting `max(0.8, 0.38 × words)` seconds. `sfx` writes `sfx.wav` and `music` writes `music.wav`, each lasting `duration` seconds. All are quiet sine tones at 48 kHz mono.
  - `cost()` returns 0.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mock_media.py`:

```python
import asyncio

import pytest

from engine.assembly.ffmpeg import FFmpeg
from engine.providers.base import CallContext, ProviderError
from engine.providers.mock_media import MediaMockProvider


def ctx(tmp_path, node_id):
    d = tmp_path / node_id
    d.mkdir()
    return CallContext(node_id=node_id, model="mock", work_dir=d)


def test_image_candidates_have_requested_size(ffmpeg, tmp_path):
    mock = MediaMockProvider(ffmpeg)
    paths = asyncio.run(mock.generate_image(ctx(tmp_path, "refs.hero"), "mug", [], "64x112", 2))
    assert [p.name for p in paths] == ["candidate_0.png", "candidate_1.png"]
    info = asyncio.run(ffmpeg.probe(paths[0]))
    assert (info.width, info.height) == (64, 112)


def test_video_matches_duration_and_aspect(ffmpeg, tmp_path):
    mock = MediaMockProvider(ffmpeg)
    still = asyncio.run(mock.generate_image(ctx(tmp_path, "v1.s01.keyframe"), "p", [], "64x112", 1))[0]
    clip = asyncio.run(mock.generate_video(ctx(tmp_path, "v1.s01.clip"), "push in", still, None, 2.0, "9:16"))
    info = asyncio.run(ffmpeg.probe(clip))
    assert (info.width, info.height) == (270, 480)
    assert info.duration == pytest.approx(2.0, abs=0.1)
    wide = asyncio.run(mock.generate_video(ctx(tmp_path, "v1.s02.clip"), "p", None, None, 1.0, "16:9"))
    assert asyncio.run(ffmpeg.probe(wide)).width == 480


def test_audio_durations(ffmpeg, tmp_path):
    mock = MediaMockProvider(ffmpeg)
    vo = asyncio.run(mock.tts(ctx(tmp_path, "v1.vo.l01"), "one two three four five", "narrator", "neutral"))
    fx = asyncio.run(mock.sfx(ctx(tmp_path, "v1.sfx.whoosh"), "whoosh", 0.5))
    bed = asyncio.run(mock.music(ctx(tmp_path, "shared.music.bed"), "lofi", 3.0))
    assert [p.name for p in (vo, fx, bed)] == ["vo.wav", "sfx.wav", "music.wav"]
    durations = [asyncio.run(ffmpeg.probe(p)).duration for p in (vo, fx, bed)]
    assert durations == pytest.approx([1.9, 0.5, 3.0], abs=0.05)


def test_bad_size_is_a_provider_error(tmp_path):
    mock = MediaMockProvider(FFmpeg())
    with pytest.raises(ProviderError, match="size"):
        asyncio.run(mock.generate_image(ctx(tmp_path, "refs.hero"), "p", [], "big", 1))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_mock_media.py -q`
Expected: `ModuleNotFoundError: No module named 'engine.providers.mock_media'`.

- [ ] **Step 3: Implement**

Create `engine/providers/mock_media.py`:

```python
"""Mock provider that emits real, tiny media files via ffmpeg, so assembly can be
exercised end to end without paid APIs. Colours are derived from the node id."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from engine.assembly.ffmpeg import FFmpeg
from engine.providers.base import CallContext, Provider, ProviderError

ASPECT_SIZES: dict[str, tuple[int, int]] = {
    "9:16": (270, 480), "16:9": (480, 270), "1:1": (360, 360), "4:5": (320, 400),
}
_SIZE = re.compile(r"^(\d+)x(\d+)$")


def _color(key: str) -> str:
    return "0x" + hashlib.sha256(key.encode()).hexdigest()[:6]


class MediaMockProvider(Provider):
    name = "mock_media"

    def __init__(self, ffmpeg: FFmpeg | None = None):
        self.ff = ffmpeg or FFmpeg()

    def _label(self, ctx: CallContext, text: str, size: int) -> str:
        (ctx.work_dir / "label.txt").write_text(text)
        return (f"drawtext={self.ff.font_option()}:textfile=label.txt:expansion=none:fontcolor=white"
                f":fontsize={size}:x=(w-text_w)/2:y=(h-text_h)/2")

    async def generate_image(self, ctx, prompt, refs, size, n):
        m = _SIZE.match(size)
        if not m:
            raise ProviderError(f"{ctx.node_id}: image size must look like 1024x1792, got {size!r}")
        width, height = int(m.group(1)), int(m.group(2))
        paths = []
        for i in range(n):
            name = f"candidate_{i}.png"
            await self.ff.run([
                "-f", "lavfi", "-i", f"color=c={_color(ctx.node_id + str(i))}:s={width}x{height}",
                "-frames:v", "1", "-vf", self._label(ctx, ctx.node_id, max(10, height // 20)), name,
            ], cwd=ctx.work_dir)
            paths.append(ctx.work_dir / name)
        return paths

    async def generate_video(self, ctx, prompt, first_frame, last_frame, duration, aspect):
        width, height = ASPECT_SIZES.get(aspect, ASPECT_SIZES["9:16"])
        if first_frame and Path(first_frame).exists():
            source = ["-loop", "1", "-i", str(first_frame)]
        else:
            source = ["-f", "lavfi", "-i", f"color=c={_color(ctx.node_id)}:s={width}x{height}"]
        vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps=24,format=yuv420p"
        await self.ff.run([
            *source, "-t", f"{duration:.3f}", "-vf", vf,
            "-c:v", "libx264", "-preset", "ultrafast", "-an", "clip.mp4",
        ], cwd=ctx.work_dir)
        return ctx.work_dir / "clip.mp4"

    async def _tone(self, ctx: CallContext, name: str, freq: int, seconds: float, volume: float) -> Path:
        await self.ff.run([
            "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={seconds:.3f}",
            "-af", f"volume={volume}", "-ac", "1", name,
        ], cwd=ctx.work_dir)
        return ctx.work_dir / name

    async def tts(self, ctx, text, voice, emotion):
        return await self._tone(ctx, "vo.wav", 220, max(0.8, 0.38 * len(text.split())), 0.1)

    async def sfx(self, ctx, prompt, duration):
        return await self._tone(ctx, "sfx.wav", 880, duration, 0.2)

    async def music(self, ctx, prompt, duration):
        return await self._tone(ctx, "music.wav", 110, duration, 0.2)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_mock_media.py -v`
Expected: 4 passed with ffmpeg installed. Without it, 3 skipped and 1 passed.

- [ ] **Step 5: Commit**

```bash
command git add engine/providers/mock_media.py tests/test_mock_media.py
command git commit -m "feat(providers): mock_media provider emitting real tiny media"
```

---

### Task 5: Timeline builder

**Files:**
- Create: `engine/assembly/timeline.py`
- Test: `tests/test_timeline.py`, `tests/golden/timeline_basic.json` (generated)

**Interfaces:**
- Consumes: `ProviderError` (Plan 1), `assert_golden` (Task 1).
- Produces:
  - Constants: `TIMELINE_VERSION = 1`, `ASPECTS`, `TRANSITIONS = ("cut", "crossfade")`, `DEFAULT_FPS = 30`, `CROSSFADE_S = 0.25`, `VO_LEAD_IN_S = 0.2`, `VO_GAP_S = 0.15`, `WORDS_PER_CAPTION = 3`, `SECONDS_PER_WORD = 0.4`, `MIN_VO_S = 0.8`, `DEFAULT_MUSIC_VOLUME = 0.25`, `DEFAULT_END_CARD_S = 2.0`, `HOLD_TOLERANCE_S = 0.05`, `IMAGE_SUFFIXES`
  - `TimelineError(ProviderError)`
  - `media_paths(inputs) -> list[str]`
  - `caption_chunks(text, start, duration, words_per_chunk=3) -> list[dict]`
  - `build_timeline(node_id, inputs, *, sources: dict[str, str], project_dir: Path, media: dict[str, float]) -> dict`. `media` maps each input path that **exists** to its duration (0.0 for images).
- Output schema (`timeline.json`). Every key is always present, and paths are project-relative POSIX strings:
  ```
  {version, node, width, height, fps, duration,
   tracks: {
     video:   [{node, path, kind: video|image|slate, start, duration, transition, transition_s, hold, placeholder_for}],
     vo:      [{node, path|null, start, duration, text}],
     sfx:     [{node, path, start, duration, volume}],
     music:   {node, path, start, duration, source_duration, volume, duck} | null,
     captions:[{start, end, text}],
     end_card:{node|null, path|null, start, duration, text} | null},
   placeholders: [node ids substituted], warnings: [str]}
  ```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_timeline.py`:

```python
import re
from pathlib import Path

import pytest

from engine.assembly.timeline import TimelineError, build_timeline, caption_chunks, media_paths
from tests.helpers import assert_golden

P = Path("/proj")


def src(rel):
    return str(P / rel)


CLIP1, CLIP2 = src("v1/shots/s01/clip.mp4"), src("v1/shots/s02/clip.mp4")
KF1, KF2 = src("v1/shots/s01/keyframe.png"), src("v1/shots/s02/keyframe.png")
L01, L02 = src("v1/vo/l01.wav"), src("v1/vo/l02.wav")
WHOOSH, BED, END = src("v1/sfx/whoosh.wav"), src("shared/music/bed.wav"), src("v1/end.png")
SOURCES = {
    CLIP1: "v1.s01.clip", CLIP2: "v1.s02.clip", KF1: "v1.s01.keyframe", KF2: "v1.s02.keyframe",
    L01: "v1.vo.l01", L02: "v1.vo.l02", WHOOSH: "v1.sfx.whoosh", BED: "shared.music.bed", END: "v1.end",
}
MEDIA = {CLIP1: 3.0, CLIP2: 2.0, KF1: 0.0, KF2: 0.0, L01: 2.0, L02: 1.0, WHOOSH: 0.5, BED: 10.0}


def inputs(**overrides):
    base = {
        "aspect": "9:16",
        "shots": [
            {"clip": CLIP1, "duration": 3, "fallback": KF1},
            {"clip": CLIP2, "duration": 2.5, "transition": "crossfade", "fallback": KF2},
        ],
        "vo": [{"audio": L01, "text": "Fresh coffee every single morning"}, {"audio": L02, "text": "Try it today"}],
        "sfx": [{"audio": WHOOSH, "start": 2.9, "volume": 0.8}],
        "music": {"audio": BED, "volume": 0.3},
        "end_card": {"text": "Shop now", "duration": 1.5},
    }
    base.update(overrides)
    return base


def build(media=MEDIA, **overrides):
    return build_timeline("v1.timeline", inputs(**overrides), sources=SOURCES, project_dir=P, media=dict(media))


def test_basic_timeline_layout():
    t = build()
    assert (t["width"], t["height"], t["fps"], t["duration"]) == (1080, 1920, 30, 7.0)
    v = t["tracks"]["video"]
    assert [(e["node"], e["kind"], e["start"], e["duration"]) for e in v] == [
        ("v1.s01.clip", "video", 0.0, 3.0), ("v1.s02.clip", "video", 3.0, 2.5),
    ]
    assert v[0]["path"] == "v1/shots/s01/clip.mp4"
    assert [(e["transition"], e["transition_s"]) for e in v] == [("cut", 0.0), ("crossfade", 0.25)]
    assert [e["hold"] for e in v] == [False, True]
    vo = t["tracks"]["vo"]
    assert [(e["start"], e["duration"]) for e in vo] == [(0.2, 2.0), (2.35, 1.0)]
    assert t["tracks"]["captions"] == [
        {"start": 0.2, "end": 1.325, "text": "Fresh coffee every"},
        {"start": 1.325, "end": 2.2, "text": "single morning"},
        {"start": 2.35, "end": 3.35, "text": "Try it today"},
    ]
    assert t["tracks"]["sfx"] == [
        {"node": "v1.sfx.whoosh", "path": "v1/sfx/whoosh.wav", "start": 2.9, "duration": 0.5, "volume": 0.8},
    ]
    assert t["tracks"]["music"] == {
        "node": "shared.music.bed", "path": "shared/music/bed.wav", "start": 0.0, "duration": 7.0,
        "source_duration": 10.0, "volume": 0.3, "duck": True,
    }
    assert t["tracks"]["end_card"] == {"node": None, "path": None, "start": 5.5, "duration": 1.5, "text": "Shop now"}
    assert t["placeholders"] == [] and t["warnings"] == []


def test_golden_basic_timeline():
    assert_golden("timeline_basic.json", build())


def test_missing_media_becomes_placeholders():
    media = {KF1: 0.0, L01: 2.0, WHOOSH: 0.5}
    t = build(media=media)
    v = t["tracks"]["video"]
    assert (v[0]["kind"], v[0]["node"], v[0]["path"], v[0]["placeholder_for"]) == (
        "image", "v1.s01.keyframe", "v1/shots/s01/keyframe.png", "v1.s01.clip",
    )
    assert (v[1]["kind"], v[1]["node"], v[1]["path"], v[1]["placeholder_for"]) == ("slate", None, None, "v1.s02.clip")
    vo = t["tracks"]["vo"][1]
    assert (vo["path"], vo["duration"]) == (None, 1.2)
    assert t["tracks"]["captions"][-1]["text"] == "Try it today"
    assert t["tracks"]["music"] is None
    assert t["placeholders"] == ["v1.s01.clip", "v1.s02.clip", "v1.vo.l02", "shared.music.bed"]


def test_end_card_image_and_missing_end_card_image():
    t = build(media={**MEDIA, END: 0.0}, end_card={"text": "", "duration": 1, "image": END})
    assert t["tracks"]["end_card"] == {"node": "v1.end", "path": "v1/end.png", "start": 5.5, "duration": 1.0, "text": ""}
    t = build(end_card={"text": "Go", "image": END})
    assert t["tracks"]["end_card"]["path"] is None and "v1.end" in t["placeholders"]
    assert t["tracks"]["end_card"]["duration"] == 2.0


def test_first_shot_transition_is_always_a_cut():
    shots = [{"clip": CLIP1, "duration": 3, "transition": "crossfade"}]
    assert build(shots=shots)["tracks"]["video"][0]["transition"] == "cut"


def test_vo_explicit_start_and_overrun_warning():
    t = build(vo=[{"audio": L01, "text": "late line", "start": 5.0}])
    assert t["tracks"]["vo"][0]["start"] == 5.0
    assert t["warnings"] == ["v1.vo.l01 ends at 7.0s, after the last shot at 5.5s"]


def test_captions_can_be_disabled():
    assert build(captions=False)["tracks"]["captions"] == []


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"shots": []}, "inputs.shots must be a non-empty list"),
        ({"shots": [{"clip": CLIP1, "duration": 0}]}, "inputs.shots[0].duration must be > 0"),
        ({"aspect": "21:9"}, "inputs.aspect must be one of"),
        ({"shots": [{"clip": CLIP1, "duration": 1}, {"clip": CLIP2, "duration": 1, "transition": "wipe"}]},
         "inputs.shots[1].transition must be one of"),
        ({"sfx": [{"audio": WHOOSH}]}, "inputs.sfx[0].start must be a number"),
    ],
)
def test_invalid_inputs_fail_with_clear_message(overrides, message):
    with pytest.raises(TimelineError, match=re.escape(f"v1.timeline: {message}")):
        build(**overrides)


def test_caption_chunks_split_by_words_and_time_by_length():
    assert caption_chunks("", 0, 1) == []
    cues = caption_chunks("a bb ccc dddd", 1.0, 2.0, words_per_chunk=2)
    assert cues == [{"start": 1.0, "end": 1.667, "text": "a bb"}, {"start": 1.667, "end": 3.0, "text": "ccc dddd"}]


def test_media_paths_lists_every_referenced_file():
    assert media_paths(inputs(end_card={"text": "x", "image": END})) == [
        CLIP1, KF1, CLIP2, KF2, L01, L02, WHOOSH, BED, END,
    ]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_timeline.py -q`
Expected: `ModuleNotFoundError: No module named 'engine.assembly.timeline'`.

- [ ] **Step 3: Implement**

Create `engine/assembly/timeline.py`:

```python
"""Editor-independent timeline (spec §7).

`build_timeline` is a pure function: a timeline node's resolved inputs plus the
durations of the input files that exist → the content of timeline.json. Missing
inputs (failed/blocked upstream nodes) become placeholders so preview and draft
are always complete (spec §8). Output paths are project-relative POSIX strings."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.providers.base import ProviderError

TIMELINE_VERSION = 1
ASPECTS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "4:5": (1080, 1350),
}
TRANSITIONS = ("cut", "crossfade")
DEFAULT_FPS = 30
CROSSFADE_S = 0.25
VO_LEAD_IN_S = 0.2
VO_GAP_S = 0.15
WORDS_PER_CAPTION = 3
SECONDS_PER_WORD = 0.4
MIN_VO_S = 0.8
DEFAULT_MUSIC_VOLUME = 0.25
DEFAULT_END_CARD_S = 2.0
HOLD_TOLERANCE_S = 0.05
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})


class TimelineError(ProviderError):
    """Invalid timeline inputs: the timeline node fails with this message."""


def _r(x: float) -> float:
    return round(float(x), 3)


def media_paths(inputs: dict[str, Any]) -> list[str]:
    """Every input path the builder may look up in `media`, existing or not, in order."""
    paths: list[Any] = []
    for shot in inputs.get("shots") or []:
        if isinstance(shot, dict):
            paths += [shot.get("clip"), shot.get("fallback")]
    for key in ("vo", "sfx"):
        paths += [item.get("audio") for item in inputs.get(key) or [] if isinstance(item, dict)]
    for key, name in (("music", "audio"), ("end_card", "image")):
        if isinstance(inputs.get(key), dict):
            paths.append(inputs[key].get(name))
    return [p for p in paths if isinstance(p, str)]


def caption_chunks(text: str, start: float, duration: float, words_per_chunk: int = WORDS_PER_CAPTION) -> list[dict]:
    """Split a VO line into short caption cues, timed in proportion to their length.
    (Word-level timestamps from the TTS provider replace this estimate in plan 3.)"""
    words = text.split()
    if not words:
        return []
    chunks = [" ".join(words[i:i + words_per_chunk]) for i in range(0, len(words), words_per_chunk)]
    total = sum(len(c) for c in chunks)
    cues, t = [], start
    for chunk in chunks:
        d = duration * len(chunk) / total
        cues.append({"start": _r(t), "end": _r(t + d), "text": chunk})
        t += d
    return cues


def build_timeline(
    node_id: str,
    inputs: dict[str, Any],
    *,
    sources: dict[str, str],
    project_dir: Path,
    media: dict[str, float],
) -> dict[str, Any]:
    """`sources` maps input path → node id. `media` maps each input path that exists
    to its duration in seconds (0.0 for images)."""

    def err(msg: str) -> TimelineError:
        return TimelineError(f"{node_id}: {msg}")

    def number(value: Any, where: str, *, positive: bool) -> float:
        try:
            x = float(value)
        except (TypeError, ValueError):
            raise err(f"{where} must be a number") from None
        if x < 0 or (positive and x == 0):
            raise err(f"{where} must be {'> 0' if positive else '>= 0'}")
        return x

    def ref(item: Any, key: str, where: str) -> str:
        if not isinstance(item, dict) or not isinstance(item.get(key), str):
            raise err(f"{where}.{key} must be a reference")
        return item[key]

    def rel(path: str) -> str:
        return Path(path).relative_to(project_dir).as_posix()

    def ident(path: str) -> str:
        return sources.get(path, path)

    aspect = inputs.get("aspect", "9:16")
    if aspect not in ASPECTS:
        raise err(f"inputs.aspect must be one of {', '.join(ASPECTS)}")
    width, height = ASPECTS[aspect]
    fps = int(number(inputs.get("fps", DEFAULT_FPS), "inputs.fps", positive=True))
    shots = inputs.get("shots")
    if not isinstance(shots, list) or not shots:
        raise err("inputs.shots must be a non-empty list")

    placeholders: list[str] = []
    warnings: list[str] = []

    video: list[dict] = []
    t = 0.0
    for i, shot in enumerate(shots):
        where = f"inputs.shots[{i}]"
        clip = ref(shot, "clip", where)
        duration = number(shot.get("duration"), f"{where}.duration", positive=True)
        transition = shot.get("transition", "cut")
        if transition not in TRANSITIONS:
            raise err(f"{where}.transition must be one of {', '.join(TRANSITIONS)}")
        if i == 0:
            transition = "cut"
        entry = {
            "node": None, "path": None, "kind": "slate", "start": _r(t), "duration": _r(duration),
            "transition": transition, "transition_s": CROSSFADE_S if transition == "crossfade" else 0.0,
            "hold": False, "placeholder_for": None,
        }
        if clip in media:
            entry.update(node=ident(clip), path=rel(clip), kind="video",
                         hold=media[clip] + HOLD_TOLERANCE_S < duration)
        else:
            placeholders.append(ident(clip))
            entry["placeholder_for"] = ident(clip)
            fallback = shot.get("fallback")
            if isinstance(fallback, str) and fallback in media:
                entry.update(node=ident(fallback), path=rel(fallback), kind="image")
        video.append(entry)
        t += duration
    video_end = t

    vo: list[dict] = []
    captions: list[dict] = []
    want_captions = bool(inputs.get("captions", True))
    cursor = VO_LEAD_IN_S
    for i, line in enumerate(inputs.get("vo") or []):
        where = f"inputs.vo[{i}]"
        audio = ref(line, "audio", where)
        text = str(line.get("text", ""))
        start = cursor if line.get("start") is None else number(line["start"], f"{where}.start", positive=False)
        if audio in media:
            duration, path = media[audio], rel(audio)
        else:
            duration, path = max(MIN_VO_S, SECONDS_PER_WORD * len(text.split())), None
            placeholders.append(ident(audio))
        vo.append({"node": ident(audio), "path": path, "start": _r(start), "duration": _r(duration), "text": text})
        if want_captions:
            captions += caption_chunks(text, start, duration)
        if start + duration > video_end + 1e-6:
            warnings.append(f"{ident(audio)} ends at {_r(start + duration)}s, after the last shot at {_r(video_end)}s")
        cursor = start + duration + VO_GAP_S

    sfx: list[dict] = []
    for i, fx in enumerate(inputs.get("sfx") or []):
        where = f"inputs.sfx[{i}]"
        audio = ref(fx, "audio", where)
        start = number(fx.get("start"), f"{where}.start", positive=False)
        volume = number(fx.get("volume", 1.0), f"{where}.volume", positive=False)
        if audio in media:
            sfx.append({"node": ident(audio), "path": rel(audio), "start": _r(start),
                        "duration": _r(media[audio]), "volume": volume})
        else:
            placeholders.append(ident(audio))

    end_card = None
    card = inputs.get("end_card")
    if card is not None:
        if not isinstance(card, dict):
            raise err("inputs.end_card must be an object")
        duration = number(card.get("duration", DEFAULT_END_CARD_S), "inputs.end_card.duration", positive=True)
        end_card = {"node": None, "path": None, "start": _r(video_end), "duration": _r(duration),
                    "text": str(card.get("text", ""))}
        image = card.get("image")
        if isinstance(image, str):
            if image in media:
                end_card.update(node=ident(image), path=rel(image))
            else:
                placeholders.append(ident(image))
    total = video_end + (end_card["duration"] if end_card else 0.0)

    music = None
    bed = inputs.get("music")
    if bed is not None:
        audio = ref(bed, "audio", "inputs.music")
        volume = number(bed.get("volume", DEFAULT_MUSIC_VOLUME), "inputs.music.volume", positive=False)
        if audio in media:
            music = {"node": ident(audio), "path": rel(audio), "start": 0.0, "duration": _r(total),
                     "source_duration": _r(media[audio]), "volume": volume, "duck": bool(bed.get("duck", True))}
        else:
            placeholders.append(ident(audio))

    return {
        "version": TIMELINE_VERSION,
        "node": node_id,
        "width": width,
        "height": height,
        "fps": fps,
        "duration": _r(total),
        "tracks": {"video": video, "vo": vo, "sfx": sfx, "music": music, "captions": captions, "end_card": end_card},
        "placeholders": placeholders,
        "warnings": warnings,
    }
```

- [ ] **Step 4: Run tests, then generate and review the golden file**

Run: `uv run pytest tests/test_timeline.py -q`
Expected: every test passes except `test_golden_basic_timeline` (missing golden file).

Run: `ADFORGE_UPDATE_GOLDEN=1 uv run pytest tests/test_timeline.py::test_golden_basic_timeline -q`, then open `tests/golden/timeline_basic.json`. Check that it matches the values asserted in `test_basic_timeline_layout` (duration 7.0, two video entries, three captions, music `source_duration` 10.0). Then:

Run: `uv run pytest tests/test_timeline.py -v`
Expected: 14 passed (the parametrized test counts as 5).

- [ ] **Step 5: Commit**

```bash
command git add engine/assembly/timeline.py tests/test_timeline.py tests/golden/timeline_basic.json
command git commit -m "feat(assembly): pure timeline builder with placeholders and caption cues"
```

---

### Task 6: ffmpeg preview renderer

**Files:**
- Create: `engine/assembly/ffmpeg_preview.py`
- Test: `tests/test_preview.py`

**Interfaces:**
- Consumes: `FFmpeg` (Task 3), `build_timeline` (Task 5) in tests.
- Produces:
  - `build_concat_filter(lengths: list[float], transitions: list[tuple[str, float]], fps: int) -> tuple[str, str]` returns a filtergraph and the final label. Each input k is normalised `[k:v]fps=…,settb=AVTB,setpts=PTS-STARTPTS[sk]`. A `crossfade` join uses `xfade=transition=fade:duration=D:offset=<acc_len-D>`. A cut uses `concat=n=2:v=1:a=0`.
  - `captions_ass(captions, width, height, font) -> str`, plus helpers `ass_time(seconds) -> "H:MM:SS.cc"` and `ass_text(text)`. `ass_text` escapes `{` → `\{`, `}` → `\}` and newlines → `\N`.
  - `async render_slate_image(ff, work_dir, name, width, height, text) -> Path`. This is also used by the CapCut task.
  - `async render_preview(timeline: dict, project_dir: Path, work_dir: Path, ff: FFmpeg) -> Path` writes `work_dir/preview.mp4`: H.264 plus AAC at the timeline's WxH, lasting `timeline["duration"]` seconds.
- All drawtext calls use `expansion=none`, so `%` in copy is literal.
- Segment rule: video segment k is rendered `duration + transition_s of segment k+1` seconds long. The crossfade overlap comes from the earlier shot, so each shot still starts at its timeline `start`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_preview.py`:

```python
import asyncio

import pytest

from engine.assembly.ffmpeg_preview import ass_text, ass_time, build_concat_filter, captions_ass, render_preview
from engine.assembly.timeline import build_timeline


def test_concat_filter_offsets_put_each_shot_at_its_start():
    graph, label = build_concat_filter([3.25, 2.5, 1.5], [("cut", 0.0), ("crossfade", 0.25), ("cut", 0.0)], 30)
    assert graph.split(";") == [
        "[0:v]fps=30,settb=AVTB,setpts=PTS-STARTPTS[s0]",
        "[1:v]fps=30,settb=AVTB,setpts=PTS-STARTPTS[s1]",
        "[2:v]fps=30,settb=AVTB,setpts=PTS-STARTPTS[s2]",
        "[s0][s1]xfade=transition=fade:duration=0.250:offset=3.000[v1]",
        "[v1][s2]concat=n=2:v=1:a=0[v2]",
    ]
    assert label == "[v2]"
    assert build_concat_filter([2.0], [("cut", 0.0)], 24) == ("[0:v]fps=24,settb=AVTB,setpts=PTS-STARTPTS[s0]", "[s0]")


def test_ass_helpers():
    assert ass_time(3725.456) == "1:02:05.46"
    assert ass_time(0.2) == "0:00:00.20"
    assert ass_text("a {b}\nc") == "a \\{b\\}\\Nc"
    doc = captions_ass([{"start": 0.2, "end": 1.325, "text": "Fresh coffee every"}], 1080, 1920, "DejaVu Sans")
    assert "PlayResX: 1080" in doc and "PlayResY: 1920" in doc
    assert "Style: Default,DejaVu Sans,87," in doc
    assert doc.rstrip().endswith("Dialogue: 0,0:00:00.20,0:00:01.32,Default,,0,0,0,,Fresh coffee every")


async def _make(ff, project, rel, args):
    path = project / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    await ff.run([*args, str(path)])
    return str(path)


def _tone(seconds, freq=440):
    return ["-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={seconds}"]


def _clip(seconds, color="red"):
    return ["-f", "lavfi", "-i", f"color=c={color}:s=320x240:r=24", "-t", str(seconds),
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]


STILL = ["-f", "lavfi", "-i", "color=c=blue:s=320x240", "-frames:v", "1"]


async def _probe_all(ff, paths):
    return {p: (0.0 if p.endswith(".png") else (await ff.probe(p)).duration) for p in paths}


def test_full_preview_matches_timeline(ffmpeg, tmp_path):
    async def scenario():
        project = tmp_path / "proj"
        files = {
            "c1": await _make(ffmpeg, project, "v1/shots/s01/clip.mp4", _clip(1.5)),
            "c2": await _make(ffmpeg, project, "v1/shots/s02/clip.mp4", _clip(0.8, "green")),
            "vo": await _make(ffmpeg, project, "v1/vo/l01.wav", _tone(1.0, 220)),
            "fx": await _make(ffmpeg, project, "v1/sfx/hit.wav", _tone(0.3, 880)),
            "bed": await _make(ffmpeg, project, "shared/music/bed.wav", _tone(3.0, 110)),
        }
        sources = {files["c1"]: "v1.s01.clip", files["c2"]: "v1.s02.clip", files["vo"]: "v1.vo.l01",
                   files["fx"]: "v1.sfx.hit", files["bed"]: "shared.music.bed"}
        inputs = {
            "aspect": "1:1",
            "shots": [{"clip": files["c1"], "duration": 1.5},
                      {"clip": files["c2"], "duration": 1.2, "transition": "crossfade"}],
            "vo": [{"audio": files["vo"], "text": "Fresh coffee {daily}"}],
            "sfx": [{"audio": files["fx"], "start": 1.4}],
            "music": {"audio": files["bed"], "volume": 0.3},
            "end_card": {"text": "Shop now: 20% off", "duration": 1.0},
        }
        timeline = build_timeline("v1.timeline", inputs, sources=sources, project_dir=project,
                                  media=await _probe_all(ffmpeg, list(sources)))
        work = tmp_path / "work"
        work.mkdir()
        out = await render_preview(timeline, project, work, ffmpeg)
        return timeline, await ffmpeg.probe(out)

    timeline, info = asyncio.run(scenario())
    assert timeline["duration"] == 3.7
    assert (info.width, info.height) == (1080, 1080)
    assert info.has_video and info.has_audio
    assert info.duration == pytest.approx(3.7, abs=0.15)


def test_placeholder_only_preview_without_audio(ffmpeg, tmp_path):
    async def scenario():
        project = tmp_path / "proj"
        kf = await _make(ffmpeg, project, "v1/shots/s01/keyframe.png", STILL)
        missing = str(project / "v1/shots/s01/clip.mp4")
        inputs = {
            "aspect": "1:1", "captions": False,
            "shots": [{"clip": missing, "duration": 1.0, "fallback": kf},
                      {"clip": str(project / "v1/shots/s02/clip.mp4"), "duration": 1.0}],
        }
        sources = {missing: "v1.s01.clip", kf: "v1.s01.keyframe",
                   str(project / "v1/shots/s02/clip.mp4"): "v1.s02.clip"}
        timeline = build_timeline("v1.timeline", inputs, sources=sources, project_dir=project, media={kf: 0.0})
        work = tmp_path / "work"
        work.mkdir()
        out = await render_preview(timeline, project, work, ffmpeg)
        return timeline, await ffmpeg.probe(out)

    timeline, info = asyncio.run(scenario())
    assert [e["kind"] for e in timeline["tracks"]["video"]] == ["image", "slate"]
    assert info.has_audio and (info.width, info.height) == (1080, 1080)
    assert info.duration == pytest.approx(2.0, abs=0.15)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_preview.py -q`
Expected: `ModuleNotFoundError: No module named 'engine.assembly.ffmpeg_preview'`.

- [ ] **Step 3: Implement**

Create `engine/assembly/ffmpeg_preview.py`:

```python
"""ffmpeg preview renderer (spec §7): timeline.json → preview.mp4 with cuts and
crossfades, mixed VO/SFX, ducked music, burned-in captions and an end card.

Rendering is several small ffmpeg calls inside the node's work dir, using relative
file names. User text reaches ffmpeg only via files (drawtext textfile=, .ass)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.assembly.ffmpeg import FFmpeg

SLATE_COLOR = "0x1e1e1e"
END_CARD_COLOR = "0x000000"
AUDIO_FORMAT = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
X264_FAST = ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]


def _fit(width: int, height: int) -> str:
    return f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1"


def drawtext(font_option: str, textfile: str, size: int) -> str:
    return (f"drawtext={font_option}:textfile={textfile}:expansion=none:fontcolor=white:fontsize={size}"
            f":borderw={max(2, size // 12)}:bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2")


def ass_time(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def ass_text(text: str) -> str:
    return text.replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def captions_ass(captions: list[dict[str, Any]], width: int, height: int, font: str) -> str:
    size = height // 22
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{font},{size},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,"
        f"{max(2, size // 12)},0,2,60,60,{int(height * 0.18)},1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    lines += [
        f"Dialogue: 0,{ass_time(c['start'])},{ass_time(c['end'])},Default,,0,0,0,,{ass_text(c['text'])}"
        for c in captions
    ]
    return "\n".join(lines) + "\n"


def build_concat_filter(lengths: list[float], transitions: list[tuple[str, float]], fps: int) -> tuple[str, str]:
    """Join inputs 0..n-1. lengths[k] already includes the crossfade overlap into input
    k+1. transitions[k] is (kind, seconds) joining input k-1 to k; transitions[0] is unused."""
    parts = [f"[{k}:v]fps={fps},settb=AVTB,setpts=PTS-STARTPTS[s{k}]" for k in range(len(lengths))]
    acc, acc_len = "[s0]", lengths[0]
    for k in range(1, len(lengths)):
        kind, seconds = transitions[k]
        label = f"[v{k}]"
        if kind == "crossfade":
            parts.append(f"{acc}[s{k}]xfade=transition=fade:duration={seconds:.3f}:offset={acc_len - seconds:.3f}{label}")
            acc_len += lengths[k] - seconds
        else:
            parts.append(f"{acc}[s{k}]concat=n=2:v=1:a=0{label}")
            acc_len += lengths[k]
        acc = label
    return ";".join(parts), acc


async def render_slate_image(ff: FFmpeg, work_dir: Path, name: str, width: int, height: int, text: str) -> Path:
    label = f"{Path(name).stem}.txt"
    (work_dir / label).write_text(text)
    await ff.run([
        "-f", "lavfi", "-i", f"color=c={SLATE_COLOR}:s={width}x{height}", "-frames:v", "1",
        "-vf", drawtext(ff.font_option(), label, height // 24), name,
    ], cwd=work_dir)
    return work_dir / name


async def _segment(ff: FFmpeg, entry: dict, length: float, project_dir: Path, work_dir: Path,
                   name: str, width: int, height: int, fps: int, index: int) -> None:
    out = ["-t", f"{length:.3f}", "-r", str(fps), *X264_FAST, "-an", name]
    if entry["kind"] == "video":
        vf = (f"{_fit(width, height)},fps={fps},tpad=stop_mode=clone:stop_duration={length:.3f},"
              f"trim=duration={length:.3f},setpts=PTS-STARTPTS")
        await ff.run(["-i", str(project_dir / entry["path"]), "-vf", vf, *out], cwd=work_dir)
    elif entry["kind"] == "image":
        frames = max(1, round(length * fps))
        vf = (f"{_fit(2 * width, 2 * height)},zoompan=z='min(zoom+0.0006,1.12)'"
              f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps={fps},setsar=1")
        await ff.run(["-i", str(project_dir / entry["path"]), "-vf", vf, *out], cwd=work_dir)
    else:
        slate = await render_slate_image(ff, work_dir, f"slate_{index:02d}.png", width, height,
                                         f"MISSING\n{entry['placeholder_for']}")
        await ff.run(["-loop", "1", "-i", slate.name, "-vf", f"fps={fps},setsar=1", *out], cwd=work_dir)


async def _end_card(ff: FFmpeg, card: dict, project_dir: Path, work_dir: Path, width: int, height: int, fps: int) -> str:
    if card["path"]:
        source = ["-loop", "1", "-i", str(project_dir / card["path"])]
        filters = [_fit(width, height)]
    else:
        source = ["-f", "lavfi", "-i", f"color=c={END_CARD_COLOR}:s={width}x{height}"]
        filters = ["setsar=1"]
    if card["text"]:
        (work_dir / "end_card.txt").write_text(card["text"])
        filters.append(drawtext(ff.font_option(), "end_card.txt", height // 14))
    filters.append(f"fps={fps}")
    await ff.run([*source, "-vf", ",".join(filters), "-t", f"{card['duration']:.3f}", "-r", str(fps),
                  *X264_FAST, "-an", "seg_end.mp4"], cwd=work_dir)
    return "seg_end.mp4"


async def _mix_audio(ff: FFmpeg, tracks: dict, project_dir: Path, work_dir: Path, total: float, name: str) -> None:
    args: list[str] = []
    filters: list[str] = []
    count = 0

    def add(path: str, loop: bool = False) -> int:
        nonlocal count
        if loop:
            args.extend(["-stream_loop", "-1"])
        args.extend(["-i", str(project_dir / path)])
        count += 1
        return count - 1

    vo_labels: list[str] = []
    for k, entry in enumerate(e for e in tracks["vo"] if e["path"]):
        i, ms = add(entry["path"]), round(entry["start"] * 1000)
        filters.append(f"[{i}:a]{AUDIO_FORMAT},adelay={ms}|{ms}[vo{k}]")
        vo_labels.append(f"[vo{k}]")
    if len(vo_labels) > 1:
        filters.append(f"{''.join(vo_labels)}amix=inputs={len(vo_labels)}:normalize=0[vo]")
    elif vo_labels:
        filters.append(f"{vo_labels[0]}anull[vo]")

    buses: list[str] = []
    music = tracks["music"]
    if music:
        i = add(music["path"], loop=True)
        filters.append(f"[{i}:a]{AUDIO_FORMAT},atrim=0:{total:.3f},volume={music['volume']}[mus]")
        if music["duck"] and vo_labels:
            filters.append("[vo]asplit=2[vomix][vokey]")
            filters.append("[mus][vokey]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[musd]")
            buses += ["[vomix]", "[musd]"]
        else:
            buses.append("[mus]")
            if vo_labels:
                buses.append("[vo]")
    elif vo_labels:
        buses.append("[vo]")
    for k, entry in enumerate(tracks["sfx"]):
        i, ms = add(entry["path"]), round(entry["start"] * 1000)
        filters.append(f"[{i}:a]{AUDIO_FORMAT},volume={entry['volume']},adelay={ms}|{ms}[fx{k}]")
        buses.append(f"[fx{k}]")

    if not buses:
        await ff.run(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{total:.3f}", name], cwd=work_dir)
        return
    head = f"{''.join(buses)}amix=inputs={len(buses)}:normalize=0," if len(buses) > 1 else buses[0]
    filters.append(f"{head}apad,atrim=0:{total:.3f}[out]")
    await ff.run([*args, "-filter_complex", ";".join(filters), "-map", "[out]", "-ac", "2", "-ar", "48000", name],
                 cwd=work_dir)


async def render_preview(timeline: dict[str, Any], project_dir: Path, work_dir: Path, ff: FFmpeg) -> Path:
    width, height, fps = timeline["width"], timeline["height"], timeline["fps"]
    tracks, total = timeline["tracks"], timeline["duration"]
    video = tracks["video"]
    names: list[str] = []
    lengths: list[float] = []
    transitions: list[tuple[str, float]] = []
    for i, entry in enumerate(video):
        overlap = video[i + 1]["transition_s"] if i + 1 < len(video) else 0.0
        length = entry["duration"] + overlap
        name = f"seg_{i:02d}.mp4"
        await _segment(ff, entry, length, project_dir, work_dir, name, width, height, fps, i)
        names.append(name)
        lengths.append(length)
        transitions.append((entry["transition"], entry["transition_s"]))
    if tracks["end_card"]:
        names.append(await _end_card(ff, tracks["end_card"], project_dir, work_dir, width, height, fps))
        lengths.append(tracks["end_card"]["duration"])
        transitions.append(("cut", 0.0))

    graph, label = build_concat_filter(lengths, transitions, fps)
    inputs = [arg for name in names for arg in ("-i", name)]
    await ff.run([*inputs, "-filter_complex", graph, "-map", label, *X264_FAST, "video.mp4"], cwd=work_dir)
    await _mix_audio(ff, tracks, project_dir, work_dir, total, "mix.wav")

    final = ["-i", "video.mp4", "-i", "mix.wav"]
    if tracks["captions"]:
        (work_dir / "captions.ass").write_text(captions_ass(tracks["captions"], width, height, ff.font))
        final += ["-vf", "subtitles=captions.ass"]
    final += ["-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "preview.mp4"]
    await ff.run(final, cwd=work_dir)
    return work_dir / "preview.mp4"
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_preview.py -v`
Expected: 4 passed with ffmpeg installed. Without it, 2 passed and 2 skipped.

If an ffmpeg filter error appears, the `ProviderError` message carries ffmpeg's stderr tail. Fix the filter string, keep the test expectations unchanged, and record the fix in the report.

- [ ] **Step 5: Commit**

```bash
command git add engine/assembly/ffmpeg_preview.py tests/test_preview.py
command git commit -m "feat(assembly): ffmpeg preview renderer (crossfades, ducking, captions, end card)"
```

---

### Task 7: CapCut draft writer

**Files:**
- Create: `engine/assembly/capcut_template.json`, `engine/assembly/capcut_draft.py`
- Test: `tests/test_capcut_draft.py`, `tests/golden/capcut_basic.json` (generated)

**Interfaces:**
- Consumes: the timeline schema (Task 5), `assert_golden` (Task 1).
- Produces:
  - `US = 1_000_000`, `us(seconds) -> int`, `draft_id(*parts) -> str` (uuid5, uppercase), `CAPTION_Y = -0.62`
  - `build_draft(timeline, *, project_dir: Path, draft_dir: Path, draft_name: str, media_root: str | None, now_us: int, slates: dict[int, Path]) -> tuple[dict, dict]` returns `(draft_content, draft_meta_info)`. It is pure. `slates` maps a video-entry index of kind `slate` to its placeholder PNG path.
  - `write_draft(out_dir: Path, draft: dict, meta: dict) -> None` writes `draft_content.json` and `draft_meta_info.json`.
- Draft layout: tracks appear in the order video `main`, audio `vo`, audio `sfx`, audio `music`, text `captions`, text `end_card`. Empty tracks are omitted, except `main`.
  - Every video and audio material's name is its node ID; a slate uses the ID it stands in for.
  - Music is split into repeated segments of `source_duration` until it covers `duration`, with one shared audio material.
  - VO entries with no file are skipped.
- Media paths: with `media_root`, a path becomes `<media_root>/<path relative to project_dir.parent>`. Otherwise it is the absolute local path.

- [ ] **Step 1: Write the template**

Create `engine/assembly/capcut_template.json`:

```json
{
  "canvas_config": {"height": 1920, "ratio": "original", "width": 1080},
  "color_space": 0,
  "config": {
    "adjust_max_index": 1, "attachment_info": [], "combination_max_index": 1, "export_range": null,
    "extract_audio_last_index": 1, "lyrics_recognition_id": "", "lyrics_sync": true, "lyrics_taskinfo": [],
    "maintrack_adsorb": true, "material_save_mode": 0, "original_sound_last_index": 1,
    "record_audio_last_index": 1, "sticker_max_index": 1, "subtitle_recognition_id": "", "subtitle_sync": true,
    "subtitle_taskinfo": [], "system_font_list": [], "video_mute": false, "zoom_info_params": null
  },
  "cover": null,
  "create_time": 0,
  "duration": 0,
  "extra_info": null,
  "fps": 30.0,
  "free_render_index_mode_on": false,
  "group_container": null,
  "id": "",
  "keyframe_graph_list": [],
  "keyframes": {"adjusts": [], "audios": [], "effects": [], "filters": [], "handwrites": [], "stickers": [], "texts": [], "videos": []},
  "last_modified_platform": {"app_id": 359289, "app_source": "cc", "app_version": "5.9.0", "os": "windows"},
  "materials": {
    "audio_balances": [], "audio_effects": [], "audio_fades": [], "audios": [], "beats": [], "canvases": [],
    "chromas": [], "color_curves": [], "digital_humans": [], "drafts": [], "effects": [], "flowers": [],
    "green_screens": [], "handwrites": [], "hsl": [], "images": [], "log_color_wheels": [], "loudnesses": [],
    "manual_deformations": [], "masks": [], "material_animations": [], "material_colors": [],
    "placeholders": [], "plugin_effects": [], "primary_color_wheels": [], "realtime_denoises": [],
    "shapes": [], "smart_crops": [], "sound_channel_mappings": [], "speeds": [], "stickers": [],
    "tail_leaders": [], "text_templates": [], "texts": [], "transitions": [], "video_effects": [],
    "video_trackings": [], "videos": [], "vocal_beautifys": [], "vocal_separations": []
  },
  "mutable_config": null,
  "name": "",
  "new_version": "110.0.0",
  "platform": {"app_id": 359289, "app_source": "cc", "app_version": "5.9.0", "os": "windows"},
  "relationships": [],
  "render_index_track_mode_on": false,
  "retouch_cover": null,
  "source": "default",
  "static_cover_image_path": "",
  "time_marks": null,
  "tracks": [],
  "update_time": 0,
  "version": 360000
}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_capcut_draft.py`:

```python
import json
from pathlib import Path

from engine.assembly.capcut_draft import CAPTION_Y, build_draft, write_draft
from tests.helpers import assert_golden

P = Path("/home/me/projects/mug-launch")
SLATES = {2: P / "v1/capcut_draft/placeholders/slate_02.png"}


def entry(node, path, kind, start, duration, transition="cut", ts=0.0, placeholder_for=None):
    return {"node": node, "path": path, "kind": kind, "start": start, "duration": duration,
            "transition": transition, "transition_s": ts, "hold": False, "placeholder_for": placeholder_for}


TIMELINE = {
    "version": 1, "node": "v1.timeline", "width": 1080, "height": 1920, "fps": 30, "duration": 7.0,
    "tracks": {
        "video": [
            entry("v1.s01.clip", "v1/shots/s01/clip.mp4", "video", 0.0, 3.0),
            entry("v1.s02.keyframe", "v1/shots/s02/keyframe.png", "image", 3.0, 2.5, "crossfade", 0.25, "v1.s02.clip"),
            entry(None, None, "slate", 5.5, 0.5, placeholder_for="v1.s03.clip"),
        ],
        "vo": [
            {"node": "v1.vo.l01", "path": "v1/vo/l01.wav", "start": 0.2, "duration": 2.0,
             "text": "Fresh coffee every single morning"},
            {"node": "v1.vo.l02", "path": None, "start": 2.35, "duration": 1.2, "text": "Try it today"},
        ],
        "sfx": [{"node": "v1.sfx.whoosh", "path": "v1/sfx/whoosh.wav", "start": 2.9, "duration": 0.5, "volume": 0.8}],
        "music": {"node": "shared.music.bed", "path": "shared/music/bed.wav", "start": 0.0, "duration": 7.0,
                  "source_duration": 3.0, "volume": 0.3, "duck": True},
        "captions": [{"start": 0.2, "end": 1.325, "text": "Fresh coffee every"},
                     {"start": 1.325, "end": 2.2, "text": "single morning"}],
        "end_card": {"node": None, "path": None, "start": 6.0, "duration": 1.0, "text": "Shop now"},
    },
    "placeholders": ["v1.s02.clip", "v1.s03.clip", "v1.vo.l02"],
    "warnings": [],
}


def build(**kw):
    args = dict(project_dir=P, draft_dir=P / "v1/capcut_draft", draft_name="mug-launch_v1",
                media_root=None, now_us=1_700_000_000_000_000, slates=SLATES)
    args.update(kw)
    return build_draft(TIMELINE, **args)


def track(draft, name):
    return next(t for t in draft["tracks"] if t["name"] == name)


def material(draft, kind, material_id):
    return next(m for m in draft["materials"][kind] if m["id"] == material_id)


def test_track_layout():
    draft, _ = build()
    assert [(t["type"], t["name"]) for t in draft["tracks"]] == [
        ("video", "main"), ("audio", "vo"), ("audio", "sfx"), ("audio", "music"),
        ("text", "captions"), ("text", "end_card"),
    ]
    assert draft["duration"] == 7_000_000 and draft["fps"] == 30.0
    assert draft["canvas_config"] == {"height": 1920, "ratio": "original", "width": 1080}
    assert draft["name"] == "mug-launch_v1"


def test_video_segments_are_named_by_node_id():
    draft, _ = build()
    segs = track(draft, "main")["segments"]
    assert [s["target_timerange"] for s in segs] == [
        {"start": 0, "duration": 3_000_000}, {"start": 3_000_000, "duration": 2_500_000},
        {"start": 5_500_000, "duration": 500_000},
    ]
    mats = [material(draft, "videos", s["material_id"]) for s in segs]
    assert [m["material_name"] for m in mats] == ["v1.s01.clip", "v1.s02.keyframe", "v1.s03.clip"]
    assert [m["type"] for m in mats] == ["video", "photo", "photo"]
    assert [m["path"] for m in mats] == [
        str(P / "v1/shots/s01/clip.mp4"), str(P / "v1/shots/s02/keyframe.png"), str(SLATES[2]),
    ]


def test_audio_tracks_skip_missing_vo_and_loop_music():
    draft, _ = build()
    vo = track(draft, "vo")["segments"]
    assert [s["target_timerange"] for s in vo] == [{"start": 200_000, "duration": 2_000_000}]
    music = track(draft, "music")["segments"]
    assert [s["target_timerange"] for s in music] == [
        {"start": 0, "duration": 3_000_000}, {"start": 3_000_000, "duration": 3_000_000},
        {"start": 6_000_000, "duration": 1_000_000},
    ]
    assert {s["volume"] for s in music} == {0.3}
    assert len({s["material_id"] for s in music}) == 1
    assert sorted(m["name"] for m in draft["materials"]["audios"]) == ["shared.music.bed", "v1.sfx.whoosh", "v1.vo.l01"]
    assert track(draft, "sfx")["segments"][0]["volume"] == 0.8


def test_caption_and_end_card_text():
    draft, _ = build()
    caps = track(draft, "captions")["segments"]
    texts = [json.loads(material(draft, "texts", s["material_id"])["content"])["text"] for s in caps]
    assert texts == ["Fresh coffee every", "single morning"]
    assert all(s["clip"]["transform"]["y"] == CAPTION_Y and s["source_timerange"] is None for s in caps)
    end = track(draft, "end_card")["segments"][0]
    assert end["target_timerange"] == {"start": 6_000_000, "duration": 1_000_000}
    assert json.loads(material(draft, "texts", end["material_id"])["content"])["text"] == "Shop now"


def test_media_root_rewrites_paths_for_the_capcut_machine():
    draft, _ = build(media_root="C:/AdForge/projects")
    first = material(draft, "videos", track(draft, "main")["segments"][0]["material_id"])
    assert first["path"] == "C:/AdForge/projects/mug-launch/v1/shots/s01/clip.mp4"


def test_references_resolve_ids_are_unique_and_output_is_deterministic():
    draft, meta = build()
    assert build() == (draft, meta)
    material_ids = {m["id"] for kind in ("videos", "audios", "texts", "speeds") for m in draft["materials"][kind]}
    segments = [s for t in draft["tracks"] for s in t["segments"]]
    for s in segments:
        assert s["material_id"] in material_ids
        assert set(s["extra_material_refs"]) <= material_ids
    all_ids = [m["id"] for kind in ("videos", "audios", "texts", "speeds") for m in draft["materials"][kind]]
    all_ids += [t["id"] for t in draft["tracks"]] + [s["id"] for s in segments]
    assert len(all_ids) == len(set(all_ids))
    assert meta["draft_id"] == draft["id"] and meta["tm_duration"] == 7_000_000
    assert meta["draft_fold_path"] == str(P / "v1/capcut_draft")


def test_write_draft_creates_both_files(tmp_path):
    draft, meta = build()
    write_draft(tmp_path / "capcut_draft", draft, meta)
    assert json.loads((tmp_path / "capcut_draft/draft_content.json").read_text()) == draft
    assert json.loads((tmp_path / "capcut_draft/draft_meta_info.json").read_text()) == meta


def test_golden_basic_draft():
    assert_golden("capcut_basic.json", build()[0])
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/test_capcut_draft.py -q`
Expected: `ModuleNotFoundError: No module named 'engine.assembly.capcut_draft'`.

- [ ] **Step 4: Implement**

Create `engine/assembly/capcut_draft.py`:

```python
"""CapCut draft writer (spec §7). Deliberately isolated: if CapCut changes its draft
format, only this module and capcut_template.json change; preview and raw assets
keep working.

Builds draft_content.json + draft_meta_info.json from timeline.json. Every clip is
named by its node id. Times are microseconds. IDs are deterministic (uuid5), so a
rebuilt draft is byte-for-byte stable and overwrites the old one in place."""
from __future__ import annotations

import copy
import json
import uuid
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

US = 1_000_000
ID_NAMESPACE = uuid.UUID("6f1c8a52-1f0e-4b7a-9d3e-0a5d2c7b9e41")
PHOTO_DURATION_US = 10_800 * US   # CapCut's material length for stills
CAPTION_Y = -0.62                 # CapCut transform space: -1 bottom … 1 top
CAPTION_SIZE = 8.0
END_CARD_SIZE = 12.0


def us(seconds: float) -> int:
    return int(round(seconds * US))


def draft_id(*parts: str) -> str:
    return str(uuid.uuid5(ID_NAMESPACE, "/".join(parts))).upper()


@lru_cache(maxsize=1)
def _template() -> dict[str, Any]:
    return json.loads(resources.files("engine.assembly").joinpath("capcut_template.json").read_text())


def _timerange(start: float, duration: float) -> dict[str, int]:
    return {"start": us(start), "duration": us(duration)}


def _track(name: str, kind: str, track_id: str) -> dict[str, Any]:
    return {"attribute": 0, "flag": 0, "id": track_id, "is_default_name": False,
            "name": name, "segments": [], "type": kind}


def _speed(speed_id: str) -> dict[str, Any]:
    return {"curve_speed": None, "id": speed_id, "mode": 0, "speed": 1.0, "type": "speed"}


def _segment(segment_id: str, material_id: str, start: float, duration: float, *, volume: float = 1.0,
             extra_refs: list[str] | None = None, transform_y: float = 0.0, has_source: bool = True) -> dict[str, Any]:
    return {
        "caption_info": None, "cartoon": False,
        "clip": {"alpha": 1.0, "flip": {"horizontal": False, "vertical": False}, "rotation": 0.0,
                 "scale": {"x": 1.0, "y": 1.0}, "transform": {"x": 0.0, "y": transform_y}},
        "common_keyframes": [], "enable_adjust": True, "enable_color_curves": True, "enable_color_wheels": True,
        "enable_lut": True, "extra_material_refs": list(extra_refs or []), "group_id": "",
        "hdr_settings": {"intensity": 1.0, "mode": 1, "nits": 1000}, "id": segment_id,
        "intensifies_audio": False, "is_placeholder": False, "is_tone_modify": False, "keyframe_refs": [],
        "last_nonzero_volume": 1.0, "material_id": material_id, "render_index": 0, "reverse": False,
        "source_timerange": _timerange(0.0, duration) if has_source else None,
        "speed": 1.0, "target_timerange": _timerange(start, duration), "template_id": "",
        "template_scene": "default", "track_attribute": 0, "track_render_index": 0,
        "uniform_scale": {"on": True, "value": 1.0}, "visible": True, "volume": volume,
    }


def _video_material(material_id: str, path: str, name: str, kind: str, duration: float,
                    width: int, height: int) -> dict[str, Any]:
    return {
        "audio_fade": None, "category_id": "", "category_name": "local", "check_flag": 63487,
        "crop": {"lower_left_x": 0.0, "lower_left_y": 1.0, "lower_right_x": 1.0, "lower_right_y": 1.0,
                 "upper_left_x": 0.0, "upper_left_y": 0.0, "upper_right_x": 1.0, "upper_right_y": 0.0},
        "crop_ratio": "free", "crop_scale": 1.0,
        "duration": PHOTO_DURATION_US if kind == "photo" else us(duration),
        "extra_type_option": 0, "height": height, "id": material_id, "local_material_id": "",
        "material_id": "", "material_name": name, "media_path": "", "path": path, "source_platform": 0,
        "type": kind, "width": width,
    }


def _audio_material(material_id: str, path: str, name: str, duration: float) -> dict[str, Any]:
    return {
        "app_id": 0, "category_id": "", "category_name": "local", "check_flag": 1, "duration": us(duration),
        "effect_id": "", "formula_id": "", "id": material_id, "intensifies_path": "",
        "local_material_id": material_id, "music_id": material_id, "name": name, "path": path,
        "source_platform": 0, "team_id": "", "text_id": "", "tone_category_id": "", "tone_category_name": "",
        "tone_effect_id": "", "tone_effect_name": "", "tone_speaker": "", "tone_type": "",
        "type": "extract_music", "video_id": "", "wave_points": [],
    }


def _text_material(material_id: str, text: str, size: float) -> dict[str, Any]:
    length = len(text.encode("utf-16-le")) // 2
    solid = lambda rgb: {"render_type": "solid", "solid": {"alpha": 1.0, "color": rgb}}  # noqa: E731
    content = {
        "styles": [{"fill": {"alpha": 1.0, "content": solid([1.0, 1.0, 1.0])}, "range": [0, length],
                    "size": size, "bold": True, "font": {"id": "", "path": ""},
                    "strokes": [{"content": solid([0.0, 0.0, 0.0]), "width": 0.08}]}],
        "text": text,
    }
    return {
        "add_type": 0, "alignment": 1, "background_alpha": 1.0, "background_color": "", "check_flag": 7,
        "content": json.dumps(content, ensure_ascii=False), "fixed_height": -1.0, "fixed_width": -1.0,
        "font_size": size, "global_alpha": 1.0, "id": material_id, "line_max_width": 0.82,
        "line_spacing": 0.02, "name": "", "text_alpha": 1.0, "text_color": "#FFFFFF", "type": "text",
        "typesetting": 0,
    }


def build_draft(
    timeline: dict[str, Any],
    *,
    project_dir: Path,
    draft_dir: Path,
    draft_name: str,
    media_root: str | None,
    now_us: int,
    slates: dict[int, Path],
) -> tuple[dict[str, Any], dict[str, Any]]:
    def mid(*parts: str) -> str:
        return draft_id(draft_name, *parts)

    def media_path(path: Path) -> str:
        if media_root:
            return f"{media_root}/{path.relative_to(project_dir.parent).as_posix()}"
        return str(path)

    width, height, fps = timeline["width"], timeline["height"], timeline["fps"]
    tracks = timeline["tracks"]
    draft = copy.deepcopy(_template())
    mats = draft["materials"]
    draft.update(
        id=mid("draft"), name=draft_name, fps=float(fps), duration=us(timeline["duration"]),
        create_time=now_us // US, update_time=now_us // US,
        canvas_config={"height": height, "ratio": "original", "width": width},
    )

    main = _track("main", "video", mid("track", "main"))

    def add_visual(key: str, path: Path, name: str, kind: str, start: float, duration: float) -> None:
        material_id, speed_id = mid("video", key), mid("speed", "video", key)
        mats["videos"].append(_video_material(material_id, media_path(path), name, kind, duration, width, height))
        mats["speeds"].append(_speed(speed_id))
        main["segments"].append(_segment(mid("segment", "video", key), material_id, start, duration,
                                         extra_refs=[speed_id]))

    for i, e in enumerate(tracks["video"]):
        if e["kind"] == "slate":
            add_visual(str(i), slates[i], e["placeholder_for"], "photo", e["start"], e["duration"])
        else:
            add_visual(str(i), project_dir / e["path"], e["node"], "video" if e["kind"] == "video" else "photo",
                       e["start"], e["duration"])
    card = tracks["end_card"]
    if card and card["path"]:
        add_visual("end_card", project_dir / card["path"], card["node"], "photo", card["start"], card["duration"])
    out_tracks = [main]

    audio_materials: dict[str, str] = {}

    def audio_material(e: dict[str, Any]) -> str:
        if e["path"] not in audio_materials:
            material_id = mid("audio", e["node"])
            mats["audios"].append(_audio_material(material_id, media_path(project_dir / e["path"]), e["node"],
                                                  e.get("source_duration", e["duration"])))
            audio_materials[e["path"]] = material_id
        return audio_materials[e["path"]]

    def audio_track(name: str, pieces: list[tuple[dict[str, Any], float, float, float]]) -> None:
        if not pieces:
            return
        track = _track(name, "audio", mid("track", name))
        for k, (e, start, duration, volume) in enumerate(pieces):
            speed_id = mid("speed", name, str(k))
            mats["speeds"].append(_speed(speed_id))
            track["segments"].append(_segment(mid("segment", name, str(k)), audio_material(e), start, duration,
                                              volume=volume, extra_refs=[speed_id]))
        out_tracks.append(track)

    audio_track("vo", [(e, e["start"], e["duration"], 1.0) for e in tracks["vo"] if e["path"]])
    audio_track("sfx", [(e, e["start"], e["duration"], e["volume"]) for e in tracks["sfx"]])
    music = tracks["music"]
    if music:
        step = music["source_duration"] if music["source_duration"] > 0 else music["duration"]
        pieces, t = [], 0.0
        while t < music["duration"] - 1e-6:
            d = min(step, music["duration"] - t)
            pieces.append((music, round(t, 3), round(d, 3), music["volume"]))
            t += d
        audio_track("music", pieces)

    def text_track(name: str, cues: list[tuple[str, float, float]], size: float, y: float) -> None:
        if not cues:
            return
        track = _track(name, "text", mid("track", name))
        for k, (text, start, end) in enumerate(cues):
            material_id = mid("text", name, str(k))
            mats["texts"].append(_text_material(material_id, text, size))
            track["segments"].append(_segment(mid("segment", name, str(k)), material_id, start, end - start,
                                              transform_y=y, has_source=False))
        out_tracks.append(track)

    text_track("captions", [(c["text"], c["start"], c["end"]) for c in tracks["captions"]], CAPTION_SIZE, CAPTION_Y)
    if card and card["text"]:
        text_track("end_card", [(card["text"], card["start"], card["start"] + card["duration"])], END_CARD_SIZE, 0.0)

    draft["tracks"] = out_tracks
    meta = {
        "draft_cover": "", "draft_fold_path": str(draft_dir), "draft_id": draft["id"], "draft_name": draft_name,
        "draft_root_path": str(draft_dir.parent), "tm_draft_create": now_us, "tm_draft_modified": now_us,
        "tm_duration": draft["duration"],
    }
    return draft, meta


def write_draft(out_dir: Path, draft: dict[str, Any], meta: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "draft_content.json").write_text(json.dumps(draft, ensure_ascii=False))
    (out_dir / "draft_meta_info.json").write_text(json.dumps(meta, ensure_ascii=False))
```

- [ ] **Step 5: Run tests, then generate and review the golden file**

Run: `uv run pytest tests/test_capcut_draft.py -q`
Expected: every test passes except `test_golden_basic_draft`.
Run: `ADFORGE_UPDATE_GOLDEN=1 uv run pytest tests/test_capcut_draft.py::test_golden_basic_draft -q`, open `tests/golden/capcut_basic.json` and spot-check the track order and material names. Then:
Run: `uv run pytest tests/test_capcut_draft.py -v`
Expected: 8 passed.

- [ ] **Step 6: Manual acceptance (human, recorded in the report as pending until done)**

After Task 8, open one generated `projects/<slug>/v1/capcut_draft` in CapCut desktop. To do that, copy the folder into CapCut's drafts folder, or set `capcut.drafts_dir` and `capcut.media_root`. Confirm that it opens, that clips are named by node ID, and that captions sit on a text track. If CapCut rejects it, record the CapCut version and the error. The follow-up then touches only `capcut_template.json` and `capcut_draft.py`.

- [ ] **Step 7: Commit**

```bash
command git add engine/assembly/capcut_template.json engine/assembly/capcut_draft.py tests/test_capcut_draft.py tests/golden/capcut_basic.json
command git commit -m "feat(assembly): template-driven CapCut draft writer"
```

---

### Task 8: Assembly provider, registry, example config, media end-to-end

**Files:**
- Create: `engine/providers/assembly.py`
- Modify: `engine/providers/__init__.py`, `config.example.yaml`, `tests/test_cli.py`
- Test: `tests/test_assembly_provider.py`, `tests/test_e2e_media.py`

**Interfaces:**
- Consumes: `FFmpeg` (T3), `MediaMockProvider` (T4), `build_timeline`/`media_paths`/`IMAGE_SUFFIXES` (T5), `render_preview`/`render_slate_image` (T6), `build_draft`/`write_draft` (T7), `CapcutConfig` (T1), `output_path` (Plan 1).
- Produces:
  - `engine.providers.assembly.AssemblyProvider(ffmpeg=None, capcut=None, clock=time.time)` with `name = "assembly"`. Its `assemble(ctx, node_type, inputs)`:
    - `timeline` probes the input files that exist (images count as 0.0 s) and writes `timeline.json`.
    - `preview` reads `inputs.timeline` and writes `preview.mp4`.
    - `capcut_draft` reads `inputs.timeline` and renders slate PNGs into `capcut_draft/placeholders/`. It writes the draft named `<project>_<variant>`. When `capcut.drafts_dir` is set, it also replaces `<drafts_dir>/<draft_name>` with a copy.
    - A missing `ctx.project_dir` or `inputs.timeline` raises `ProviderError`. `cost()` is 0.
  - `engine.providers.build_providers(config)` returns `{"mock": MockProvider(), "mock_media": MediaMockProvider(ff), "assembly": AssemblyProvider(ff, config.capcut)}` with `ff = FFmpeg(config.assembly)`.
  - `config.example.yaml` routes generation types to `mock_media` and assembly types to `assembly` (model `builtin`), and documents `assembly:` and `capcut:`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_assembly_provider.py`:

```python
import asyncio
import json

import pytest

from engine.assembly.ffmpeg import FFmpeg
from engine.providers import build_providers
from engine.providers.assembly import AssemblyProvider
from engine.providers.base import CallContext, ProviderError
from engine.providers.mock_media import MediaMockProvider
from engine.config import EngineConfig


def ctx(tmp_path, node_id, **kw):
    work = tmp_path / ".tmp" / node_id
    work.mkdir(parents=True)
    return CallContext(node_id=node_id, model="builtin", work_dir=work, **kw)


def test_registry_has_mock_media_and_assembly():
    providers = build_providers(EngineConfig())
    assert isinstance(providers["mock_media"], MediaMockProvider)
    assert isinstance(providers["assembly"], AssemblyProvider)


def test_assembly_needs_project_dir(tmp_path):
    with pytest.raises(ProviderError, match="project directory"):
        asyncio.run(AssemblyProvider(FFmpeg()).assemble(ctx(tmp_path, "v1.timeline"), "timeline", {}))


def test_preview_needs_a_rendered_timeline(tmp_path):
    with pytest.raises(ProviderError, match="inputs.timeline"):
        asyncio.run(AssemblyProvider(FFmpeg()).assemble(
            ctx(tmp_path, "v1.preview", project_dir=tmp_path), "preview", {"timeline": str(tmp_path / "nope.json")}))


def test_timeline_with_all_inputs_missing_needs_no_ffmpeg(tmp_path):
    clip = str(tmp_path / "v1/shots/s01/clip.mp4")
    c = ctx(tmp_path, "v1.timeline", project_dir=tmp_path, sources={clip: "v1.s01.clip"})
    out = asyncio.run(AssemblyProvider(FFmpeg()).assemble(c, "timeline", {"shots": [{"clip": clip, "duration": 2}]}))
    data = json.loads(out.read_text())
    assert data["placeholders"] == ["v1.s01.clip"] and data["tracks"]["video"][0]["kind"] == "slate"
    assert AssemblyProvider(FFmpeg()).cost("timeline", {}) == 0.0
```

Create `tests/test_e2e_media.py`:

```python
"""Spec §10 mock end-to-end with real media: manifest → parallel run (mock_media)
→ timeline → preview.mp4 → CapCut draft, through the adengine CLI."""
import asyncio
import json
import shutil
from pathlib import Path

import pytest
import yaml

from engine.cli import main

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.yaml"


@pytest.fixture
def media_project(project_dir, ffmpeg):
    shutil.copy(EXAMPLE, project_dir / "config.yaml")
    return project_dir


def test_full_render_produces_previews_and_drafts(media_project, ffmpeg):
    assert main(["run", str(media_project)]) == 0
    for v in ("v1", "v2"):
        info = asyncio.run(ffmpeg.probe(media_project / v / "preview.mp4"))
        assert (info.width, info.height) == (1080, 1920) and info.has_audio
        assert info.duration == pytest.approx(10.0, abs=0.2)
        timeline = json.loads((media_project / v / "timeline.json").read_text())
        assert timeline["placeholders"] == [] and timeline["duration"] == 10.0
        draft = json.loads((media_project / v / "capcut_draft/draft_content.json").read_text())
        assert [t["name"] for t in draft["tracks"]] == ["main", "vo", "captions", "end_card"]
        assert [m["material_name"] for m in draft["materials"]["videos"]] == [f"{v}.s01.clip", f"{v}.s02.clip"]


def test_failed_clip_degrades_to_keyframe_placeholder(media_project, ffmpeg, capsys):
    assert main(["revise", str(media_project), "v1.s01.clip", "--json",
                 '{"provider": "nope", "model": "x"}', "--no-run"]) == 0
    assert main(["run", str(media_project), "--only", "v1.preview"]) == 1
    assert "ATTENTION v1.s01.clip" in capsys.readouterr().out
    timeline = json.loads((media_project / "v1/timeline.json").read_text())
    assert timeline["placeholders"] == ["v1.s01.clip"]
    assert timeline["tracks"]["video"][0]["kind"] == "image"
    info = asyncio.run(ffmpeg.probe(media_project / "v1/preview.mp4"))
    assert info.duration == pytest.approx(10.0, abs=0.2)


def test_capcut_draft_exported_to_drafts_dir_with_rewritten_paths(media_project, tmp_path):
    path = media_project / "config.yaml"
    config = yaml.safe_load(path.read_text())
    config["capcut"] = {"drafts_dir": str(tmp_path / "drafts"), "media_root": "C:/AdForge/projects"}
    path.write_text(yaml.safe_dump(config))
    assert main(["run", str(media_project), "--only", "v1.capcut_draft"]) == 0
    exported = tmp_path / "drafts" / "mug-launch_v1" / "draft_content.json"
    draft = json.loads(exported.read_text())
    assert draft["materials"]["videos"][0]["path"] == "C:/AdForge/projects/mug-launch/v1/shots/s01/clip.mp4"
```

In `tests/test_cli.py`, change the last line of `test_example_config_loads` to:

```python
    assert cfg.routing["video"].provider == "mock_media"
    assert cfg.routing["timeline"].provider == "assembly"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_assembly_provider.py tests/test_e2e_media.py tests/test_cli.py -q`
Expected: `ModuleNotFoundError: No module named 'engine.providers.assembly'` (collection error), and the example-config assertion fails.

- [ ] **Step 3: Implement the provider**

Create `engine/providers/assembly.py`:

```python
"""Engine-internal provider for timeline, preview and capcut_draft nodes (spec §7).
Free: assembly never reaches the ledger."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from engine.assembly.capcut_draft import build_draft, write_draft
from engine.assembly.ffmpeg import FFmpeg
from engine.assembly.ffmpeg_preview import render_preview, render_slate_image
from engine.assembly.timeline import IMAGE_SUFFIXES, build_timeline, media_paths
from engine.config import CapcutConfig
from engine.core.paths import output_path
from engine.providers.base import CallContext, Provider, ProviderError


class AssemblyProvider(Provider):
    name = "assembly"

    def __init__(self, ffmpeg: FFmpeg | None = None, capcut: CapcutConfig | None = None,
                 clock: Callable[[], float] = time.time):
        self.ff = ffmpeg or FFmpeg()
        self.capcut = capcut or CapcutConfig()
        self.clock = clock

    async def assemble(self, ctx: CallContext, node_type: str, inputs: dict[str, Any]) -> Path:
        if ctx.project_dir is None:
            raise ProviderError(f"{ctx.node_id}: assembly needs the project directory")
        if node_type == "timeline":
            return await self._timeline(ctx, inputs)
        timeline = self._load_timeline(ctx, inputs)
        if node_type == "preview":
            return await render_preview(timeline, ctx.project_dir, ctx.work_dir, self.ff)
        if node_type == "capcut_draft":
            return await self._capcut_draft(ctx, timeline)
        raise ProviderError(f"{ctx.node_id}: assembly does not handle {node_type}")

    async def _timeline(self, ctx: CallContext, inputs: dict[str, Any]) -> Path:
        media: dict[str, float] = {}
        for path in dict.fromkeys(media_paths(inputs)):
            p = Path(path)
            if p.exists():
                media[path] = 0.0 if p.suffix.lower() in IMAGE_SUFFIXES else (await self.ff.probe(p)).duration
        data = build_timeline(ctx.node_id, inputs, sources=ctx.sources, project_dir=ctx.project_dir, media=media)
        out = ctx.work_dir / "timeline.json"
        out.write_text(json.dumps(data, indent=2) + "\n")
        return out

    def _load_timeline(self, ctx: CallContext, inputs: dict[str, Any]) -> dict[str, Any]:
        path = inputs.get("timeline")
        if not isinstance(path, str) or not Path(path).exists():
            raise ProviderError(f"{ctx.node_id}: inputs.timeline must reference a rendered timeline node")
        return json.loads(Path(path).read_text())

    async def _capcut_draft(self, ctx: CallContext, timeline: dict[str, Any]) -> Path:
        project_dir = ctx.project_dir
        draft_name = f"{project_dir.name}_{ctx.node_id.split('.')[0]}"
        final_dir = output_path(project_dir, ctx.node_id, "capcut_draft")
        out_dir = ctx.work_dir / "capcut_draft"
        placeholders = out_dir / "placeholders"
        placeholders.mkdir(parents=True)
        slates: dict[int, Path] = {}
        for i, e in enumerate(timeline["tracks"]["video"]):
            if e["kind"] == "slate":
                name = f"slate_{i:02d}.png"
                await render_slate_image(self.ff, placeholders, name, timeline["width"], timeline["height"],
                                         f"MISSING\n{e['placeholder_for']}")
                slates[i] = final_dir / "placeholders" / name
        export_dir = self.capcut.drafts_dir / draft_name if self.capcut.drafts_dir else None
        draft, meta = build_draft(
            timeline, project_dir=project_dir, draft_dir=export_dir or final_dir, draft_name=draft_name,
            media_root=self.capcut.media_root, now_us=int(self.clock() * 1_000_000), slates=slates,
        )
        write_draft(out_dir, draft, meta)
        if export_dir:
            if export_dir.exists():
                shutil.rmtree(export_dir)
            shutil.copytree(out_dir, export_dir)
        return out_dir
```

Replace `engine/providers/__init__.py` with:

```python
from engine.assembly.ffmpeg import FFmpeg
from engine.config import EngineConfig
from engine.providers.assembly import AssemblyProvider
from engine.providers.base import Provider
from engine.providers.mock import MockProvider
from engine.providers.mock_media import MediaMockProvider


def build_providers(config: EngineConfig) -> dict[str, Provider]:
    """Provider instances keyed by the name used in routing. Plan 3 adds real providers."""
    ff = FFmpeg(config.assembly)
    return {
        "mock": MockProvider(),
        "mock_media": MediaMockProvider(ff),
        "assembly": AssemblyProvider(ff, config.capcut),
    }
```

- [ ] **Step 4: Update the example config**

Replace `config.example.yaml` with:

```yaml
# AdForge engine config. Copy to projects/<slug>/config.yaml or pass --config.
# Model names live here, never in engine code. Secrets come from env / .env only.
routing:
  image:        {provider: mock_media, model: mock-image}
  video:        {provider: mock_media, model: mock-video}
  tts:          {provider: mock_media, model: mock-tts}
  sfx:          {provider: mock_media, model: mock-sfx}
  music:        {provider: mock_media, model: mock-music}
  timeline:     {provider: assembly, model: builtin}
  preview:      {provider: assembly, model: builtin}
  capcut_draft: {provider: assembly, model: builtin}

# Max simultaneous calls per provider. Real providers arrive in plan 3, e.g.
#   openai_image: 8
#   seedance: 4
#   fishaudio: 10
concurrency:
  mock_media: 4
  assembly: 2
default_concurrency: 4

# Temporary failures (429/5xx/timeouts) retry with exponential backoff.
retry:
  max_attempts: 3
  base_delay_s: 1.0
  max_delay_s: 30.0

# External binaries used by assembly and mock_media (sudo apt install ffmpeg).
assembly:
  ffmpeg: ffmpeg
  ffprobe: ffprobe
  # Defaults: macOS → font Helvetica + font_file /System/Library/Fonts/Helvetica.ttc; Linux → DejaVu Sans.
  # font: Helvetica
  # font_file: /System/Library/Fonts/Helvetica.ttc

# CapCut export. Unset drafts_dir keeps each draft only in projects/<slug>/vN/capcut_draft.
capcut:
  # Folder CapCut scans for drafts. On a Mac running CapCut desktop this is usually:
  # drafts_dir: ~/Movies/CapCut/User Data/Projects/com.lveditor.draft
  # Only when CapCut runs on a DIFFERENT machine: how this machine's projects/ folder is seen there.
  # Leave unset when the engine and CapCut share the Mac (paths are already correct).
  # media_root: /Volumes/Shared/AdForge/projects
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_assembly_provider.py tests/test_cli.py -v`
Expected: all pass.
Run: `uv run pytest tests/test_e2e_media.py -v`
Expected: 3 passed with ffmpeg installed (this takes a while, since it renders two 1080x1920 previews). Without ffmpeg, 3 are skipped.
Run: `uv run pytest -q -W error`
Expected: all pass, with no warnings.

- [ ] **Step 6: Manual smoke test**

```bash
SMOKE=$(mktemp -d)/demo && mkdir -p "$SMOKE"
uv run python -c "import json; from tests.helpers import make_manifest; print(json.dumps(make_manifest(), indent=2))" > "$SMOKE/manifest.json"
cp config.example.yaml "$SMOKE/config.yaml"
uv run adengine run "$SMOKE"
ls "$SMOKE/v1"
```

Expected: `ran 17, cached 0, failed 0, needs_review 0, blocked 0`. `v1/` contains `capcut_draft  preview.mp4  shots  timeline.json  vo`. Open `v1/preview.mp4` in a player: two coloured shots (4 s each) with captions "Line for v1", a quiet tone under them, and a 2 s black "Shop now" end card. Report the path so the human can watch it.

- [ ] **Step 7: Commit**

```bash
command git add engine/providers config.example.yaml tests/test_assembly_provider.py tests/test_e2e_media.py tests/test_cli.py
command git commit -m "feat(assembly): assembly provider, registry and media end-to-end"
```

---

## Spec coverage (Plan 2)

| Spec item | Task |
|---|---|
| §7 timeline.json: video, VO, SFX, music, captions, end-card tracks; node IDs with in/out/position; ducking flag | 5 |
| §7 caption cues from word timing | 5 (estimated from VO text; word-level timestamps from TTS deferred to plan 3) |
| §7 ffmpeg preview: cuts and light crossfades, mixed VO/SFX, ducked music, burned-in captions | 6 |
| §7 CapCut draft: separate tracks, caption text track, clips named by node ID, `drafts_dir`, `media_root`, isolated module | 7, 8 |
| §7 variants assemble independently; revisions rebuild that variant's timeline and draft in place | existing DAG + freshness rule; deterministic draft IDs (7) |
| §8 placeholders (keyframe with slow zoom, or slate showing the node ID) so preview and draft are always complete | 2, 5, 6, 7 |
| §4 all audio is `.wav` | 1 |
| §10 mock end-to-end through to preview and CapCut draft; timeline and CapCut JSON golden tests | 5, 7, 8 |

**Deferred, recorded for later plans:**
- Word-level caption timing (plan 3, from Fish Audio timestamps).
- CapCut transitions and ducking keyframes. The draft keeps cuts and a static music volume.
- Real-provider default routing (plan 3).
- The spec's single generic `render(RenderRequest)` provider interface. The engine still dispatches through typed methods plus `assemble`; plan 3 should decide whether to migrate before adding real adapters.
- The `lipsync` and `creator_asset` node types (plan 5).
