"""Parse media/<id>/script.md.

Format:
    ---
    title: One setting that stops users seeing each other's data
    pillar: build
    target_seconds: 55
    ---
    ## Script
    [1] Your users can read each other's data, and you might not know.
    [2] ...

    ## Visuals
    [1] screen: two browser windows logged in as different users
"""
from __future__ import annotations

import re
from pathlib import Path

WORDS_PER_SECOND = 2.5
LINE_RE = re.compile(r"^\s*\[(\d+)\]\s*(.+?)\s*$")


def parse(text: str) -> dict:
    text = text.lstrip("﻿")  # Notepad and PowerShell 5 add a BOM
    meta: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        for raw in fm.strip().splitlines():
            if ":" in raw:
                k, v = raw.split(":", 1)
                meta[k.strip()] = v.strip()
    lines: dict[int, str] = {}
    visuals: dict[int, str] = {}
    section = None
    for raw in body.splitlines():
        heading = raw.strip().lower()
        if heading.startswith("## "):
            section = heading[3:].strip()
            continue
        match = LINE_RE.match(raw)
        if not match:
            continue
        n, content = int(match.group(1)), match.group(2)
        if section == "script":
            lines[n] = content
        elif section and section.startswith("visual"):
            visuals[n] = content
    words = sum(len(t.split()) for t in lines.values())
    return {"meta": meta, "lines": dict(sorted(lines.items())), "visuals": visuals,
            "word_count": words, "est_seconds": round(words / WORDS_PER_SECOND, 1)}


def load(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Missing {path}. Run /script first.")
    return parse(path.read_text(encoding="utf-8"))


TEMPLATE = """---
title: {title}
pillar: {pillar}
format: {format}
target_seconds: {target}
idea_id: {idea_id}
---
## Script
[1]

## Visuals
[1]

## Sources
-
"""
