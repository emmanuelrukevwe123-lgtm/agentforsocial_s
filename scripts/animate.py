"""Paper-cut motion design from media/<id>/scenes.json. No filming: every visual is generated.

  python scripts/animate.py vocab                      icons, text styles, motions, colours (for /scenes)
  python scripts/animate.py render <id>                every scene, both formats, then writes timeline.json
  python scripts/animate.py render <id> --line 3       only the scene that starts at line 3
  python scripts/animate.py still <id> --line 3 --at 1.2 [--fmt 9x16]   one PNG frame, for checking a layout

Rendered in stop-motion at 12 fps (on twos, with a slight "boil"). Timing comes from lines.json
(captions.py) so pieces land on the spoken word; before the voice is recorded it is estimated.

Each scene has a moving background (a scrolling paper pattern plus drifting paper confetti) and a
torn-paper transition in from the previous scene. Elements enter, can move to new spots (and fly in an arc),
exit, and knock each other: a piece that slams or drops shakes its neighbours and the camera.

scenes.json:
  {"seed": 7, "scenes": [
    {"line": 1, "bg": "cream", "pattern": "stripes", "floaters": 14, "transition": "iris", "camera": "push",
     "elements": [
      {"type": "icon", "name": "calendar", "x": 0.3, "y": 0.42, "size": 0.38, "enter": "drop", "at_word": "fourteen"},
      {"type": "text", "text": "14 DAYS", "style": "ransom", "x": 0.5, "y": 0.8, "size": 0.12, "enter": "pop",
       "moves": [{"at_word": "naira", "x": 0.5, "y": 0.6, "scale": 1.3, "arc": 0.1, "impact": true}],
       "exit": {"at_word": "spending", "type": "fly-left"}},
      {"type": "text", "text": "₦0", "style": "stamp", "color": "red", "x": 0.72, "y": 0.35, "size": 0.16,
       "enter": "slam", "at": 2.0},
      {"type": "image", "src": "pexels:lagos skyline", "treatment": "duotone", "x": 0.5, "y": 0.5, "w": 0.6, "h": 0.4}]}]}
x, y are the element centre inside the square stage (0..1). size is the icon width or text height as a
fraction of the stage. A scene covers "line": n or "lines": [a, b]. Unset patterns and transitions rotate
through the lists so no two neighbouring scenes look the same.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.config import ROOT, utf8_stdout, video_dir  # noqa: E402
from common.media import ffmpeg_exe  # noqa: E402

import cut  # noqa: E402
import scriptmd  # noqa: E402

FPS = 12
# Frame size and the square stage (x, y, side) inside it. The stage sits above the captions.
FORMATS = {"9x16": ((1080, 1920), (40, 290, 1000)), "16x9": ((1920, 1080), (530, 30, 880))}
ENTERS = ("pop", "drop", "slam", "slide-left", "slide-right", "slide-up", "unfold", "spin-in", "none")
EXITS = ("pop", "shrink", "fly-left", "fly-right", "fly-up", "fall")
IDLES = ("none", "float", "spin", "pulse", "wiggle")
TEXT_STYLES = ("cutout", "strip", "ransom", "stamp")
TREATMENTS = ("duotone", "halftone", "polaroid", "torn")
CAMERAS = ("none", "push", "drift")
TRANSITIONS = ("slide-left", "slide-right", "slide-up", "drop", "push-left", "push-up", "wipe", "iris", "blinds",
               "flip", "cut")
DEFAULT_TRANSITIONS = ("slide-left", "iris", "push-up", "wipe", "blinds", "drop", "flip", "slide-right",
                       "push-left", "slide-up")
DEFAULT_PATTERNS = ("stripes", "dots", "zigzag", "diamonds", "rays", "plus", "waves")


# ---------- easing ----------

def back_out(p: float, s: float = 1.9) -> float:
    p -= 1
    return 1 + (s + 1) * p ** 3 + s * p ** 2


def bounce_out(p: float) -> float:
    n, d = 7.5625, 2.75
    if p < 1 / d:
        return n * p * p
    if p < 2 / d:
        p -= 1.5 / d
        return n * p * p + 0.75
    if p < 2.5 / d:
        p -= 2.25 / d
        return n * p * p + 0.9375
    p -= 2.625 / d
    return n * p * p + 0.984375


def smooth(p: float) -> float:
    p = min(1.0, max(0.0, p))
    return p * p * (3 - 2 * p)


# ---------- timing ----------

def norm(token: str) -> str:
    return re.sub(r"[^a-z0-9]", "", token.lower())


def load_timing(folder: Path) -> tuple[list[dict], list[dict], float, bool]:
    """(lines, words, total seconds, real). Estimated from the script until captions.py has run."""
    lines_path = folder / "lines.json"
    if lines_path.exists():
        data = json.loads(lines_path.read_text(encoding="utf-8"))
        return data["lines"], data["words"], data["duration"], True
    script = scriptmd.load(folder / "script.md")
    lines, words, t = [], [], 0.0
    for n, text in script["lines"].items():
        toks = text.split()
        dur = len(toks) / scriptmd.WORDS_PER_SECOND + 0.35
        lines.append({"n": n, "text": text, "start": round(t, 3), "end": round(t + dur, 3)})
        for i, tok in enumerate(toks):
            words.append({"text": tok, "line": n, "start": round(t + i / scriptmd.WORDS_PER_SECOND, 3)})
        t += dur
    return lines, words, round(t, 3), False


def element_start(el: dict, scene_lines: tuple[int, int], words: list[dict], scene_start: float) -> float:
    """Seconds into the scene for anything with "at" or "at_word" (elements, moves, exits)."""
    if "at_word" in el:
        key = norm(str(el["at_word"]))
        for w in words:
            if scene_lines[0] <= w["line"] <= scene_lines[1] and key and key in norm(w["text"]):
                return max(0.0, w["start"] - scene_start - 0.08)  # land a beat before the word
        print(f"  note: word {el['at_word']!r} not found in lines {scene_lines}; using 'at'")
    return float(el.get("at", 0.0))


# ---------- sprites ----------

def build_sprite(el: dict, stage: int, folder: Path, seed: int, credits: list[str], value: str | None = None):
    import papercut as pc

    kind = el.get("type", "icon")
    if kind == "icon":
        return pc.icon_sprite(el["name"], max(16, round(el.get("size", 0.3) * stage)), el.get("recolor"))
    if kind == "text":
        return pc.text_sprite(value if value is not None else el["text"], el.get("style", "cutout"),
                              max(12, round(el.get("size", 0.1) * stage)), el.get("color", "navy"),
                              el.get("paper", "cream"), el.get("font"), seed)
    if kind == "image":
        path = resolve_image(el["src"], folder, credits)
        w, h = max(16, round(el.get("w", 0.5) * stage)), max(16, round(el.get("h", 0.4) * stage))
        if path is None:
            return pc.shape_sprite([("kraft", [("rect", 0, 0, 1, 1)]),
                                    ("grey", [("poly", [(.1, .85), (.4, .45), (.6, .7), (.75, .55), (.9, .85)]),
                                              ("ellipse", .65, .15, .8, .3)])], w, h)
        return pc.photo_sprite(path, w, h, el.get("treatment", "duotone"), el.get("ink", "navy"), el.get("paper", "cream"))
    raise SystemExit(f"Unknown element type {kind!r}")


def resolve_image(src: str, folder: Path, credits: list[str]) -> Path | None:
    if src.startswith("pexels:"):
        import stock
        hit = stock.fetch(src.split(":", 1)[1].strip())
        if hit is None:
            print(f"  note: no photo for {src!r} (set PEXELS_API_KEY in .env); drawing a placeholder")
            return None
        credit = f"Photo by {hit['photographer']} on Pexels: {hit['url']}"
        if credit not in credits:
            credits.append(credit)
        return Path(hit["file"])
    for base in (folder, ROOT):
        if (base / src).exists():
            return base / src
    raise SystemExit(f"Image not found: {src}")


def counter_value(el: dict, t: float) -> str:
    a, b = el["count"]
    p = min(1.0, max(0.0, t / float(el.get("count_dur", 1.2))))
    p = 1 - (1 - p) ** 3
    v = round(a + (b - a) * p)
    return f"{el.get('prefix', '')}{v:,}{el.get('suffix', '')}"


# ---------- element motion ----------

def impacts_for(scene: dict) -> list[dict]:
    """Moments where a piece lands hard: they shake nearby pieces and the camera."""
    out = []
    for i, el in enumerate(scene.get("elements", [])):
        enter = el.get("enter", "pop")
        if enter in ("slam", "drop") and el.get("impact", True):
            land = el["_start"] + float(el.get("dur", 0.5)) * (1.0 if enter == "slam" else 0.364)
            out.append({"t": land, "x": el.get("x", .5), "y": el.get("y", .5), "src": i,
                        "power": 1.0 if enter == "slam" else 0.7})
        x, y = el.get("x", .5), el.get("y", .5)
        for m in el.get("moves", []):
            x, y = m.get("x", x), m.get("y", y)
            if m.get("impact"):
                out.append({"t": m["_start"] + float(m.get("dur", 0.6)) * 0.75, "x": x, "y": y, "src": i, "power": 0.85})
    return out


def transform(el: dict, t: float, frame: int, idx: int, seed: int, stage_xy: tuple[int, int, int],
              size: tuple[int, int], impacts: list[dict] = ()):
    """Position, scale (x, y) and rotation of one element at time t (seconds into the scene), or None if hidden."""
    sx0, sy0, side = stage_xy
    start = el["_start"]
    if t < start:
        return None
    # Resting state, then any moves in order.
    x, y = el.get("x", 0.5), el.get("y", 0.5)
    scale, rot = float(el.get("scale", 1.0)), float(el.get("rotate", 0))
    for m in el.get("moves", []):
        if t < m["_start"]:
            break
        p = min(1.0, (t - m["_start"]) / float(m.get("dur", 0.6)))
        e = smooth(p) if m.get("ease") == "smooth" else back_out(p, 1.3)
        tx, ty = m.get("x", x), m.get("y", y)
        ts, tr = float(m.get("scale", scale)), float(m.get("rotate", rot))
        lift = float(m.get("arc", 0)) * math.sin(math.pi * p)
        x, y, scale, rot = x + (tx - x) * e, y + (ty - y) * e - lift, scale + (ts - scale) * e, rot + (tr - rot) * e
    X, Y = sx0 + x * side, sy0 + y * side
    scale_x = scale_y = scale

    p = min(1.0, (t - start) / float(el.get("dur", 0.5)))
    enter = el.get("enter", "pop")
    if enter == "pop":
        scale_x = scale_y = scale * back_out(p)
    elif enter == "drop":
        Y -= (1 - bounce_out(p)) * (Y + size[1])
    elif enter == "slam":
        s = 1 + 1.4 * (1 - p) ** 2
        scale_x = scale_y = scale * (s if p < 1 else 1)
    elif enter == "slide-left":
        X -= (1 - back_out(p, 1.2)) * (X + size[0])
    elif enter == "slide-right":
        X += (1 - back_out(p, 1.2)) * (sx0 + side * 2 - X + size[0])
    elif enter == "slide-up":
        Y += (1 - back_out(p, 1.2)) * (sy0 + side * 1.4 - Y + size[1])
    elif enter == "unfold":
        scale_y = scale * back_out(p)
    elif enter == "spin-in":
        scale_x = scale_y = scale * back_out(p)
        rot -= (1 - p) * 200

    # Squash on its own landing.
    if enter in ("slam", "drop"):
        dt = t - (start + float(el.get("dur", 0.5)) * (1.0 if enter == "slam" else 0.364))
        if 0 <= dt < 0.25:
            k = 1 - dt / 0.25
            scale_x, scale_y = scale_x * (1 + 0.14 * k), scale_y * (1 - 0.18 * k)

    idle = el.get("idle", "none")
    held = t - start
    if idle == "float":
        Y += math.sin(held * 2 * math.pi / 2.6) * side * 0.012
    elif idle == "spin":
        rot -= held * float(el.get("speed", 25))
    elif idle == "pulse":
        k = 1 + 0.045 * math.sin(held * 2 * math.pi * 1.4)
        scale_x, scale_y = scale_x * k, scale_y * k
    elif idle == "wiggle":
        rot += 5 * math.sin(held * 2 * math.pi * 1.8)

    # Knocked by other pieces landing nearby: hop, jiggle, tilt.
    for imp in impacts:
        dt = t - imp["t"]
        if imp["src"] == idx or not 0 <= dt < 0.45:
            continue
        dist = math.hypot(X - (sx0 + imp["x"] * side), Y - (sy0 + imp["y"] * side))
        k = imp["power"] * max(0.2, 1 - dist / (side * 0.9)) * (1 - dt / 0.45)
        rnd = random.Random(f"{seed}:{idx}:{frame}:hit")
        a = side * 0.022 * k
        X, Y, rot = X + rnd.uniform(-a, a), Y + rnd.uniform(-a, a) - a * 0.7, rot + rnd.uniform(-6, 6) * k

    ex = el.get("exit")
    if ex and t >= ex["_start"]:
        p = min(1.0, (t - ex["_start"]) / float(ex.get("dur", 0.4)))
        if p >= 1:
            return None
        kind, q = ex.get("type", "pop"), p * p
        if kind == "pop":
            k = max(0.0, 1 + 0.2 * math.sin(math.pi * min(p * 2, 1)) - q * 1.2)
            scale_x, scale_y = scale_x * k, scale_y * k
        elif kind == "shrink":
            scale_x, scale_y = scale_x * (1 - q), scale_y * (1 - q)
        elif kind == "fly-left":
            X -= q * (X + size[0] + side * 0.2)
        elif kind == "fly-right":
            X += q * (sx0 + side * 2.2 - X + size[0])
        elif kind == "fly-up":
            Y -= q * (Y + size[1] + side * 0.2)
        elif kind == "fall":
            Y += q * side * 1.8
            rot += p * 70

    # Boil: tiny jitter that changes every other frame, like pieces nudged by hand between shots.
    rnd = random.Random(f"{seed}:{idx}:{frame // 2}")
    j = side * 0.0028
    return X + rnd.uniform(-j, j), Y + rnd.uniform(-j, j), scale_x, scale_y, rot + rnd.uniform(-0.7, 0.7)


def camera_shake(impacts: list[dict], t: float, frame: int, side: int, seed: int) -> tuple[float, float]:
    dx = dy = 0.0
    for imp in impacts:
        dt = t - imp["t"]
        if 0 <= dt < 0.3 and imp["power"] >= 0.8:
            a = side * 0.012 * imp["power"] * (1 - dt / 0.3)
            rnd = random.Random(f"{seed}:{frame}:cam")
            dx, dy = dx + rnd.uniform(-a, a), dy + rnd.uniform(-a, a)
    return dx, dy


# ---------- background ----------

class MovingBackground:
    """Scrolling paper pattern (or a turning sunburst) plus drifting paper confetti, updated on twos."""

    def __init__(self, size: tuple[int, int], scene: dict, seed: int):
        import papercut as pc
        from PIL import Image

        self.pc, self.Image = pc, Image
        self.w, self.h = size
        k = self.w / 1080 if self.w < self.h else self.h / 1080
        rnd = random.Random(seed)
        color = scene.get("bg", "cream")
        self.pattern = scene.get("pattern", "stripes")
        self.period = max(40, round(150 * k))
        speed = float(scene.get("bg_speed", 1.0))
        dx, dy = rnd.choice([(1, 1), (1, -1), (-1, 1), (1, 0.4), (0.4, 1), (-1, 0.5)])
        self.v = (dx * self.period * 0.5 * speed, dy * self.period * 0.5 * speed)
        self.base = pc.pattern_layer(self.w, self.h, color, self.pattern, self.period, seed)
        self.rays = None
        if self.pattern == "rays":
            self.rays_size = int(math.hypot(self.w, self.h) / 2) + 4
            self.rays = pc.rays_layer(self.rays_size, color)
            self.rays_dir = rnd.choice((-1, 1)) * 9 * speed
        colors = pc.accents(color) or ["navy", "red", "mustard"]
        self.floaters = []
        for _ in range(int(scene.get("floaters", 20))):
            shape = rnd.choice(list(pc.FLOATER_SHAPES))
            fill = rnd.choice(colors) if rnd.random() < 0.6 else pc.tone(color, rnd.choice((-40, 35)))
            px = max(10, round(rnd.uniform(0.04, 0.1) * 1080 * k))
            self.floaters.append({
                "sprite": pc.floater_sprite(shape, px, fill),
                "x": rnd.uniform(0, self.w), "y": rnd.uniform(0, self.h),
                "vx": rnd.uniform(-30, 30) * k * speed, "vy": rnd.uniform(-75, -25) * k * speed,
                "spin": rnd.uniform(-80, 80) * speed, "phase": rnd.uniform(0, 6.28), "sway": rnd.uniform(8, 26) * k,
            })
        self._cache: tuple[int, object] | None = None

    def frame(self, f: int):
        key = f // 2  # stop-motion: the background changes every other frame
        if self._cache and self._cache[0] == key:
            return self._cache[1].copy()
        tq = key * 2 / FPS
        ox, oy = int(tq * self.v[0]) % self.period, int(tq * self.v[1]) % self.period
        img = self.base.crop((ox, oy, ox + self.w, oy + self.h))
        if self.rays is not None:
            r = self.rays.rotate(tq * self.rays_dir, resample=self.Image.BICUBIC)
            r = r.resize((self.rays_size * 2, self.rays_size * 2), self.Image.BILINEAR)
            img.paste(r, (self.w // 2 - self.rays_size, int(self.h * 0.4) - self.rays_size), r)
        margin = 120
        for fl in self.floaters:
            x = (fl["x"] + fl["vx"] * tq + math.sin(tq * 1.3 + fl["phase"]) * fl["sway"]) % (self.w + 2 * margin) - margin
            y = (fl["y"] + fl["vy"] * tq) % (self.h + 2 * margin) - margin
            spr = fl["sprite"].rotate(fl["spin"] * tq, resample=self.Image.BILINEAR, expand=True)
            img.paste(spr, (int(x - spr.width / 2), int(y - spr.height / 2)), spr)
        self._cache = (key, img)
        return img.copy()


# ---------- transitions ----------

def apply_transition(kind: str, prev, cur, p: float, seed: int):
    """Bring `cur` in over `prev` like paper: sheets slide, push, drop, tear open or flip."""
    import papercut as pc
    from PIL import Image, ImageDraw

    if prev is None or kind == "cut" or p >= 1:
        return cur
    w, h = cur.size
    e = smooth(p)
    n = 24
    jag = pc.torn_edge(n, max(w, h) * 0.018, seed)

    def mask(points):
        m = Image.new("L", (w, h), 0)
        ImageDraw.Draw(m).polygon(points, fill=255)
        return m

    def shifted(img, dx, dy):
        out = Image.new("RGB", (w, h))
        out.paste(img, (int(dx), int(dy)))
        return out

    def v_edge(x, keep_right):
        pts = [(x + jag[i], -50 + (h + 100) * i / n) for i in range(n + 1)]
        return pts + ([(w + 60, h + 50), (w + 60, -50)] if keep_right else [(-60, h + 50), (-60, -50)])

    def h_edge(y, keep_below):
        pts = [(-50 + (w + 100) * i / n, y + jag[i]) for i in range(n + 1)]
        return pts + ([(w + 50, h + 60), (-50, h + 60)] if keep_below else [(w + 50, -60), (-50, -60)])

    if kind == "slide-left":
        x = w * (1 - e)
        return pc.sheet_over(prev, shifted(cur, x, 0), mask(v_edge(x, True)))
    if kind == "slide-right":
        x = w * e
        return pc.sheet_over(prev, shifted(cur, x - w, 0), mask(v_edge(x, False)))
    if kind == "slide-up":
        y = h * (1 - e)
        return pc.sheet_over(prev, shifted(cur, 0, y), mask(h_edge(y, True)))
    if kind == "drop":
        y = h * bounce_out(min(1.0, p * 1.1))
        return pc.sheet_over(prev, shifted(cur, 0, y - h), mask(h_edge(y, False)))
    if kind == "push-left":
        x = w * (1 - e)
        return pc.sheet_over(shifted(prev, x - w, 0), shifted(cur, x, 0), mask(v_edge(x, True)))
    if kind == "push-up":
        y = h * (1 - e)
        return pc.sheet_over(shifted(prev, 0, y - h), shifted(cur, 0, y), mask(h_edge(y, True)))
    if kind == "wipe":
        pts = [(-0.35 * w + e * 1.7 * w - 0.35 * w * i / n + jag[i], -50 + (h + 100) * i / n) for i in range(n + 1)]
        return pc.sheet_over(prev, cur, mask(pts + [(-60, h + 50), (-60, -50)]))
    if kind == "iris":
        cx, cy, r = w / 2, h * 0.42, e * math.hypot(w, h) * 0.6
        pts = [(cx + (r + jag[i % (n + 1)] * 1.6) * math.cos(2 * math.pi * i / 48),
                cy + (r + jag[i % (n + 1)] * 1.6) * math.sin(2 * math.pi * i / 48)) for i in range(48)]
        return pc.sheet_over(prev, cur, mask(pts)) if r > 2 else prev
    if kind == "blinds":
        out, strips = prev, 6
        for i in range(strips):
            pi = min(1.0, max(0.0, p * 1.7 - i * 0.14))
            if pi <= 0:
                continue
            y = h * bounce_out(pi)
            x0, x1 = i * w / strips - 2, (i + 1) * w / strips + 2
            pts = [(x0, -60), (x1, -60)] + [(x1 - (x1 - x0) * k / 6, y + jag[(i * 4 + k) % (n + 1)]) for k in range(7)]
            out = pc.sheet_over(out, shifted(cur, 0, y - h), mask(pts))
        return out
    if kind == "flip":
        img, s = (prev, 1 - 2 * e) if e < 0.5 else (cur, 2 * e - 1)
        width = max(1, int(w * s))
        out = Image.new("RGB", (w, h), (58, 44, 30))
        out.paste(img.resize((width, h), Image.BILINEAR), ((w - width) // 2, 0))
        return out
    raise SystemExit(f"Unknown transition {kind!r}; choose from {TRANSITIONS}")


# ---------- frames ----------

def draw_frame(bg, placed: list, camera: str, t: float, dur: float, shake: tuple[float, float] = (0, 0)):
    from PIL import Image

    frame = bg
    for sprite, (x, y, sx, sy, rot) in placed:
        if sx < 0.02 or sy < 0.02:
            continue
        if abs(sx - 1) > 0.01 or abs(sy - 1) > 0.01:
            sprite = sprite.resize((max(1, round(sprite.width * sx)), max(1, round(sprite.height * sy))), Image.BILINEAR)
        if abs(rot) > 0.05:
            sprite = sprite.rotate(rot, resample=Image.BICUBIC, expand=True)
        frame.paste(sprite, (round(x - sprite.width / 2), round(y - sprite.height / 2)), sprite)
    shaking = abs(shake[0]) + abs(shake[1]) > 0.5
    if camera in ("push", "drift") or shaking:
        w, h = frame.size
        p = min(1.0, t / dur) if dur > 0 else 0
        z = {"push": 1 + 0.05 * p, "drift": 1.04}.get(camera, 1.03)
        cw, ch = w / z, h / z
        left = (w - cw) * (0.2 + 0.6 * p if camera == "drift" else 0.5) + shake[0]
        top = (h - ch) / 2 + shake[1]
        left, top = min(max(0, left), w - cw), min(max(0, top), h - ch)
        frame = frame.resize((w, h), Image.BICUBIC, box=(left, top, left + cw, top + ch))
    return frame


class SceneRenderer:
    def __init__(self, folder: Path, spec: dict, fmt: str, draft: bool = False):
        self.folder, self.spec, self.fmt = folder, spec, fmt
        (w, h), (sx, sy, side) = FORMATS[fmt]
        k = 0.5 if draft else 1.0
        self.size = (round(w * k) // 2 * 2, round(h * k) // 2 * 2)
        self.stage = (round(sx * k), round(sy * k), round(side * k))
        self.seed = int(spec.get("seed", 7))
        self.credits: list[str] = []
        self._cache: dict = {}

    def sprite(self, scene_key: int, idx: int, el: dict, value: str | None = None):
        key = (scene_key, idx, value)
        if key not in self._cache:
            sprite = build_sprite(el, self.stage[2], self.folder, self.seed + scene_key * 31 + idx, self.credits, value)
            limit = self.stage[2] * 1.02  # long text shrinks to fit the stage instead of running off screen
            if sprite.width > limit:
                from PIL import Image
                k = limit / sprite.width
                sprite = sprite.resize((round(sprite.width * k), round(sprite.height * k)), Image.LANCZOS)
            self._cache[key] = sprite
        return self._cache[key]

    def frames(self, scene: dict, dur: float, prev=None, only_at: float | None = None):
        scene_key = cut.seg_lines(scene)[0]
        bg = MovingBackground(self.size, scene, self.seed + scene_key * 97)
        els = scene.get("elements", [])
        impacts = scene.get("_impacts", [])
        n = max(1, math.ceil(dur * FPS))
        n_tr = max(1, round(float(scene.get("tdur", 0.55)) * FPS))
        frame_ids = [min(n - 1, int(only_at * FPS))] if only_at is not None else range(n)
        for f in frame_ids:
            t = f / FPS
            placed = []
            for i, el in enumerate(els):
                value = counter_value(el, t - el["_start"]) if el.get("type") == "text" and "count" in el else None
                sprite = self.sprite(scene_key, i, el, value)
                tr = transform(el, t, f, i, self.seed, self.stage, sprite.size, impacts)
                if tr:
                    placed.append((sprite, tr))
            shake = camera_shake(impacts, t, f, self.stage[2], self.seed)
            frame = draw_frame(bg.frame(f), placed, scene.get("camera", "none"), t, dur, shake)
            if prev is not None and f < n_tr:
                frame = apply_transition(scene.get("transition", "cut"), prev, frame, (f + 1) / n_tr,
                                         self.seed + scene_key)
            yield frame

    def last_frame(self, scene: dict, dur: float):
        return next(self.frames(scene, dur, None, only_at=dur))

    def render(self, scene: dict, dur: float, out: Path, prev=None):
        """Write one scene clip; returns its last frame for the next scene's transition."""
        out.parent.mkdir(parents=True, exist_ok=True)
        w, h = self.size
        cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-", "-vf", "fps=30", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "18", "-pix_fmt", "yuv420p", str(out)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        last = None
        try:
            for frame in self.frames(scene, dur, prev):
                proc.stdin.write(frame.tobytes())
                last = frame
        finally:
            proc.stdin.close()
        if proc.wait() != 0:
            raise SystemExit(f"FFmpeg failed writing {out}")
        return last


# ---------- CLI ----------

def load_spec(folder: Path) -> dict:
    path = folder / "scenes.json"
    if not path.exists():
        raise SystemExit(f"No {path}. Run /scenes first.")
    spec = json.loads(path.read_text(encoding="utf-8"))
    for i, scene in enumerate(spec["scenes"]):
        scene.setdefault("pattern", DEFAULT_PATTERNS[i % len(DEFAULT_PATTERNS)])
        scene.setdefault("transition", "cut" if i == 0 else DEFAULT_TRANSITIONS[(i - 1) % len(DEFAULT_TRANSITIONS)])
        if scene["transition"] not in TRANSITIONS:
            raise SystemExit(f"Unknown transition {scene['transition']!r}; choose from {TRANSITIONS}")
        for el in scene.get("elements", []):
            if el.get("enter", "pop") not in ENTERS:
                raise SystemExit(f"Unknown enter {el['enter']!r}; choose from {ENTERS}")
            if el.get("exit") and el["exit"].get("type", "pop") not in EXITS:
                raise SystemExit(f"Unknown exit {el['exit']['type']!r}; choose from {EXITS}")
    return spec


def prepare(folder: Path, spec: dict):
    lines, words, total, real = load_timing(folder)
    times = cut.segment_times(spec["scenes"], lines, total)
    for scene, (start, _) in zip(spec["scenes"], times):
        rng = cut.seg_lines(scene)
        for el in scene.get("elements", []):
            el["_start"] = element_start(el, rng, words, start)
            for m in el.get("moves", []):
                m["_start"] = element_start(m, rng, words, start)
            if el.get("exit"):
                el["exit"]["_start"] = element_start(el["exit"], rng, words, start)
        scene["_impacts"] = impacts_for(scene)
    return times, real


def clip_name(scene: dict) -> str:
    return f"scene_{cut.seg_lines(scene)[0]:02d}.mp4"


def write_timeline(folder: Path, spec: dict, times, real: bool) -> None:
    old = folder / "timeline.json"
    music = json.loads(old.read_text(encoding="utf-8")).get("music") if old.exists() else None
    segments = []
    for scene, (_, dur) in zip(spec["scenes"], times):
        first, last = cut.seg_lines(scene)
        seg = {"lines": [first, last], "clip": f"anim/{{fmt}}/{clip_name(scene)}",
               "vertical": {"layout": "fill"}, "horizontal": {"layout": "fill"}}
        if not real:
            seg["duration"] = dur  # lets cut.py make a silent preview before the voice exists
        segments.append(seg)
    timeline = {"fps": 30, "background": "#F3E9D2", "segments": segments}
    if music:
        timeline["music"] = music  # keep hand-set music level/start across re-renders
    old.write_text(json.dumps(timeline, indent=2), encoding="utf-8")


def vocab() -> None:
    import papercut as pc
    print("icons: " + ", ".join(sorted(pc.ICONS)))
    print("colours: " + ", ".join(pc.PALETTE))
    print("text styles: " + ", ".join(TEXT_STYLES) + "   fonts: " + ", ".join(pc.FONT_FILES))
    print("image treatments: " + ", ".join(TREATMENTS) + "   src: pexels:<query> or a file path")
    print("enter: " + ", ".join(ENTERS) + "   exit: " + ", ".join(EXITS) + "   idle: " + ", ".join(IDLES))
    print("scene: bg (colour), pattern: " + ", ".join(pc.PATTERNS) + ", floaters (count, default 20), bg_speed,")
    print("       transition (into this scene): " + ", ".join(TRANSITIONS) + ", tdur, camera: " + ", ".join(CAMERAS))
    print("element keys: type, name|text|src, x, y, size (icon width / text height), w, h (image), color, paper, "
          "recolor {old: new}, rotate, scale, enter, dur, at (s) | at_word, idle, impact (bool), count [a, b], prefix, suffix")
    print("  moves: [{at|at_word, x, y, scale, rotate, dur, arc (lift, 0..0.3), ease back|smooth, impact}]")
    print("  exit: {at|at_word, type, dur}")


def main(argv: list[str] | None = None) -> None:
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("vocab")
    s = sub.add_parser("render")
    s.add_argument("video_id")
    s.add_argument("--line", type=int, help="only the scene starting at this line")
    s.add_argument("--only", choices=list(FORMATS))
    s.add_argument("--draft", action="store_true", help="half resolution")
    s = sub.add_parser("still")
    s.add_argument("video_id")
    s.add_argument("--line", type=int, required=True)
    s.add_argument("--at", type=float, default=1.5)
    s.add_argument("--fmt", choices=list(FORMATS), default="9x16")
    args = p.parse_args(argv)

    if args.cmd == "vocab":
        vocab()
        return
    folder = video_dir(args.video_id)
    spec = load_spec(folder)
    times, real = prepare(folder, spec)
    pairs = list(zip(spec["scenes"], times))
    starts = [cut.seg_lines(sc)[0] for sc, _ in pairs]
    if args.line is not None and args.line not in starts:
        raise SystemExit(f"No scene starts at line {args.line}")

    if args.cmd == "still":
        i = starts.index(args.line)
        r = SceneRenderer(folder, spec, args.fmt)
        prev = r.last_frame(pairs[i - 1][0], pairs[i - 1][1][1]) if i > 0 else None
        frame = next(r.frames(pairs[i][0], pairs[i][1][1], prev, only_at=args.at))
        out = folder / "anim" / f"still_{args.fmt}_line{args.line:02d}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        frame.save(out)
        print(f"Wrote {out}")
        return

    print(f"Timing: {'from your recording' if real else 'estimated from the script (no lines.json yet)'}")
    credits: list[str] = []
    for fmt in ([args.only] if args.only else FORMATS):
        renderer = SceneRenderer(folder, spec, fmt, args.draft)
        prev = None
        for i, (scene, (_, dur)) in enumerate(pairs):
            if args.line is not None and starts[i] != args.line:
                continue
            if args.line is not None and i > 0:
                prev = renderer.last_frame(pairs[i - 1][0], pairs[i - 1][1][1])
            print(f"  {fmt} {clip_name(scene)} ({dur:.1f}s, {scene.get('transition')} in, {scene.get('pattern')})")
            prev = renderer.render(scene, dur, folder / "anim" / fmt / clip_name(scene), prev)
        credits += [c for c in renderer.credits if c not in credits]
    if credits:
        (folder / "credits.json").write_text(json.dumps(credits, indent=2, ensure_ascii=False), encoding="utf-8")
    write_timeline(folder, spec, times, real)
    print(f"Wrote anim/ clips and timeline.json. Next: python scripts/cut.py render {args.video_id}")


if __name__ == "__main__":
    main()
