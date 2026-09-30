"""Paths and a tiny .env loader (no python-dotenv dependency)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MEDIA_DIR = ROOT / "media"
DB_PATH = Path(os.environ.get("AGENT_DB", DATA_DIR / "agent.db"))


def load_env(path: Path = ROOT / ".env") -> None:
    """Read KEY=VALUE lines into os.environ without overriding existing values."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key == "ANTHROPIC_API_KEY":
            # Setting this moves Claude Code from the Pro subscription to paid API billing.
            print("WARNING: ignoring ANTHROPIC_API_KEY in .env (it would bill the API, not Pro).",
                  file=sys.stderr)
            continue
        os.environ.setdefault(key, value)


def utf8_stdout() -> None:
    """Windows pipes default to cp1252; skills read our output through a pipe."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def video_dir(video_id: str) -> Path:
    return MEDIA_DIR / video_id
