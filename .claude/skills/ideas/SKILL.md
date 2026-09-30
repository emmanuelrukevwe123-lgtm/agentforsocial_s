---
name: ideas
description: Generate new video ideas for the channel and add them to the SQLite backlog.
argument-hint: "[count, default 7] [pillar]"
disable-model-invocation: true
allowed-tools:
  - Bash(python scripts/db.py *)
  - Write
---

# /ideas

Arguments: `$ARGUMENTS` (optional count and pillar; default 7 ideas across pillars).

## Current backlog and recent videos
!`python scripts/db.py backlog --top 25`

## Facts I can claim
!`python -m common.profile --summary`

## Do this
1. Propose the ideas. Rules:
   - Every idea must be something I can film with my own screen, lab or projects. No stock-footage-only ideas.
   - Each has its own angle. No near-copies of the backlog above, and no shared template storyline.
   - Prefer ideas grounded in my real builds and projects above. `scams` ideas are awareness only.
   - `hook` is the first spoken sentence: a problem or a result, under 15 words.
   - `score` 1-5: 5 = strong hook, my own footage, clearly helps one of my target roles, filmable this week.
   - `format`: `short` (35-60 s) or `walkthrough` (up to 3 min, for a finished project).
2. Write them as a JSON list to `data/ideas_batch.json`:
   `[{"title": "...", "pillar": "build|k8s|linux|scams|certs", "angle": "...", "hook": "...", "format": "short", "score": 4, "notes": "what to screen-record"}]`
3. Run `python scripts/db.py idea-import data/ideas_batch.json`.
4. Reply with only the added ids and titles, one line each, and: "Start one with `python scripts/db.py video-new <id>`."
