---
description: Turn an Ellora ad brief into a rendered ad — script, shots, Ellora prompts, one approval gate, then every image and video (clips with their own spoken lines and natural sound) rendered in Ellora Studio and assembled by adengine.
argument-hint: <brief, e.g. "Complete Kit, broom-with-no-dustpan angle, 2 variants">
---

# /ad — Ellora

Brief: $ARGUMENTS

If the brief is empty, ask the user for one (product, angle or audience, anything they care about) and stop.

Run these stages in order. Each stage is a skill in this plugin; follow it exactly and let it write its file before moving on.

1. **ad-strategist** — brand file, slug, `brief.md`, `script-source.md` (supplied scripts), `plan.md`.
2. **script-writer** — `v1/script.md` (and `body/script.md` for hooks + shared body) with the claim check.
3. **cast-designer** — `cast.md`: one look phrase, voice phrase and reference prompt per person.
4. **shot-planner** — `v1/shots.md` (and `body/shots.md`).
5. **prompt-craft** — `v1/prompts.md` (and `body/prompts.md`).
   When `plan.md` has more than one variant, do stages 2–5 for v1 and the body yourself, then dispatch one **variant-writer** agent per other variant, in parallel, and wait for all of them. The body is written once, never per variant. If a variant-writer replies `needs cast: <role> — …`, run **cast-designer** to add that person to `cast.md`, then dispatch that variant's writer again.
6. **ad-runner** — manifest and config, the cast preview (only with the user's OK), then **the gate: stop and wait for the user's approval**. Only after approval: the Ellora render loop, the report, and revisions.

If the user changes a person at the cast preview or the gate, update `cast.md`. When their role or name changes, first rename the role in the Speaker column of every `script.md` that uses it (the words of the lines stay the same; roles are how scripts, shots and prompts find people in `cast.md`), then redo stages 4–5 (shot-planner and prompt-craft) for every shot with that person. For a look or voice change, redo stage 5 alone. Re-validate before continuing.

Never call Ellora's `generate_image` or `generate_video` before the user agrees: the cast preview needs its own OK, everything else needs the gate.
