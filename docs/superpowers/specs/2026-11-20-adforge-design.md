# AdForge — Design Spec

**Date:** 2026-11-20
**Status:** Approved in brainstorming, pending written-spec review
**Inspired by:** ViMax (`/home/iinko/ViMax`) — idea→script→storyboard→keyframes→clips→concat pipeline with file-cached stages.

## 1. Goal

A Claude Code plugin where the user pastes a short-form ad brief (text only) and gets back N fully assembled ad variants — each as a quick-review MP4 **and** an editable CapCut draft — with exactly one human gate (script approval). All generation runs in parallel. Every asset has a stable ID so any piece can be revised individually.

**Primary content type:** short-form ads / UGC / product promos (15–60s, VO-led, product shots, hooks, captions).

### Non-goals (v1)
Web dashboard, multi-user shared server, FCPXML export, brand kits, auto-publishing to ad platforms.

## 2. Key decisions

| Decision | Choice |
|---|---|
| Final output | ffmpeg preview MP4 + CapCut draft per variant |
| Human gates | One: after script/shot list + reference images |
| Brief inputs | Text only; brain designs a product hero reference, approved at the gate |
| Recurring creator/avatar | Reusable AI creators (consistent face + voice) stored in a creator library; UGC talking-head shots via lip-sync provider (Higgsfield MCP or similar) |
| Outputs per brief | N full variants (different angles), default N=3, all parallel |
| Architecture | Claude plugin (brain) + local Python engine exposed via MCP server + CLI (execution) |
| Model names | Config values, never hard-coded (`provider` + `model`) |

## 3. Architecture

**Separation rule:** the brain makes all creative decisions and never calls generation APIs. The engine makes no creative decisions and only executes the manifest. The single contract between them is `manifest.json` (validated by `engine/schemas/manifest.schema.json`).

```
adforge/
  .claude-plugin/plugin.json
  commands/ad.md                  # /ad <brief>
  skills/
    ad-strategist/                # brief parsing, angle selection, defaults
    script-writer/                # hooks, beat structures, CTA patterns
    shot-planner/                 # shot list with timings fit to video model limits
    prompt-craft/                 # per-provider prompt guides (gpt-image, seedance, fishaudio)
  agents/variant-writer.md        # one subagent per variant, run in parallel
  engine/
    core/      graph.py scheduler.py cache.py store.py ledger.py
    providers/ base.py openai_image.py seedance.py fishaudio.py mcp_bridge.py mock.py
    qc/        vision_judge.py
    assembly/  timeline.py ffmpeg_preview.py capcut_draft.py
    mcp_server.py  cli.py  config.py
    schemas/   manifest.schema.json   # packaged with the engine
  config.example.yaml
  tests/
creators/                         # creator library, shared across all projects (location configurable)
  <creator_slug>/creator.json  face_front.png  face_side.png  full_body.png  voice_sample.wav
```

## 3a. Recurring creators (avatars)

A **creator** is a reusable on-camera persona with a locked look and voice, used across many briefs.

- **`creator.json`**: `{slug, name, persona (age, vibe, style notes), look_prompt, voice: {provider: "fishaudio", voice_id, default_emotion}, refs: {face_front, face_side, full_body}, version}`.
- **Creation:** if the brief asks for UGC/talking-head and no suitable creator exists (or the user names a new one), the brain designs one at the gate: it writes `look_prompt` and persona, the engine renders the face/body refs (same consistency approach as the product hero: front first, then side/body edited from front), and Fish Audio either picks a stock voice or clones from a provided sample. The user approves the creator at the same single gate. Approved creators are saved to the library and reused automatically after that.
- **Reuse:** the strategist can pick an existing creator by slug ("use @maya"). The manifest pulls creator assets in through special read-only nodes `creator.<slug>.<asset>` (e.g. `creator.maya.face_front`) that point at library files and never re-render inside a project.
- **Talking-head shots:** new node type `lipsync`, e.g. `v1.s02.talk`. Inputs: `face: "@v1.s02.keyframe"` (keyframe generated from the creator refs + scene), `audio: "@v1.vo.l02"`. Provider: `higgsfield` via `mcp_bridge` by default (configurable to any lip-sync/avatar provider). Duration follows the audio length.
- **Consistency QC:** the vision judge also scores face similarity of creator keyframes and lip-sync clips against `creator.<slug>.face_front`. Low scores trigger the normal retry → `needs_review` path.
- **Revisions:** changing a creator in the library (new face or voice) bumps its `version`. Projects that use it pick up the new version only when explicitly asked (`adengine run --refresh-creators`), so finished ads don't change unexpectedly.

## 4. Project folder & manifest

Per brief: `projects/<slug>/`

```
brief.md
manifest.json          # brain writes, engine reads/updates status
state.json             # engine run state (resumable)
ledger.jsonl           # every paid call
refs/                  # product_hero.png, creator/location refs
v1/ v2/ v3/
  shots/s03/keyframe.png  clip.mp4  versions/
  vo/l04.wav   sfx/whoosh02.wav   music/bed.mp3
  timeline.json  preview.mp4  capcut_draft/
```

### Node schema

```json
{
  "id": "v2.s03.clip",
  "type": "video",
  "provider": "seedance",
  "model": "seedance-2.5",
  "inputs": {"first_frame": "@v2.s03.keyframe", "duration": 4, "aspect": "9:16"},
  "prompt": "Slow push-in, steam rising from mug…",
  "depends_on": ["v2.s03.keyframe"]
}
```

Runtime fields (`status`, `version`, `fingerprint`, `output`, the spec that produced the output) live per node in `state.json`, owned by the engine, so the brain can edit `manifest.json` without conflicts. All audio outputs are `.wav`.

- **Node types:** `image`, `video`, `lipsync`, `tts`, `sfx`, `music`, `creator_asset`, `timeline`, `preview`, `capcut_draft`.
- **IDs:** `<scope>.<unit>.<kind>`, e.g. `refs.product_hero`, `creator.maya.face_front`, `v2.s03.keyframe`, `v2.s03.clip`, `v2.s02.talk`, `v2.vo.l04`, `v2.sfx.whoosh02`, `v2.timeline`. IDs are stable forever within a project.
- **`creator_asset` nodes** are read-only links to creator library files. Their fingerprint is the library file hash plus the creator version, so they are never rendered by the project and only change when the creator changes.
- **References:** `@<id>` in `inputs` resolves to that node's current output path. `depends_on` must include every referenced ID (schema-validated).
- **Status values:** `pending | running | done | failed | blocked | needs_review`.
- **Fingerprint:** `sha256(type, provider, model, prompt, resolved inputs, fingerprints of dependencies)`. If it matches the stored fingerprint and the output exists, the node is skipped. Otherwise the node re-renders, and so does everything that depends on it.
- **Versioning:** before overwriting, the previous output moves to `versions/<node>_v<N>.<ext>`. `version` increments. Rollback = restore a version via `adengine rollback <id> <N>`.
- **Shared vs per-variant:** `refs.*` and shared music beds render once. Each variant owns its own node tree.

## 5. Brain flow

1. **Strategist** (`/ad` command + `ad-strategist` skill): extract product, audience, offer, platform, duration, aspect. Defaults: 9:16, 30s, N=3. Every assumed default is listed in the plan. Choose N distinct angles (e.g. problem/solution, demo, testimonial-style).
2. **Parallel variant writers:** dispatch N `variant-writer` subagents concurrently. Each returns: script (hook, beats, CTA), shot list (6–8 shots of 3–5s), VO lines, SFX cues, music mood, caption text.
3. **Reference design:** `prompt-craft` writes prompts for `refs.product_hero` (+ location refs if needed). If a variant uses UGC/talking-head, the brain either selects an existing creator from the library or designs a new one (section 3a). Brain calls engine `run_nodes(["refs.*"])` (+ new creator refs). This is the only render before the gate.
4. **Gate:** present scripts, shot lists, reference images, the chosen/new creator (face refs + voice sample) and estimated cost per variant. The user may approve, drop variants, edit lines, or request reference regeneration (loop on step 3).
5. **Hand-off:** brain writes the final `manifest.json`, calls `run_manifest`, polls `status`, and reports drafts and any `needs_review` IDs when done.

**Post-gate revisions:** natural-language feedback ("v2 shot 3 too dark") is translated by the brain into `revise(node_id, changes)` calls. The engine re-renders affected nodes and their dependents, then rebuilds that variant's timeline, preview and draft.

## 6. Engine

### Interfaces
- **MCP server tools:** `validate_manifest`, `estimate_cost`, `run_manifest`, `run_nodes(ids)`, `status`, `revise(node_id, changes)`, `rollback(node_id, version)`, `list_outputs(variant?)`.
- **CLI:** `adengine run|status|revise|rollback|estimate|dry-run <project>`. Same core, so long renders can run detached without Claude.
- Core is a library. MCP and CLI are thin layers on top (keeps a future web dashboard possible).

### Scheduler
- asyncio DAG executor: starts every node whose dependencies are `done`, and starts dependents as soon as each node finishes (pipelining: a clip starts the moment its keyframe is done).
- Per-provider concurrency caps from config (e.g. `openai_image: 8, seedance: 4, fishaudio: 10`).
- `state.json` saved after every node change. Re-running resumes.

### Providers
```python
class ImageProvider:  async def generate(prompt, refs, size, n) -> list[Path]
class VideoProvider:  async def generate(prompt, first_frame, last_frame=None, duration, aspect) -> Path
class LipsyncProvider: async def generate(face_image, audio, prompt=None, aspect) -> Path
class AudioProvider:  async def tts(text, voice, emotion) -> Path
                      async def sfx(prompt, duration) -> Path
                      async def music(prompt, duration) -> Path   # optional; else library/stock track
```
- The engine calls every adapter through one generic interface: `render(RenderRequest) -> Path` + `cost(node) -> float`. The typed methods above are internal to concrete adapters.
- `openai_image`: default image provider; model from config.
- `seedance`: video; configurable base URL/host (BytePlus, fal, etc.).
- `fishaudio`: TTS (per-project voice ID) and SFX.
- `mcp_bridge`: engine acts as an MCP client to external servers (Higgsfield, etc.). Config maps a node type to `{server, tool, arg_template}`, so any such tool becomes a `provider:` value.
- `mock`: instant placeholder outputs for tests and dry runs.
- Each adapter declares `cost(call_params) -> usd`.
- Routing: config default per node type. A node-level `provider` overrides it. Optional fallback chain (`video: [seedance, higgsfield]`).
- Secrets only from env / `.env` (`OPENAI_API_KEY`, `SEEDANCE_API_KEY`, `FISH_API_KEY`, …). Never written to manifests or ledgers.

### Automatic QC (replaces later human gates)
- Keyframes: generate `n=2` candidates. The vision judge scores them against the shot description and `refs.product_hero` (product looks the same, no artifacts), and the best one is kept.
- Clips: sample 3 frames and score them against the shot intent.
- On fail: up to 2 automatic retries with an adjusted prompt, then `needs_review`. Never blocks unrelated nodes.

## 7. Assembly

Per variant, `vX.timeline` depends on all of that variant's clips and audio. `preview` and `capcut_draft` depend on the timeline. Variants assemble independently as they finish.

- **`timeline.json`** (independent of any editor): tracks = video, VO, SFX, music, captions, end card. Clips reference node IDs with in/out and position. Caption cues come from word-level timing (Fish Audio timestamps if available, else local Whisper). Music ducking under VO.
- **`ffmpeg_preview`** → `preview.mp4`: cuts and light crossfades, mixed VO/SFX, ducked music, burned-in captions.
- **`capcut_draft`** → `capcut_draft/` (`draft_content.json`, `draft_meta_info.json`): separate editable tracks and a caption text track. **Each clip is named by its node ID** in CapCut. Config: `capcut.drafts_dir` (Windows/Mac CapCut drafts folder via sync) and `capcut.media_root` (path rewriting for the target OS). Isolated module, built on the open-source `pyJianYingDraft`-style approach. If CapCut changes its format, only this module breaks. The preview and raw assets still work.
- Any revision marks that variant's timeline for rebuild. The draft is overwritten in place.

## 8. Error handling

- **Temporary failures** (429/5xx/timeouts): retry with exponential backoff, capped per provider.
- **Content refusals:** the engine marks the node `needs_review` with `reason: "refused"` and the provider's message (the engine never rewrites prompts itself). When the brain is attached and polling `status`, it rewrites the prompt once via `revise`. A second refusal stays `needs_review` for the user.
- **Hard failures:** node `failed`, its dependents `blocked`, everything else continues. Assembly substitutes a placeholder (keyframe with slow zoom, or a slate showing the node ID) so preview and draft are always complete. The final report lists every ID that needs attention.

## 9. Cost guardrails

- `estimate_cost` before the gate (per variant + total).
- `budget.max_usd` per project: the scheduler stops starting new paid calls when the limit would be exceeded and reports what's left to render.
- `ledger.jsonl` logs node ID, provider, model, cost and time for every paid call, QC retries included.
- `dry-run`: full plan and estimate, zero API calls.

## 10. Testing

- **Mock-provider end-to-end test** (CI, zero cost): brief fixture → manifest → parallel run → timeline → preview → CapCut draft.
- **Unit tests:** schema validation, `@ref`/`depends_on` consistency, fingerprinting and downstream invalidation (changing one node re-renders exactly its dependents), scheduler concurrency caps, resume from `state.json`, timeline building, CapCut JSON shape.
- **Golden tests:** sample `timeline.json` and draft JSON compared against saved fixtures.
- **Contract tests** per real provider: manual, keys required, one minimal call each.

## 11. Build order

1. Manifest schema + engine core (graph, fingerprint, scheduler, store) with mock providers.
2. Assembly: timeline + ffmpeg preview, then CapCut draft writer.
3. Real providers: openai_image, seedance, fishaudio. Then mcp_bridge.
4. QC vision judge.
5. Creators: creator library, `creator_asset` nodes, `lipsync` node type via mcp_bridge (Higgsfield), face-consistency QC.
6. Brain: plugin skeleton, `/ad` command, skills, variant-writer subagent, gate UX (incl. creator selection/design).
7. MCP server + CLI polish, cost estimation and budget enforcement.
