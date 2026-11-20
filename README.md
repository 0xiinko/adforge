# AdForge

Paste a short-form ad brief, get back N ad variants — each as a review MP4 and an editable
CapCut draft. This repo is the rendering **engine** (`adengine`).

## Install (macOS or Linux)

```bash
bash install.sh
```

Or open this folder in Claude Code and say **"install this engine"** — Claude follows
[CLAUDE.md](CLAUDE.md) and runs the same script.

The script installs uv, ffmpeg, the `adengine` command and the `adforge` Claude Code plugin
(`/ad`), then runs `adengine doctor` to check ffmpeg has every filter AdForge needs.
Re-running it is safe and updates the plugin. Afterwards restart Claude Code, enable the
Ellora Studio connector in claude.ai, and run `/ad <brief>`.

## Use /ad in the Claude desktop app (no terminal)

1. Get this repo (GitHub Desktop → Clone `0xiinko/adforge`, branch `feat/ellora`).
2. In the Claude app, open the **Code** tab and choose this folder as the project.
3. Say **"install this engine"** once; approve the commands Claude runs.
4. Enable the **Ellora Studio** connector in your Claude settings.
5. Type `/ad <brief>` (or attach a brief PDF and type `/ad`).

`/ad` loads straight from this folder's `.claude/` (it links to `commands/`, `skills/` and
`agents/`), so it works in any Claude Code session opened here, even without the plugin installed.

## Quick try

```bash
mkdir -p projects/demo
uv run python -c "import json; from tests.helpers import make_manifest; print(json.dumps(make_manifest(), indent=2))" > projects/demo/manifest.json
cp config.example.yaml projects/demo/config.yaml
adengine run projects/demo
open projects/demo/v1/preview.mp4    # macOS
```

The example config uses free mock providers (placeholder media). Real image/video/voice
providers arrive in a later plan.
