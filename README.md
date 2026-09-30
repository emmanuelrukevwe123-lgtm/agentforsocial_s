# Content agent

A Claude Code agent that takes a short video from idea to script, captions, rough cut and upload
package for a "cybersecurity and cloud, learned in public from Lagos" channel.

Claude only writes text: ideas, scripts, fact checks, titles. Free local tools do the rest:
faster-whisper for captions, FFmpeg for both aspect ratios, Pillow for thumbnails. A human does the three
steps that need one: recording the voice, the final edit, and the upload.

## The problem

Making one good short takes hours of writing, captioning, reframing for 9:16 and 16:9, and packaging.
Fully automated "AI video" tools cut that time, but they produce the templated, stock-footage content that
YouTube's inauthentic-content policy demonetises channel-wide. This agent automates the mechanical work and
keeps the parts that make a channel original (my voice, my screen, my projects) in human hands.

## Pipeline

| Stage | Tool | Who |
|---|---|---|
| Ideas and backlog | `/ideas` skill + SQLite | Agent |
| Script and fact check | `/script` + `fact-checker` subagent (Haiku) | Agent, I approve |
| Voiceover | My own voice | Me |
| Captions | `scripts/captions.py`: faster-whisper, aligned to the script | Python |
| Visuals | `/scenes` writes `scenes.json`; `scripts/animate.py` draws paper-cut stop-motion | Agent + Python |
| Final cut, 9:16 + 16:9 | `scripts/cut.py`: animation + voice + captions with FFmpeg | Python |
| Thumbnail | `scripts/thumb.py`: Pillow | Python, I tweak |
| Titles, descriptions, disclosure | `/package` skill + `scripts/package.py` | Agent |
| Polish | CapCut or DaVinci Resolve, local | Me |
| Upload | YouTube Studio, TikTok app | Me |

## Setup (Windows, from a fresh clone)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python scripts/db.py init --seed
pytest
```

FFmpeg is bundled through `imageio-ffmpeg`, so no separate install is needed. A system `ffmpeg` on PATH is
used if present. The first `captions.py` run downloads the Whisper `small` model (about 500 MB).

Open the folder in Claude Code, logged in with `/login`. **Do not set `ANTHROPIC_API_KEY`**: it moves
billing from the Pro subscription to the paid API. `common/llm.py` strips it from child processes, and
`.claude/settings.json` blocks `--bare`.

## Making a video

```text
/ideas 7                                   # Claude adds ideas to the backlog
python scripts/db.py video-new 3           # creates media/<id>/ with a script template
/script <id>                               # Claude writes, fact-checks, you approve
  -> record the voiceover into media/<id>/ (any file with "voice" in its name)
python scripts/captions.py <id>            # transcript, lines.json, .srt, word-highlight .ass
/scenes <id>                               # Claude designs the paper-cut scenes, animate.py renders them
python scripts/cut.py render <id>          # final 1080x1920 and 1920x1080
/package <id>                              # titles, description, tags, disclosure, upload folder
python scripts/thumb.py <id>
  -> polish, upload by hand, then:
/log-video <id> https://youtu.be/... 1,200 views
```

### timeline.json

```json
{"fps": 30, "background": "#0b1220",
 "segments": [
   {"lines": [1, 2], "clip": "screen/rls.mp4", "from": 3.5},
   {"line": 3, "clip": "screen/policy.mp4", "speed": 2.0,
    "vertical": {"layout": "crop", "crop": [420, 0, 1080, 1080]}},
   {"line": 4, "clip": "screen/diagram.png"}]}
```

Each segment covers one or more script lines, and its length comes from where those lines fall in the
recording. Layouts are `blur` (the 9:16 default), `fit` (the 16:9 default), `fill` and `crop`. A segment with
`"clip": null` renders a plain card, so timing can be checked before any footage exists.

## Paper-cut animation (no filming)

`/scenes <id>` has Claude turn each script line into a small scene: paper icons (about 30, drawn from
shapes in code, so there are no logo or icon licences), cut-out, ransom-note, strip and rubber-stamp text, and
optional Pexels photos printed as duotone or halftone. `animate.py` renders each scene at 12 fps. Every
piece is a stack of paper layers with grain, a rough cut edge and a soft shadow, with a slight "boil"
between frames. Pieces enter on the spoken word (`at_word`, timed from `lines.json`). The same scenes render
at 9:16 and 16:9, and `cut.py` adds the voice and paper-label captions.

```text
.venv/Scripts/python scripts/animate.py vocab                        what can be drawn
.venv/Scripts/python scripts/animate.py still <id> --line 3 --at 99  check one scene as a PNG
.venv/Scripts/python scripts/animate.py render <id>                  all scenes, writes timeline.json
.venv/Scripts/python scripts/cut.py render <id>                      final videos in media/<id>/out/
```

## Design notes

- **Captions follow the script.** The transcript supplies the timing and the script supplies the spelling,
  so "Supabase", "kube-bench" and Nigerian pronunciations come out right. Words the recogniser missed are
  interpolated. If the recording drifts from the script, `--mode transcript` trusts the audio instead.
- **One FFmpeg pass per format.** Every segment is normalised, concatenated and captioned in a single filter
  graph, so there is one encode. The command runs from the video folder so the subtitle path has no Windows
  drive colon to escape.
- **Approval gate.** `package.py` refuses to build unless the latest script passed the fact check and was
  approved unchanged since it was saved.
- **Numbers only from records.** `db.py stats` sums the latest analytics snapshot per post, which is what the
  job agent will quote on a CV.
- **Manual upload.** YouTube and TikTok lock API uploads from unaudited personal apps to private, and TikTok
  bans unauthorised automation, so the agent stops at `media/<id>/upload/`.
- `common/` (the LLM wrapper, profile loader, config) is shared with the planned job agent.

## Decisions and trade-offs

<!-- Write this section yourself: it is your interview preparation. Suggested prompts: -->
<!-- Why does Claude only write text? What would break if it rendered video too? -->
<!-- Why SQLite and not Supabase for this project? -->
<!-- Why align captions to the script instead of trusting Whisper? What fails if you ad-lib? -->
<!-- Why a hand-written timeline.json instead of automatic B-roll matching? -->
<!-- What did the PyAV 19 break teach you about pinning dependencies? -->

## Licences of tools used

faster-whisper (MIT), FFmpeg (LGPL/GPL build via imageio-ffmpeg), Pillow (MIT-CMU). My own voice, so there
are no TTS licence questions. Rendered without music: music is added inside each app at upload.
