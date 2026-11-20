---
name: prompt-craft
description: Stage 4 of /ad. Writes projects/<slug>/vN/prompts.md — an Ellora image prompt for each shot's keyframe and a clip prompt (motion plus the spoken line) for its clip — using the brand file's exact label wording so Ellora attaches the right bottle reference.
---

# Prompt craft (stage 4)

Input: `projects/<slug>/vN/shots.md`, `projects/<slug>/brand/ellora.md`.
Output: `projects/<slug>/vN/prompts.md`.

## Models

Call the Ellora connector's `list_models` once per brief and confirm the defaults are still offered:
- image: `nano-banana-pro` (legible label text, takes reference images);
- video: `kling-3.0/video` (takes a first frame, 9:16, 3–15 s).

If the user named other models, use those. Check every shot's duration and the 9:16 aspect are within the chosen video model's options; if not, pick the nearest allowed duration and update `shots.md`.

Use `search_prompts` with a few key words of each shot (e.g. "packshot greige", "dropper water") and reuse phrasing the team already uses. Apply every rule in the brand file's House rules section.

## Keyframe (image) prompts

- Start with "Photoreal vertical 9:16" and describe one frame: subject, setting, light, mood.
- **Bottle shots:** name the product exactly — "Ellora Gut Cleanse (Step 1)" or "Ellora Zeolite Drops (Step 2)" — then describe the bottle and label with the brand file's wording: the squat 30 mL amber-brown glass dropper bottle, round shoulders, matte black ribbed child-resistant collar, smooth black rubber dropper bulb; the label colour, the white "Ellora" and product name, the small-capitals line, the line drawing, the "30 SERVINGS" circle. Naming the product attaches Ellora's reference picture automatically; the wording makes sure the label is drawn right. Both bottles are the same physical object — only the label differs.
- Every bottle shown keeps "Dietary Supplement" legible.
- Packshots: the house look (seamless warm greige backdrop, soft key from the upper left, soft shadow to the right, no props, no hands, dead centre).
- Never: text overlays, doctors or pharmacists, white coats, before/after bodies, named conditions.
- One image per keyframe.

## Clip prompts (motion and audio)

- Describe the movement over the shot's seconds: what moves, how the camera moves, what stays still. The keyframe is the first frame, so do not re-describe the scene.
- Keep labels sharp and readable in bottle shots ("the label stays sharp and readable").
- Clips render with their own audio. Every clip prompt contains:
  - the shot's exact spoken line from `shots.md`, in double quotes, word for word;
  - who speaks it: the on-camera person ("she looks into the camera and says, lips in sync: ...") or, when nobody is on screen, a voice ("a warm woman's voice, off camera, says: ..."); keep the same voice across the variant;
  - the delivery, in the brand's tone (plain, unembarrassed, a bit conspiratorial; never clinical or influencer);
  - "Natural ambient sound, no music."

## Write `projects/<slug>/vN/prompts.md`

```markdown
# Prompts — vN

- Image model: nano-banana-pro
- Video model: kling-3.0/video
- Aspect: 9:16

## s01 (4 s)
**Keyframe:** <image prompt>
**Clip:** <motion> <who> says, <delivery>: "<spoken line>" Natural ambient sound, no music.

## s02 (5 s)
...
```

See `skills/ad-runner/example-manifest.json` for five complete, approved-style examples.
