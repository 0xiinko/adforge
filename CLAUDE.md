# AdForge — instructions for Claude

AdForge turns a short-form ad brief into rendered ad variants (preview MP4 + CapCut draft).
This repo currently contains the **engine** (`adengine` CLI, Python package `engine/`).
The Claude plugin "brain" and the MCP server come in later plans; for now Claude drives
the engine through the `adengine` CLI.

## "Install the engine"

When the user asks to install or set up AdForge / the engine:

1. Run `bash install.sh` from the repo root. It is idempotent and installs uv, ffmpeg
   (Homebrew on macOS) and the `adengine` command, then runs `adengine doctor`.
2. If it stops asking for Homebrew or `sudo apt install …`, show the user that exact
   command (it needs their password) and re-run `bash install.sh` afterwards.
3. If `adengine doctor` reports `MISSING` filters on macOS, the script offers to switch to
   the homebrew-ffmpeg tap build; that prompt is interactive, so ask the user to run
   `bash install.sh` in their own terminal and answer it.
4. Done when `adengine doctor` exits 0. Tell the user: `adengine --help`.

## Using the engine

- A project is a folder `projects/<slug>/` containing `manifest.json` (and optionally
  `config.yaml`; start from `config.example.yaml`).
- `adengine validate|dry-run|estimate|run|status|revise|rollback|doctor <project>`.
- Outputs per variant: `vN/timeline.json`, `vN/preview.mp4`, `vN/capcut_draft/`.
- To drop drafts straight into CapCut on a Mac, set in the project's `config.yaml`:
  `capcut: {drafts_dir: "~/Movies/CapCut/User Data/Projects/com.lveditor.draft"}`.

## Developing

- Tests: `uv run pytest -q -W error` (ffmpeg must be installed; nothing should skip).
- Design spec and plans: `docs/superpowers/specs/`, `docs/superpowers/plans/`.
