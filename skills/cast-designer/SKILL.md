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
- **Voice phrase**: one phrase for every line they speak, on or off camera — pitch, age, accent, pace, attitude. Example: `Maya's voice: a warm, low, unhurried American woman's voice, a little dry and knowing`.
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
