---
description: Turn an Ellora ad brief into a rendered ad — script, shots, Ellora prompts, one approval gate, then every image and video (clips with their own spoken lines and natural sound) rendered in Ellora Studio and assembled by adengine.
argument-hint: <brief, e.g. "Complete Kit, broom-with-no-dustpan angle, 2 variants">
---

# /ad — Ellora

Brief: $ARGUMENTS

An attached document counts as the brief: a PDF, text or Markdown file (or any document whose text you can read) attached to the message that ran `/ad` is the brief, together with any words typed after `/ad`. Only when there is no typed brief and no attached document, ask the user for one (product, angle or audience, anything they care about, or a brief doc to attach) and stop.

## 0. Check the folder

Before any stage writes a file, check that the current working directory is the AdForge repo: it has a `pyproject.toml` that defines the `adengine` script, and this command's own file at `commands/ad.md`. Then run `uv run adengine --help` and check that it succeeds. Projects are written to `projects/<slug>/` in this folder, and every stage and the engine assume it. If either check fails, write nothing and stop: tell the user to start Claude in the AdForge repo (for example `cd <adforge> && claude --plugin-dir .`) and run `/ad` again.

Run these stages in order. Each stage is a skill in this plugin; follow it exactly and let it write its file before moving on. If a skill isn't listed in this session (for example `/ad` came from the project's `.claude/` folder rather than an installed plugin), read and follow its file instead: `skills/<name>/SKILL.md` in this repo, e.g. `skills/ad-strategist/SKILL.md`.

1. **ad-strategist** — brand file, slug, `brief.md`, `script-source.md` (supplied scripts), `plan.md`.
2. **script-writer** — `v1/script.md` (and `body/script.md` for hooks + shared body) with the claim check.
3. **cast-designer** — `cast.md`: one look phrase, voice phrase and reference prompt per person.
4. **shot-planner** — `v1/shots.md` (and `body/shots.md`).
5. **prompt-craft** — `v1/prompts.md` (and `body/prompts.md`).
   When `plan.md` has more than one variant, do stages 2–5 for v1 and the body yourself, then dispatch one **variant-writer** agent per other variant, in parallel, and wait for all of them (if no variant-writer agent type is available, dispatch a general-purpose agent per variant with the instructions in `agents/variant-writer.md`). The body is written once, never per variant. If a variant-writer replies `needs cast: <role> — …`, run **cast-designer** to add that person to `cast.md`, then dispatch that variant's writer again.
6. **ad-runner** — manifest and config, the cast preview (only with the user's OK), then **the gate: stop and wait for the user's approval**. Only after approval: the Ellora render loop, the report, and revisions.

If the user changes a person at the cast preview or the gate, update `cast.md`. When their role or name changes, first rename the role in the Speaker column of every `script.md` that uses it (the words of the lines stay the same; roles are how scripts, shots and prompts find people in `cast.md`), then redo stages 4–5 (shot-planner and prompt-craft) for every shot with that person. For a look or voice change, redo stage 5 alone. Re-validate before continuing.

Never call Ellora's `generate_image` or `generate_video` before the user agrees: the cast preview needs its own OK, everything else needs the gate.
