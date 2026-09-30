"""SQLite CLI for ideas, videos, scripts, posts and metrics. DB: data/agent.db

  python scripts/db.py init --seed          create tables, add the first four build videos
  python scripts/db.py backlog --top 10     best unused ideas
  python scripts/db.py idea-import FILE     add ideas from a JSON list (skips near-duplicates)
  python scripts/db.py video-new IDEA_ID    create media/<id>/ with a script.md template
  python scripts/db.py script-save ID       store media/<id>/script.md as a new version
  python scripts/db.py post-add ID --platform youtube --url URL
  python scripts/db.py metrics-add ID --platform youtube --views 1200
  python scripts/db.py stats                totals from recorded numbers only
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import config  # noqa: E402
from common.config import utf8_stdout, video_dir  # noqa: E402

import scriptmd  # noqa: E402

PILLARS = ("build", "k8s", "linux", "scams", "certs")
IDEA_STATUS = ("backlog", "in-progress", "used", "dropped")
VIDEO_STATUS = ("draft", "scripted", "approved", "captioned", "cut", "packaged", "published")
VOICES = ("own", "kokoro", "edge-tts-draft")
PLATFORMS = ("youtube", "tiktok", "linkedin", "other")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS ideas (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  pillar TEXT NOT NULL CHECK (pillar IN {PILLARS}),
  angle TEXT,
  hook TEXT,
  format TEXT NOT NULL DEFAULT 'short' CHECK (format IN ('short', 'walkthrough')),
  score INTEGER NOT NULL DEFAULT 3 CHECK (score BETWEEN 1 AND 5),
  status TEXT NOT NULL DEFAULT 'backlog' CHECK (status IN {IDEA_STATUS}),
  source TEXT,
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS videos (
  id TEXT PRIMARY KEY,
  idea_id INTEGER REFERENCES ideas(id),
  title TEXT NOT NULL,
  pillar TEXT,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN {VIDEO_STATUS}),
  voice_source TEXT NOT NULL DEFAULT 'own' CHECK (voice_source IN {VOICES}),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS scripts (
  id INTEGER PRIMARY KEY,
  video_id TEXT NOT NULL REFERENCES videos(id),
  version INTEGER NOT NULL,
  body TEXT NOT NULL,
  word_count INTEGER,
  est_seconds REAL,
  fact_check TEXT NOT NULL DEFAULT 'pending' CHECK (fact_check IN ('pending', 'pass', 'issues')),
  fact_check_notes TEXT,
  approved INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (video_id, version)
);
CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY,
  video_id TEXT NOT NULL REFERENCES videos(id),
  platform TEXT NOT NULL CHECK (platform IN {PLATFORMS}),
  url TEXT,
  posted_at TEXT NOT NULL DEFAULT (date('now')),
  UNIQUE (video_id, platform)
);
CREATE TABLE IF NOT EXISTS metrics (
  id INTEGER PRIMARY KEY,
  post_id INTEGER NOT NULL REFERENCES posts(id),
  captured_at TEXT NOT NULL DEFAULT (datetime('now')),
  views INTEGER, likes INTEGER, comments INTEGER, shares INTEGER,
  watch_hours REAL, subs_gained INTEGER
);
CREATE TABLE IF NOT EXISTS profile (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, name TEXT, status TEXT, summary TEXT, stack TEXT, repo TEXT, live TEXT
);
"""

# The first four videos come from the build itself (plan: days 5, 9, 11, 13).
SEED_IDEAS = [
    ("Seven projects, 14 days, zero naira", "build", "The plan and the free tools behind it",
     "I'm building seven portfolio projects in 14 days and spending zero naira.", 5),
    ("One setting that stops users seeing each other's data", "build",
     "Supabase row-level security on ApplyTrack, shown with two logged-in users",
     "Without this one setting, any user of my app could read everyone's job applications.", 5),
    ("I scanned my own app: what CodeQL and ZAP found", "build",
     "Real findings from the DevSecOps review of ApplyTrack, and the fixes",
     "I pointed four free security scanners at my own app. Here is what they found.", 5),
    ("Kubernetes hardening: before and after scores", "k8s",
     "kube-bench and trivy k8s scores on a deliberately weak kind cluster, before and after fixes",
     "My Kubernetes cluster failed most of its security benchmark. Then I fixed it.", 5),
]


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    return con


def slugify(text: str, max_words: int = 5) -> str:
    words = re.sub(r"[^a-z0-9\s-]", "", text.lower()).split()
    return "-".join(words[:max_words]) or "video"


def is_duplicate(title: str, existing: list[str], threshold: float = 0.85) -> str | None:
    norm = title.lower().strip()
    for other in existing:
        if difflib.SequenceMatcher(None, norm, other.lower().strip()).ratio() >= threshold:
            return other
    return None


# ---------- ideas ----------

def add_idea(con, title, pillar, angle=None, hook=None, fmt="short", score=3, source=None, notes=None) -> int:
    cur = con.execute(
        "INSERT INTO ideas (title, pillar, angle, hook, format, score, source, notes) VALUES (?,?,?,?,?,?,?,?)",
        (title, pillar, angle, hook, fmt, score, source, notes))
    con.commit()
    return cur.lastrowid


def import_ideas(con, items: list[dict]) -> tuple[list[int], list[str]]:
    existing = [r["title"] for r in con.execute("SELECT title FROM ideas")]
    added, skipped = [], []
    for item in items:
        dup = is_duplicate(item["title"], existing)
        if dup:
            skipped.append(f"{item['title']!r} ~ {dup!r}")
            continue
        added.append(add_idea(con, item["title"], item["pillar"], item.get("angle"), item.get("hook"),
                              item.get("format", "short"), int(item.get("score", 3)),
                              item.get("source", "ideas-skill"), item.get("notes")))
        existing.append(item["title"])
    return added, skipped


def backlog(con, top: int = 10, pillar: str | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM ideas WHERE status = 'backlog'"
    params: list = []
    if pillar:
        sql += " AND pillar = ?"
        params.append(pillar)
    sql += " ORDER BY score DESC, id LIMIT ?"
    params.append(top)
    return con.execute(sql, params).fetchall()


# ---------- videos and scripts ----------

def new_video(con, idea_id: int, slug: str | None = None, date: str | None = None, voice: str = "own") -> str:
    idea = con.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
    if not idea:
        raise SystemExit(f"No idea #{idea_id}")
    date = date or dt.date.today().strftime("%Y%m%d")
    video_id = f"{date}-{slug or slugify(idea['title'])}"
    con.execute("INSERT INTO videos (id, idea_id, title, pillar, voice_source) VALUES (?,?,?,?,?)",
                (video_id, idea_id, idea["title"], idea["pillar"], voice))
    con.execute("UPDATE ideas SET status = 'in-progress' WHERE id = ?", (idea_id,))
    con.commit()
    folder = video_dir(video_id)
    (folder / "screen").mkdir(parents=True, exist_ok=True)
    script = folder / "script.md"
    if not script.exists():
        target = 150 if idea["format"] == "walkthrough" else 55
        script.write_text(scriptmd.TEMPLATE.format(title=idea["title"], pillar=idea["pillar"],
                                                   format=idea["format"], target=target, idea_id=idea_id),
                          encoding="utf-8")
    return video_id


def get_video(con, video_id: str) -> sqlite3.Row:
    row = con.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
    if not row:
        raise SystemExit(f"No video {video_id!r}. See: python scripts/db.py video-list")
    return row


def set_video_status(con, video_id: str, status: str) -> None:
    """Move forward only, so re-running an earlier step never downgrades a published video."""
    current = get_video(con, video_id)["status"]
    if VIDEO_STATUS.index(status) > VIDEO_STATUS.index(current):
        con.execute("UPDATE videos SET status = ?, updated_at = datetime('now') WHERE id = ?", (status, video_id))
        con.commit()


def save_script(con, video_id: str, fact_check: str = "pending", notes: str | None = None) -> int:
    get_video(con, video_id)
    body = (video_dir(video_id) / "script.md").read_text(encoding="utf-8")
    parsed = scriptmd.parse(body)
    if not parsed["lines"]:
        raise SystemExit("script.md has no numbered lines under '## Script'.")
    version = con.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM scripts WHERE video_id = ?",
                          (video_id,)).fetchone()[0]
    con.execute("INSERT INTO scripts (video_id, version, body, word_count, est_seconds, fact_check, fact_check_notes)"
                " VALUES (?,?,?,?,?,?,?)",
                (video_id, version, body, parsed["word_count"], parsed["est_seconds"], fact_check, notes))
    if parsed["meta"].get("title"):
        con.execute("UPDATE videos SET title = ? WHERE id = ?", (parsed["meta"]["title"], video_id))
    con.commit()
    set_video_status(con, video_id, "scripted")
    return version


def latest_script(con, video_id: str) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM scripts WHERE video_id = ? ORDER BY version DESC LIMIT 1",
                       (video_id,)).fetchone()


def approve_script(con, video_id: str) -> int:
    row = latest_script(con, video_id)
    if not row:
        raise SystemExit("No saved script. Run script-save first.")
    current = (video_dir(video_id) / "script.md").read_text(encoding="utf-8")
    if current != row["body"]:
        raise SystemExit("script.md changed since the last script-save. Save it (and re-check facts) first.")
    if row["fact_check"] != "pass":
        raise SystemExit(f"Fact check is {row['fact_check']!r}. Resolve it and save with --fact-check pass.")
    con.execute("UPDATE scripts SET approved = 1 WHERE id = ?", (row["id"],))
    con.execute("UPDATE ideas SET status = 'used' WHERE id = (SELECT idea_id FROM videos WHERE id = ?)", (video_id,))
    con.commit()
    set_video_status(con, video_id, "approved")
    return row["version"]


# ---------- posts, metrics, stats ----------

def add_post(con, video_id: str, platform: str, url: str | None, date: str | None = None) -> int:
    get_video(con, video_id)
    con.execute("INSERT INTO posts (video_id, platform, url, posted_at) VALUES (?,?,?,COALESCE(?, date('now')))"
                " ON CONFLICT (video_id, platform) DO UPDATE SET url = excluded.url",
                (video_id, platform, url, date))
    con.commit()
    set_video_status(con, video_id, "published")
    return con.execute("SELECT id FROM posts WHERE video_id = ? AND platform = ?", (video_id, platform)).fetchone()[0]


def add_metrics(con, video_id: str, platform: str, **values) -> None:
    post = con.execute("SELECT id FROM posts WHERE video_id = ? AND platform = ?", (video_id, platform)).fetchone()
    if not post:
        raise SystemExit(f"No {platform} post for {video_id}. Run post-add first.")
    cols = [k for k, v in values.items() if v is not None]
    if not cols:
        raise SystemExit("Give at least one metric, e.g. --views 1200")
    con.execute(f"INSERT INTO metrics (post_id, {', '.join(cols)}) VALUES (?{', ?' * len(cols)})",
                (post["id"], *[values[c] for c in cols]))
    con.commit()


def stats(con) -> dict:
    """Latest recorded snapshot per post, summed. Never estimates."""
    rows = con.execute("""
        SELECT p.platform, v.pillar, m.views, m.likes, m.watch_hours, m.subs_gained
        FROM posts p JOIN videos v ON v.id = p.video_id
        LEFT JOIN metrics m ON m.id = (SELECT id FROM metrics WHERE post_id = p.id ORDER BY captured_at DESC, id DESC LIMIT 1)
    """).fetchall()
    out: dict = {"published_videos": con.execute("SELECT COUNT(*) FROM videos WHERE status = 'published'").fetchone()[0],
                 "by_platform": {}}
    for r in rows:
        agg = out["by_platform"].setdefault(r["platform"], {"posts": 0, "views": 0, "likes": 0,
                                                            "watch_hours": 0.0, "subs_gained": 0, "by_pillar": {}})
        agg["posts"] += 1
        agg["views"] += r["views"] or 0
        agg["likes"] += r["likes"] or 0
        agg["watch_hours"] += r["watch_hours"] or 0
        agg["subs_gained"] += r["subs_gained"] or 0
        agg["by_pillar"][r["pillar"]] = agg["by_pillar"].get(r["pillar"], 0) + 1
    return out


def sync_profile(con) -> int:
    from common.profile import load_profile, load_projects
    profile = load_profile()
    con.execute("DELETE FROM profile")
    con.executemany("INSERT INTO profile (key, value) VALUES (?, ?)",
                    [(k, json.dumps(v, ensure_ascii=False)) for k, v in profile.items()])
    projects = load_projects()
    con.execute("DELETE FROM projects")
    con.executemany("INSERT INTO projects VALUES (?,?,?,?,?,?,?)",
                    [(p["id"], p["name"], p.get("status"), p.get("summary"), json.dumps(p.get("stack", [])),
                      p.get("repo"), p.get("live")) for p in projects])
    con.commit()
    return len(projects)


# ---------- CLI ----------

def _print_idea(r) -> None:
    print(f"#{r['id']} [{r['pillar']}] ({r['score']}) {r['title']}"
          + (f"  | angle: {r['angle']}" if r["angle"] else ""))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create tables")
    s.add_argument("--seed", action="store_true", help="add the four build-video ideas")

    s = sub.add_parser("backlog", help="best unused ideas")
    s.add_argument("--top", type=int, default=10)
    s.add_argument("--pillar", choices=PILLARS)

    s = sub.add_parser("idea-add")
    s.add_argument("--title", required=True)
    s.add_argument("--pillar", required=True, choices=PILLARS)
    s.add_argument("--angle")
    s.add_argument("--hook")
    s.add_argument("--format", default="short", choices=("short", "walkthrough"))
    s.add_argument("--score", type=int, default=3)
    s.add_argument("--notes")

    s = sub.add_parser("idea-import", help="JSON list of {title, pillar, angle, hook, format, score, notes}")
    s.add_argument("file", type=Path)

    s = sub.add_parser("idea-show")
    s.add_argument("id", type=int)

    s = sub.add_parser("idea-set")
    s.add_argument("id", type=int)
    s.add_argument("--status", required=True, choices=IDEA_STATUS)

    s = sub.add_parser("video-new", help="start a video from an idea")
    s.add_argument("idea_id", type=int)
    s.add_argument("--slug")
    s.add_argument("--date", help="YYYYMMDD, default today")
    s.add_argument("--voice", default="own", choices=VOICES)

    s = sub.add_parser("video-show")
    s.add_argument("id")

    sub.add_parser("video-list")

    s = sub.add_parser("video-set")
    s.add_argument("id")
    s.add_argument("--status", choices=VIDEO_STATUS)
    s.add_argument("--voice", choices=VOICES)

    s = sub.add_parser("script-save", help="store media/<id>/script.md as a new version")
    s.add_argument("id")
    s.add_argument("--fact-check", default="pending", choices=("pending", "pass", "issues"))
    s.add_argument("--notes")

    s = sub.add_parser("script-approve", help="mark the latest fact-checked version approved")
    s.add_argument("id")

    s = sub.add_parser("post-add")
    s.add_argument("id")
    s.add_argument("--platform", required=True, choices=PLATFORMS)
    s.add_argument("--url")
    s.add_argument("--date", help="YYYY-MM-DD, default today")

    s = sub.add_parser("metrics-add", help="numbers you read from YouTube Studio / TikTok analytics")
    s.add_argument("id")
    s.add_argument("--platform", required=True, choices=PLATFORMS)
    for name, typ in (("views", int), ("likes", int), ("comments", int), ("shares", int),
                      ("watch-hours", float), ("subs-gained", int)):
        s.add_argument(f"--{name}", type=typ)

    sub.add_parser("stats", help="totals from recorded numbers (JSON)")
    sub.add_parser("sync-profile", help="copy profile.json and projects.json into the DB")
    return p


def main(argv: list[str] | None = None) -> None:
    utf8_stdout()
    args = build_parser().parse_args(argv)
    con = connect()
    cmd = args.cmd

    if cmd == "init":
        if args.seed:
            added, skipped = import_ideas(con, [dict(title=t, pillar=p, angle=a, hook=h, score=s, source="plan")
                                                for t, p, a, h, s in SEED_IDEAS])
            print(f"Seeded {len(added)} ideas" + (f", skipped {len(skipped)} existing" if skipped else ""))
        print(f"DB ready: {config.DB_PATH}")
    elif cmd == "backlog":
        rows = backlog(con, args.top, args.pillar)
        if not rows:
            print("Backlog empty. Run /ideas.")
        for r in rows:
            _print_idea(r)
        recent = con.execute("SELECT id, title FROM videos ORDER BY created_at DESC LIMIT 5").fetchall()
        if recent:
            print("Recent videos: " + "; ".join(f"{r['id']}" for r in recent))
    elif cmd == "idea-add":
        print(f"Added idea #{add_idea(con, args.title, args.pillar, args.angle, args.hook, args.format, args.score, 'manual', args.notes)}")
    elif cmd == "idea-import":
        items = json.loads(args.file.read_text(encoding="utf-8"))
        added, skipped = import_ideas(con, items)
        print(f"Added {len(added)} ideas: {added}")
        for s in skipped:
            print(f"Skipped duplicate: {s}")
    elif cmd == "idea-show":
        r = con.execute("SELECT * FROM ideas WHERE id = ?", (args.id,)).fetchone()
        print(json.dumps(dict(r), indent=2, ensure_ascii=False) if r else f"No idea #{args.id}")
    elif cmd == "idea-set":
        con.execute("UPDATE ideas SET status = ? WHERE id = ?", (args.status, args.id))
        con.commit()
        print(f"Idea #{args.id} -> {args.status}")
    elif cmd == "video-new":
        vid = new_video(con, args.idea_id, args.slug, args.date, args.voice)
        print(f"Created video {vid}\nFolder: {video_dir(vid)}\nNext: /script {vid}")
    elif cmd == "video-show":
        v = dict(get_video(con, args.id))
        s = latest_script(con, args.id)
        if s:
            v["script"] = {k: s[k] for k in ("version", "word_count", "est_seconds", "fact_check", "approved")}
        v["posts"] = [dict(r) for r in con.execute("SELECT platform, url, posted_at FROM posts WHERE video_id = ?",
                                                   (args.id,))]
        print(json.dumps(v, indent=2, ensure_ascii=False))
    elif cmd == "video-list":
        for r in con.execute("SELECT id, status, voice_source, title FROM videos ORDER BY id"):
            print(f"{r['id']:<40} {r['status']:<10} {r['voice_source']:<14} {r['title']}")
    elif cmd == "video-set":
        get_video(con, args.id)
        if args.status:
            con.execute("UPDATE videos SET status = ?, updated_at = datetime('now') WHERE id = ?", (args.status, args.id))
        if args.voice:
            con.execute("UPDATE videos SET voice_source = ? WHERE id = ?", (args.voice, args.id))
        con.commit()
        print("Updated.")
    elif cmd == "script-save":
        v = save_script(con, args.id, args.fact_check, args.notes)
        print(f"Saved script v{v} for {args.id} (fact check: {args.fact_check})")
    elif cmd == "script-approve":
        print(f"Approved script v{approve_script(con, args.id)} for {args.id}")
    elif cmd == "post-add":
        add_post(con, args.id, args.platform, args.url, args.date)
        print(f"Logged {args.platform} post for {args.id}")
    elif cmd == "metrics-add":
        add_metrics(con, args.id, args.platform, views=args.views, likes=args.likes, comments=args.comments,
                    shares=args.shares, watch_hours=args.watch_hours, subs_gained=args.subs_gained)
        print(f"Logged metrics for {args.id} on {args.platform}")
    elif cmd == "stats":
        print(json.dumps(stats(con), indent=2))
    elif cmd == "sync-profile":
        print(f"Synced profile and {sync_profile(con)} projects")


if __name__ == "__main__":
    main()
