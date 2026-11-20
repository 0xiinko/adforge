# AdForge × Ellora Studio — Design Spec

**Date:** 2026-11-20
**Status:** Approved in brainstorming, pending written-spec review
**Branch:** `feat/ellora` (cut from `feat/assembly` at ce0c037)
**Extends:** `2026-11-20-adforge-design.md` (§5 Brain flow, §6 Engine)

## 1. Goal

Use Ellora Studio (a claude.ai MCP connector) in AdForge for two things:

1. **Brand knowledge for the brain:** products, bottle/label wording, audience, ad-claim rules, house prompt rules and past storyboards feed the skills that write scripts and prompts.
2. **Rendering:** image and video nodes can be routed to Ellora, so renders run on the user's Ellora key and land in their Ellora library.

**Constraint that shapes the design:** Ellora is reachable only from inside a Claude session. The engine never talks to Ellora. Claude (the brain) makes every Ellora call and hands finished files to the engine.

### Non-goals
- Any network code for Ellora in the engine, or Ellora API keys in `.env`.
- Ellora for TTS, SFX, music or assembly (it only renders images and video).
- Detached CLI-only runs of Ellora nodes. They wait until Claude supplies them.

## 2. Brain side (skills)

| Where | What it does with Ellora |
|---|---|
| `ad-strategist` | At the start of each brief, calls `get_brand_context` and `get_house_rules` once and writes both verbatim to `projects/<slug>/brand/ellora.md` (with the date fetched). All later steps read this file instead of calling Ellora again. |
| `variant-writer` subagents | Read `brand/ellora.md`. Call `list_storyboards` and `get_storyboard` for 1–2 recent storyboards as house-style examples. |
| `prompt-craft` | Any shot with a bottle names the product and describes its label with the wording from `brand/ellora.md`. Uses `search_prompts` for phrasing the team already uses. Uses `list_models` to pick Ellora model IDs and options (aspect, resolution, duration ranges) instead of guessing. |
| Gate | (a) Checks every script line, caption and on-screen text against the claim rules in `brand/ellora.md`, and flags each hit with the rule it breaks. (b) Lists every Ellora render (node ID, image/video, model) with the credit warning. Approving the gate is the single confirmation for that batch of renders, videos included, and for downloading the results into the project. Renders that fall outside the approved list (new nodes, revisions) are confirmed separately. |

`brand/ellora.md` is refreshed only when the user asks, so the brand rules a project was written against stay recorded.

## 3. Engine side: external providers

### 3.1 Config

```yaml
external_providers: [ellora]          # never called by the engine; Claude supplies outputs
routing:
  image: {provider: ellora, model: <Ellora modelId from list_models>}
  video: {provider: ellora, model: <Ellora modelId>}
concurrency:
  ellora: 4                            # unused by the engine; kept for symmetry
```

- `external_providers` is a list of provider names. A route or node-level `provider` naming one of them makes that node **external**.
- Only `image` and `video` node types may be external. Any other type routed to an external provider is a config error.
- An external provider needs no entry in `build_providers`. `dry-run` shows it as `(external: supplied by Claude)` rather than `(provider not registered)`, with cost `$0.00` (Ellora bills in credits, not tracked by the engine).

### 3.2 New status: `awaiting_external`

The status values become `pending | running | done | failed | blocked | needs_review | awaiting_external`.

When `run` reaches a stale external node whose dependencies are all `done`:
- It does not launch a task. It sets `status = awaiting_external` and records `expected_fingerprint` (the fingerprint the output must be supplied against).
- `awaiting_external` is **not** finished. Non-assembly dependents stay `pending` (not `blocked`), and assembly nodes also wait (no placeholder). Unrelated nodes keep running.
- The run ends when nothing is running. `RunReport` gains `awaiting: list[str]`. `ok` is false while anything is awaiting.
- CLI exit codes for `run` and `revise`: `0` all done, `1` failures/needs_review/blocked, `3` nothing failed but some nodes are awaiting external supply. When both apply, `1` wins.

A fresh external node (fingerprint matches and output exists) is skipped like any cached node.

### 3.3 `NodeState` additions

```python
expected_fingerprint: str | None = None   # set while awaiting_external
external: dict | None = None              # {"provider": "ellora", "ref": "<Ellora path>", "id": "<generation id>"}
```

`external` is kept on the committed version, so later nodes can refer to the Ellora copy of this output. Older state files load with both fields set to `None`.

`external_history: dict[str, dict] | None` keeps that metadata per version, so `rollback` restores the Ellora path that belongs to the restored file.

### 3.4 `adengine external <project> [--json]`

Lists every `awaiting_external` node. With `--json`, each entry is:

```json
{
  "id": "v1.s03.keyframe",
  "type": "image",
  "provider": "ellora",
  "model": "<modelId>",
  "prompt": "…",
  "inputs": {"aspect": "9:16", "refs": ["/abs/path/refs/product_hero.png"]},
  "external_inputs": {"aspect": "9:16", "refs": ["<Ellora path of refs.product_hero>"]},
  "fingerprint": "<expected_fingerprint>"
}
```

- `inputs` are resolved as usual (refs become absolute local paths).
- `external_inputs` maps each `@ref` input to that node's stored `external.ref`. This is what Claude passes to Ellora (`referenceImageUrls`, `firstFrameUrl`). Plain-text inputs and public `http(s)` URLs pass through unchanged.

### 3.5 `adengine supply`

```
adengine supply <project> <node_id> <file> --ref <path> [--id <id>] [--fingerprint <fp>]
adengine supply <project> <node_id> --failed "<message>"
adengine supply <project> <node_id> --refused "<message>"
```

- **Checks:** the node exists, it is external, its status is `awaiting_external`, and its current fingerprint equals `expected_fingerprint` (and `--fingerprint` if given). If not, it stops with an error naming the mismatch, e.g. the node was revised after `external` listed it.
- **File:** copied (not moved) into the node's work dir, then committed through `ProjectStore.commit` with the expected fingerprint, so versioning and rollback behave exactly as for an engine render. The extension must match the node type (`.png`/`.jpg`/`.webp` for image, `.mp4` for video). A `.jpg` or `.webp` image is converted to PNG with the configured ffmpeg before commit, so the output keeps the node's normal `.png` path.
- **Metadata:** stores `external = {provider, ref, id}`, clears `expected_fingerprint`, and writes a ledger entry: `provider`, `model`, `cost_usd: 0.0`, `attempt: 1`, `ok: true`, plus `external_id`.
- **`--failed` / `--refused`:** set the node to `failed` (reason `external`) or `needs_review` (reason `refused`) with the message, and write a ledger entry with `ok: false`. Failed retries, refused holds: a `--failed` node shows as failed in `adengine status` until the next `run`, which lists it as `awaiting_external` again (like engine renders, which retry on the next run). A `--refused` node keeps its `expected_fingerprint`, and while its fingerprint is unchanged every `run` reports it as needs_review (it is not listed as awaiting again) and blocks its dependents; a `revise` changes the fingerprint, so the next `run` puts it back to `awaiting_external`.
- `supply` does not run anything. Claude calls `run` afterwards to continue the pipeline.

### 3.6 Validation

`validate` and `dry-run` report an error when an external node has an `@ref` input pointing at a node that is not external (creator assets are covered in 3.7). Ellora cannot read local files, so such a manifest can never be supplied. The message names both nodes and suggests routing the referenced node to Ellora too.

External image nodes must have `n` absent or `1`. Ellora returns one image per call.

### 3.7 Out of scope for now

`creator_asset` nodes do not exist yet (build order step 5). Until they do, an external node cannot reference one. When creators land, they will need an Ellora path too (uploaded once per creator version); that belongs to the creators spec.

## 4. Claude's run loop

1. `adengine run <project>`. Exit code `3` means nodes are awaiting.
2. `adengine external <project> --json`.
3. For each node, in dependency order (an external video waits for its external keyframe):
   - image: `generate_image` with the prompt, `modelId`, `aspectRatio` and `referenceImageUrls` from `external_inputs`. Independent images run in parallel.
   - video: `generate_video` with the prompt, `modelId`, `durationSec`, `aspectRatio` and `firstFrameUrl` from `external_inputs`. Then `check_generation` with `wait: true` until it finishes or fails.
   - Download the finished file from the link `check_generation` returns into `projects/<slug>/.tmp/ellora/`.
   - `adengine supply … --ref <Ellora path> --id <id>`, or `--failed` / `--refused` with Ellora's message.
4. Back to step 1 until `run` exits `0` or `1`. A node reported with `--failed` is listed as awaiting again by the next `run` (exit `3`), so Claude retries it at most once more in the loop; if it fails a second time, Claude stops the loop and reports the node to the user (it stays listed as awaiting until then).

Because dependents of a keyframe can't start until it is supplied, the loop usually takes two passes per variant: keyframes, then clips. Revisions reuse the same loop: `revise` changes the fingerprint, so the node goes back to `awaiting_external` on the next run.

A refusal is rewritten once by Claude via `revise` (same rule as spec §8). A second refusal stays `needs_review`.

## 5. Error handling

| Case | Result |
|---|---|
| Ellora render fails or times out | Claude retries once, then `supply --failed`. The next run lists the node as awaiting again (failed retries). A refusal (`supply --refused`) instead holds the node as needs_review and blocks its dependents until it is revised. |
| Ellora refuses the prompt | `supply --refused`, then the §4 rewrite rule. |
| Node revised between `external` and `supply` | `supply` rejects the stale file. Claude lists again and re-renders. |
| Claude never comes back | Nodes stay `awaiting_external`. Nothing is blocked or lost. The next `run` lists them again. |
| Downloaded file missing or wrong type | `supply` errors and the node stays awaiting. |

## 6. Testing (mock, zero cost)

- Config: `external_providers` parsed; external routing on a non-image/video type is rejected; dry-run labels external nodes.
- Scheduler: a stale external node becomes `awaiting_external` with `expected_fingerprint`; its dependents and assembly wait (not blocked, no placeholder); unrelated nodes finish; `RunReport.awaiting` is filled; a fresh external node is cached.
- `supply`: commits, versions and archives the old output, stores `external`, writes the ledger entry, and a following `run` finishes the dependents; rejects a stale fingerprint, a node that isn't awaiting, a non-external node, and a wrong extension; `--failed` and `--refused` map to the right statuses; on the next run a failed node is awaiting again, while a refused one holds and blocks its dependents.
- `external --json`: resolved inputs and `external_inputs` mapped from the stored `external.ref`.
- Validation: an external node referencing a non-external node is an error.
- CLI: exit code `3` when only awaiting; `1` wins over `3`.
- State: an old `state.json` without the new fields still loads.

## 7. Build order

1. Engine: config, status, `NodeState` fields, scheduler handling, `external`, `supply`, validation, tests. This can be built now against the mock provider.
2. Brain: the Ellora steps in `ad-strategist`, `variant-writer`, `prompt-craft` and the gate. These land with the plugin skeleton (main spec build order step 6), and this spec is their reference.
