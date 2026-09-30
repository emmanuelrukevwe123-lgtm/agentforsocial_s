---
name: log-video
description: Record published links and analytics numbers I paste in.
argument-hint: "<video-id> <links and/or numbers>"
disable-model-invocation: true
model: haiku
allowed-tools:
  - Bash(python scripts/db.py *)
---

# /log-video

Input: `$ARGUMENTS`

1. If no video id is given, run `python scripts/db.py video-list` and pick the one that matches, or ask.
2. For each link: `python scripts/db.py post-add <id> --platform youtube|tiktok|linkedin|other --url <url>`.
3. For each set of numbers I pasted: `python scripts/db.py metrics-add <id> --platform <p> --views N --likes N ...`
   (options: `--views --likes --comments --shares --watch-hours --subs-gained`).
   Only numbers I actually gave. Never estimate. Ask if a number's platform is unclear.
4. Reply with one line per logged item.
