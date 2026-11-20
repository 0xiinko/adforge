# AdForge `/ad` for Ellora — Design Spec

**Date:** 2026-11-20
**Status:** Approved in brainstorming, pending written-spec review
**Branch:** `feat/ellora`
**Extends:** `2026-11-20-adforge-design.md` (§2, §3, §5 brain flow) and `2026-11-20-ellora-integration-design.md` (§2 brain side, §4 run loop)

## 1. Goal

Typing `/ad <brief>` in Claude Code takes an Ellora ad from brief to rendered assets with one human gate:
brief → Ellora brand context → script and shot list → Ellora prompts → **gate** → manifest → `adengine` run, with Claude rendering every image and video in Ellora Studio → preview and CapCut draft paths reported.

This is the first piece of the AdForge "brain" (main spec build order step 6), scoped to the Ellora brand.

### Non-goals (this spec)
- Other brands. The skills are written so a second brand can be added later (brand-specific steps are marked "Ellora:"), but only Ellora is supported now.
- Real TTS, SFX or music. Those nodes route to `mock` until the real providers land (main spec build order step 3).
- Creators, lip-sync, the vision-judge QC, the MCP server.
- Real preview/CapCut output. That depends on `feat/assembly` being merged and its assembly providers registered; until then the engine's `mock` assembly writes placeholders. `/ad` works unchanged either way.

## 2. Decisions

| Decision | Choice |
|---|---|
| Packaging | Claude Code plugin at the repo root: `.claude-plugin/plugin.json`, `commands/ad.md`, `skills/`, `agents/`. Loaded with `claude --plugin-dir <adforge repo>` (or a marketplace later). |
| Defaults | 1 variant, 5 shots of 4–5 s, 20–25 s total, 9:16, Meta/TikTok. Product: Complete Kit ($49.99) unless the brief names another. More variants only when the brief asks (e.g. "3 variants"). |
| Renders | Every keyframe (image) and clip (video) renders in Ellora (`provider: ellora`). VO, SFX and music are `mock`. |
| Product reference | No separate `refs.product_hero` node. Ellora attaches the right bottle reference automatically when a prompt names the product with its trigger words (brand context lists them), so keyframes have no `@ref` inputs. |
| Gate | One. It shows the script, the claim check, the shot list with prompts, and the full render list. Approval covers exactly those renders and their downloads. |
| Engine access | The brain runs the `adengine` CLI through Bash (the MCP server does not exist yet). |

## 3. Plugin layout

```
.claude-plugin/plugin.json          # name "adforge", version, description
commands/ad.md                      # /ad <brief>: the orchestrator; follows the five skills in order
skills/
  ad-strategist/SKILL.md            # brief → plan.md (brand file, product, audience, offer, defaults, angles)
  script-writer/SKILL.md            # hook / beats / CTA, VO lines, captions, Ellora claim rules
  shot-planner/SKILL.md             # shot list: 5 × 4–5 s, framing, motion, which shots show a bottle
  prompt-craft/SKILL.md             # Ellora image + motion prompts, label wording, model choice
  ad-runner/SKILL.md                # manifest writing, gate, render loop, revisions, final report
  ad-runner/example-manifest.json   # a complete one-variant, 5-shot manifest; the shape /ad writes
agents/variant-writer.md            # one subagent per variant when the brief asks for > 1
```

The five skills each own one stage and one output file (§4), so a stage can be redone without redoing the others. `commands/ad.md` is short: it names the stages, their order, and the stop at the gate.

## 4. Flow and files

All files live in `projects/<slug>/` (slug from the product and angle, e.g. `complete-kit-dustpan`). The repo root is the engine's working directory; the command checks `adengine` is runnable (`uv run adengine --help`) before starting.

| Stage | Skill | Reads | Writes |
|---|---|---|---|
| 1. Strategy | ad-strategist | the brief; Ellora `get_brand_context`, `get_house_rules` | `brand/ellora.md` (both verbatim, with the date), `brief.md`, `plan.md` |
| 2. Script | script-writer (or `variant-writer` × N) | `plan.md`, `brand/ellora.md`; `list_storyboards` / `get_storyboard` when any exist | `v1/script.md` |
| 3. Shots | shot-planner | `v1/script.md` | `v1/shots.md` |
| 4. Prompts | prompt-craft | `v1/shots.md`, `brand/ellora.md`; Ellora `list_models`, `search_prompts` | `v1/prompts.md` |
| 5. Gate → run | ad-runner | all of the above | `manifest.json`, `config.yaml`, `report.md` |

**`plan.md`** lists: product and price, audience, offer, platform, length, aspect, variant count, shot count, and the angle for each variant (one line each). Every value the brief did not state is marked *(default)*.

**Angles (Ellora):** picked from the brand's strongest material — broom-without-dustpan / two-step argument, week-two die-off crash, "tests came back normal", great-grandmother remedy done properly, three-failed-cleanses price arithmetic. With N > 1, each variant gets a different angle.

**`v1/script.md`:** hook (first 2 s), beats, CTA; VO lines (one per shot, ≤ 14 words each); on-screen caption per shot; end card text; music mood. Tone per brand context: plain, unembarrassed, slightly conspiratorial, not clinical, not influencer.

**`v1/shots.md`:** for each shot `s01`–`s05`: duration (4 or 5 s), what is on screen, framing, camera motion, whether a bottle appears and which product, and the matching VO line.

**`v1/prompts.md`:** per shot, the keyframe image prompt and the clip motion prompt, plus the chosen Ellora image and video model IDs, aspect `9:16`, and clip duration within the video model's range (from `list_models`).

### Prompt rules (prompt-craft, Ellora)
- A shot with a bottle names the product ("Ellora Gut Cleanse (Step 1)" / "Ellora Zeolite Drops (Step 2)") and describes the label with the brand file's exact wording, so the reference image is attached and the label is drawn right. Both bottles are the same physical object; only the label differs.
- Packshots use the house packshot look from the brand file.
- "Dietary Supplement" stays legible on any bottle shown.
- No doctor/pharmacist characters, no before/after bodies, no named conditions on screen.
- Apply every rule from `get_house_rules` when any exist; use `search_prompts` for phrasing already used.
- One image per keyframe (Ellora returns one; the engine requires `n` absent or 1).

### Claim check (script-writer writes, ad-runner shows at the gate)
Every VO line, caption and end-card string is checked against the brand file's "DO NOT WRITE" list (cure/treat/prevent, named conditions incl. candida as an infection, before/after body claims, "clinically proven", doctor/pharmacist endorsement, testimonial stating a resolved diagnosis). Each hit is listed with the line, the rule, and a compliant rewrite. A testimonial-style line carries a results disclaimer on screen. The gate cannot be approved while a hit is unresolved: the user accepts the rewrite or edits the line.

## 5. The gate

The gate message shows, in this order:
1. Assumptions (every *(default)* from `plan.md`).
2. The script per variant: hook, VO lines, captions, end card.
3. Claim check: "clean", or the list of hits with rewrites.
4. Shot list with each keyframe and motion prompt.
5. Render list: per variant 5 Ellora images and 5 Ellora videos, the model IDs, and a reminder that renders spend the user's Ellora credits and land in their Ellora library.

The user can approve, edit lines or shots, change the angle, drop or add variants, or ask for new prompts; the runner loops back to the affected stage and shows the gate again. Approval is the single confirmation for exactly the listed renders and for downloading their results into the project. Any render not on the approved list (a revision, an added shot) is confirmed separately, per Ellora's rule to confirm before more than one render and before any video.

## 6. Manifest

ad-runner writes `manifest.json` following `skills/ad-runner/example-manifest.json` (same node ids, types and input shapes; its own prompts, text and durations), and `config.yaml`:

```yaml
external_providers: [ellora]
routing:
  image: {provider: ellora, model: <image modelId from prompts.md>}
  video: {provider: ellora, model: <video modelId from prompts.md>}
```

Per variant `vN`:

| Node | Type | Inputs |
|---|---|---|
| `vN.sXX.keyframe` | image | `aspect: "9:16"`; prompt = keyframe prompt; no refs, no `n` |
| `vN.sXX.clip` | video | `first_frame: "@vN.sXX.keyframe"`, `duration`, `aspect: "9:16"`; prompt = motion prompt |
| `vN.vo.lXX` | tts (mock) | `text`, `voice: "narrator"` |
| `vN.music.bed` | music (mock) | prompt = music mood, `duration` = total length |
| `vN.timeline` | timeline | `aspect`, `shots: [{clip, duration, fallback: keyframe}]`, `vo: [{audio, text}]`, `music: {audio}`, `end_card: {text, duration: 2}`, `captions: true` |
| `vN.preview`, `vN.capcut_draft` | assembly | `timeline: "@vN.timeline"` |

`adengine validate` must print `OK` before the gate's render list is final; any error is fixed in the manifest (never by editing engine code) and validation re-run.

## 7. Render loop

After approval (ellora-integration spec §4, with these specifics):
1. `adengine run projects/<slug>`. Exit `3` → continue; `0` → done; `1` → report what needs attention.
2. `adengine external projects/<slug> --json`.
3. Images: `generate_image` per awaiting keyframe (prompt, `modelId`, `aspectRatio`), independent ones in parallel. Videos: `generate_video` with `firstFrameUrl` = the keyframe's `external_inputs.first_frame`, then `check_generation` (`wait: true`) until done.
4. Download each result from the link `check_generation` returns into `projects/<slug>/.tmp/ellora/` and `adengine supply <project> <node> <file> --ref <Ellora path> --id <generation id> --fingerprint <fp>`. Supplies may run in parallel (the engine locks state).
5. Failure → `supply --failed "<message>"`; the next run retries it once; a second failure stops the loop and is reported. Refusal → `supply --refused`, one prompt rewrite through `adengine revise` (a re-render of the same shot is covered by the gate approval); a second refusal is reported.
6. Repeat from 1.

Expected passes per variant: keyframes, then clips, then assembly finishes.

## 8. Report and revisions

`report.md` and the final message list: preview and CapCut draft paths per variant, the Ellora generation IDs used, anything `needs_review` or `failed` with its reason, and what is still mock (audio, and assembly while `feat/assembly` is unmerged).

After the report, natural-language feedback ("shot 3 is too dark") becomes `adengine revise projects/<slug> v1.s03.keyframe --json '{"prompt": "..."}' --no-run`, a confirmation of the new render(s), then the render loop again. The engine re-renders only that keyframe, its clip, and the assembly.

## 9. Testing

- **Example-manifest test (CI, zero cost):** a test copies `skills/ad-runner/example-manifest.json` (one variant, 5 shots, sample Ellora prompts) into a temp project with the Ellora `config.yaml` from §6, validates it with the Ellora config and drives the full mock supply loop to exit 0, checking keyframes have no `@ref` inputs and every clip's `external_inputs.first_frame` is its keyframe's ref.
- **Plugin structure test:** `plugin.json` parses; every skill has `SKILL.md` with `name` and `description` frontmatter; `commands/ad.md` names all five skills.
- **Manual end-to-end trial (spends credits):** one real `/ad` run with the user, approved at the gate.
