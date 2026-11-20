# AdForge — instructions for Claude

AdForge turns a short-form ad brief into rendered ad variants (preview MP4 + CapCut draft).
This repo holds two parts:

- the **engine**: the `adengine` CLI (Python package `engine/`), which runs the manifest,
  assembles timelines, previews and CapCut drafts;
- the **Claude Code plugin** `adforge`: the `/ad` command, its stage skills (`skills/`) and
  the `variant-writer` agent. For Ellora Studio, `/ad` renders every image and video in
  Ellora and hands the files to the engine with `adengine supply`.

## "Install the engine" / "install AdForge"

When the user asks to install or set up AdForge, the engine or the plugin:

1. Run `bash install.sh` from the repo root. It is idempotent: it installs uv, ffmpeg
   (Homebrew on macOS) and the `adengine` command, installs or updates the `adforge`
   plugin in Claude Code (user scope, from this checkout), then runs `adengine doctor`.
2. If it stops asking for Homebrew or `sudo apt install …`, show the user that exact
   command (it needs their password) and re-run `bash install.sh` afterwards.
3. If `adengine doctor` reports `MISSING` filters on macOS, the script offers to switch to
   the homebrew-ffmpeg tap build; that prompt is interactive, so ask the user to run
   `bash install.sh` in their own terminal and answer it.
4. Done when the script prints "AdForge engine installed". Then tell the user to:
   restart Claude Code, make sure the **Ellora Studio** connector is enabled in their
   claude.ai connector settings, and run `/ad <brief>`.

## Using the engine directly

- A project is a folder `projects/<slug>/` containing `manifest.json` (and optionally
  `config.yaml`; start from `config.example.yaml`).
- `adengine validate|dry-run|estimate|run|status|revise|rollback|external|supply|doctor`.
- Outputs per variant: `vN/timeline.json`, `vN/preview.mp4`, `vN/capcut_draft/`.
- To drop drafts straight into CapCut on a Mac, set in the project's `config.yaml`:
  `capcut: {drafts_dir: "~/Movies/CapCut/User Data/Projects/com.lveditor.draft"}`.

## Developing

- Tests: `uv run pytest -q -W error` (ffmpeg must be installed; nothing should skip).
- Design specs and plans: `docs/superpowers/specs/`, `docs/superpowers/plans/`.
