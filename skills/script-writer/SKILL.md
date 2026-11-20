---
name: script-writer
description: Stage 2 of /ad. Writes projects/<slug>/vN/script.md for one variant from plan.md and brand/ellora.md, including a claim check of every line against the Ellora ad-claim rules.
---

# Script writer (stage 2)

Input: `projects/<slug>/plan.md` (the variant's angle), `projects/<slug>/brand/ellora.md`.
Output: `projects/<slug>/vN/script.md`.

If the Ellora connector's `list_storyboards` returns any storyboards, read the one or two newest with `get_storyboard` and match their structure and tone. If there are none, the brand file is the only style source.

## Structure

- 5 beats, one per shot (or the plan's shot count).
- Beat 1 is the hook: it must land in the first 2 seconds and name a feeling the audience recognises (in their own words from the brand file: bloated by the afternoon, foggy, tests came back normal, crashed at week two).
- Middle beats argue the angle. The two-step argument (kill first, flush second; a broom with no dustpan) is the brand's strongest material.
- Last beat is the offer and CTA: product, price, the 30-day money-back guarantee.
- End card: short, e.g. "Complete Kit $49.99 · myellora.com".

## Lines

- One VO line per beat, **14 words or fewer**, spoken naturally.
- One on-screen caption per beat (may repeat the VO's key words; ≤ 6 words).
- Tone: plain, unembarrassed, a bit conspiratorial about what the industry leaves out. Not clinical. Not wellness-influencer.
- Music mood: one line (e.g. "warm, understated acoustic groove, no vocals").

## Claim check (Ellora)

Check every VO line, caption and the end card against the brand file's "do not write" list:

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

| Beat | VO (≤ 14 words) | Caption |
|---|---|---|
| 1 hook | ... | ... |
| 2 | ... | ... |
| 3 | ... | ... |
| 4 | ... | ... |
| 5 CTA | ... | ... |

- End card: ...
- Music mood: ...

## Claim check
Clean.
```

If the check finds anything, replace "Clean." with one row per hit and keep the original line in the table until the user decides at the gate:

```markdown
| Line | Rule it breaks | Compliant rewrite |
|---|---|---|
| "..." | names a condition | "..." |
```
