"""Load profile.json and projects.json, the single source of truth shared with the portfolio.

Lookup order for the content folder:
  1. PORTFOLIO_CONTENT_DIR (env or .env)
  2. ../portfolio/content  (the portfolio repo, once it exists)
  3. ./content             (seed copy in this repo)

Usage: python -m common.profile --summary
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from common.config import ROOT, load_env, utf8_stdout


def content_dir() -> Path:
    load_env()
    env = os.environ.get("PORTFOLIO_CONTENT_DIR")
    candidates = [Path(env)] if env else []
    candidates += [ROOT.parent / "portfolio" / "content", ROOT / "content"]
    for folder in candidates:
        if (folder / "profile.json").exists():
            return folder
    raise SystemExit("profile.json not found. Set PORTFOLIO_CONTENT_DIR or add content/profile.json.")


def load_profile() -> dict:
    return json.loads((content_dir() / "profile.json").read_text(encoding="utf-8"))


def load_projects() -> list[dict]:
    path = content_dir() / "projects.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["projects"] if isinstance(data, dict) else data


def summary() -> str:
    """Compact fact sheet for prompts. Only these facts may be claimed in scripts."""
    p = load_profile()
    out = [
        f"Name: {p.get('name')} | Location: {p.get('location')}",
        f"Headline: {p.get('headline', '')}",
        f"Education: {'; '.join(p.get('education', []))}",
        f"Certifications: {', '.join(p.get('certifications', [])) or 'none listed'}",
        f"Skills: {', '.join(p.get('skills', []))}",
        f"Experience: {'; '.join(p.get('experience', []))}",
        "Links: " + ", ".join(f"{k}={v}" for k, v in p.get("links", {}).items() if v),
        "Projects:",
    ]
    for pr in load_projects():
        links = " ".join(x for x in (pr.get("repo"), pr.get("live")) if x)
        out.append(f"- [{pr.get('status', '?')}] {pr['name']}: {pr.get('summary', '')} {links}".rstrip())
    return "\n".join(out)


def main() -> None:
    utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--summary", action="store_true", help="print the compact fact sheet")
    parser.add_argument("--where", action="store_true", help="print which content folder is used")
    args = parser.parse_args()
    if args.where:
        print(content_dir())
    else:
        print(summary())


if __name__ == "__main__":
    main()
