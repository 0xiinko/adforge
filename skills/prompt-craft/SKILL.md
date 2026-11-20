---
name: prompt-craft
description: Stage 4 of /ad. Writes projects/<slug>/vN/prompts.md — an Ellora image prompt for each shot's keyframe and a clip prompt (motion plus the spoken line) for its clip — using the brand file's exact label wording so Ellora attaches the right bottle reference.
---

# Prompt craft (stage 4)

Input: `projects/<slug>/vN/shots.md` (and `body/shots.md`), `projects/<slug>/cast.md`, `projects/<slug>/brand/ellora.md`.
Output: `projects/<slug>/vN/prompts.md`, plus `projects/<slug>/body/prompts.md` once for hooks + shared body.

## Models

Call the Ellora connector's `list_models` once per brief and confirm the defaults are still offered:
- image: `nano-banana-pro` (legible label text, takes reference images);
- video: `kling-3.0/video` (takes a first frame, 9:16, 3–15 s).

If the user named other models, use those. Check every shot's duration and the 9:16 aspect are within the chosen video model's options; if not, pick the nearest allowed duration and update `shots.md`.

Use `search_prompts` with a few key words of each shot (e.g. "packshot greige", "dropper water") and reuse phrasing the team already uses. Apply every rule in the brand file's House rules section.

## Cast consistency

- Every keyframe with a cast member on screen: write `Reference: cast.<id>.ref` above the prompt (the manifest attaches that image), and put the person's **look phrase** from `cast.md` in the prompt, word for word. Never re-describe them in other words, and never change the outfit or hair unless `shots.md` says the story does.
- Every clip prompt with a spoken line: use the speaker's **voice phrase** from `cast.md`, word for word, whether they are on camera ("she looks into the camera and says, lips in sync, in <voice phrase>: …") or off camera ("<voice phrase>, off camera, says: …").
- Keep one look for the whole ad: the same light, lens and colour words in every keyframe of a setting.
- A voice-only cast member (no reference node) is never shown on screen; their lines are always off camera, using their voice phrase.

## Keyframe (image) prompts

- Start with "Photoreal vertical 9:16" and describe one frame: subject, setting, light, mood.
- **Bottle shots:** name the product exactly — "Ellora Gut Cleanse (Step 1)" or "Ellora Zeolite Drops (Step 2)" — then describe the bottle and label with the brand file's wording: the squat 30 mL amber-brown glass dropper bottle, round shoulders, matte black ribbed child-resistant collar, smooth black rubber dropper bulb; the label colour, the white "Ellora" and product name, the small-capitals line, the line drawing, the "30 SERVINGS" circle. Naming the product attaches Ellora's reference picture automatically; the wording makes sure the label is drawn right. Both bottles are the same physical object — only the label differs.
- Every bottle shown keeps "Dietary Supplement" legible.
- Packshots: the house look (seamless warm greige backdrop, soft key from the upper left, soft shadow to the right, no props, no hands, dead centre).
- Never: text overlays, doctors or pharmacists, white coats, before/after bodies, named conditions.
- One image per keyframe.
- End every keyframe prompt with exactly: `Natural skin texture, anatomically correct hands, no extra fingers, no text, no watermark.`

## Clip prompts (motion and audio)

- Describe the movement over the shot's seconds: what moves, how the camera moves, what stays still. The keyframe is the first frame, so do not re-describe the scene.
- Keep labels sharp and readable in bottle shots ("the label stays sharp and readable").
- Clips render with their own audio. Every clip prompt contains:
  - the shot's exact spoken line from `shots.md`, in double quotes, word for word;
  - who speaks it: the on-camera person ("she looks into the camera and says, lips in sync: ...") or, when nobody is on screen, a voice ("a warm woman's voice, off camera, says: ..."); keep the same voice across the variant;
  - the delivery, in the brand's tone (plain, unembarrassed, a bit conspiratorial; never clinical or influencer);
  - "Natural ambient sound, no music."
- Every clip prompt contains exactly: `Stable face and hands, no morphing or warping.` Keep motion small and continuous; never ask for hands to do fine work (opening caps, counting drops) in close-up.

## Write `projects/<slug>/vN/prompts.md`

```markdown
# Prompts — vN

- Image model: nano-banana-pro
- Video model: kling-3.0/video
- Aspect: 9:16

## v1.s01 (4 s)
**Reference:** cast.maya.ref  ← or "none"
**Keyframe:** <image prompt with the look phrase> Natural skin texture, anatomically correct hands, no extra fingers, no text, no watermark.
**Clip:** <motion> she looks into the camera and says, lips in sync, in <voice phrase>: "<spoken line>" Stable face and hands, no morphing or warping. Natural ambient sound, no music.

## v1.s02 (5 s)
...
```

For hooks + shared body, body shots go in body/prompts.md (written once) with the same layout.

See `skills/ad-runner/example-manifest.json` for five complete, approved-style examples.
