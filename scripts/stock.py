"""Free Pexels photos for mixed-media scenes, cached so each query hits the API once.

Pexels allows commercial use; credit the photographer (animate.py writes credits.json for /package).
Limits: 200 requests an hour. Avoid identifiable people in scam videos ("not in a bad light").

  python scripts/stock.py "server room"
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.config import ROOT, load_env, utf8_stdout  # noqa: E402

CACHE = ROOT / "assets" / "stock"
API = "https://api.pexels.com/v1/search?"


def _get(url: str, key: str) -> bytes:
    req = urllib.request.Request(url, headers={"Authorization": key, "User-Agent": "content-agent/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def fetch(query: str, orientation: str = "square") -> dict | None:
    index_path = CACHE / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    if query in index and Path(index[query]["file"]).exists():
        return index[query]
    load_env()
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return None
    params = urllib.parse.urlencode({"query": query, "per_page": 1, "orientation": orientation})
    data = json.loads(_get(API + params, key))
    if not data.get("photos"):
        return None
    photo = data["photos"][0]
    CACHE.mkdir(parents=True, exist_ok=True)
    file = CACHE / f"pexels_{photo['id']}.jpg"
    if not file.exists():
        file.write_bytes(_get(photo["src"]["large"], key))
    index[query] = {"file": str(file), "photographer": photo["photographer"], "url": photo["url"]}
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    return index[query]


if __name__ == "__main__":
    utf8_stdout()
    hit = fetch(" ".join(sys.argv[1:]))
    print(json.dumps(hit, indent=2) if hit else "No result (is PEXELS_API_KEY set in .env?)")
