# Content agent

Takes a short video from idea to script, captions, paper-cut animation, final cut and upload package.
Claude only writes text (including scenes.json). Python + free local tools (Pillow, FFmpeg, faster-whisper) draw,
animate and render. Emmanuel records the voice and uploads by hand. He does not film: all visuals are generated.
Emmanuel is not a programmer: run the commands for him and explain results in plain words.

## Channel
- Niche: cybersecurity and cloud, learned in public from Lagos.
- Pillars: `build` (my own projects), `k8s` (home lab, Kubernetes security), `linux` (Linux/DevOps quick wins),
  `scams` (Nigerian scam and phishing awareness), `certs` (honest study notes).
- Audience: Nigerian and global early-career tech people, and recruiters checking my work.
- Voice: first person, plain English, calm, specific. Show, don't hype. Nigerian context where it is real.

## Format rules (every script)
- Hook in the first 3 seconds, stated as a problem or a result.
- One idea per video. Most videos 35 to 60 seconds (about 2.5 spoken words per second). Walkthroughs up to 3 minutes.
- Written for burned-in captions: short sentences, one per numbered line.
- End with a call to action pointing to the GitHub repo or portfolio.
- Every video needs its own angle. Never reuse a template storyline: YouTube judges "inauthentic content" channel-wide.

## Banned claims and content
- No skill, certificate, job, number or result that is not in `python -m common.profile --summary` or supplied by me.
- No view counts, follower counts or earnings unless read from `data/agent.db`.
- No attacks or scans on systems I do not own. Labs only: my kind cluster, my own apps, retired rooms.
- No answers, flags or walkthroughs for active TryHackMe rooms.
- No real IPs, tokens, keys, phone numbers or account details in scripts or on screen.
- Scam videos: never name or show identifiable victims, never shame real people, never give steps that help a scammer.
- No "hack anyone", "guaranteed job" or "make money fast" framing.

## Cost rules
- Never set or ask for `ANTHROPIC_API_KEY`. Never use `claude --bare`. Both move billing off the Pro plan.
- Do not transcribe, cut or render inside Claude. Tell me the Python command to run.
- Keep replies short. Read only the files a step needs.

## Layout
- `scripts/db.py` SQLite CLI (ideas, videos, scripts, posts, metrics). DB at `data/agent.db`.
- `scripts/captions.py` transcribe voice, align to script, write `.srt` + `.ass`.
- `scripts/animate.py` paper-cut stop-motion scenes from `scenes.json` (drawing code in `scripts/papercut.py`,
  photos from `scripts/stock.py`). Needs the venv: `.venv/Scripts/python`.
- `scripts/cut.py` `render` 9:16 and 16:9 with FFmpeg: animation + voice + burned-in captions.
- `scripts/thumb.py` thumbnail from a frame + big text. `scripts/package.py` builds the upload folder.
- `common/` shared with the future job agent: `llm.py`, `profile.py`, `config.py`, `media.py`.
- `media/<video-id>/` per video: `script.md`, `voice.wav`, `screen/`, `timeline.json`, `lines.json`, `out/`, `upload/`.
- Video ids look like `20261005-seven-projects`.

## Workflow
`/ideas` -> `python scripts/db.py video-new <idea-id>` -> `/script <video-id>` -> I record the voiceover
-> `.venv/Scripts/python scripts/captions.py <id>` (if I ad-libbed, update script.md to my words, re-save, rerun with `--reuse`)
-> `/scenes <id>` -> `.venv/Scripts/python scripts/cut.py render <id>` (music: first file in `media/<id>/Music/`, ducked under the voice) -> `/package <id>` -> upload by hand -> `/log-video`.
