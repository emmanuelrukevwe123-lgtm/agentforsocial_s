"""Transcribe voice.wav with faster-whisper, align it to script.md, write captions.

  python scripts/captions.py 20261005-seven-projects
  python scripts/captions.py <id> --reuse          restyle only, skip transcription
  python scripts/captions.py <id> --mode transcript  trust the recording, not the script (ad-libs)

Writes into media/<id>/:
  transcript.json      raw faster-whisper words (cached)
  lines.json           start/end per script line, used by cut.py
  captions.srt         plain captions for YouTube's caption upload
  captions_9x16.ass    word-by-word highlight, burned into Shorts/TikTok
  captions_16x9.ass    same for the horizontal cut
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.config import utf8_stdout, video_dir  # noqa: E402
from common.media import ffmpeg_exe, find_voice, probe_duration  # noqa: E402

import scriptmd  # noqa: E402

FORMATS = {
    # name: (width, height, font size, max words per caption, bottom margin)
    "9x16": (1080, 1920, 84, 3, 470),
    "16x9": (1920, 1080, 62, 7, 70),
}
# ASS colours are &HAABBGGRR. bold: white text, black outline, yellow word (for screen footage).
# paper: navy text on a cream paper label, red word (matches the paper-cut animation).
STYLES = {
    "bold": {"primary": "&H00FFFFFF", "outline": "&H00000000", "back": "&H80000000", "border": 1,
             "highlight": "&H0000D4FF&", "outline_w": lambda size: round(size / 13), "shadow": 2},
    "paper": {"primary": "&H0057351D", "outline": "&H00D2E9F3", "back": "&H50000000", "border": 3,
              "highlight": "&H004639E6&", "outline_w": lambda size: round(size / 5), "shadow": 4},
}
PUNCT_BREAK = re.compile(r"[.,!?;:]$")


# ---------- transcription ----------

def load_audio(audio: Path, rate: int = 16000):
    """Decode to 16 kHz mono float32 with our FFmpeg (avoids faster-whisper's PyAV decoder,
    which breaks on PyAV 19)."""
    import numpy as np

    proc = subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", str(audio),
                           "-f", "f32le", "-ac", "1", "-ar", str(rate), "-"], capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(f"Could not decode {audio}: {proc.stderr.decode(errors='replace')}")
    return np.frombuffer(proc.stdout, dtype=np.float32)


def transcribe(audio: Path, model_size: str, prompt: str | None) -> list[dict]:
    from faster_whisper import WhisperModel  # heavy import, only when needed

    print(f"Loading faster-whisper '{model_size}' (first run downloads the model)...")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, info = model.transcribe(load_audio(audio), language="en", word_timestamps=True, vad_filter=True,
                                      initial_prompt=prompt[:800] if prompt else None)
    words = []
    for seg in segments:
        for w in seg.words or []:
            words.append({"text": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3)})
        print(f"  {seg.end:6.1f}s / {info.duration:.1f}s", end="\r")
    print()
    return words


# ---------- alignment ----------

def norm(token: str) -> str:
    return re.sub(r"[^a-z0-9]", "", token.lower())


def align(script_lines: dict[int, str], heard: list[dict]) -> tuple[list[dict], float]:
    """Give every script word a time taken from the transcript.

    Script spelling wins (fixes accent errors and jargon); timing comes from the recording.
    Words the recogniser missed are interpolated between their neighbours.
    """
    words = [{"text": tok, "line": n} for n, text in script_lines.items() for tok in text.split()]
    a = [norm(w["text"]) for w in words]
    b = [norm(w["text"]) for w in heard]
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                words[i1 + k]["start"], words[i1 + k]["end"] = heard[j1 + k]["start"], heard[j1 + k]["end"]
        elif tag == "replace":
            # Spread the heard span evenly over the script words it replaces.
            start, end = heard[j1]["start"], heard[j2 - 1]["end"]
            step = (end - start) / (i2 - i1)
            for k in range(i2 - i1):
                words[i1 + k]["start"] = round(start + k * step, 3)
                words[i1 + k]["end"] = round(start + (k + 1) * step, 3)
    _interpolate(words, heard[-1]["end"] if heard else 0.0)
    matched = sum(size for _, _, size in matcher.get_matching_blocks())
    ratio = matched / max(len(a), 1)
    return words, round(ratio, 3)


def _interpolate(words: list[dict], total_end: float) -> None:
    i = 0
    while i < len(words):
        if "start" in words[i]:
            i += 1
            continue
        j = i
        while j < len(words) and "start" not in words[j]:
            j += 1
        left = words[i - 1]["end"] if i > 0 else 0.0
        right = words[j]["start"] if j < len(words) else max(total_end, left)
        step = max(right - left, 0.0) / (j - i)
        for k in range(i, j):
            words[k]["start"] = round(left + (k - i) * step, 3)
            words[k]["end"] = round(left + (k - i + 1) * step, 3)
        i = j


def words_from_transcript(heard: list[dict], gap: float = 0.7) -> list[dict]:
    """Transcript mode: split into pseudo-lines at sentence ends or long pauses."""
    out, line = [], 1
    for i, w in enumerate(heard):
        out.append({**w, "line": line})
        nxt = heard[i + 1] if i + 1 < len(heard) else None
        if nxt and (re.search(r"[.!?]$", w["text"]) or nxt["start"] - w["end"] > gap):
            line += 1
    return out


def line_times(words: list[dict], duration: float) -> list[dict]:
    """Each line runs from its first word to the next line's first word, so cuts land on speech."""
    by_line: dict[int, list[dict]] = {}
    for w in words:
        by_line.setdefault(w["line"], []).append(w)
    numbers = sorted(by_line)
    out = []
    for idx, n in enumerate(numbers):
        ws = by_line[n]
        start = 0.0 if idx == 0 else ws[0]["start"]
        end = by_line[numbers[idx + 1]][0]["start"] if idx + 1 < len(numbers) else duration
        out.append({"n": n, "text": " ".join(w["text"] for w in ws), "start": round(start, 3),
                    "end": round(max(end, start), 3)})
    return out


# ---------- caption chunks ----------

def chunk(words: list[dict], max_words: int, max_gap: float = 0.6, max_dur: float = 3.0) -> list[list[dict]]:
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if (nxt is None or len(cur) >= max_words or PUNCT_BREAK.search(w["text"])
                or nxt["line"] != w["line"] or nxt["start"] - w["end"] > max_gap
                or w["end"] - cur[0]["start"] >= max_dur):
            chunks.append(cur)
            cur = []
    return chunks


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ass_time(t: float) -> str:
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def _chunk_end(chunks: list[list[dict]], i: int) -> float:
    end = chunks[i][-1]["end"] + 0.25
    if i + 1 < len(chunks):
        end = min(end, chunks[i + 1][0]["start"])
    return max(end, chunks[i][-1]["start"] + 0.05)


def to_srt(chunks: list[list[dict]]) -> str:
    blocks = []
    for i, c in enumerate(chunks):
        text = " ".join(w["text"] for w in c)
        blocks.append(f"{i + 1}\n{srt_time(c[0]['start'])} --> {srt_time(_chunk_end(chunks, i))}\n{text}\n")
    return "\n".join(blocks)


def to_ass(chunks: list[list[dict]], fmt: str, upper: bool = False, style: str = "paper") -> str:
    width, height, size, _, margin_v = FORMATS[fmt]
    st = STYLES[style]
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{size},{st['primary']},{st['primary']},{st['outline']},{st['back']},-1,0,0,0,100,100,0,0,{st['border']},{st['outline_w'](size)},{st['shadow']},2,80,80,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for ci, c in enumerate(chunks):
        texts = [ass_escape(w["text"].upper() if upper else w["text"]) for w in c]
        chunk_end = _chunk_end(chunks, ci)
        for wi, w in enumerate(c):
            # One event per spoken word, with that word highlighted.
            start = c[0]["start"] if wi == 0 else w["start"]
            end = c[wi + 1]["start"] if wi + 1 < len(c) else chunk_end
            if end <= start:
                end = start + 0.05
            parts = [f"{{\\c{st['highlight']}}}{t}{{\\r}}" if k == wi else t for k, t in enumerate(texts)]
            events.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{' '.join(parts)}")
    return head + "\n".join(events) + "\n"


# ---------- CLI ----------

def main(argv: list[str] | None = None) -> None:
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video_id")
    p.add_argument("--model", default="small", help="tiny, base, small (default), medium")
    p.add_argument("--mode", choices=("script", "transcript"), default="script")
    p.add_argument("--reuse", action="store_true", help="use cached transcript.json")
    p.add_argument("--upper", action="store_true", help="UPPERCASE captions on the vertical cut")
    p.add_argument("--style", choices=list(STYLES), default="paper", help="paper (default) or bold")
    args = p.parse_args(argv)

    folder = video_dir(args.video_id)
    audio = find_voice(folder)
    if not audio:
        raise SystemExit(f"No voice recording in {folder} (expected voice.wav, .m4a or .mp3).")
    script = scriptmd.load(folder / "script.md") if args.mode == "script" else None
    duration = probe_duration(audio)

    cache = folder / "transcript.json"
    if args.reuse and cache.exists():
        heard = json.loads(cache.read_text(encoding="utf-8"))
    else:
        prompt = " ".join(script["lines"].values()) if script else None
        heard = transcribe(audio, args.model, prompt)
        cache.write_text(json.dumps(heard, indent=1, ensure_ascii=False), encoding="utf-8")
    if not heard:
        raise SystemExit("No speech detected. Check the recording level.")

    if script:
        words, ratio = align(script["lines"], heard)
        print(f"Script match: {ratio:.0%} of script words heard")
        if ratio < 0.6:
            print("WARNING: recording differs a lot from script.md. Re-record, update the script, "
                  "or rerun with --mode transcript.")
    else:
        words, ratio = words_from_transcript(heard), None

    lines = line_times(words, duration)
    (folder / "lines.json").write_text(json.dumps(
        {"duration": round(duration, 3), "mode": args.mode, "match_ratio": ratio, "lines": lines, "words": words},
        indent=1, ensure_ascii=False), encoding="utf-8")
    (folder / "captions.srt").write_text(to_srt(chunk(words, 8)), encoding="utf-8")
    for fmt, spec in FORMATS.items():
        text = to_ass(chunk(words, spec[3]), fmt, upper=args.upper and fmt == "9x16", style=args.style)
        (folder / f"captions_{fmt}.ass").write_text(text, encoding="utf-8")

    print(f"{len(lines)} lines, {len(words)} words, {duration:.1f}s. Wrote lines.json, captions.srt, captions_*.ass")
    _mark(args.video_id, "captioned")
    print(f"Next: fill media/{args.video_id}/timeline.json, then python scripts/cut.py render {args.video_id}")


def _mark(video_id: str, status: str) -> None:
    import db
    con = db.connect()
    if con.execute("SELECT 1 FROM videos WHERE id = ?", (video_id,)).fetchone():
        db.set_video_status(con, video_id, status)


if __name__ == "__main__":
    main()
