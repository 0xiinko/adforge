---
description: Turn an Ellora ad brief into a rendered ad — script, shots, Ellora prompts, one approval gate, then every image and video (clips with their own spoken lines and natural sound) rendered in Ellora Studio and assembled by adengine.
argument-hint: <brief, e.g. "Complete Kit, broom-with-no-dustpan angle, 2 variants">
---

# /ad — Ellora

Brief: $ARGUMENTS

If the brief is empty, ask the user for one (product, angle or audience, anything they care about) and stop.

Run these stages in order. Each stage is a skill in this plugin; follow it exactly and let it write its file before moving on.

1. **ad-strategist** — brand file, slug, `brief.md`, `plan.md`.
2. **script-writer** — `v1/script.md` with the claim check.
3. **shot-planner** — `v1/shots.md`.
4. **prompt-craft** — `v1/prompts.md`.
   When `plan.md` has more than one variant, do stages 2–4 for v1 yourself and dispatch one **variant-writer** agent per other variant, in parallel, then wait for all of them.
5. **ad-runner** — manifest and config, then **the gate: stop and wait for the user's approval**. Only after approval: the Ellora render loop, the report, and revisions.

Never call Ellora's `generate_image` or `generate_video` before the user approves the gate.
