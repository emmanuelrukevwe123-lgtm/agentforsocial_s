---
name: package
description: Write titles, descriptions, hashtags, credits and the AI-disclosure decision, then build the upload folder.
argument-hint: "<video-id>"
disable-model-invocation: true
allowed-tools:
  - Bash(python scripts/db.py *)
  - Bash(python scripts/package.py *)
  - Read
  - Write
---

# /package

Video: `$ARGUMENTS`.

## Facts and links
!`python -m common.profile --summary`

## Do this
1. Run `python scripts/db.py video-show $ARGUMENTS`. Read `media/$ARGUMENTS/script.md` and, if present,
   `media/$ARGUMENTS/credits.json` (Pexels photos used in the animation; copy every line into `credits`).
2. Write `media/$ARGUMENTS/package.json`:
   ```json
   {
     "youtube": {"title": "", "description": "", "tags": []},
     "tiktok": {"caption": "", "hashtags": []},
     "linkedin": {"post": ""},
     "thumbnail_text": "",
     "credits": [],
     "ai_disclosure": {"label_required": false, "reason": ""}
   }
   ```
   - YouTube title: under 70 characters, the key term first, no clickbait, no hashtags.
   - Description: two sentences on what the viewer learns, then links (repo, portfolio) from the facts above,
     then credits, then 3 hashtags including `#Shorts` for a short. If a link is empty, write `[add link]`.
   - Tags: 8 to 12 plain phrases.
   - TikTok caption: one line, under 150 characters, plus 3 to 5 hashtags in `hashtags`.
   - LinkedIn: 80 to 150 words, first person, what I built or learned and one concrete detail. No hype.
   - `thumbnail_text`: 2 to 4 words.
   - Credits: every stock clip (Pexels: photographer + "via Pexels"), borrowed code or tool shown. Empty list if none.
   - AI disclosure. My own voice + AI-written script + paper-cut graphics drawn by code (not realistic): `false`,
     reason says so.
     Kokoro or any synthetic voice, AI images or video of realistic scenes, or AI music: `true`.
     When unsure, `true`.
   - Follow the banned claims in CLAUDE.md. No numbers I did not give you.
3. Run `python scripts/package.py $ARGUMENTS`. Fix any reported problem and rerun.
4. Reply with the YouTube title, the disclosure decision, and any missing files. If `thumbnail.png` is missing,
   tell me to run `python scripts/thumb.py $ARGUMENTS`.
