---
name: cast-designer
description: Stage 3 of /ad. Designs every on-screen person once — a look phrase, a voice phrase and a reference-image prompt — and writes projects/<slug>/cast.md, so every keyframe and clip shows and sounds like the same person.
---

# Cast designer (stage 3)

Input: `projects/<slug>/plan.md` ("Story and cast notes" and each variant's angle/hook), `projects/<slug>/script-source.md` (if any), every `script.md` written so far (the Speaker column), `projects/<slug>/brand/ellora.md`.
Output: `projects/<slug>/cast.md`.

AI images and videos drift: render the same description twice and you get two different people. The cure is one reference image per person, approved by the user, plus fixed wording reused everywhere.

## Who is in the cast

- Cover everyone who speaks, or may be shown on screen in any variant. Build the list from the Speaker columns of the scripts written so far, plus every person named or implied in `plan.md`'s "Story and cast notes" and in every variant's angle/hook in `plan.md` and `script-source.md`. Variant scripts are written later, by variant-writers, from this cast.
- Variant-writers may only use people already in cast.md; if a later stage needs a new person, add them here first.
- Off-camera narration is spoken by a cast member (usually the presenter) and uses their voice phrase. A narrator who is never on screen gets a voice-only entry (see below).
- Take who they are from the brief: its story and cast notes, how the script talks (a friend telling it straight, a mum at the kitchen table). Where the brief is silent, choose someone believable for the audience (the brand file's audience, roughly 28–55) and record each such choice under `Defaults chosen` so the gate shows it.
- Never a doctor, pharmacist or anyone in a white coat; no before/after bodies.
- If nobody appears on screen and there is no narration, write `No cast` and stop.

## Per person

- **id**: lowercase first name, e.g. `maya`. Node: `cast.<id>.ref`.
- **Role**: the role name the scripts use for this person (e.g. presenter, friend); shot-planner and prompt-craft look people up by role → id here. Roles are unique: two friends are `friend-1` and `friend-2`.
- **Look phrase**: one sentence that pins the visual identity — name, age, hair (length, colour, texture, how it's worn), skin tone, one or two distinctive details (earrings, glasses), and one outfit worn in every shot. Example: `Maya (the woman in the reference image: mid-thirties, warm brown skin, shoulder-length dark curly hair pulled half up, small gold hoop earrings, oversized cream knit sweater)`.
- **Voice phrase**: one noun phrase for every line they speak, on or off camera — pitch, age, accent, pace, attitude — with no name prefix. Example (example — pick the accent from the brief/audience): `a warm, low, unhurried American woman's voice, a little dry and knowing`.
- **Reference prompt**: the exact form is "Photoreal vertical 9:16 waist-up portrait of" + the name + the look phrase's description (without the parenthesis and the words "in the reference image") + "looking straight into the camera, neutral relaxed expression, plain soft-grey backdrop, soft even window light from the left." + "Natural skin texture, anatomically correct hands, no extra fingers, no text, no watermark." Worked example: `Photoreal vertical 9:16 waist-up portrait of Maya, a woman in her mid-thirties with warm brown skin, shoulder-length dark curly hair pulled half up, small gold hoop earrings and an oversized cream knit sweater, looking straight into the camera, neutral relaxed expression, plain soft-grey backdrop, soft even window light from the left. Natural skin texture, anatomically correct hands, no extra fingers, no text, no watermark.`

The look phrase and the voice phrase are copied **word for word** into every keyframe and clip prompt that person appears in. Never paraphrase them later; a changed word is a changed person. The look phrase and voice phrase themselves never contain markers or notes — they are copied into prompts.

Record every choice the brief did not make (age, skin tone, hair, outfit, accent, voice) on a separate `- Defaults chosen: <comma list>` line under the person, so the gate shows it.

## Voice-only narrator

A narrator who is never on screen gets this entry form instead: id, Role, Voice phrase, `Node: none (voice only)`. No look phrase, no reference prompt.

## Write `projects/<slug>/cast.md`

```markdown
# Cast

## maya — presenter
- Node: cast.maya.ref
- Role: <role from the scripts>
- Look phrase: <one sentence>
- Voice phrase: <one phrase>
- Reference prompt: <prompt>
- Defaults chosen: <list, or "none">
- Appears in: <shot ids, filled in by shot-planner>

## narrator — voice only
- Node: none (voice only)
- Role: <role from the scripts>
- Voice phrase: <one phrase>
```
