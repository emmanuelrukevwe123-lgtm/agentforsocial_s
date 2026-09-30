"""Rough cut from timeline.json: 1080x1920 for Shorts/TikTok and 1920x1080 for YouTube.

  python scripts/cut.py init <id>                 timeline.json from script.md, one segment per line
  python scripts/cut.py render <id>               both formats, captions burned in, voice loudness-normalised
  python scripts/cut.py render <id> --draft       half resolution, fast, for checking sync
  python scripts/cut.py render <id> --only 9x16

timeline.json:
  {"fps": 30, "background": "#0b1220",
   "segments": [
     {"lines": [1, 2], "clip": "screen/rls.mp4", "from": 3.5, "speed": 1.0,
      "vertical": {"layout": "crop", "crop": [420, 0, 1080, 1080]}, "horizontal": {"layout": "fit"}},
     {"line": 3, "clip": "screen/diagram.png"}]}

Each segment covers one or more script lines and lasts from its first line's start to the next
segment's start (timings from lines.json, written by captions.py). Layouts: blur (default for 9:16,
fitted over a blurred copy), fit (default for 16:9, padded), fill (centre crop), crop ([x, y, w, h]
in source pixels, then fitted). A missing clip renders a plain background so you can check timing
before recording visuals.

Music: the first audio file in media/<id>/Music/ (or timeline "music": {"file", "level", "start"})
is levelled to -30 LUFS, looped with a crossfade if short, faded, and ducked under the voice.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.config import DATA_DIR, utf8_stdout, video_dir  # noqa: E402
from common.media import AUDIO_EXTS, IMAGE_EXTS, find_voice, probe_duration, run_ffmpeg  # noqa: E402

import scriptmd  # noqa: E402

FORMATS = {"9x16": (1080, 1920, "vertical", "blur"), "16x9": (1920, 1080, "horizontal", "fit")}


# ---------- timeline ----------

def init_timeline(video_id: str, force: bool = False) -> Path:
    folder = video_dir(video_id)
    path = folder / "timeline.json"
    if path.exists() and not force:
        raise SystemExit(f"{path} exists. Use --force to overwrite.")
    script = scriptmd.load(folder / "script.md")
    clips = sorted(str(p.relative_to(folder)).replace("\\", "/") for p in (folder / "screen").glob("*")
                   if p.is_file())
    timeline = {
        "fps": 30,
        "background": "#0b1220",
        "_available_clips": clips,
        "segments": [{"line": n, "clip": None, "from": 0, "note": script["visuals"].get(n, "")}
                     for n in script["lines"]],
    }
    path.write_text(json.dumps(timeline, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def seg_lines(seg: dict) -> tuple[int, int]:
    if "lines" in seg:
        first, last = seg["lines"][0], seg["lines"][-1]
    elif "line" in seg:
        first = last = seg["line"]
    else:
        raise SystemExit(f"Segment needs 'line' or 'lines': {seg}")
    return int(first), int(last)


def segment_times(segments: list[dict], lines: list[dict], total: float) -> list[tuple[float, float]]:
    """(start, duration) per segment. Segments tile the whole voice track with no gaps."""
    starts = {ln["n"]: ln["start"] for ln in lines}
    firsts = []
    for seg in segments:
        first, _ = seg_lines(seg)
        if first not in starts:
            raise SystemExit(f"Line {first} is not in lines.json. Re-run captions.py after editing script.md.")
        firsts.append(starts[first])
    if firsts != sorted(firsts):
        raise SystemExit("Segments must be in script order.")
    firsts[0] = 0.0
    out = []
    for i, start in enumerate(firsts):
        end = firsts[i + 1] if i + 1 < len(firsts) else total
        if end - start <= 0.04:
            raise SystemExit(f"Segment {i + 1} has no duration; merge it into its neighbour with 'lines'.")
        out.append((round(start, 3), round(end - start, 3)))
    covered = {n for seg in segments for n in range(seg_lines(seg)[0], seg_lines(seg)[1] + 1)}
    missing = sorted(set(starts) - covered)
    if missing:
        print(f"Note: lines {missing} have no segment of their own; the previous segment runs over them.")
    return out


# ---------- filter graph ----------

def hex_color(value: str) -> str:
    return "0x" + value.lstrip("#")


def layout_filter(layout: dict, w: int, h: int, bg: str, i: int) -> str:
    """Filter chain from [src{i}] to [lay{i}]."""
    kind = layout.get("layout", "fit")
    fit = f"scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2"
    pad = f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={bg}"
    if kind == "blur":
        return (f"[src{i}]split=2[b{i}][f{i}];"
                f"[b{i}]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=24:2,"
                f"eq=brightness=-0.12[bg{i}];[f{i}]{fit}[fg{i}];"
                f"[bg{i}][fg{i}]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2[lay{i}]")
    if kind == "fill":
        return f"[src{i}]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}[lay{i}]"
    if kind == "crop":
        x, y, cw, ch = layout["crop"]
        return f"[src{i}]crop={cw}:{ch}:{x}:{y},{fit},{pad}[lay{i}]"
    if kind == "fit":
        return f"[src{i}]{fit},{pad}[lay{i}]"
    raise SystemExit(f"Unknown layout {kind!r}")


def find_music(folder: Path, timeline: dict) -> dict | None:
    """timeline.json "music": {"file", "level" (LUFS, default -30), "start" (s into the track)},
    else the first audio file in the video's Music/ folder."""
    cfg = dict(timeline.get("music") or {})
    if cfg.get("file") is False:
        return None
    path = folder / cfg["file"] if cfg.get("file") else None
    if path is None:
        for sub in ("Music", "music"):
            files = sorted(p for p in (folder / sub).glob("*") if p.suffix.lower() in AUDIO_EXTS)
            if files:
                path = files[0]
                break
    if path is None or not path.exists():
        return None
    return {"path": path.relative_to(folder), "duration": probe_duration(path),
            "level": float(cfg.get("level", -30)), "start": float(cfg.get("start", 0))}


def music_chains(voice_idx: int, music_idx: int, music: dict, total: float, loudnorm: bool,
                 xfade: float = 2.0) -> list[str]:
    """Voice on top; music levelled, looped with a crossfade if too short, faded, and ducked under speech."""
    usable = music["duration"] - music["start"]
    copies = 1 if usable >= total else math.ceil((total - xfade) / (usable - xfade))
    voice_norm = "loudnorm=I=-16:TP=-2:LRA=11,aresample=48000," if loudnorm else ""
    chains = [f"[{voice_idx}:a]aresample=48000,{voice_norm}aformat=channel_layouts=stereo,asplit=2[vo][key]",
              f"[{music_idx}:a]atrim=start={music['start']:.3f},asetpts=PTS-STARTPTS,aresample=48000,"
              f"loudnorm=I={music['level']:.0f}:TP=-6,aresample=48000,aformat=channel_layouts=stereo"
              + (f",asplit={copies}" + "".join(f"[m{i}]" for i in range(copies)) if copies > 1 else "[m0]")]
    last = "m0"
    for i in range(1, copies):
        chains.append(f"[{last}][m{i}]acrossfade=d={xfade}[x{i}]")
        last = f"x{i}"
    fade_out = max(0.0, total - 2.5)
    chains.append(f"[{last}]afade=t=in:d=0.8,afade=t=out:st={fade_out:.3f}:d=2.5[mu]")
    chains.append("[mu][key]sidechaincompress=threshold=0.04:ratio=6:attack=15:release=400[duck]")
    master = ",loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000" if loudnorm else ""
    chains.append(f"[vo][duck]amix=inputs=2:duration=first:normalize=0{master}[aout]")
    return chains


def build_command(folder: Path, timeline: dict, times: list[tuple[float, float]], fmt: str, *,
                  voice: Path | None, total: float, draft: bool, captions: bool, loudnorm: bool,
                  out: Path, music: dict | None = None) -> list[str]:
    w, h, key, default_layout = FORMATS[fmt]
    if draft:
        w, h = w // 2, h // 2
    fps = int(timeline.get("fps", 30))
    bg = hex_color(timeline.get("background", "#0b1220"))
    inputs: list[str] = []
    chains: list[str] = []
    for i, (seg, (_, dur)) in enumerate(zip(timeline["segments"], times)):
        clip = seg.get("clip")
        if clip:
            clip = clip.replace("{fmt}", fmt)  # animate.py renders one clip per format
        speed = float(seg.get("speed", 1.0))
        if not clip:
            inputs += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", f"color=c={bg}:s={w}x{h}:r={fps}"]
        elif not (folder / clip).exists() and not Path(clip).is_absolute():
            raise SystemExit(f"Clip not found: {folder / clip}")
        elif Path(clip).suffix.lower() in IMAGE_EXTS:
            inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", clip]
        else:
            inputs += ["-ss", f"{float(seg.get('from', 0)):.3f}", "-t", f"{dur * speed + 1:.3f}", "-i", clip]
        layout = {"layout": default_layout, **seg.get(key, {})}
        chains.append(f"[{i}:v]setpts=(PTS-STARTPTS)/{speed},fps={fps}[src{i}]")
        chains.append(layout_filter(layout, w, h, bg, i))
        chains.append(f"[lay{i}]tpad=stop_mode=clone:stop_duration={dur:.3f},trim=duration={dur:.3f},"
                      f"setpts=PTS-STARTPTS,format=yuv420p,setsar=1[v{i}]")
    n = len(times)
    concat = "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0"
    ass = folder / f"captions_{fmt}.ass"
    if captions and ass.exists():
        concat += f"[vc];[vc]ass={ass.name}"  # relative name: cwd is the video folder (no drive colon to escape)
    elif captions:
        print(f"Note: {ass.name} missing, rendering without captions. Run captions.py first.")
    chains.append(concat + "[vout]")
    maps = ["-map", "[vout]"]
    if voice:
        inputs += ["-i", str(voice)]
        if music:
            inputs += ["-i", str(music["path"])]
            chains += music_chains(n, n + 1, music, total, loudnorm)
        else:
            audio = "loudnorm=I=-14:TP=-1.5:LRA=11," if loudnorm else ""
            chains.append(f"[{n}:a]{audio}aresample=48000[aout]")
        maps += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
    preset, crf = ("ultrafast", "28") if draft else ("medium", "20")
    return [*inputs, "-filter_complex", ";".join(chains), *maps,
            "-c:v", "libx264", "-preset", preset, "-crf", crf, "-pix_fmt", "yuv420p", "-r", str(fps),
            "-movflags", "+faststart", "-t", f"{total:.3f}", str(out)]


def fontconfig_env() -> dict[str, str]:
    """The bundled Windows FFmpeg uses fontconfig, which needs to be told where Windows keeps fonts."""
    env = dict(os.environ)
    if os.name != "nt" or "FONTCONFIG_FILE" in env:
        return env
    conf = DATA_DIR / "fonts.conf"
    if not conf.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        windir = os.environ.get("WINDIR", "C:/Windows").replace("\\", "/")
        user_fonts = (Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Windows/Fonts").as_posix()
        conf.write_text(f"""<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>{windir}/Fonts</dir>
  <dir>{user_fonts}</dir>
  <cachedir>{(DATA_DIR / 'fontcache').as_posix()}</cachedir>
</fontconfig>
""", encoding="utf-8")
    env["FONTCONFIG_FILE"] = str(conf)
    return env


# ---------- CLI ----------

def render(video_id: str, only: str | None, draft: bool, captions: bool, loudnorm: bool,
           use_music: bool = True) -> list[Path]:
    folder = video_dir(video_id)
    tl_path = folder / "timeline.json"
    if not tl_path.exists():
        raise SystemExit(f"No timeline.json. Run: python scripts/cut.py init {video_id}")
    timeline = json.loads(tl_path.read_text(encoding="utf-8"))
    if not timeline.get("segments"):
        raise SystemExit("timeline.json has no segments.")
    lines_path = folder / "lines.json"
    voice = find_voice(folder)
    if lines_path.exists():
        lines = json.loads(lines_path.read_text(encoding="utf-8"))
        total = lines["duration"]
        times = segment_times(timeline["segments"], lines["lines"], total)
    elif all("duration" in s for s in timeline["segments"]):
        # Silent preview before the voice is recorded.
        times, t = [], 0.0
        for s in timeline["segments"]:
            times.append((t, float(s["duration"])))
            t += float(s["duration"])
        total, voice = t, None
    else:
        raise SystemExit(f"No lines.json. Run: python scripts/captions.py {video_id}")

    if all("duration" in s for s in timeline["segments"]) and not lines_path.exists():
        captions = False
    music = find_music(folder, timeline) if use_music and voice else None
    if music:
        print(f"Music: {music['path']} ({music['duration']:.1f}s, {music['level']:.0f} LUFS, ducked under the voice)")
    (folder / "out").mkdir(exist_ok=True)
    outputs = []
    for fmt in ([only] if only else FORMATS):
        out = Path("out") / f"{video_id}_{fmt}{'_draft' if draft else ''}.mp4"
        print(f"Rendering {out} ({total:.1f}s, {len(times)} segments)...")
        args = build_command(folder, timeline, times, fmt, voice=voice.relative_to(folder) if voice else None,
                             total=total, draft=draft, captions=captions, loudnorm=loudnorm, out=out, music=music)
        os.environ.update(fontconfig_env())
        run_ffmpeg(args, cwd=folder)
        outputs.append(folder / out)
    return outputs


def main(argv: list[str] | None = None) -> None:
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init")
    s.add_argument("video_id")
    s.add_argument("--force", action="store_true")
    s = sub.add_parser("render")
    s.add_argument("video_id")
    s.add_argument("--only", choices=list(FORMATS))
    s.add_argument("--draft", action="store_true")
    s.add_argument("--no-captions", action="store_true")
    s.add_argument("--no-loudnorm", action="store_true", help="keep your own mastering")
    s.add_argument("--no-music", action="store_true")
    args = p.parse_args(argv)

    if args.cmd == "init":
        path = init_timeline(args.video_id, args.force)
        print(f"Wrote {path}. Set 'clip' for each segment (files from screen/), merge lines with \"lines\": [a, b].")
        return
    outputs = render(args.video_id, args.only, args.draft, not args.no_captions, not args.no_loudnorm,
                     not args.no_music)
    for o in outputs:
        print(f"Done: {o}")
    if not args.draft:
        import db
        con = db.connect()
        if con.execute("SELECT 1 FROM videos WHERE id = ?", (args.video_id,)).fetchone():
            db.set_video_status(con, args.video_id, "cut")
        print(f"Next: /package {args.video_id}")


if __name__ == "__main__":
    main()
