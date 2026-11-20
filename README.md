# AdForge

Paste a short-form ad brief, get back N ad variants — each as a review MP4 and an editable
CapCut draft. This repo is the rendering **engine** (`adengine`).

## Install (macOS or Linux)

```bash
bash install.sh
```

Or open this folder in Claude Code and say **"install this engine"** — Claude follows
[CLAUDE.md](CLAUDE.md) and runs the same script.

The script installs uv, ffmpeg and the `adengine` command, then runs `adengine doctor` to
check ffmpeg has every filter AdForge needs. Re-running it is safe.

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
