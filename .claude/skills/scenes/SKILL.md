---
name: scenes
description: Design the paper-cut animated scenes for a video's script, then render them.
argument-hint: "<video-id>"
disable-model-invocation: true
allowed-tools:
  - Bash(.venv/Scripts/python scripts/animate.py *)
  - Bash(python scripts/db.py *)
  - Read
  - Write
  - Edit
---

# /scenes

Video: `$ARGUMENTS`.

## What the renderer can draw
!`.venv/Scripts/python scripts/animate.py vocab`

## Do this
1. Read `media/$ARGUMENTS/script.md`. If `media/$ARGUMENTS/lines.json` exists, the voice is recorded and
   `at_word` will sync to it; otherwise timing is estimated.
2. Write `media/$ARGUMENTS/scenes.json` (format in the docstring of `scripts/animate.py`):
   - One scene per script line, or `"lines": [a, b]` for short lines that belong together.
   - 2 to 5 elements per scene. Stage is a square: x, y are 0..1. Keep y between 0.1 and 0.9.
     Icons 0.25-0.6 wide, text 0.07-0.14 tall. Leave space between pieces.
   - Sync each piece to the word that names it with `at_word`. The first piece at `"at": 0`.
   - Vary composition, background colour, `pattern`, `transition`, enter motions and text styles between
     scenes. No two neighbouring scenes alike: the channel must not look templated. The first scene uses
     `"transition": "cut"`; scenes under 1.2 s use `cut` or a short `tdur` (0.3).
   - Make pieces interact, at least one moment per scene, tied to the words:
     a `stamp` that `slam`s onto an icon (it shakes), an icon that `drop`s next to another (knocks it),
     `moves` that carry a piece onto another (`impact: true`) or fly it in an `arc` from one to another
     (a chat bubble out of a phone), an `exit` when the script says "not" or "instead", one icon shrinking
     out as its replacement spins in at the same spot.
   - Mixed media: `ransom` for hooks and titles, `stamp` for verdicts and numbers, `strip` for labels,
     `image` with `pexels:<query>` for real-world texture (objects and places, never identifiable people in scam
     stories). No real brand logos: say the brand in text, draw a generic icon.
3. Check two or three scenes: `.venv/Scripts/python scripts/animate.py still $ARGUMENTS --line N --at 99`
   and read the PNG. Fix overlaps or pieces off the stage.
4. Render: `.venv/Scripts/python scripts/animate.py render $ARGUMENTS`. This also writes `timeline.json`.
5. Tell me: "Scenes rendered. Next: `python scripts/cut.py render $ARGUMENTS`" (or, if there is no voice yet,
   that `cut.py render` will make a silent preview).
