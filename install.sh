#!/usr/bin/env bash
# AdForge engine installer — macOS (production) and Linux (development).
#
#   bash install.sh            # from a clone of this repo
#
# What it does (safe to re-run):
#   1. macOS: makes sure Homebrew exists (prints the official install command if not).
#   2. Installs uv (Python toolchain) if missing.
#   3. Installs ffmpeg if missing (macOS: brew; Linux: tells you the apt command).
#   4. Installs the `adengine` command from this checkout (editable, so `git pull` updates it).
#   5. Runs `adengine doctor`. On macOS, if the stock ffmpeg lacks required filters
#      (libass/freetype), it offers to switch to the homebrew-ffmpeg tap build.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OS="$(uname -s)"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

[ -f "$REPO_DIR/pyproject.toml" ] || die "run this from the adforge repo (pyproject.toml not found in $REPO_DIR)"

# --- 1. Homebrew (macOS) ------------------------------------------------------
if [ "$OS" = "Darwin" ]; then
  if ! have brew; then
    die "Homebrew is required on macOS. Install it first:
    /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"
then re-run: bash install.sh"
  fi
fi

# --- 2. uv --------------------------------------------------------------------
if ! have uv; then
  say "Installing uv"
  if [ "$OS" = "Darwin" ]; then
    brew install uv
  else
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  fi
fi
have uv || die "uv is still not on PATH; open a new terminal and re-run"
say "uv: $(uv --version)"

# --- 3. ffmpeg ----------------------------------------------------------------
if ! have ffmpeg || ! have ffprobe; then
  if [ "$OS" = "Darwin" ]; then
    say "Installing ffmpeg (Homebrew)"
    brew install ffmpeg
  else
    die "ffmpeg is missing. Install it, then re-run:
    sudo apt install -y ffmpeg fonts-dejavu-core"
  fi
fi
say "ffmpeg: $(ffmpeg -hide_banner -version | head -1)"

# --- 4. adengine ----------------------------------------------------------------
say "Installing the adengine command from $REPO_DIR"
uv tool install --force --python 3.12 --editable "$REPO_DIR"
export PATH="$HOME/.local/bin:$PATH"
have adengine || die "adengine not on PATH. Add this to your shell profile, then re-run:
    export PATH=\"\$HOME/.local/bin:\$PATH\""

# --- 5. doctor ----------------------------------------------------------------
say "Checking ffmpeg filters and fonts"
if adengine doctor; then
  say "AdForge engine installed. Try: adengine --help"
  exit 0
fi

if [ "$OS" = "Darwin" ]; then
  warn "The installed ffmpeg is missing filters AdForge needs (captions/text need libass + freetype)."
  if [ -t 0 ]; then
    read -r -p "Replace Homebrew's ffmpeg with the homebrew-ffmpeg tap build? [y/N] " reply
  else
    reply="n"
  fi
  if [[ "$reply" =~ ^[Yy]$ ]]; then
    brew uninstall --ignore-dependencies ffmpeg || true
    brew tap homebrew-ffmpeg/ffmpeg
    brew install homebrew-ffmpeg/ffmpeg/ffmpeg
    adengine doctor && { say "AdForge engine installed. Try: adengine --help"; exit 0; }
  fi
  die "ffmpeg still lacks required filters. See the MISSING lines above, install an ffmpeg
build with libass and freetype, then run: adengine doctor"
fi
die "adengine doctor failed; see the lines above"
