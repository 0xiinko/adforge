"""Mock provider that emits real, tiny media files via ffmpeg, so assembly can be
exercised end to end without paid APIs. Colours are derived from the node id."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from engine.assembly.ffmpeg import FFmpeg
from engine.providers.base import CallContext, Provider, ProviderError

ASPECT_SIZES: dict[str, tuple[int, int]] = {
    "9:16": (270, 480), "16:9": (480, 270), "1:1": (360, 360), "4:5": (320, 400),
}
_SIZE = re.compile(r"^(\d+)x(\d+)$")


def _color(key: str) -> str:
    return "0x" + hashlib.sha256(key.encode()).hexdigest()[:6]


class MediaMockProvider(Provider):
    name = "mock_media"

    def __init__(self, ffmpeg: FFmpeg | None = None):
        self.ff = ffmpeg or FFmpeg()

    def _label(self, ctx: CallContext, text: str, size: int) -> str:
        (ctx.work_dir / "label.txt").write_text(text)
        return (f"drawtext={self.ff.font_option()}:textfile=label.txt:expansion=none:fontcolor=white"
                f":fontsize={size}:x=(w-text_w)/2:y=(h-text_h)/2")

    async def generate_image(self, ctx, prompt, refs, size, n):
        m = _SIZE.match(size)
        if not m:
            raise ProviderError(f"{ctx.node_id}: image size must look like 1024x1792, got {size!r}")
        width, height = int(m.group(1)), int(m.group(2))
        paths = []
        for i in range(n):
            name = f"candidate_{i}.png"
            await self.ff.run([
                "-f", "lavfi", "-i", f"color=c={_color(ctx.node_id + str(i))}:s={width}x{height}",
                "-frames:v", "1", "-vf", self._label(ctx, ctx.node_id, max(10, height // 20)), name,
            ], cwd=ctx.work_dir)
            paths.append(ctx.work_dir / name)
        return paths

    async def generate_video(self, ctx, prompt, first_frame, last_frame, duration, aspect):
        width, height = ASPECT_SIZES.get(aspect, ASPECT_SIZES["9:16"])
        if first_frame and Path(first_frame).exists():
            source = ["-loop", "1", "-i", str(first_frame)]
        else:
            source = ["-f", "lavfi", "-i", f"color=c={_color(ctx.node_id)}:s={width}x{height}"]
        vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps=24,format=yuv420p"
        await self.ff.run([
            *source, "-t", f"{duration:.3f}", "-vf", vf,
            "-c:v", "libx264", "-preset", "ultrafast", "-an", "clip.mp4",
        ], cwd=ctx.work_dir)
        return ctx.work_dir / "clip.mp4"

    async def _tone(self, ctx: CallContext, name: str, freq: int, seconds: float, volume: float) -> Path:
        await self.ff.run([
            "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={seconds:.3f}",
            "-af", f"volume={volume}", "-ac", "1", name,
        ], cwd=ctx.work_dir)
        return ctx.work_dir / name

    async def tts(self, ctx, text, voice, emotion):
        return await self._tone(ctx, "vo.wav", 220, max(0.8, 0.38 * len(text.split())), 0.1)

    async def sfx(self, ctx, prompt, duration):
        return await self._tone(ctx, "sfx.wav", 880, duration, 0.2)

    async def music(self, ctx, prompt, duration):
        return await self._tone(ctx, "music.wav", 110, duration, 0.2)
