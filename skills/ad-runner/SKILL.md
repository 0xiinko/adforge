---
name: ad-runner
description: Stage 5 of /ad. Shows the single approval gate, writes manifest.json and config.yaml, then runs the adengine render loop with Claude rendering every image and video in Ellora Studio, and reports previews, drafts and anything needing attention. Also handles revisions after the report.
---

# Ad runner (stage 5)

Input: everything under `projects/<slug>/` from stages 1–4.
Output: `projects/<slug>/manifest.json`, `config.yaml`, `report.md`, and the rendered ad.

The engine CLI runs from the AdForge repo root (the plugin root): `uv run adengine <command> projects/<slug>`. Check it works (`uv run adengine --help`) before the gate; if it doesn't, stop and tell the user.

## 1. Manifest and config

- `config.yaml`: copy `skills/ad-runner/example-config.yaml`, replacing the model IDs if prompt-craft chose others.
- `manifest.json`: follow `skills/ad-runner/example-manifest.json` exactly — same node ids, types and input shapes — with this ad's prompts, VO text, durations, music mood and end card. Per variant `vN`:
  - `vN.sXX.keyframe` (image): prompt = keyframe prompt; `inputs: {"aspect": "9:16"}`; no refs; no `n`.
  - `vN.sXX.clip` (video): prompt = motion prompt; `inputs: {"first_frame": "@vN.sXX.keyframe", "duration": <s>, "aspect": "9:16"}`.
  - `vN.vo.lXX` (tts, mock): `{"text": <VO line>, "voice": "narrator"}`.
  - `vN.music.bed` (music, mock): prompt = music mood; `duration` = shots total + end card.
  - `vN.timeline`, `vN.preview`, `vN.capcut_draft` as in the example; the timeline's `vo[].text` is the VO line, `end_card.text` the end card.
  - `project` = the slug.
- Run `uv run adengine validate projects/<slug>` until it prints `OK`. Fix errors in the manifest, never in engine code.

## 2. The gate

Show, in this order, then stop and wait for the user:

1. **Assumptions** — every *(default)* from `plan.md`.
2. **Script** per variant — hook, VO lines, captions, end card.
3. **Claim check** — "clean", or each hit with the rule and the compliant rewrite. The gate cannot be approved while a hit is unresolved: the user accepts the rewrite or edits the line.
4. **Shots and prompts** — per shot: seconds, keyframe prompt, motion prompt.
5. **Render list** — per variant: 5 Ellora images (`nano-banana-pro`) and 5 Ellora videos (`kling-3.0/video`), N variants in total. Say plainly: these spend your Ellora credits (videos far more than images) and land in your Ellora library.

The user may approve, edit lines or shots, change an angle, drop or add variants, or ask for new prompts. Redo only the affected stage, update the manifest, re-validate, and show the gate again.

Approval confirms exactly the listed renders and downloading their results into the project. Anything not on that list later (a revision, an extra shot) needs a new confirmation.

## 3. Render loop

1. `uv run adengine run projects/<slug>`. Exit `0` → go to §4. Exit `1` → go to §4 and report what needs attention. Exit `3` → continue.
2. `uv run adengine external projects/<slug> --json` — the nodes waiting for Ellora, with `prompt`, `model`, `inputs`, `external_inputs` and `fingerprint`.
3. Render each node in Ellora:
   - **image:** `generate_image` with `prompt`, `modelId` = the node's `model`, `aspectRatio: "9:16"`. Independent keyframes can render in parallel.
   - **video:** `generate_video` with `prompt`, `modelId`, `firstFrameUrl` = `external_inputs.first_frame`, `durationSec` = `inputs.duration`, `aspectRatio: "9:16"`, `generateAudio: false` (VO and music come from the timeline). Then `check_generation` with `wait: true`, repeating until it is finished or failed.
4. Download each finished file from the link `check_generation` returns into `projects/<slug>/.tmp/ellora/<node id>.<ext>`, then:
   `uv run adengine supply projects/<slug> <node id> <file> --ref <Ellora path> --id <generation id> --fingerprint <fingerprint>`.
   Supplies may run in parallel; the engine locks its state.
5. Problems:
   - Ellora render failed or timed out → `adengine supply ... --failed "<Ellora's message>"`. The next run lists it again; render it once more. A second failure → stop the loop and report it.
   - Ellora refused the prompt → `adengine supply ... --refused "<message>"`, rewrite the prompt once within the claim and prompt rules, `uv run adengine revise projects/<slug> <node id> --json '{"prompt": "<new prompt>"}' --no-run`, and continue the loop (a re-render of the same shot is covered by the gate approval). A second refusal → report it.
6. Back to step 1. Expect two passes per variant (keyframes, then clips) before assembly finishes.

## 4. Report

Write `projects/<slug>/report.md` and show the same to the user:

- per variant: `vN/preview.mp4` and `vN/capcut_draft/` paths;
- the Ellora generation IDs used (from `adengine status` / the ledger);
- every node `failed` or `needs_review`, with its reason;
- what is still placeholder: audio (mock TTS and music), and assembly while the real preview/CapCut providers are not merged in.

## 5. Revisions

After the report, turn feedback into node changes:
- "shot 3 too dark" → `uv run adengine revise projects/<slug> v1.s03.keyframe --json '{"prompt": "<revised prompt>"}' --no-run`.
- Motion only → revise `v1.s03.clip` instead (the keyframe stays).
- A VO line → revise `v1.vo.lXX` `inputs.text` **and** the matching `vo[].text` in `v1.timeline`.

List the renders the change causes (e.g. "1 image + 1 video in Ellora") and get the user's OK, then run the render loop again. The engine re-renders only the changed node, what depends on it, and the assembly.
