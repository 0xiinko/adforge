---
name: shot-planner
description: Stage 3 of /ad. Turns projects/<slug>/vN/script.md into vN/shots.md — one shot per beat, 4 or 5 seconds each, with framing, motion and which Ellora bottle (if any) is on screen.
---

# Shot planner (stage 3)

Input: `projects/<slug>/vN/script.md`, `projects/<slug>/plan.md`.
Output: `projects/<slug>/vN/shots.md`.

## Rules

- One shot per beat: `s01`, `s02`, … in beat order.
- Each shot is 4 or 5 seconds; the total is within the plan's length (default 20–25 s, plus the 2 s end card).
- Each shot is one continuous, simple action that a single image-to-video clip can show. No cuts inside a shot.
- Bottle shots: say which product is on screen — "Gut Cleanse (Step 1)", "Zeolite Drops (Step 2)", or both. A bottle must be upright and its label readable.
- Packshots use the house look from the brand file: seamless warm greige backdrop, one soft key from the upper left, soft shadow to the right, no props, no hands, bottle dead centre.
- People: ordinary, believable, the audience's age; never a doctor, pharmacist or anyone in a white coat; no before/after bodies.
- No on-screen text inside the shots; captions and the end card are added in assembly.

## Write `projects/<slug>/vN/shots.md`

```markdown
# Shots — vN

| Shot | Seconds | On screen | Framing | Camera / motion | Bottle | VO |
|---|---|---|---|---|---|---|
| s01 | 4 | ... | medium, eye level | slow push-in | none | <beat 1 VO> |
| s02 | 5 | ... | packshot, centred | slow orbit | Gut Cleanse (Step 1) | <beat 2 VO> |
| ... |

Total: <sum> s + 2 s end card.
```
