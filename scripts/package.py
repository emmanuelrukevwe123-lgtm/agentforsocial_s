"""Build media/<id>/upload/ from package.json (written by /package) and the rendered files.

  python scripts/package.py <id>
  python scripts/package.py <id> --force     skip the approved-script gate (not recommended)

The agent stops here. Upload by hand: API uploads from personal projects are locked to private
on YouTube and TikTok, and TikTok bans unauthorised automation.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.config import utf8_stdout, video_dir  # noqa: E402

import db  # noqa: E402

LIMITS = {"youtube.title": 100, "youtube.description": 5000, "tiktok.caption": 2200, "linkedin.post": 3000}
REQUIRED = ["youtube.title", "youtube.description", "youtube.tags", "tiktok.caption",
            "thumbnail_text", "ai_disclosure.label_required", "ai_disclosure.reason"]
BANNED_PHRASES = ("guaranteed", "hack any", "hack anyone", "make money fast", "100% safe")


def get(data: dict, dotted: str):
    for part in dotted.split("."):
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


def validate(pkg: dict, voice_source: str) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    for key in REQUIRED:
        if get(pkg, key) in (None, "", []):
            errors.append(f"missing {key}")
    for key, limit in LIMITS.items():
        value = get(pkg, key)
        if isinstance(value, str) and len(value) > limit:
            errors.append(f"{key} is {len(value)} chars (limit {limit})")
    text = json.dumps(pkg, ensure_ascii=False).lower()
    for phrase in BANNED_PHRASES:
        if phrase in text:
            errors.append(f"banned phrase {phrase!r} (see CLAUDE.md)")
    label = get(pkg, "ai_disclosure.label_required")
    if voice_source != "own" and label is False:
        warnings.append(f"voice is {voice_source!r}: tick the AI label anyway, over-disclosing has no known penalty")
    if voice_source == "edge-tts-draft":
        errors.append("edge-tts has no confirmed commercial licence; re-record with your own voice or Kokoro")
    if "[add link]" in text:
        warnings.append("description still has [add link]; fill links in profile.json or by hand")
    if "#" in (get(pkg, "youtube.title") or ""):
        warnings.append("hashtags in the YouTube title; put them in the description")
    return errors, warnings


def upload_md(video_id: str, pkg: dict, files: list[str]) -> str:
    yt, tt, li = pkg["youtube"], pkg["tiktok"], pkg.get("linkedin", {})
    disclosure = pkg["ai_disclosure"]
    label = "YES: turn on 'Altered or synthetic content' / TikTok AIGC label" if disclosure["label_required"] \
        else "No label needed"
    credits = "\n".join(f"- {c}" for c in pkg.get("credits", [])) or "- none"
    checklist = "\n".join(f"- [ ] {c}" for c in [
        "Watched the final cut once with sound off (captions readable, nothing cut off by app UI)",
        "Blurred IPs, tokens, emails and anything from real accounts",
        "Only my own lab or apps are attacked or scanned on screen",
        "Music is licensed for both platforms (Epidemic Sound: channel connected in your account so Content ID "
        "claims are cleared; otherwise remove it with cut.py --no-music and add music in the app)",
        f"AI disclosure: {label}",
        "YouTube: uploaded captions.srt, set thumbnail, added to playlist, pinned comment with the repo link",
        "TikTok: caption pasted, cover frame picked, cloud sync off in CapCut",
        f"Logged the links: /log-video {video_id}",
    ])
    return f"""# Upload: {video_id}

Files: {", ".join(files)}

## YouTube
**Title** ({len(yt['title'])}/100)
```
{yt['title']}
```
**Description**
```
{yt['description']}
```
**Tags**
```
{", ".join(yt['tags'])}
```

## TikTok
```
{tt['caption']} {" ".join(tt.get('hashtags', []))}
```

## LinkedIn
```
{li.get('post', '(none)')}
```

## AI disclosure
{label}. Reason: {disclosure['reason']}

## Credits
{credits}

## Checklist
{checklist}
"""


def main(argv: list[str] | None = None) -> None:
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video_id")
    p.add_argument("--force", action="store_true")
    args = p.parse_args(argv)

    folder = video_dir(args.video_id)
    con = db.connect()
    video = db.get_video(con, args.video_id)
    script = db.latest_script(con, args.video_id)
    if not (script and script["approved"]) and not args.force:
        raise SystemExit("Script not approved. Run /script, pass the fact check, then db.py script-approve.")

    pkg_path = folder / "package.json"
    if not pkg_path.exists():
        raise SystemExit(f"No package.json. Run /package {args.video_id}")
    pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
    errors, warnings = validate(pkg, video["voice_source"])
    for w in warnings:
        print(f"WARNING: {w}")
    if errors:
        raise SystemExit("package.json problems:\n  " + "\n  ".join(errors))

    upload = folder / "upload"
    upload.mkdir(exist_ok=True)
    copied = []
    for src in [folder / "out" / f"{args.video_id}_9x16.mp4", folder / "out" / f"{args.video_id}_16x9.mp4",
                folder / "captions.srt", folder / "thumbnail.png"]:
        if src.exists():
            shutil.copy2(src, upload / src.name)
            copied.append(src.name)
        else:
            print(f"Missing (add before upload): {src.relative_to(folder)}")
    (upload / "UPLOAD.md").write_text(upload_md(args.video_id, pkg, copied), encoding="utf-8")
    db.set_video_status(con, args.video_id, "packaged")
    print(f"Upload folder ready: {upload}\nOpen UPLOAD.md, polish the edit, upload by hand.")


if __name__ == "__main__":
    main()
