"""Thin async wrapper around the ffmpeg/ffprobe binaries. Always argument lists,
never a shell."""
from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from engine.config import AssemblyConfig
from engine.providers.base import ProviderError


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    width: int | None
    height: int | None
    has_video: bool
    has_audio: bool


def _float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


class FFmpeg:
    def __init__(self, config: AssemblyConfig | None = None):
        cfg = config or AssemblyConfig()
        self.ffmpeg = cfg.ffmpeg
        self.ffprobe = cfg.ffprobe
        self.font = cfg.font
        self.font_file = cfg.font_file

    def font_option(self) -> str:
        """drawtext font selector: an explicit file (macOS default) or a fontconfig family name."""
        return f"fontfile='{self.font_file}'" if self.font_file else f"font='{self.font}'"

    def available(self) -> bool:
        return shutil.which(self.ffmpeg) is not None and shutil.which(self.ffprobe) is not None

    async def _exec(self, args: list[str], cwd: Path | None) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                *args, cwd=cwd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            raise ProviderError(
                f"{args[0]} not found; install ffmpeg or set assembly.ffmpeg/ffprobe in config"
            ) from None
        out, err = await proc.communicate()
        if proc.returncode != 0:
            tail = err.decode(errors="replace").strip().splitlines()[-8:]
            raise ProviderError(f"{Path(args[0]).name} failed (exit {proc.returncode}): " + " | ".join(tail))
        return out.decode(errors="replace")

    async def run(self, args: list[str], cwd: Path | None = None) -> None:
        await self._exec([self.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args], cwd)

    async def probe(self, path: Path) -> MediaInfo:
        out = await self._exec([
            self.ffprobe, "-v", "error",
            "-show_entries", "format=duration:stream=codec_type,width,height",
            "-of", "json", str(path),
        ], None)
        data = json.loads(out or "{}")
        streams = data.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        return MediaInfo(
            duration=_float(data.get("format", {}).get("duration")),
            width=video.get("width") if video else None,
            height=video.get("height") if video else None,
            has_video=video is not None,
            has_audio=any(s.get("codec_type") == "audio" for s in streams),
        )
