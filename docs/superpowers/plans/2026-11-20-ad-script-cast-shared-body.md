# /ad: Supplied Scripts, Shared Body, Consistent Cast — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/ad` handle real briefs like `docs/examples/brief-ellora-four-hooks.md`:
- **Supplied scripts:** a brief that contains a script keeps its wording after the claim check, and a story in the brief drives the ad.
- **Hook variants with a shared body:** "N hooks + one body" becomes N variants that share body footage rendered once in Ellora.
- **Consistent cast:** every on-screen person stays the same across all clips. This comes from a cast reference image approved at the gate, a fixed look phrase, and a fixed voice description.
- **Less AI slop:** fixed anti-slop phrases in every prompt, and a visual check of each Ellora render before it is supplied.

**Architecture:** Only the Claude Code plugin changes (skills, the agent, the command, the example manifest and its tests). The engine already provides everything needed:
- Nodes in any scope render once and can feed many timelines, so the `body.*` nodes are shared.
- `@ref` image inputs reach Ellora as `external_inputs.refs`, which the plugin passes as `referenceImageUrls`. So keyframes reference `cast.<name>.ref`.
- `adengine run --only "cast.*"` renders only the cast, which allows a cast preview before the gate.

**Tech Stack:** Markdown skills, JSON example manifest, pytest (`uv run pytest -q -W error`), ffmpeg (already installed).

**Spec context:**
- `docs/superpowers/specs/2026-11-20-ad-command-ellora-design.md` (the `/ad` flow, gate, render loop)
- `docs/superpowers/specs/2026-11-20-ellora-integration-design.md` (external providers, `external_inputs`)
- `docs/examples/brief-ellora-four-hooks.md` (the motivating brief)

## Global Constraints

- **The engine is not touched.** No file under `engine/` changes. If a task seems to need an engine change, stop and report.
- **Ellora claim rules still gate everything.** A supplied script is never published unchecked: each hit is shown at the gate with a compliant rewrite, and the gate can't be approved while a hit is open. Supplied wording is otherwise kept exactly (only split into shots, never paraphrased).
- **No renders before the user agrees.** The cast preview needs its own explicit OK, which states the number of Ellora images it will spend. The full render list needs gate approval. Revisions need a new OK.
- **Every spoken line** is ≤ 14 words and ≤ 2.6 words per second of its shot, and it appears word for word, in double quotes, in its clip prompt.
- **IDs.** Cast references are `cast.<name>.ref` (image). Shared body shots are `body.sXX.keyframe` / `body.sXX.clip`. Hook shots are `vN.sXX.*`. Assembly is `vN.timeline` / `vN.preview` / `vN.capcut_draft`.
- **Fixed phrases.** Each cast member has one **look phrase** and one **voice phrase**, defined in `cast.md` and copied word for word into every keyframe and clip prompt they appear in.
- **Anti-slop endings.** Every keyframe prompt ends with the exact sentence
  `Natural skin texture, anatomically correct hands, no extra fingers, no text, no watermark.`
  Every clip prompt contains the exact sentence `Stable face and hands, no morphing or warping.`
- **No music; clips carry their own audio.** This is unchanged from the clip-audio decision.

---

## File Structure

```
skills/
  ad-strategist/SKILL.md     # MODIFY: script source detection, story-driven angles, hooks/body plan
  script-writer/SKILL.md     # MODIFY: supplied-script mode (verbatim segmentation), body/ + hook files, speakers = cast ids
  cast-designer/SKILL.md     # NEW: cast.md — look phrase, voice phrase, reference prompt per person
  shot-planner/SKILL.md      # MODIFY: body/shots.md + hook shots, "Cast" column
  prompt-craft/SKILL.md      # MODIFY: cast reference prompts, look/voice phrases, anti-slop endings
  ad-runner/SKILL.md         # MODIFY: manifest shape (cast, body, refs), cast preview, gate, render loop (referenceImageUrls, visual check)
  ad-runner/example-manifest.json   # REPLACE: 2 hooks + shared body + cast (23 nodes)
agents/variant-writer.md     # MODIFY: writes one hook variant (or full variant when there is no body)
commands/ad.md               # MODIFY: stage order with cast-designer, body handled once
tests/test_plugin_structure.py      # MODIFY: new skill, stage order, needles
tests/test_ad_example.py            # REPLACE: tests for the new example
docs/superpowers/specs/2026-11-20-ad-command-ellora-design.md   # MODIFY: record the decisions
```

---

### Task 1: Strategist: script source and story-driven angles

**Files:**
- Modify: `skills/ad-strategist/SKILL.md` (sections 2, 4 and 5)
- Modify: `tests/test_plugin_structure.py`

**Interfaces:**
- Produces, in `plan.md`, the lines `- Script source: supplied | written` and `- Structure: hooks + shared body | full variants`. When the brief has a body, it also produces a `## Body` section and per-variant hook names. Later stages branch on these exact labels.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_plugin_structure.py`:

```python
def test_strategist_detects_supplied_scripts_and_story():
    body = (ROOT / "skills" / "ad-strategist" / "SKILL.md").read_text()
    for needle in ("Script source: supplied", "Script source: written", "hooks + shared body",
                   "script-source.md", "The brief's story wins", "Never invent a script"):
        assert needle in body, needle
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_plugin_structure.py::test_strategist_detects_supplied_scripts_and_story -q`
Expected: FAIL, `AssertionError: Script source: supplied`.

- [ ] **Step 3: Edit the skill**

In `skills/ad-strategist/SKILL.md`, replace section `## 2. Slug and brief` with:

```markdown
## 2. Slug, brief and script source

- Slug: `<product>-<angle>` in lowercase with hyphens, e.g. `complete-kit-dustpan`. If `projects/<slug>/` already holds a different ad, add `-2`, `-3`.
- Write the user's brief, word for word, to `projects/<slug>/brief.md`. If the user gave a file path (`.txt`, `.md`), read it and copy its text; for a Google Doc, PDF or Word file, ask the user to paste the text.
- Decide the **script source**:
  - **Script source: supplied** — the brief already contains spoken copy: hook paragraphs, a body, a full monologue, lines in quotes. Copy that copy, word for word and in order, to `projects/<slug>/script-source.md`, split into sections: `## Hook 1 — <name>`, `## Hook 2 — <name>`, …, and `## Body` when there is one (a single monologue with no hooks is `## Hook 1` with no body). Keep any stage notes from the brief (who speaks, tone, banners) under `## Notes`.
  - **Script source: written** — the brief describes the product, audience, angle or a story, but has no spoken copy. Never invent a script at this stage; script-writer writes it.
- Decide the **structure**:
  - **hooks + shared body** — the supplied script has several hooks that each lead into the same body (marked "→ BODY", "BODY", "+ body"). One variant per hook; the body is rendered once and shared.
  - **full variants** — anything else: each variant is a complete ad.
```

Replace the first paragraph of section `## 4. Angles` (before the numbered list) with:

```markdown
**The brief's story wins.** If the brief describes a story, a concept, characters, a setting or scenes, that is the creative direction: v1 (and every variant, unless the brief asks for alternatives) follows it, and `plan.md` records its specifics (who is in it, where, what happens) under the variant. With **Script source: supplied**, each variant's angle is its hook's name and argument.

Only when the brief gives no story and no script, pick one angle per variant, each different, from the brand's strongest material:
```

In the `plan.md` template of section 5, add these two lines directly after `- Variants: <N>`:

```markdown
- Script source: <supplied | written>
- Structure: <hooks + shared body | full variants>
```

Add after the `## Angles` block in the template:

```markdown
## Story and cast notes
- <from the brief: who is on screen, how they talk, where it happens; "none given" if none>

## Body
- <only for hooks + shared body: one line on what the body argues; the copy is in script-source.md>
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_plugin_structure.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
/usr/bin/git add skills/ad-strategist/SKILL.md tests/test_plugin_structure.py
/usr/bin/git commit -m "feat(ad): strategist detects supplied scripts and hook/body structure; brief's story drives the angle"
```

---

### Task 2: New stage: cast-designer

**Files:**
- Create: `skills/cast-designer/SKILL.md`
- Modify: `commands/ad.md`, `tests/test_plugin_structure.py`

**Interfaces:**
- Consumes: `plan.md` ("Story and cast notes"), the scripts (`body/script.md` and `vN/script.md` speakers), and `brand/ellora.md`.
- Produces: `projects/<slug>/cast.md`. Per person it holds the `id` (lowercase name, e.g. `maya`), a **Look phrase**, a **Voice phrase**, a **Reference prompt**, and the node `cast.<id>.ref`. Off-camera narration uses the voice phrase of the person who narrates. `cast.md` with "No cast" means no on-screen person.

- [ ] **Step 1: Write the failing tests**

In `tests/test_plugin_structure.py`, change `SKILLS` to:

```python
SKILLS = ["ad-strategist", "script-writer", "cast-designer", "shot-planner", "prompt-craft", "ad-runner"]
```

Append:

```python
def test_cast_designer_defines_fixed_phrases():
    body = (ROOT / "skills" / "cast-designer" / "SKILL.md").read_text()
    for needle in ("cast.md", "Look phrase", "Voice phrase", "Reference prompt", "cast.<id>.ref",
                   "word for word", "No cast"):
        assert needle in body, needle
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_plugin_structure.py -q`
Expected: FAIL in `test_skill_has_name_and_description[cast-designer]` (file missing), `test_ad_command_runs_every_stage_in_order` (no cast-designer), and `test_cast_designer_defines_fixed_phrases`.

- [ ] **Step 3: Create the skill**

Create `skills/cast-designer/SKILL.md`:

````markdown
---
name: cast-designer
description: Stage 3 of /ad. Designs every on-screen person once — a look phrase, a voice phrase and a reference-image prompt — and writes projects/<slug>/cast.md, so every keyframe and clip shows and sounds like the same person.
---

# Cast designer (stage 3)

Input: `projects/<slug>/plan.md` ("Story and cast notes"), every `script.md` (the Speaker column), `projects/<slug>/brand/ellora.md`.
Output: `projects/<slug>/cast.md`.

AI images and videos drift: render the same description twice and you get two different people. The cure is one reference image per person, approved by the user, plus fixed wording reused everywhere.

## Who is in the cast

- Everyone who speaks on camera or appears in more than one shot gets a cast entry. Off-camera narration is spoken by a cast member (usually the presenter) and uses their voice phrase.
- Take who they are from the brief: its story and cast notes, how the script talks (a friend telling it straight, a mum at the kitchen table). Where the brief is silent, choose someone believable for the audience (the brand file's audience, roughly 28–55) and mark each such choice *(default)* so the gate shows it.
- Never a doctor, pharmacist or anyone in a white coat; no before/after bodies.
- If nobody appears on screen and there is no narration, write `No cast` and stop.

## Per person

- **id**: lowercase first name, e.g. `maya`. Node: `cast.<id>.ref`.
- **Look phrase**: one sentence that pins the visual identity — name, age, hair (length, colour, texture, how it's worn), skin tone, one or two distinctive details (earrings, glasses), and one outfit worn in every shot. Example: `Maya (the woman in the reference image: mid-thirties, warm brown skin, shoulder-length dark curly hair pulled half up, small gold hoop earrings, oversized cream knit sweater)`.
- **Voice phrase**: one phrase for every line they speak, on or off camera — pitch, age, accent, pace, attitude. Example: `a warm, low, unhurried American woman's voice, a little dry and knowing` (one noun phrase, no name prefix).
- **Reference prompt**: the image Ellora renders as `cast.<id>.ref` — "Photoreal vertical 9:16 waist-up portrait of" + the look phrase (without the "in the reference image" words) + "looking straight into the camera, neutral relaxed expression, plain soft-grey backdrop, soft even window light from the left." + the anti-slop ending from prompt-craft.

The look phrase and the voice phrase are copied **word for word** into every keyframe and clip prompt that person appears in. Never paraphrase them later; a changed word is a changed person.

## Write `projects/<slug>/cast.md`

```markdown
# Cast

## maya — presenter *(default where marked)*
- Node: cast.maya.ref
- Look phrase: <one sentence>
- Voice phrase: <one phrase>
- Reference prompt: <prompt>
- Appears in: <shot ids, filled in by shot-planner>
```
````

- [ ] **Step 4: Update the /ad command**

Replace the numbered stage list in `commands/ad.md` with:

```markdown
1. **ad-strategist** — brand file, slug, `brief.md`, `script-source.md` (supplied scripts), `plan.md`.
2. **script-writer** — `v1/script.md` (and `body/script.md` for hooks + shared body) with the claim check.
3. **cast-designer** — `cast.md`: one look phrase, voice phrase and reference prompt per person.
4. **shot-planner** — `v1/shots.md` (and `body/shots.md`).
5. **prompt-craft** — `v1/prompts.md` (and `body/prompts.md`).
   When `plan.md` has more than one variant, do stages 2–5 for v1 and the body yourself, then dispatch one **variant-writer** agent per other variant, in parallel, and wait for all of them. The body is written once, never per variant.
6. **ad-runner** — manifest and config, the cast preview (only with the user's OK), then **the gate: stop and wait for the user's approval**. Only after approval: the Ellora render loop, the report, and revisions.
```

Replace the final line (`Never call Ellora's …`) with:

```markdown
Never call Ellora's `generate_image` or `generate_video` before the user agrees: the cast preview needs its own OK, everything else needs the gate.
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_plugin_structure.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
/usr/bin/git add skills/cast-designer commands/ad.md tests/test_plugin_structure.py
/usr/bin/git commit -m "feat(ad): cast-designer stage — fixed look and voice phrases and a reference image per person"
```

---

### Task 3: Script-writer and shot-planner: supplied mode, shared body, cast column

**Files:**
- Modify: `skills/script-writer/SKILL.md`, `skills/shot-planner/SKILL.md`
- Modify: `tests/test_plugin_structure.py`

**Interfaces:**
- **Script-writer** produces `body/script.md` (hooks + shared body only) and `vN/script.md`. In hook variants, `vN/script.md` holds only that hook's beats. The Speaker column holds a cast id (`maya`) or `maya (off camera)`.
- **Shot-planner** produces `body/shots.md` with shots `body.s01…`, and `vN/shots.md` with shots `vN.s01…`. Each shot row has a **Cast** column (cast ids, or `—`). It fills in "Appears in:" in `cast.md`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_plugin_structure.py`:

```python
def test_writer_and_planner_handle_supplied_scripts_and_shared_body():
    writer = (ROOT / "skills" / "script-writer" / "SKILL.md").read_text()
    planner = (ROOT / "skills" / "shot-planner" / "SKILL.md").read_text()
    for needle in ("Script source: supplied", "script-source.md", "word for word", "never paraphrase",
                   "body/script.md", "compliant rewrite"):
        assert needle in writer, needle
    for needle in ("body/shots.md", "body.s01", "Cast", "cast.md"):
        assert needle in planner, needle
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_plugin_structure.py::test_writer_and_planner_handle_supplied_scripts_and_shared_body -q`
Expected: FAIL, `AssertionError: Script source: supplied`.

- [ ] **Step 3: Edit script-writer**

In `skills/script-writer/SKILL.md`, change the `Input:`/`Output:` lines to:

```markdown
Input: `projects/<slug>/plan.md`, `projects/<slug>/brand/ellora.md`, and `projects/<slug>/script-source.md` when the plan says **Script source: supplied**.
Output: `projects/<slug>/vN/script.md`, plus `projects/<slug>/body/script.md` once when the plan says **hooks + shared body**.
```

Insert a new section directly before `## Structure`:

```markdown
## Supplied scripts (Script source: supplied)

The user's copy is the script. Split it into beats; never paraphrase, reorder or "improve" it.

- Split at sentence or clause boundaries into spoken lines that obey the line rules below (≤ 14 words, ≤ ~2.6 words per second of the shot). Keep the words exactly, word for word, including the user's grammar and voice; only the line breaks are yours.
- With **hooks + shared body**: `vN/script.md` holds only hook N's beats; `body/script.md` holds the body's beats, written once. The ad for variant N is its hook followed by the body.
- Long copy makes long ads (a 60-second script is ~15 shots). Say so in the plan's assumptions; do not cut copy to fit a length default.
- The claim check below still applies to every line. A hit keeps the original line in the table and adds a compliant rewrite; the user decides at the gate. Nothing with an open hit renders.

When the plan says **Script source: written**, write the script yourself following Structure and Lines.
```

In the `## Lines` section, replace the first bullet's speaker wording with:

```markdown
- One spoken line per beat, said inside that shot's clip by a cast member: on camera (lip-synced) or off camera (their voice over a shot without them). Speakers are cast ids from `cast.md` (written next); use a short role name here (`presenter`, `friend`) and cast-designer turns it into the id. Ellora renders the line with the clip, so there is no separate voiceover. **14 words or fewer**, spoken naturally, and short enough for its shot: at most ~2.6 words per second (≤ 10 words for a 4 s shot, ≤ 13 for 5 s).
```

In `## Write projects/<slug>/vN/script.md`, add after the template:

```markdown
For **hooks + shared body**, write `body/script.md` with the same table (beats `b1`, `b2`, …) and no end card; each `vN/script.md` has only its hook beats and the end card.
```

- [ ] **Step 4: Edit shot-planner**

In `skills/shot-planner/SKILL.md`, change `Input:`/`Output:` to:

```markdown
Input: `projects/<slug>/vN/script.md` (and `body/script.md`), `projects/<slug>/plan.md`, `projects/<slug>/cast.md`.
Output: `projects/<slug>/vN/shots.md`, plus `projects/<slug>/body/shots.md` once for hooks + shared body; and the "Appears in" lines of `cast.md`.
```

Replace the first rule bullet with:

```markdown
- One shot per beat. Hook or full-variant shots are `vN.s01`, `vN.s02`, …; shared body shots are `body.s01`, `body.s02`, … (written once, used by every variant).
- Each shot lists its **Cast**: the cast ids on screen (or `—`). A shot whose line is spoken off camera lists `—` on screen and names the voice in the Spoken line column. Then fill in each person's "Appears in" line in `cast.md`.
- Keep each person in one setting and one outfit across the ad unless the story moves them; a new setting is a new risk of drift.
- Prefer shots that AI video renders cleanly: one person, one simple action, steady or slowly moving camera, hands still or out of frame; avoid fiddly hand actions, crowds, fast motion, and text on objects other than the product labels.
```

Change the template's header row to add the Cast column:

```markdown
| Shot | Seconds | On screen | Cast | Framing | Camera / motion | Bottle | Spoken line (speaker) |
|---|---|---|---|---|---|---|---|
| v1.s01 | 4 | ... | maya | medium, eye level | slow push-in | none | <line> (maya, on camera) |
| body.s03 | 5 | ... | — | packshot, centred | slow orbit | Gut Cleanse (Step 1) | <line> (maya, off camera) |
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_plugin_structure.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
/usr/bin/git add skills/script-writer/SKILL.md skills/shot-planner/SKILL.md tests/test_plugin_structure.py
/usr/bin/git commit -m "feat(ad): supplied scripts split verbatim; shared body script and shots; cast column"
```

---

### Task 4: Prompt-craft: cast references, fixed phrases, anti-slop endings

**Files:**
- Modify: `skills/prompt-craft/SKILL.md`
- Modify: `tests/test_plugin_structure.py`

**Interfaces:**
- Produces `body/prompts.md` and `vN/prompts.md`. Each keyframe states whether it uses the cast reference (`Reference: cast.maya.ref`) or none.
- The anti-slop sentences and the look/voice phrase rules here are the ones the example manifest and its tests enforce in Task 5.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_plugin_structure.py`:

```python
ANTI_SLOP_IMAGE = "Natural skin texture, anatomically correct hands, no extra fingers, no text, no watermark."
ANTI_SLOP_VIDEO = "Stable face and hands, no morphing or warping."


def test_prompt_craft_keeps_cast_consistent_and_fights_slop():
    body = (ROOT / "skills" / "prompt-craft" / "SKILL.md").read_text()
    for needle in (ANTI_SLOP_IMAGE, ANTI_SLOP_VIDEO, "look phrase", "voice phrase", "cast.md",
                   "Reference: cast.", "body/prompts.md", "word for word"):
        assert needle in body, needle
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_plugin_structure.py::test_prompt_craft_keeps_cast_consistent_and_fights_slop -q`
Expected: FAIL on the first needle.

- [ ] **Step 3: Edit the skill**

In `skills/prompt-craft/SKILL.md`, change `Input:`/`Output:` to:

```markdown
Input: `projects/<slug>/vN/shots.md` (and `body/shots.md`), `projects/<slug>/cast.md`, `projects/<slug>/brand/ellora.md`.
Output: `projects/<slug>/vN/prompts.md`, plus `projects/<slug>/body/prompts.md` once for hooks + shared body.
```

Insert a new section before `## Keyframe (image) prompts`:

```markdown
## Cast consistency

- Every keyframe with a cast member on screen: write `Reference: cast.<id>.ref` above the prompt (the manifest attaches that image), and put the person's **look phrase** from `cast.md` in the prompt, word for word. Never re-describe them in other words, and never change the outfit or hair unless `shots.md` says the story does.
- Every clip prompt with a spoken line: use the speaker's **voice phrase** from `cast.md`, word for word, whether they are on camera ("she looks into the camera and says, lips in sync, in <voice phrase>: …") or off camera ("<voice phrase>, off camera, says: …").
- Keep one look for the whole ad: the same light, lens and colour words in every keyframe of a setting.
```

At the end of the `## Keyframe (image) prompts` bullet list, add:

```markdown
- End every keyframe prompt with exactly: `Natural skin texture, anatomically correct hands, no extra fingers, no text, no watermark.`
```

At the end of the `## Clip prompts (motion and audio)` bullet list, add:

```markdown
- Every clip prompt contains exactly: `Stable face and hands, no morphing or warping.` Keep motion small and continuous; never ask for hands to do fine work (opening caps, counting drops) in close-up.
```

In `## Write projects/<slug>/vN/prompts.md`, change the per-shot template to:

```markdown
## v1.s01 (4 s)
**Reference:** cast.maya.ref  ← or "none"
**Keyframe:** <image prompt with the look phrase> Natural skin texture, anatomically correct hands, no extra fingers, no text, no watermark.
**Clip:** <motion> she looks into the camera and says, lips in sync, in <voice phrase>: "<spoken line>" Stable face and hands, no morphing or warping. Natural ambient sound, no music.
```

and add: `For hooks + shared body, body shots go in body/prompts.md (written once) with the same layout.`

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_plugin_structure.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
/usr/bin/git add skills/prompt-craft/SKILL.md tests/test_plugin_structure.py
/usr/bin/git commit -m "feat(ad): prompt-craft — cast reference, word-for-word look and voice phrases, anti-slop endings"
```

---

### Task 5: New example manifest, ad-runner flow (cast preview, refs, visual check), tests

**Files:**
- Replace: `skills/ad-runner/example-manifest.json`, `tests/test_ad_example.py`
- Modify: `skills/ad-runner/SKILL.md`, `tests/test_plugin_structure.py`

**Interfaces:**
- Consumes: the phrases and IDs from Tasks 2–4.
- Produces: the canonical manifest shape that `ad-runner` copies.
  - `cast.maya.ref` (image).
  - Hook keyframes and clips `v1.s01–s02` and `v2.s01–s02`.
  - Shared body keyframes and clips `body.s01–s04`.
  - Per variant: timeline, preview and capcut_draft.
  - Every keyframe with Maya has `inputs.refs = ["@cast.maya.ref"]` and `depends_on = ["cast.maya.ref"]`.
  - Both timelines list their two hook shots, then the same four `body.*` shots.
  - 23 nodes in total.

- [ ] **Step 1: Write the new example test (failing)**

Replace `tests/test_ad_example.py` with:

```python
"""The manifest /ad writes (skills/ad-runner/example-manifest.json) — two hooks sharing one body,
one consistent presenter — must work with the engine end to end."""
import asyncio
import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

from engine.assembly.timeline import build_timeline
from engine.cli import main
from engine.core.graph import load_manifest
from engine.core.paths import output_path, resolve_inputs
from engine.providers.mock import PNG_1X1

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "skills" / "ad-runner" / "example-manifest.json"
CONFIG = ROOT / "skills" / "ad-runner" / "example-config.yaml"
VARIANTS = {"v1": ["v1.s01", "v1.s02"], "v2": ["v2.s01", "v2.s02"]}
BODY = ["body.s01", "body.s02", "body.s03", "body.s04"]
CAST = "cast.maya.ref"
NO_CAST = {"body.s03"}  # the packshot: no person on screen, Maya speaks off camera
LOOK = ("Maya (the woman in the reference image: mid-thirties, warm brown skin, shoulder-length dark "
        "curly hair pulled half up, small gold hoop earrings, oversized cream knit sweater)")
VOICE = "a warm, low, unhurried American woman's voice, a little dry and knowing"
ANTI_SLOP_IMAGE = "Natural skin texture, anatomically correct hands, no extra fingers, no text, no watermark."
ANTI_SLOP_VIDEO = "Stable face and hands, no morphing or warping."


@pytest.fixture
def ad_dir(tmp_path):
    d = tmp_path / "complete-kit-four-hooks"
    d.mkdir()
    shutil.copy(EXAMPLE, d / "manifest.json")
    shutil.copy(CONFIG, d / "config.yaml")
    return d


def nodes():
    return {n["id"]: n for n in json.loads(EXAMPLE.read_text())["nodes"]}


def test_example_config_routes_images_and_video_to_ellora():
    cfg = yaml.safe_load(CONFIG.read_text())
    assert cfg["external_providers"] == ["ellora"]
    assert cfg["routing"]["image"] == {"provider": "ellora", "model": "nano-banana-pro"}
    assert cfg["routing"]["video"] == {"provider": "ellora", "model": "kling-3.0/video"}
    for t in ("timeline", "preview", "capcut_draft"):
        assert cfg["routing"][t]["provider"] == "assembly"


def test_example_manifest_validates(ad_dir, capsys):
    assert main(["validate", str(ad_dir)]) == 0
    assert capsys.readouterr().out.strip() == "OK: 23 nodes"


def test_cast_reference_is_a_plain_portrait():
    cast = nodes()[CAST]
    assert cast["type"] == "image" and cast["depends_on"] == [] and cast["inputs"] == {"aspect": "9:16"}
    assert "looking straight into the camera" in cast["prompt"]
    assert cast["prompt"].endswith(ANTI_SLOP_IMAGE)


def test_every_shot_with_maya_uses_the_reference_and_the_look_phrase():
    n = nodes()
    for shot in [s for shots in VARIANTS.values() for s in shots] + BODY:
        kf = n[f"{shot}.keyframe"]
        assert kf["type"] == "image" and kf["prompt"].endswith(ANTI_SLOP_IMAGE), shot
        if shot in NO_CAST:
            assert kf["inputs"] == {"aspect": "9:16"} and kf["depends_on"] == [], shot
            assert "Maya" not in kf["prompt"], shot
        else:
            assert kf["inputs"] == {"aspect": "9:16", "refs": [f"@{CAST}"]}, shot
            assert kf["depends_on"] == [CAST], shot
            assert LOOK in kf["prompt"], shot


def test_every_clip_speaks_its_line_in_mayas_voice():
    n = nodes()
    for shot in [s for shots in VARIANTS.values() for s in shots] + BODY:
        clip = n[f"{shot}.clip"]
        assert clip["type"] == "video" and clip["depends_on"] == [f"{shot}.keyframe"], shot
        assert clip["inputs"]["first_frame"] == f"@{shot}.keyframe" and clip["inputs"]["aspect"] == "9:16"
        assert clip["inputs"]["duration"] in (4, 5), shot
        assert VOICE in clip["prompt"] and ANTI_SLOP_VIDEO in clip["prompt"], shot
        assert "natural ambient sound, no music" in clip["prompt"].lower(), shot


def test_each_variant_is_its_hook_then_the_shared_body():
    n = nodes()
    assert not [i for i, node in n.items() if node["type"] in ("tts", "sfx", "music")]
    assert not [i for i in n if i.startswith(("v1.body", "v2.body"))]
    for v, hook in VARIANTS.items():
        tl = n[f"{v}.timeline"]
        shots = tl["inputs"]["shots"]
        assert [s["clip"] for s in shots] == [f"@{x}.clip" for x in hook + BODY]
        assert tl["inputs"]["captions"] is True and "vo" not in tl["inputs"] and "music" not in tl["inputs"]
        assert set(tl["depends_on"]) == {f"{x}.{k}" for x in hook + BODY for k in ("clip", "keyframe")}
        for s, x in zip(shots, hook + BODY):
            clip = n[f"{x}.clip"]
            assert s["fallback"] == f"@{x}.keyframe" and s["audio"] is True
            assert s["duration"] == clip["inputs"]["duration"]
            words = len(s["text"].split())
            assert 0 < words <= 14 and words <= 2.6 * s["duration"], s["text"]
            assert f'"{s["text"]}"' in clip["prompt"], x
        assert n[f"{v}.preview"]["inputs"] == {"timeline": f"@{v}.timeline"}
        assert n[f"{v}.capcut_draft"]["inputs"] == {"timeline": f"@{v}.timeline"}


def test_lines_come_word_for_word_from_the_example_brief():
    brief = " ".join((ROOT / "docs" / "examples" / "brief-ellora-four-hooks.md").read_text().split())
    n = nodes()
    for v in VARIANTS:
        for s in n[f"{v}.timeline"]["inputs"]["shots"]:
            assert s["text"] in brief, s["text"]


def test_example_copy_respects_ellora_claim_rules():
    banned = ["cure", "treat", "prevent", "clinically proven", "doctor", "pharmacist", "candida", "ibs",
              "before and after", "parasite", "heal", "diagnosed", "diagnosis", "herpes", "virus", "antiviral"]
    n = nodes()
    copy = [s["text"] for v in VARIANTS for s in n[f"{v}.timeline"]["inputs"]["shots"]]
    copy += [n[f"{v}.timeline"]["inputs"]["end_card"]["text"] for v in VARIANTS]
    for line in copy:
        hits = [w for w in banned if re.search(r"\b" + re.escape(w) + r"\b", line.lower())]
        assert not hits, line


def test_bottle_shots_use_the_label_wording():
    n = nodes()
    held = n["body.s01.keyframe"]["prompt"]
    assert "Ellora Gut Cleanse (Step 1)" in held and "DIGESTIVE HEALTH & GUT BALANCE" in held
    pack = n["body.s03.keyframe"]["prompt"]
    for needle in ("Ellora Gut Cleanse (Step 1)", "DIGESTIVE HEALTH & GUT BALANCE",
                   "Ellora Zeolite Drops (Step 2)", "NATURAL HEAVY METAL DETOX SUPPORT"):
        assert needle in pack, needle
    assert pack.lower().count("dietary supplement") >= 2 and "Dietary Supplement" in held


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_example_timeline_inputs_build(ad_dir, variant):
    manifest = load_manifest(ad_dir / "manifest.json")
    node = manifest.nodes[f"{variant}.timeline"]
    inputs = resolve_inputs(manifest, ad_dir, node)
    sources, media = {}, {}
    for dep in node.depends_on:
        dn = manifest.nodes[dep]
        path = str(output_path(ad_dir, dep, dn.type))
        sources[path] = dep
        media[path] = {"image": 0.0, "video": float(dn.inputs.get("duration", 0))}[dn.type]
    audio = frozenset(p for p, dep in sources.items() if manifest.nodes[dep].type == "video")
    timeline = build_timeline(f"{variant}.timeline", inputs, sources=sources, project_dir=ad_dir,
                              media=media, audio_paths=audio)
    assert [e["audio"] for e in timeline["tracks"]["video"]] == [True] * 6
    assert timeline["warnings"] == [] and timeline["placeholders"] == []


def test_example_runs_through_the_ellora_loop(ad_dir, capsys, ffmpeg):
    """Plays Claude's part: 'renders' each awaiting node (tiny real media), supplies it, re-runs."""
    passes = 0
    while (code := main(["run", str(ad_dir)])) == 3:
        passes += 1
        assert passes <= 4
        capsys.readouterr()
        assert main(["external", str(ad_dir), "--json"]) == 0
        for item in json.loads(capsys.readouterr().out):
            if item["type"] == "video":
                keyframe = item["id"].replace(".clip", ".keyframe")
                assert item["external_inputs"]["first_frame"] == f"ellora://{keyframe}"
                f = ad_dir / f"{item['id']}.mp4"
                asyncio.run(ffmpeg.run([
                    "-f", "lavfi", "-i", "color=c=gray:s=270x480:r=24",
                    "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000",
                    "-t", str(item["inputs"]["duration"]), "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(f),
                ]))
            else:
                if item["id"] == CAST or item["id"].replace(".keyframe", "") in NO_CAST:
                    assert "refs" not in item["inputs"], item["id"]
                else:
                    assert item["external_inputs"]["refs"] == [f"ellora://{CAST}"], item["id"]
                f = ad_dir / f"{item['id']}.png"
                f.write_bytes(PNG_1X1)
            assert main(["supply", str(ad_dir), item["id"], str(f), "--ref", f"ellora://{item['id']}",
                         "--fingerprint", item["fingerprint"]]) == 0
    assert code == 0 and passes == 3  # cast + packshot keyframe; keyframes (+ packshot clip); clips
    for v, hook in VARIANTS.items():
        timeline = json.loads((ad_dir / v / "timeline.json").read_text())
        assert timeline["placeholders"] == []
        info = asyncio.run(ffmpeg.probe(ad_dir / v / "preview.mp4"))
        assert (info.width, info.height) == (1080, 1920) and info.has_audio
        assert info.duration == pytest.approx(timeline["duration"], abs=0.2)
        draft = json.loads((ad_dir / v / "capcut_draft" / "draft_content.json").read_text())
        assert [m["material_name"] for m in draft["materials"]["videos"]] == [f"{x}.clip" for x in hook + BODY]
    body_versions = {json.loads((ad_dir / "state.json").read_text())["nodes"][f"{b}.clip"]["version"] for b in BODY}
    assert body_versions == {1}  # the shared body rendered exactly once
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_ad_example.py -q`
Expected: most tests FAIL, because the current example has 13 nodes, no cast and no body.

- [ ] **Step 3: Replace the example manifest**

Replace `skills/ad-runner/example-manifest.json` with:

```json
{
  "manifest_version": 1,
  "project": "complete-kit-four-hooks",
  "nodes": [
    {
      "id": "cast.maya.ref",
      "type": "image",
      "prompt": "Photoreal vertical 9:16 waist-up portrait of Maya, a woman in her mid-thirties with warm brown skin, shoulder-length dark curly hair pulled half up, small gold hoop earrings and an oversized cream knit sweater, looking straight into the camera, neutral relaxed expression, plain soft-grey backdrop, soft even window light from the left. Natural skin texture, anatomically correct hands, no extra fingers, no text, no watermark.",
      "inputs": {"aspect": "9:16"},
      "depends_on": []
    },
    {
      "id": "v1.s01.keyframe",
      "type": "image",
      "prompt": "Photoreal vertical 9:16 frame. Maya (the woman in the reference image: mid-thirties, warm brown skin, shoulder-length dark curly hair pulled half up, small gold hoop earrings, oversized cream knit sweater) stands behind a bright, lived-in kitchen counter, a small pile of mismatched supplement tubs and tea boxes pushed to one side, arms folded, looking into the camera, unimpressed. Warm late-afternoon window light, shallow depth of field. Natural skin texture, anatomically correct hands, no extra fingers, no text, no watermark.",
      "inputs": {"aspect": "9:16", "refs": ["@cast.maya.ref"]},
      "depends_on": ["cast.maya.ref"]
    },
    {
      "id": "v1.s01.clip",
      "type": "video",
      "prompt": "Slow push-in. Maya unfolds her arms and nods toward the pile of tubs, then back to the camera. She looks into the camera and says, lips in sync, in a warm, low, unhurried American woman's voice, a little dry and knowing: \"Stop buying random cleanses that only do half the job.\" Stable face and hands, no morphing or warping. Natural ambient sound, no music.",
      "inputs": {"first_frame": "@v1.s01.keyframe", "duration": 5, "aspect": "9:16"},
      "depends_on": ["v1.s01.keyframe"]
    },
    {
      "id": "v1.s02.keyframe",
      "type": "image",
      "prompt": "Photoreal vertical 9:16 close-up. Maya (the woman in the reference image: mid-thirties, warm brown skin, shoulder-length dark curly hair pulled half up, small gold hoop earrings, oversized cream knit sweater) in the same bright kitchen, leaning slightly toward the camera with one eyebrow raised, a knowing half-smile. Warm late-afternoon window light. Natural skin texture, anatomically correct hands, no extra fingers, no text, no watermark.",
      "inputs": {"aspect": "9:16", "refs": ["@cast.maya.ref"]},
      "depends_on": ["cast.maya.ref"]
    },
    {
      "id": "v1.s02.clip",
      "type": "video",
      "prompt": "Static camera, very slight drift. Maya holds the raised eyebrow, then gives a small shrug. She looks into the camera and says, lips in sync, in a warm, low, unhurried American woman's voice, a little dry and knowing: \"That's a broom with no dustpan.\" Stable face and hands, no morphing or warping. Natural ambient sound, no music.",
      "inputs": {"first_frame": "@v1.s02.keyframe", "duration": 4, "aspect": "9:16"},
      "depends_on": ["v1.s02.keyframe"]
    },
    {
      "id": "v2.s01.keyframe",
      "type": "image",
      "prompt": "Photoreal vertical 9:16 frame. Maya (the woman in the reference image: mid-thirties, warm brown skin, shoulder-length dark curly hair pulled half up, small gold hoop earrings, oversized cream knit sweater) sits at the same bright kitchen's small table, a loose stack of paper receipts in front of her, looking up into the camera with tired amusement. Warm late-afternoon window light. Natural skin texture, anatomically correct hands, no extra fingers, no text, no watermark.",
      "inputs": {"aspect": "9:16", "refs": ["@cast.maya.ref"]},
      "depends_on": ["cast.maya.ref"]
    },
    {
      "id": "v2.s01.clip",
      "type": "video",
      "prompt": "Slow push-in. Maya rests her hand flat on the receipts and tilts her head. She looks into the camera and says, lips in sync, in a warm, low, unhurried American woman's voice, a little dry and knowing: \"How much have you spent trying to feel normal again?\" Stable face and hands, no morphing or warping. Natural ambient sound, no music.",
      "inputs": {"first_frame": "@v2.s01.keyframe", "duration": 5, "aspect": "9:16"},
      "depends_on": ["v2.s01.keyframe"]
    },
    {
      "id": "v2.s02.keyframe",
      "type": "image",
      "prompt": "Photoreal vertical 9:16 close-up. Maya (the woman in the reference image: mid-thirties, warm brown skin, shoulder-length dark curly hair pulled half up, small gold hoop earrings, oversized cream knit sweater) at the same kitchen table, leaning in toward the camera, serious and kind. Warm late-afternoon window light. Natural skin texture, anatomically correct hands, no extra fingers, no text, no watermark.",
      "inputs": {"aspect": "9:16", "refs": ["@cast.maya.ref"]},
      "depends_on": ["cast.maya.ref"]
    },
    {
      "id": "v2.s02.clip",
      "type": "video",
      "prompt": "Static camera. Maya holds eye contact and gives one small nod. She looks into the camera and says, lips in sync, in a warm, low, unhurried American woman's voice, a little dry and knowing: \"Nobody told you what was missing.\" Stable face and hands, no morphing or warping. Natural ambient sound, no music.",
      "inputs": {"first_frame": "@v2.s02.keyframe", "duration": 4, "aspect": "9:16"},
      "depends_on": ["v2.s02.keyframe"]
    },
    {
      "id": "body.s01.keyframe",
      "type": "image",
      "prompt": "Photoreal vertical 9:16 medium shot. Maya (the woman in the reference image: mid-thirties, warm brown skin, shoulder-length dark curly hair pulled half up, small gold hoop earrings, oversized cream knit sweater) in the same bright kitchen holds up Ellora Gut Cleanse (Step 1) beside her face, label toward the camera: a squat 30 mL amber-brown glass dropper bottle with a matte black ribbed collar and black rubber dropper bulb, deep sea-green / teal label with \"Ellora\" and \"Gut Cleanse\" in white, \"DIGESTIVE HEALTH & GUT BALANCE\" in small white capitals, a white intestine line drawing, and \"Dietary Supplement / 30 mL\" legible at the bottom. Warm late-afternoon window light. Natural skin texture, anatomically correct hands, no extra fingers, no text, no watermark.",
      "inputs": {"aspect": "9:16", "refs": ["@cast.maya.ref"]},
      "depends_on": ["cast.maya.ref"]
    },
    {
      "id": "body.s01.clip",
      "type": "video",
      "prompt": "Static camera, slight push-in. Maya keeps the bottle still beside her face, the label sharp and readable. She looks into the camera and says, lips in sync, in a warm, low, unhurried American woman's voice, a little dry and knowing: \"It has to be a liquid. Not a capsule.\" Stable face and hands, no morphing or warping. Natural ambient sound, no music.",
      "inputs": {"first_frame": "@body.s01.keyframe", "duration": 5, "aspect": "9:16"},
      "depends_on": ["body.s01.keyframe"]
    },
    {
      "id": "body.s02.keyframe",
      "type": "image",
      "prompt": "Photoreal vertical 9:16 close-up. Maya (the woman in the reference image: mid-thirties, warm brown skin, shoulder-length dark curly hair pulled half up, small gold hoop earrings, oversized cream knit sweater) in the same bright kitchen, hands out of frame, mid-thought, looking into the camera like she is letting you in on something. Warm late-afternoon window light. Natural skin texture, anatomically correct hands, no extra fingers, no text, no watermark.",
      "inputs": {"aspect": "9:16", "refs": ["@cast.maya.ref"]},
      "depends_on": ["cast.maya.ref"]
    },
    {
      "id": "body.s02.clip",
      "type": "video",
      "prompt": "Static camera. Maya leans in a little, hands staying out of frame. She looks into the camera and says, lips in sync, in a warm, low, unhurried American woman's voice, a little dry and knowing: \"And it needs a binder. This is the part nobody mentions.\" Stable face and hands, no morphing or warping. Natural ambient sound, no music.",
      "inputs": {"first_frame": "@body.s02.keyframe", "duration": 5, "aspect": "9:16"},
      "depends_on": ["body.s02.keyframe"]
    },
    {
      "id": "body.s03.keyframe",
      "type": "image",
      "prompt": "Photoreal vertical 9:16 packshot of two identical squat 30 mL amber-brown glass dropper bottles with round shoulders, matte black ribbed child-resistant screw collars and smooth black rubber dropper bulbs, standing upright side by side, centred. Left: Ellora Gut Cleanse (Step 1), deep sea-green / teal label with \"Ellora\" in white top left, \"Gut Cleanse\" large and bold across two lines in white, a thin white rule, \"DIGESTIVE HEALTH & GUT BALANCE\" in small white capitals, a white single-stroke intestine line drawing on the right, a \"30 SERVINGS\" circle, \"Dietary Supplement / 30 mL\" bottom left and \"(1 fl oz)\" bottom right. Right: Ellora Zeolite Drops (Step 2), identical layout on a dusty slate-blue label with \"Ellora\" top left, \"Zeolite Drops\" large and bold across two lines in white, a thin white rule, \"NATURAL HEAVY METAL DETOX SUPPORT\" in small white capitals, a white outline drawing of an elongated six-sided crystal on the right, the same \"30 SERVINGS\" circle, \"Dietary supplement / 30 mL\" and \"(1 fl oz)\" at the bottom. Seamless warm greige backdrop, one soft key light from the upper left, soft shadows falling to the right, no props, no hands. Natural skin texture, anatomically correct hands, no extra fingers, no text, no watermark.",
      "inputs": {"aspect": "9:16"},
      "depends_on": []
    },
    {
      "id": "body.s03.clip",
      "type": "video",
      "prompt": "Very slow push-in on the two bottles. Both labels stay sharp and readable; light shifts gently across the amber glass. No other movement. Off camera, in a warm, low, unhurried American woman's voice, a little dry and knowing, she says: \"Ellora is both steps. Gut Cleanse first, then Zeolite Drops.\" Stable face and hands, no morphing or warping. Natural ambient sound, no music.",
      "inputs": {"first_frame": "@body.s03.keyframe", "duration": 5, "aspect": "9:16"},
      "depends_on": ["body.s03.keyframe"]
    },
    {
      "id": "body.s04.keyframe",
      "type": "image",
      "prompt": "Photoreal vertical 9:16 medium shot. Maya (the woman in the reference image: mid-thirties, warm brown skin, shoulder-length dark curly hair pulled half up, small gold hoop earrings, oversized cream knit sweater) back at the same bright kitchen counter, relaxed, a warm direct smile to the camera, hands resting on the counter. Warm late-afternoon window light. Natural skin texture, anatomically correct hands, no extra fingers, no text, no watermark.",
      "inputs": {"aspect": "9:16", "refs": ["@cast.maya.ref"]},
      "depends_on": ["cast.maya.ref"]
    },
    {
      "id": "body.s04.clip",
      "type": "video",
      "prompt": "Slow push-in. Maya keeps the warm smile and points one finger down toward the bottom of the frame on the last words. She looks into the camera and says, lips in sync, in a warm, low, unhurried American woman's voice, a little dry and knowing: \"Stop buying half a cleanse. Link below. Get the one with both steps.\" Stable face and hands, no morphing or warping. Natural ambient sound, no music.",
      "inputs": {"first_frame": "@body.s04.keyframe", "duration": 5, "aspect": "9:16"},
      "depends_on": ["body.s04.keyframe"]
    },
    {
      "id": "v1.timeline",
      "type": "timeline",
      "inputs": {
        "aspect": "9:16",
        "shots": [
          {"clip": "@v1.s01.clip", "duration": 5, "fallback": "@v1.s01.keyframe", "audio": true, "text": "Stop buying random cleanses that only do half the job."},
          {"clip": "@v1.s02.clip", "duration": 4, "fallback": "@v1.s02.keyframe", "audio": true, "text": "That's a broom with no dustpan."},
          {"clip": "@body.s01.clip", "duration": 5, "fallback": "@body.s01.keyframe", "audio": true, "text": "It has to be a liquid. Not a capsule."},
          {"clip": "@body.s02.clip", "duration": 5, "fallback": "@body.s02.keyframe", "audio": true, "text": "And it needs a binder. This is the part nobody mentions."},
          {"clip": "@body.s03.clip", "duration": 5, "fallback": "@body.s03.keyframe", "audio": true, "text": "Ellora is both steps. Gut Cleanse first, then Zeolite Drops."},
          {"clip": "@body.s04.clip", "duration": 5, "fallback": "@body.s04.keyframe", "audio": true, "text": "Stop buying half a cleanse. Link below. Get the one with both steps."}
        ],
        "end_card": {"text": "Complete Kit · myellora.com", "duration": 2},
        "captions": true
      },
      "depends_on": [
        "v1.s01.clip", "v1.s02.clip", "body.s01.clip", "body.s02.clip", "body.s03.clip", "body.s04.clip",
        "v1.s01.keyframe", "v1.s02.keyframe", "body.s01.keyframe", "body.s02.keyframe", "body.s03.keyframe", "body.s04.keyframe"
      ]
    },
    {
      "id": "v1.preview",
      "type": "preview",
      "inputs": {"timeline": "@v1.timeline"},
      "depends_on": ["v1.timeline"]
    },
    {
      "id": "v1.capcut_draft",
      "type": "capcut_draft",
      "inputs": {"timeline": "@v1.timeline"},
      "depends_on": ["v1.timeline"]
    },
    {
      "id": "v2.timeline",
      "type": "timeline",
      "inputs": {
        "aspect": "9:16",
        "shots": [
          {"clip": "@v2.s01.clip", "duration": 5, "fallback": "@v2.s01.keyframe", "audio": true, "text": "How much have you spent trying to feel normal again?"},
          {"clip": "@v2.s02.clip", "duration": 4, "fallback": "@v2.s02.keyframe", "audio": true, "text": "Nobody told you what was missing."},
          {"clip": "@body.s01.clip", "duration": 5, "fallback": "@body.s01.keyframe", "audio": true, "text": "It has to be a liquid. Not a capsule."},
          {"clip": "@body.s02.clip", "duration": 5, "fallback": "@body.s02.keyframe", "audio": true, "text": "And it needs a binder. This is the part nobody mentions."},
          {"clip": "@body.s03.clip", "duration": 5, "fallback": "@body.s03.keyframe", "audio": true, "text": "Ellora is both steps. Gut Cleanse first, then Zeolite Drops."},
          {"clip": "@body.s04.clip", "duration": 5, "fallback": "@body.s04.keyframe", "audio": true, "text": "Stop buying half a cleanse. Link below. Get the one with both steps."}
        ],
        "end_card": {"text": "Complete Kit · myellora.com", "duration": 2},
        "captions": true
      },
      "depends_on": [
        "v2.s01.clip", "v2.s02.clip", "body.s01.clip", "body.s02.clip", "body.s03.clip", "body.s04.clip",
        "v2.s01.keyframe", "v2.s02.keyframe", "body.s01.keyframe", "body.s02.keyframe", "body.s03.keyframe", "body.s04.keyframe"
      ]
    },
    {
      "id": "v2.preview",
      "type": "preview",
      "inputs": {"timeline": "@v2.timeline"},
      "depends_on": ["v2.timeline"]
    },
    {
      "id": "v2.capcut_draft",
      "type": "capcut_draft",
      "inputs": {"timeline": "@v2.timeline"},
      "depends_on": ["v2.timeline"]
    }
  ]
}
```

Note: the packshot keyframe (`body.s03.keyframe`) ends with the anti-slop sentence like every keyframe, even though it has no person. The rule is uniform on purpose.

- [ ] **Step 4: Update the ad-runner skill**

In `skills/ad-runner/SKILL.md`, replace the manifest bullets under `## 1. Manifest and config` (from `- \`manifest.json\`:` to the `project` bullet) with:

```markdown
- `manifest.json`: follow `skills/ad-runner/example-manifest.json` exactly — same id scheme, types and input shapes — with this ad's cast, prompts, spoken lines, durations and end card. Each clip carries its own audio from Ellora; there is no voiceover node and no music bed. Nodes:
  - `cast.<id>.ref` (image), one per person in `cast.md`: prompt = the reference prompt; `inputs: {"aspect": "9:16"}`.
  - Keyframes `vN.sXX.keyframe` and, for hooks + shared body, `body.sXX.keyframe` (image): prompt from `prompts.md`; `inputs: {"aspect": "9:16"}`, plus `"refs": ["@cast.<id>.ref"]` and `depends_on: ["cast.<id>.ref"]` when the shot's Reference is a cast member.
  - Clips `vN.sXX.clip` / `body.sXX.clip` (video): prompt from `prompts.md`; `inputs: {"first_frame": "@<shot>.keyframe", "duration": <s>, "aspect": "9:16"}`.
  - `vN.timeline` per variant: the variant's hook shots, then the body shots (`@body.sXX.clip`), each `{"clip", "duration", "fallback", "audio": true, "text": <spoken line>}`; `end_card`; `captions: true`. Body nodes appear once in the manifest and are shared by every variant's timeline, so they render once.
  - `vN.preview`, `vN.capcut_draft` as in the example. `project` = the slug.
```

Insert a new section between `## 1. Manifest and config` and `## 2. The gate`:

```markdown
## 1b. Cast preview (before the gate, only with an OK)

If `cast.md` lists anyone, the user should see their faces before approving. Ask: "Render <N> cast reference image(s) in Ellora so you can approve the faces? This uses <N> Ellora image credits." Only on a yes, run the render loop (§3) restricted to the cast: `uv run adengine run projects/<slug> --only "cast.*"`, then `adengine external`, render, check (§3 step 4), supply, until it exits `0`. If the user declines, the gate shows the look phrases only and the cast renders in the main loop.
```

In `## 2. The gate`, insert as item 2 (renumber the rest):

```markdown
2. **Cast** — per person: the reference image (`cast/<id>/ref.png`) if rendered, the look phrase and the voice phrase, with every *(default)* choice marked. The user may ask for a different face, outfit or voice: revise the cast entry and its prompt, re-render the reference (another OK), and show the gate again.
```

In the **Render list** item, replace its text with:

```markdown
**Render list** — Ellora images: cast references not yet rendered + every keyframe; Ellora videos: every clip. Count shared body shots once, and say so ("body: 4 images + 4 videos, shared by all N variants"). Say plainly: these spend your Ellora credits (videos far more than images) and land in your Ellora library.
```

In `## 3. Render loop`, step 3, replace the **image** bullet with:

```markdown
   - **image:** `generate_image` with `prompt`, `modelId` = the node's `model`, `aspectRatio: "9:16"`, and `referenceImageUrls` = `external_inputs.refs` when the node has refs (the cast reference). Independent images can render in parallel.
```

Replace step 4's first sentence with:

```markdown
4. Download each finished file from the link `check_generation` returns into `projects/<slug>/.tmp/ellora/<node id>.<ext>` and **look at it before supplying** (Read the image; for a clip, extract three frames with `ffmpeg -ss <t> -i <clip> -frames:v 1 <png>` at the start, middle and end and Read them). Reject it if any of these fail: the person matches the cast reference (face, hair, outfit); hands and fingers look right; product labels are legible and match the brand wording; no warped objects, extra limbs, melted faces or stray text; the shot matches its description. A rejected render is re-rendered with the same prompt plus one corrective sentence ("…her face matches the reference exactly", "…the label text is crisp"); after two rejected attempts, supply it with `--failed "visual check: <what was wrong>"` so it is reported. A passing render is supplied:
```

In `## 4. Report`, add a bullet: `- the cast: each reference image path, and any render that needed a retry after the visual check.`

In `## 5. Revisions`, add:

```markdown
- A cast change ("make Maya older", "different sweater") → revise `cast.<id>.ref` and the look phrase in every prompt that uses it. List the cost honestly: the engine re-renders the reference and every keyframe and clip that depends on it.
- A body shot change affects every variant (it is shared); say so when listing the renders.
```

- [ ] **Step 5: Update the plugin-structure needles**

In `tests/test_plugin_structure.py`, in `test_ad_runner_points_at_its_examples_and_the_engine_loop`, add `"referenceImageUrls"`, `'--only "cast.*"'`, `"look at it before supplying"` and `"cast.<id>.ref"` to the needle tuple.

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_ad_example.py tests/test_plugin_structure.py -q -W error`
Expected: all pass, including the full Ellora-loop test. That test renders two 1080x1920 previews and checks that the shared body clips are at version 1.
Run: `uv run pytest -q -W error`
Expected: all pass, 0 skipped.

- [ ] **Step 7: Commit**

```bash
/usr/bin/git add skills/ad-runner tests/test_ad_example.py tests/test_plugin_structure.py
/usr/bin/git commit -m "feat(ad): example with consistent cast and shared body; cast preview, reference images and visual check in the render loop"
```

---

### Task 6: Variant-writer and spec notes

**Files:**
- Modify: `agents/variant-writer.md`, `docs/superpowers/specs/2026-11-20-ad-command-ellora-design.md`
- Modify: `tests/test_plugin_structure.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_plugin_structure.py`:

```python
def test_variant_writer_writes_hooks_only_and_never_the_body():
    body = (ROOT / "agents" / "variant-writer.md").read_text()
    for needle in ("cast.md", "hooks + shared body", "never write body/", "look phrase"):
        assert needle in body, needle
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_plugin_structure.py::test_variant_writer_writes_hooks_only_and_never_the_body -q`
Expected: FAIL.

- [ ] **Step 3: Edit the agent**

Replace the numbered steps and the "Touch only" paragraph of `agents/variant-writer.md` with:

```markdown
1. Read `projects/<slug>/plan.md` (your variant's angle and the structure), `projects/<slug>/brand/ellora.md`, `projects/<slug>/cast.md`, and `script-source.md` if the plan says **Script source: supplied**.
2. Follow the **script-writer** skill for your variant → `projects/<slug>/<vN>/script.md`. With **hooks + shared body** that is your hook's beats only.
3. Follow the **shot-planner** skill → `projects/<slug>/<vN>/shots.md`.
4. Follow the **prompt-craft** skill → `projects/<slug>/<vN>/prompts.md`, using each person's look phrase and voice phrase from `cast.md` word for word.

Touch only your own `<vN>/` folder: never write body/ (the orchestrator writes the shared body once), never edit `cast.md`, `manifest.json` or another variant. Do not render anything and do not call Ellora's `generate_image` or `generate_video`.
```

- [ ] **Step 4: Record the decisions in the spec**

In `docs/superpowers/specs/2026-11-20-ad-command-ellora-design.md`, add a section at the end:

```markdown
## 10. Supplied scripts, shared body, consistent cast (2026-11-20)

- A brief that contains spoken copy is used word for word (split into ≤ 14-word lines, never paraphrased) after the claim check; a story in the brief drives the angle.
- "N hooks + one body" briefs become N variants whose timelines share `body.*` nodes, rendered once.
- Each on-screen person is designed once in `cast.md` (look phrase, voice phrase, reference prompt). `cast.<id>.ref` renders before the gate only with the user's OK; every keyframe with that person references it (`refs` → Ellora `referenceImageUrls`) and repeats the look phrase; every line uses the voice phrase.
- Every render is visually checked before `adengine supply` (face matches the reference, hands, labels, artifacts); two failed checks → reported as failed.
- Known limit: Ellora generates each clip's voice separately, so the voice phrase reduces but does not remove voice drift between clips. A fixed TTS voice plus lip-sync is the follow-up for long talking-head ads.
```

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q -W error`
Expected: all pass, 0 skipped.

- [ ] **Step 6: Commit**

```bash
/usr/bin/git add agents/variant-writer.md docs/superpowers/specs/2026-11-20-ad-command-ellora-design.md tests/test_plugin_structure.py
/usr/bin/git commit -m "feat(ad): variant-writer writes hook variants only; spec records supplied-script, shared-body and cast decisions"
```

---

## Spec coverage

| Need (from the four-hook brief and the user) | Task |
|---|---|
| Brief text with or without a script; a story in the brief drives the ad | 1, 3 |
| Supplied wording kept word for word, with claim-check rewrites only at the gate | 1, 3 |
| N hooks + shared body → N variants, body rendered once | 1, 3, 5 (test asserts body clips stay at v1) |
| Same person in every clip: reference image approved at the gate, fixed look phrase | 2, 4, 5 |
| Same voice across clips (as far as Ellora allows) | 2, 4, 5 |
| Less AI slop: anti-slop endings, slop-prone shots avoided, visual check before supply | 3, 4, 5 |
| No renders without explicit agreement (the cast preview has its own OK) | 2, 5 |

**Deferred, recorded:**
- **Fixed TTS voice plus lip-sync** for long talking-head ads. It needs a voice and lip-sync provider.
- **Black Friday static banners.** They need the reference screenshot.
- **On-screen legal lines** (the FDA disclaimer). This needs an engine timeline field for a persistent small text line; the end card is too large for it.
- **Captions from the script's caption column** versus the full spoken line.
