"""FFmpeg lookup and small media helpers."""
from __future__ import annotations

import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

AUDIO_EXTS = (".wav", ".m4a", ".mp3", ".flac", ".aac", ".ogg")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


@lru_cache(maxsize=1)
def ffmpeg_exe() -> str:
    """System FFmpeg if on PATH, else the static build bundled with imageio-ffmpeg."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise SystemExit(
            "FFmpeg not found. Run: pip install -r requirements.txt  (or: winget install Gyan.FFmpeg)"
        ) from exc
    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(args: list[str], cwd: Path | None = None, quiet: bool = True) -> None:
    cmd = [ffmpeg_exe(), "-hide_banner", "-y"]
    if quiet:
        cmd += ["-loglevel", "error", "-stats"]
    cmd += args
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        raise SystemExit(f"FFmpeg failed (exit {result.returncode}). Command:\n{' '.join(cmd)}")


def probe_duration(path: Path) -> float:
    """Duration in seconds, read from `ffmpeg -i` (imageio-ffmpeg ships no ffprobe)."""
    proc = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr)
    if not match:
        raise SystemExit(f"Could not read duration of {path}")
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


VOICE_EXTS = AUDIO_EXTS + (".mp4", ".mov", ".m4v", ".webm", ".mkv")  # phone recorders often save video


def find_voice(folder: Path) -> Path | None:
    """voice.wav first, then any audio/video file with "voice" in its name (e.g. "Voice Over.mp4")."""
    for ext in AUDIO_EXTS:
        candidate = folder / f"voice{ext}"
        if candidate.exists():
            return candidate
    matches = sorted(p for p in folder.glob("*") if p.is_file() and p.suffix.lower() in VOICE_EXTS
                     and "voice" in p.stem.lower().replace(" ", ""))
    return matches[0] if matches else None
