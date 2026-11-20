---
name: shot-planner
description: Stage 3 of /ad. Turns projects/<slug>/vN/script.md into vN/shots.md — one shot per beat, 4 or 5 seconds each, with framing, motion and which Ellora bottle (if any) is on screen.
---

# Shot planner (stage 3)

Input: `projects/<slug>/vN/script.md` (and `body/script.md`), `projects/<slug>/plan.md`, `projects/<slug>/cast.md`.
Output: `projects/<slug>/vN/shots.md`, plus `projects/<slug>/body/shots.md` once for hooks + shared body; and the "Appears in" lines of `cast.md`.

## Rules

- One shot per beat. Hook or full-variant shots are `vN.s01`, `vN.s02`, …; shared body shots are `body.s01`, `body.s02`, … (written once, used by every variant).
- Each shot lists its **Cast**: the cast ids on screen (or `—`). A shot whose line is spoken off camera lists `—` on screen and names the voice in the Spoken line column. Then fill in each person's "Appears in" line in `cast.md`.
- Keep each person in one setting and one outfit across the ad unless the story moves them; a new setting is a new risk of drift.
- Prefer shots that AI video renders cleanly: one person, one simple action, steady or slowly moving camera, hands still or out of frame; avoid fiddly hand actions, crowds, fast motion, and text on objects other than the product labels.
- Each shot is 4 or 5 seconds; the total is within the plan's length (default 20–25 s, plus the 2 s end card).
- Each shot is one continuous, simple action that a single image-to-video clip can show. No cuts inside a shot.
- Each shot carries its beat's spoken line, said inside the clip (lip-synced when the speaker is on screen). The shot must be long enough for it: at most ~2.6 words per second (≤ 10 words in 4 s, ≤ 13 in 5 s); if a line doesn't fit, make the shot 5 s or ask script-writer to shorten it. Lines stay ≤ 14 words and keep the script's claim check.
- Bottle shots: say which product is on screen — "Gut Cleanse (Step 1)", "Zeolite Drops (Step 2)", or both. A bottle must be upright and its label readable.
- Packshots use the house look from the brand file: seamless warm greige backdrop, one soft key from the upper left, soft shadow to the right, no props, no hands, bottle dead centre.
- People: ordinary, believable, the audience's age; never a doctor, pharmacist or anyone in a white coat; no before/after bodies.
- No on-screen text inside the shots; captions and the end card are added in assembly.

## Write `projects/<slug>/vN/shots.md`

```markdown
# Shots — vN

| Shot | Seconds | On screen | Cast | Framing | Camera / motion | Bottle | Spoken line (speaker) |
|---|---|---|---|---|---|---|---|
| v1.s01 | 4 | ... | maya | medium, eye level | slow push-in | none | <line> (maya, on camera) |
| body.s03 | 5 | ... | — | packshot, centred | slow orbit | Gut Cleanse (Step 1) | <line> (maya, off camera) |
| ... |

Total: <sum> s + 2 s end card.
```
