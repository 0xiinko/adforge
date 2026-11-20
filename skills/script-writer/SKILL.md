---
name: script-writer
description: Stage 2 of /ad. Writes projects/<slug>/vN/script.md for one variant from plan.md and brand/ellora.md, including a claim check of every line against the Ellora ad-claim rules.
---

# Script writer (stage 2)

Input: `projects/<slug>/plan.md` (the variant's angle), `projects/<slug>/brand/ellora.md`, and `projects/<slug>/script-source.md` when the plan says **Script source: supplied**.
Output: `projects/<slug>/vN/script.md`, plus `projects/<slug>/body/script.md` once when the plan says **hooks + shared body**.

If the Ellora connector's `list_storyboards` returns any storyboards, read the one or two newest with `get_storyboard` and match their structure and tone. If there are none, the brand file is the only style source.

## Supplied scripts (Script source: supplied)

The user's copy is the script. Split it into beats; never paraphrase, reorder or "improve" it.

- Split at sentence or clause boundaries into spoken lines that obey the line rules below (≤ 14 words, ≤ ~2.6 words per second of the shot). Keep the words exactly, word for word, including the user's grammar and voice; only the line breaks are yours.
- With **hooks + shared body**: `vN/script.md` holds only hook N's beats; `body/script.md` holds the body's beats, written once. The ad for variant N is its hook followed by the body.
- Long copy makes long ads (a 60-second script is ~15 shots). Say so in the plan's assumptions; do not cut copy to fit a length default.
- The claim check below still applies to every line. A hit keeps the original line in the table and adds a compliant rewrite; the user decides at the gate. Nothing with an open hit renders.

When the plan says **Script source: written**, write the script yourself following Structure and Lines.

## Structure

- 5 beats, one per shot (or the plan's shot count).
- Beat 1 is the hook: it must land in the first 2 seconds and name a feeling the audience recognises (in their own words from the brand file: bloated by the afternoon, foggy, tests came back normal, crashed at week two).
- Middle beats argue the angle. The two-step argument (kill first, flush second; a broom with no dustpan) is the brand's strongest material.
- Last beat is the offer and CTA: product, price, the 30-day money-back guarantee.
- End card: short, e.g. "Complete Kit $49.99 · myellora.com".

## Lines

- One spoken line per beat, said inside that shot's clip by a cast member: on camera (lip-synced) or off camera (their voice over a shot without them). Speakers are role names (`presenter`, `friend`), not cast ids: cast-designer maps each role to a cast id in `cast.md`. Write the speaker as `role (on camera)` or `role (off camera)`. Ellora renders the line with the clip, so there is no separate voiceover. **14 words or fewer**, spoken naturally, and short enough for its shot: at most ~2.6 words per second (≤ 10 words for a 4 s shot, ≤ 13 for 5 s).
- One on-screen caption per beat (may repeat the line's key words; ≤ 6 words).
- Tone: plain, unembarrassed, a bit conspiratorial about what the industry leaves out. Not clinical. Not wellness-influencer.
- No music: the clips carry natural sound only (music can be added later in CapCut).

## Claim check (Ellora)

Check every spoken line, caption and the end card against the brand file's "do not write" list:

- cures, treats or prevents any disease;
- naming herpes, candida as an infection, or any named condition;
- before-and-after body claims;
- "clinically proven";
- a doctor or pharmacist recommending it;
- a testimonial stating a diagnosis was resolved.

Safe ground: digestive comfort, bloating, regularity, energy, gut health support, detox support, feeling like yourself again. Frame results as what a customer noticed, not what the product does. A testimonial-style line needs an on-screen results disclaimer ("Individual results vary").

## Write `projects/<slug>/vN/script.md`

```markdown
# Script — vN (<angle>)

| Beat | Spoken line (≤ 14 words) | Speaker | Caption |
|---|---|---|---|
| 1 hook | ... | presenter (on camera) | ... |
| 2 | ... | presenter (off camera) | ... |
| 3 | ... | ... | ... |
| 4 | ... | ... | ... |
| 5 CTA | ... | ... | ... |

- End card: ...

## Claim check
Clean.
```

For **hooks + shared body**, write `body/script.md` with the same table (beats `b1`, `b2`, …) and no end card; each `vN/script.md` has only its hook beats and the end card.

If the check finds anything, replace "Clean." with one row per hit and keep the original line in the table until the user decides at the gate:

```markdown
| Line | Rule it breaks | Compliant rewrite |
|---|---|---|
| "..." | names a condition | "..." |
```
