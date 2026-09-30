"""Thumbnail: a frame grab plus big text. 1280x720 PNG for YouTube.

  python scripts/thumb.py <id>                           frame at 2s of the first timeline clip, text from package.json
  python scripts/thumb.py <id> --src screen/scan.mp4 --at 14.5 --text "ZERO NAIRA"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.config import utf8_stdout, video_dir  # noqa: E402
from common.media import IMAGE_EXTS, run_ffmpeg  # noqa: E402

SIZE = (1280, 720)
FONT_CANDIDATES = ["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"]


def load_font(size: int):
    from PIL import ImageFont
    windir = os.environ.get("WINDIR", "C:/Windows")
    for name in FONT_CANDIDATES:
        for path in (Path(windir) / "Fonts" / name, Path(name)):
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def grab_frame(src: Path, at: float, dest: Path) -> None:
    run_ffmpeg(["-ss", f"{at:.2f}", "-i", str(src), "-frames:v", "1", str(dest)])


def compose(frame: Path, text: str, out: Path) -> None:
    from PIL import Image, ImageDraw, ImageOps

    img = ImageOps.fit(Image.open(frame).convert("RGB"), SIZE)
    shade = Image.new("L", SIZE)
    shade_draw = ImageDraw.Draw(shade)
    for x in range(SIZE[0]):  # left-to-right dark gradient so text reads on any frame
        shade_draw.line((x, 0, x, SIZE[1]), fill=int(190 * max(0.0, 1 - x / (SIZE[0] * 0.75))))
    img = Image.composite(Image.new("RGB", SIZE, (0, 0, 0)), img, shade)

    draw = ImageDraw.Draw(img)
    lines = textwrap.wrap(text.upper(), width=12)[:3]
    size = 150 if len(lines) <= 2 else 120
    font = load_font(size)
    y = SIZE[1] - 60 - len(lines) * int(size * 1.05)
    for i, line in enumerate(lines):
        fill = (255, 212, 0) if i == len(lines) - 1 else (255, 255, 255)
        draw.text((60, y), line, font=font, fill=fill, stroke_width=8, stroke_fill=(0, 0, 0))
        y += int(size * 1.05)
    img.save(out, optimize=True)


def default_source(folder: Path) -> Path | None:
    """First clip in the timeline (a raw frame has no burned-in captions), else any file in screen/."""
    timeline = folder / "timeline.json"
    if timeline.exists():
        for seg in json.loads(timeline.read_text(encoding="utf-8")).get("segments", []):
            clip = (seg.get("clip") or "").replace("{fmt}", "16x9")
            if clip and (folder / clip).exists():
                return folder / clip
    return next((p for p in sorted((folder / "screen").glob("*")) if p.is_file()), None)


def main(argv: list[str] | None = None) -> None:
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video_id")
    p.add_argument("--src", help="video or image inside the video folder")
    p.add_argument("--at", type=float, default=2.0, help="seconds into the video")
    p.add_argument("--text")
    args = p.parse_args(argv)

    folder = video_dir(args.video_id)
    text = args.text
    pkg = folder / "package.json"
    if not text and pkg.exists():
        text = json.loads(pkg.read_text(encoding="utf-8")).get("thumbnail_text")
    if not text:
        raise SystemExit("No text. Pass --text or run /package first (it sets thumbnail_text).")
    src = folder / args.src if args.src else default_source(folder)
    if not src or not src.exists():
        raise SystemExit(f"Source not found: {src}")

    out = folder / "thumbnail.png"
    if src.suffix.lower() in IMAGE_EXTS:
        compose(src, text, out)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            frame = Path(tmp) / "frame.png"
            grab_frame(src, args.at, frame)
            compose(frame, text, out)
    print(f"Wrote {out}. Tweak it in Photopea or GIMP if needed.")


if __name__ == "__main__":
    main()
