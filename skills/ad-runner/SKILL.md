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
- `manifest.json`: follow `skills/ad-runner/example-manifest.json` exactly — same id scheme, types and input shapes — with this ad's cast, prompts, spoken lines, durations and end card. Each clip carries its own audio from Ellora; there is no voiceover node and no music bed. Nodes:
  - `cast.<id>.ref` (image), one per on-screen person in `cast.md`: prompt = the reference prompt; `inputs: {"aspect": "9:16"}`. Voice-only cast members (cast.md "Node: none (voice only)") get no `cast.<id>.ref` node and no refs.
  - Keyframes `vN.sXX.keyframe` and, for hooks + shared body, `body.sXX.keyframe` (image): prompt from `vN/prompts.md` or `body/prompts.md` (the `## <shot id>` section); `inputs: {"aspect": "9:16"}`, plus, for a shot whose Reference line names cast members, one `@cast.<id>.ref` per id on that line, in both `refs` and `depends_on`.
  - Clips `vN.sXX.clip` / `body.sXX.clip` (video): prompt from `vN/prompts.md` or `body/prompts.md` (the `## <shot id>` section); `inputs: {"first_frame": "@<shot>.keyframe", "duration": <s>, "aspect": "9:16"}`.
  - `vN.timeline` per variant: the variant's hook shots, then the body shots (`@body.sXX.clip`), each `{"clip", "duration", "fallback", "audio": true, "text": <spoken line>}`; `end_card`; `captions: true`. Body nodes appear once in the manifest and are shared by every variant's timeline, so they render once.
  - `vN.preview`, `vN.capcut_draft` as in the example. `project` = the slug.
- Run `uv run adengine validate projects/<slug>` until it prints `OK`. Fix errors in the manifest, never in engine code.

## 1b. Cast preview (before the gate, only with an OK)

If `cast.md` lists anyone on screen, the user should see their faces before approving. Ask: "Render <N> cast reference image(s) in Ellora so you can approve the faces? This uses <N> Ellora image credits, plus at most one retry each if an image fails the visual check." <N> is the exact number of images, one per on-screen cast member. Only on a yes, run the render loop (§3) restricted to the cast: `uv run adengine run projects/<slug> --only "cast.*"`, then `adengine external`, render, check (§3 step 4), supply, until it exits `0`. Check each reference image against: matches the look phrase, plain backdrop, faces the camera, natural face and hands (not "matches the cast reference"; it is the reference). If it exits `1` (a reference held after its retry), tell the user and ask whether to revise the look phrase before the gate. If the user declines, the gate shows the look phrases only and the cast renders in the main loop.

## 2. The gate

Show, in this order, then stop and wait for the user:

1. **Assumptions** — every *(default)* from `plan.md`.
2. **Cast** — per person: the reference image (`cast/<id>/ref.png`) if rendered, the look phrase and the voice phrase, their "Defaults chosen" line, with every *(default)* choice marked. The user may ask for a different face, outfit or voice: revise the cast entry and its prompt, re-render the reference (another OK), and show the gate again.
3. **Script** per variant — hook, spoken lines (who says each), captions, end card.
4. **Claim check** — "clean", or each hit with the rule and the compliant rewrite. The gate cannot be approved while a hit is unresolved: the user accepts the rewrite or edits the line.
5. **Shots and prompts** — per shot: seconds, keyframe prompt, clip prompt (with its quoted spoken line).
6. **Render list** — Ellora images: cast references not yet rendered + every keyframe; Ellora videos: every clip. Count shared body shots once, and say so ("body: 4 images + 4 videos, shared by all N variants"). Say plainly: these spend your Ellora credits (videos far more than images) and land in your Ellora library — plus at most one corrective retry per image or clip after a failed visual check (a clip retry costs a video).

The user may approve, edit lines or shots, change an angle, drop or add variants, or ask for new prompts. Redo only the affected stage, update the manifest, re-validate, and show the gate again.

Approval confirms exactly the listed renders and downloading their results into the project. That approval covers the listed renders and at most one visual-check retry each; nothing else. Anything not on that list later (a revision, an extra shot) needs a new confirmation.

## 3. Render loop

1. `uv run adengine run projects/<slug>`. Exit `0` → go to §4. Exit `1` → go to §4 and report what needs attention. Exit `3` → continue.
2. `uv run adengine external projects/<slug> --json` — the nodes waiting for Ellora, with `prompt`, `model`, `inputs`, `external_inputs` and `fingerprint`.
3. Render each node in Ellora:
   - **image:** `generate_image` with `prompt`, `modelId` = the node's `model`, `aspectRatio: "9:16"`, and `referenceImageUrls` = `external_inputs.refs` when the node has refs (the cast reference). Independent images can render in parallel.
   - **video:** `generate_video` with `prompt`, `modelId`, `firstFrameUrl` = `external_inputs.first_frame`, `durationSec` = `inputs.duration`, `aspectRatio: "9:16"`, `generateAudio: true` (the clip's audio is the spoken line plus natural sound; the prompt already contains the line). Then `check_generation` with `wait: true`, repeating until it is finished or failed.
4. Download each finished file from the link `check_generation` returns into `projects/<slug>/.tmp/ellora/<node id>.<ext>` and **look at it before supplying** (Read the image; for a clip, extract three frames with `ffmpeg -ss <t> -i <clip> -frames:v 1 <png>` at the start, middle and end and Read them). Reject it if any of these fail: the person matches the cast reference (face, hair, outfit); hands and fingers look right; product labels are legible and match the brand wording; no warped objects, extra limbs, melted faces or stray text; the shot matches its description; for a clip, the clip has an audio stream (`ffprobe -v error -show_streams <clip>` lists an audio stream), and a clip without audio fails the check. A rejected render gets **one** corrective retry: add one corrective sentence to the prompt ("…her face matches the reference exactly", "…the label text is crisp"), record it with `uv run adengine revise projects/<slug> <node id> --json '{"prompt": "<prompt + correction>"}' --no-run`, and let the loop render it again. If the retry is rejected too, supply it with `adengine supply … --refused "visual check: <what was wrong>"`: the engine holds it for review (it is not re-rendered), its media dependents wait and its variant assembles with a placeholder, and the run exits `1`, so go to §4 and report it. A passing render is supplied:
   `uv run adengine supply projects/<slug> <node id> <file> --ref <Ellora path> --id <generation id> --fingerprint <fingerprint>`.
   Supplies may run in parallel; the engine locks its state.
5. Problems:
   - Ellora render failed or timed out → `adengine supply ... --failed "<Ellora's message>"`. The next run lists it again; render it once more. A second failure → stop the loop and report it.
   - Ellora refused the prompt → `adengine supply ... --refused "<message>"`, rewrite the prompt once within the claim and prompt rules, `uv run adengine revise projects/<slug> <node id> --json '{"prompt": "<new prompt>"}' --no-run`, and continue the loop (a re-render of the same shot is covered by the gate approval). A second refusal → report it.
6. Back to step 1. Expect a few passes (keyframes, then clips) before assembly finishes.

## 4. Report

Write `projects/<slug>/report.md` and show the same to the user:

- per variant: `vN/preview.mp4` and `vN/capcut_draft/` paths;
- the Ellora generation IDs used (from `adengine status` / the ledger);
- every node `failed` or `needs_review`, with its reason;
- the cast: each reference image path, and any render that needed a retry after the visual check.
- that no music is added: the audio is each clip's own spoken line and natural sound; add music in CapCut if wanted.

## 5. Revisions

After the report, turn feedback into node changes:
- "shot 3 too dark" → `uv run adengine revise projects/<slug> v1.s03.keyframe --json '{"prompt": "<revised prompt>"}' --no-run`.
- Motion only → revise `v1.s03.clip` instead (the keyframe stays).
- A spoken line → revise the clip's prompt so it quotes the new line (`v1.sXX.clip`, re-rendered in Ellora) **and** the matching `shots[k].text` in `v1.timeline` (the caption).
- A cast change ("make Maya older", "different sweater") → revise `cast.<id>.ref` and the look phrase in every prompt that uses it. List the cost honestly: the engine re-renders the reference and every keyframe and clip that depends on it.
- A body shot change affects every variant (it is shared); say so when listing the renders.

List the renders the change causes (e.g. "1 image + 1 video in Ellora") and get the user's OK, then run the render loop again. The engine re-renders only the changed node, what depends on it, and the assembly.
