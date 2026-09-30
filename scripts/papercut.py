"""Paper-cut drawing: paper texture, torn edges, drop shadows, icons, cut-out text, mixed-media photos.

Every sprite is built from layers. Each layer is a mask filled with a colour (or an image), given a rough
cut edge and paper grain, and casts a soft shadow on the layers below. That stacking is the paper-cut look.
Icons are drawn from simple shapes in a 0..1 box, so there are no third-party logos or icon licences.
"""
from __future__ import annotations

import math
import os
import random
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageOps

PALETTE = {
    "cream": "#F3E9D2", "white": "#FBF8F1", "kraft": "#C9A27E", "navy": "#1D3557", "ink": "#14213D",
    "red": "#E63946", "teal": "#2A9D8F", "mustard": "#E9C46A", "orange": "#F4A261", "sky": "#A8DADC",
    "green": "#008751", "blue": "#326CE5", "grey": "#8D99AE", "pink": "#F4ACB7", "black": "#2B2B2B",
}
FONT_FILES = {
    "bold": ["arialbd.ttf", "DejaVuSans-Bold.ttf"],
    "black": ["ariblk.ttf", "arialbd.ttf"],
    "impact": ["impact.ttf", "arialbd.ttf"],
    "serif": ["georgiab.ttf", "timesbd.ttf", "arialbd.ttf"],
    "type": ["courbd.ttf", "arialbd.ttf"],
    "hand": ["segoeprb.ttf", "comicbd.ttf", "arialbd.ttf"],
    "stencil": ["STENCIL.TTF", "impact.ttf", "arialbd.ttf"],
    "round": ["segoeuib.ttf", "verdanab.ttf", "arialbd.ttf"],
}
RANSOM_FONTS = ["black", "serif", "impact", "type", "stencil", "round"]


def rgb(color) -> tuple[int, int, int]:
    if isinstance(color, (tuple, list)):
        return tuple(color)[:3]
    return ImageColor.getrgb(PALETTE.get(color, color))


@lru_cache(maxsize=64)
def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    windir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in FONT_FILES.get(kind, FONT_FILES["bold"]):
        for path in (windir / name, Path(name)):
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def _covers(f: ImageFont.FreeTypeFont, text: str) -> bool:
    """False if any character would render as the font's empty 'missing glyph' box."""
    def glyph(ch: str) -> bytes:
        img = Image.new("L", (f.size * 2, f.size * 2), 0)
        ImageDraw.Draw(img).text((f.size // 2, f.size // 2), ch, font=f, fill=255)
        return img.tobytes()

    missing = glyph("\U000F0000")
    return all(ch.isspace() or glyph(ch) != missing for ch in set(text))


def font_for(kind: str, size: int, text: str) -> ImageFont.FreeTypeFont:
    """The requested font, or the first fallback that has every character (e.g. the naira sign)."""
    for k in (kind, "bold", "round"):
        f = font(k, size)
        if _covers(f, text):
            return f
    return font(kind, size)


# ---------- paper ----------

@lru_cache(maxsize=32)
def grain(w: int, h: int) -> Image.Image:
    """Mottled paper grain with fibres, values ~205..255, used as a multiply layer."""
    rnd = random.Random(w * 7919 + h)
    coarse = Image.effect_noise((max(w // 10, 1), max(h // 10, 1)), 50).resize((w, h), Image.BICUBIC)
    fine = Image.effect_noise((w, h), 22)
    g = ImageChops.add(coarse, fine, scale=2.0).point(lambda v: max(205, min(255, 243 + (v - 128) // 5)))
    draw = ImageDraw.Draw(g)
    for _ in range(w * h // 5000):
        x, y, a, n = rnd.randrange(w), rnd.randrange(h), rnd.uniform(0, math.pi), rnd.randint(4, 16)
        draw.line((x, y, x + n * math.cos(a), y + n * math.sin(a)), fill=rnd.choice((214, 255)), width=1)
    return g


def paperize(img: Image.Image) -> Image.Image:
    return ImageChops.multiply(img.convert("RGB"), grain(*img.size).convert("RGB"))


def rough(mask: Image.Image, amount: float) -> Image.Image:
    """Hand-cut edge: blur the mask, push the edge around with noise, threshold again."""
    if amount <= 0:
        return mask
    w, h = mask.size
    blurred = mask.filter(ImageFilter.GaussianBlur(amount))
    step = max(2, int(amount * 1.5))
    noise = Image.effect_noise((max(w // step, 1), max(h // step, 1)), 70).resize((w, h), Image.BILINEAR)
    edge = ImageChops.add(blurred, noise, scale=1.0, offset=-128)
    return edge.point(lambda v: 255 if v >= 128 else 0).filter(ImageFilter.GaussianBlur(0.7))


def compose(layers: list[tuple[object, Image.Image]], ref: int, edge: float | None = None,
            shadow: float = 0.38) -> Image.Image:
    """layers: (colour or RGB image, L mask), all the same canvas size. Returns RGBA."""
    size = layers[0][1].size
    edge = max(1.2, ref * 0.006) if edge is None else edge
    off = max(2, round(ref * 0.016))
    blur = max(2, ref * 0.018)
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    for fill, mask in layers:
        mask = rough(mask, edge)
        if shadow:
            sh = mask.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * shadow))
            sh_layer = Image.new("RGBA", size, (20, 14, 8, 0))
            sh_layer.putalpha(ImageChops.offset(sh, off // 2, off))
            out = Image.alpha_composite(out, sh_layer)
        base = fill.resize(size) if isinstance(fill, Image.Image) else Image.new("RGB", size, rgb(fill))
        piece = paperize(base).convert("RGBA")
        piece.putalpha(mask)
        out = Image.alpha_composite(out, piece)
    return out


# ---------- shape DSL ----------
# A primitive is a tuple in a 0..1 box; a kind starting with "-" cuts a hole instead of filling.
#   ("ellipse", x0, y0, x1, y1)  ("rect", x0, y0, x1, y1)  ("rrect", x0, y0, x1, y1, r)
#   ("poly", [(x, y), ...])      ("line", [(x, y), ...], width)   ("text", s, font, cx, cy, height)

def star(cx, cy, r1, r2, n, rot=-90.0):
    return [(cx + (r1 if i % 2 == 0 else r2) * math.cos(math.radians(rot + i * 180 / n)),
             cy + (r1 if i % 2 == 0 else r2) * math.sin(math.radians(rot + i * 180 / n))) for i in range(n * 2)]


def ngon(cx, cy, r, n, rot=-90.0):
    return [(cx + r * math.cos(math.radians(rot + i * 360 / n)), cy + r * math.sin(math.radians(rot + i * 360 / n)))
            for i in range(n)]


def spoke(cx, cy, r0, r1, half, angle):
    a = math.radians(angle)
    ux, uy, px, py = math.cos(a), math.sin(a), -math.sin(a) * half, math.cos(a) * half
    return [(cx + ux * r0 + px, cy + uy * r0 + py), (cx + ux * r1 + px, cy + uy * r1 + py),
            (cx + ux * r1 - px, cy + uy * r1 - py), (cx + ux * r0 - px, cy + uy * r0 - py)]


def _eye():
    top = [(0.06 + 0.88 * i / 20, 0.5 - 0.34 * math.sin(math.pi * i / 20)) for i in range(21)]
    return top + [(x, 1 - y) for x, y in reversed(top)]


ICONS: dict[str, list[tuple[str, list]]] = {
    "shield": [("red", [("poly", [(.5, .04), (.92, .2), (.86, .6), (.5, .96), (.14, .6), (.08, .2)])]),
               ("cream", [("poly", [(.5, .16), (.8, .28), (.75, .58), (.5, .84), (.25, .58), (.2, .28)])]),
               ("teal", [("line", [(.34, .5), (.46, .62), (.67, .38)], .08)])],
    "lock": [("navy", [("ellipse", .27, .06, .73, .62), ("-ellipse", .36, .15, .64, .53)]),
             ("mustard", [("rrect", .16, .4, .84, .94, .07)]),
             ("navy", [("ellipse", .44, .55, .56, .67), ("poly", [(.47, .63), (.53, .63), (.55, .82), (.45, .82)])])],
    "cloud": [("sky", [("ellipse", .06, .42, .42, .78), ("ellipse", .26, .2, .7, .66), ("ellipse", .54, .36, .94, .78),
                       ("rect", .24, .56, .76, .78)]),
              ("white", [("ellipse", .2, .5, .4, .7), ("ellipse", .34, .34, .6, .6), ("ellipse", .52, .48, .78, .7),
                         ("rect", .3, .6, .7, .7)])],
    "server": [("navy", [("rrect", .15, .08, .85, .33, .04), ("rrect", .15, .38, .85, .63, .04),
                         ("rrect", .15, .68, .85, .93, .04)]),
               ("green", [("ellipse", .22, .16, .3, .24), ("ellipse", .22, .46, .3, .54), ("ellipse", .22, .76, .3, .84)]),
               ("grey", [("rect", .5, .18, .78, .23), ("rect", .5, .48, .78, .53), ("rect", .5, .78, .78, .83)])],
    "laptop": [("navy", [("rrect", .14, .16, .86, .68, .03)]), ("sky", [("rect", .19, .21, .81, .63)]),
               ("grey", [("poly", [(.04, .7), (.96, .7), (.9, .82), (.1, .82)])])],
    "phone": [("navy", [("rrect", .3, .05, .7, .95, .07)]), ("sky", [("rect", .34, .13, .66, .8)]),
              ("grey", [("ellipse", .46, .84, .54, .91)])],
    "calendar": [("cream", [("rrect", .1, .16, .9, .92, .05)]),
                 ("red", [("rrect", .1, .16, .9, .36, .05), ("rect", .1, .28, .9, .36)]),
                 ("navy", [("rrect", .27, .07, .34, .26, .03), ("rrect", .66, .07, .73, .26, .03)]
                  + [("rect", .17 + c * .17, .44 + r * .15, .28 + c * .17, .54 + r * .15) for r in range(3) for c in range(4)])],
    "clock": [("cream", [("ellipse", .06, .06, .94, .94)]), ("navy", [("ellipse", .06, .06, .94, .94), ("-ellipse", .13, .13, .87, .87)]),
              ("navy", [("line", [(.5, .5), (.5, .22)], .06), ("line", [(.5, .5), (.7, .6)], .06)])],
    "coin": [("mustard", [("ellipse", .08, .08, .92, .92)]), ("orange", [("ellipse", .18, .18, .82, .82)]),
             ("cream", [("text", "\u20a6", "black", .5, .5, .44)])],
    "money": [("green", [("rrect", .04, .24, .96, .76, .03)]), ("cream", [("ellipse", .37, .32, .63, .68)]),
              ("green", [("text", "\u20a6", "black", .5, .5, .26)])],
    "bug": [("navy", [("line", [(.1, .44), (.9, .44)], .035), ("line", [(.08, .62), (.92, .62)], .035),
                      ("line", [(.12, .8), (.88, .8)], .035), ("line", [(.43, .2), (.33, .05)], .03),
                      ("line", [(.57, .2), (.67, .05)], .03)]),
            ("red", [("ellipse", .24, .28, .76, .92)]),
            ("navy", [("ellipse", .36, .13, .64, .38), ("rect", .485, .32, .515, .9), ("ellipse", .32, .5, .42, .6),
                      ("ellipse", .58, .64, .68, .74)])],
    "magnifier": [("navy", [("line", [(.6, .6), (.9, .9)], .12), ("ellipse", .06, .06, .68, .68)]),
                  ("sky", [("ellipse", .15, .15, .59, .59)]), ("white", [("ellipse", .22, .22, .33, .33)])],
    "check": [("green", [("ellipse", .06, .06, .94, .94)]), ("cream", [("line", [(.28, .52), (.44, .68), (.74, .34)], .1)])],
    "cross": [("red", [("ellipse", .06, .06, .94, .94)]),
              ("cream", [("line", [(.32, .32), (.68, .68)], .11), ("line", [(.68, .32), (.32, .68)], .11)])],
    "arrow": [("orange", [("poly", [(.04, .38), (.58, .38), (.58, .16), (.96, .5), (.58, .84), (.58, .62), (.04, .62)])])],
    "burst": [("mustard", [("poly", star(.5, .5, .49, .35, 14))]), ("orange", [("poly", star(.5, .5, .37, .27, 14))])],
    "star": [("mustard", [("poly", star(.5, .53, .47, .2, 5))])],
    "gear": [("grey", [("ellipse", .2, .2, .8, .8)] + [("poly", spoke(.5, .5, .25, .47, .075, a)) for a in range(0, 360, 45)]
              + [("-ellipse", .38, .38, .62, .62)])],
    "wheel": [("blue", [("poly", ngon(.5, .5, .48, 7))]),
              ("cream", [("ellipse", .22, .22, .78, .78), ("-ellipse", .3, .3, .7, .7), ("ellipse", .42, .42, .58, .58)]
               + [("poly", spoke(.5, .5, .05, .37, .03, a)) for a in range(-90, 270, 360 // 7)])],
    "folder": [("orange", [("poly", [(.06, .2), (.4, .2), (.46, .28), (.94, .28), (.94, .84), (.06, .84)])]),
               ("mustard", [("poly", [(.06, .38), (.94, .38), (.94, .84), (.06, .84)])])],
    "chat": [("teal", [("rrect", .06, .12, .94, .7, .1), ("poly", [(.22, .64), (.42, .64), (.18, .9)])]),
             ("cream", [("ellipse", .25, .35, .36, .46), ("ellipse", .445, .35, .555, .46), ("ellipse", .64, .35, .75, .46)])],
    "person": [("navy", [("rrect", .16, .5, .84, .98, .22)]), ("orange", [("ellipse", .32, .06, .68, .44)])],
    "globe": [("sky", [("ellipse", .06, .06, .94, .94)]),
              ("green", [("poly", [(.26, .2), (.48, .16), (.52, .36), (.36, .52), (.2, .44)]),
                         ("poly", [(.56, .5), (.8, .46), (.84, .64), (.64, .84), (.54, .68)])])],
    "database": [("teal", [("rect", .18, .2, .82, .8), ("ellipse", .18, .1, .82, .3), ("ellipse", .18, .7, .82, .9)]),
                 ("sky", [("ellipse", .22, .12, .78, .28)]), ("navy", [("rect", .18, .4, .82, .43), ("rect", .18, .6, .82, .63)])],
    "terminal": [("navy", [("rrect", .05, .14, .95, .86, .04)]), ("grey", [("rrect", .05, .14, .95, .27, .04), ("rect", .05, .21, .95, .27)]),
                 ("green", [("line", [(.16, .42), (.3, .54), (.16, .66)], .05), ("rect", .36, .62, .58, .67)]),
                 ("red", [("ellipse", .1, .175, .15, .225)]), ("mustard", [("ellipse", .18, .175, .23, .225)])],
    "chart": [("navy", [("rect", .06, .86, .94, .9)]), ("teal", [("rect", .14, .52, .3, .86)]),
              ("mustard", [("rect", .4, .32, .56, .86)]), ("red", [("rect", .66, .12, .82, .86)])],
    "target": [("red", [("ellipse", .04, .04, .96, .96)]), ("cream", [("ellipse", .18, .18, .82, .82)]),
               ("red", [("ellipse", .32, .32, .68, .68)]), ("cream", [("ellipse", .44, .44, .56, .56)])],
    "key": [("mustard", [("ellipse", .04, .3, .44, .7), ("-ellipse", .16, .42, .32, .58), ("rect", .4, .45, .94, .55),
                         ("rect", .74, .55, .82, .72), ("rect", .86, .55, .93, .66)])],
    "warning": [("mustard", [("poly", [(.5, .05), (.96, .9), (.04, .9)])]),
                ("navy", [("poly", [(.45, .33), (.55, .33), (.53, .64), (.47, .64)]), ("ellipse", .45, .7, .55, .8)])],
    "document": [("white", [("poly", [(.18, .05), (.64, .05), (.82, .23), (.82, .95), (.18, .95)])]),
                 ("kraft", [("poly", [(.64, .05), (.82, .23), (.64, .23)])]),
                 ("grey", [("rect", .28, y, .72, y + .035) for y in (.36, .47, .58, .69, .8)])],
    "envelope": [("white", [("rect", .05, .2, .95, .8)]), ("kraft", [("poly", [(.05, .2), (.95, .2), (.5, .56)])]),
                 ("red", [("ellipse", .44, .46, .56, .58)])],
    "hook": [("grey", [("ellipse", .55, .02, .69, .14), ("-ellipse", .59, .06, .65, .1), ("rect", .585, .12, .655, .62),
                       ("ellipse", .28, .4, .7, .92), ("-ellipse", .36, .48, .6, .84), ("-rect", .2, .38, .5, .66),
                       ("poly", [(.28, .66), (.36, .5), (.42, .68)])])],
    "shop": [("red", [("poly", [(.08, .38), (.2, .12), (.8, .12), (.92, .38)])]), ("cream", [("rect", .13, .38, .87, .92)]),
             ("teal", [("rect", .42, .6, .58, .92)]), ("sky", [("rect", .19, .48, .35, .64), ("rect", .65, .48, .81, .64)])],
    "firewall": [("red", [("rect", x0, y, x0 + .26, y + .12) for i, y in enumerate((.14, .3, .46, .62, .78))
                          for x0 in ((.06, .36, .66) if i % 2 == 0 else (.2, .5))]
                  + [("rect", .06, .3, .16, .42), ("rect", .8, .3, .92, .42), ("rect", .06, .62, .16, .74), ("rect", .8, .62, .92, .74)])],
    "eye": [("white", [("poly", _eye())]), ("teal", [("ellipse", .34, .28, .66, .72)]), ("navy", [("ellipse", .43, .39, .57, .61)])],
    "scissors": [("grey", [("poly", [(.34, .66), (.42, .6), (.8, .04), (.72, .04)]), ("poly", [(.66, .66), (.58, .6), (.2, .04), (.28, .04)])]),
                 ("red", [("ellipse", .08, .6, .44, .96), ("-ellipse", .17, .69, .35, .87),
                          ("ellipse", .56, .6, .92, .96), ("-ellipse", .65, .69, .83, .87)]),
                 ("navy", [("ellipse", .47, .44, .53, .5)])],
    "mic": [("grey", [("rect", .47, .7, .53, .88), ("rrect", .3, .86, .7, .94, .03),
                      ("ellipse", .22, .3, .78, .78), ("-ellipse", .28, .28, .72, .72), ("-rect", .2, .2, .8, .54)]),
            ("navy", [("rrect", .34, .04, .66, .64, .16)]),
            ("sky", [("rect", .39, .16, .61, .19), ("rect", .39, .25, .61, .28), ("rect", .39, .34, .61, .37)])],
    "rocket": [("red", [("poly", [(.3, .62), (.14, .86), (.36, .78)]), ("poly", [(.7, .62), (.86, .86), (.64, .78)])]),
               ("cream", [("poly", [(.5, .04), (.66, .26), (.66, .8), (.34, .8), (.34, .26)])]),
               ("sky", [("ellipse", .41, .3, .59, .48)]), ("orange", [("poly", [(.38, .82), (.62, .82), (.5, .98)])])],
}


def _draw(draw: ImageDraw.ImageDraw, prim: tuple, w: int, h: int, m: int) -> None:
    kind = prim[0]
    fill = 0 if kind.startswith("-") else 255
    kind = kind.lstrip("-")
    X = lambda v: m + v * w  # noqa: E731
    Y = lambda v: m + v * h  # noqa: E731
    if kind in ("ellipse", "rect"):
        _, x0, y0, x1, y1 = prim
        getattr(draw, "ellipse" if kind == "ellipse" else "rectangle")((X(x0), Y(y0), X(x1), Y(y1)), fill=fill)
    elif kind == "rrect":
        _, x0, y0, x1, y1, r = prim
        draw.rounded_rectangle((X(x0), Y(y0), X(x1), Y(y1)), radius=r * min(w, h), fill=fill)
    elif kind == "poly":
        draw.polygon([(X(x), Y(y)) for x, y in prim[1]], fill=fill)
    elif kind == "line":
        draw.line([(X(x), Y(y)) for x, y in prim[1]], fill=fill, width=max(1, round(prim[2] * min(w, h))), joint="curve")
    elif kind == "text":
        _, s, fkind, cx, cy, height = prim
        draw.text((X(cx), Y(cy)), s, font=font_for(fkind, max(8, round(height * h)), s), fill=fill, anchor="mm")


def shape_sprite(layers: list[tuple[str, list]], w: int, h: int | None = None) -> Image.Image:
    h = h or w
    m = max(6, round(max(w, h) * 0.08))
    size = (w + 2 * m, h + 2 * m)
    built = []
    for color, prims in layers:
        mask = Image.new("L", size, 0)
        draw = ImageDraw.Draw(mask)
        for prim in prims:
            _draw(draw, prim, w, h, m)
        built.append((color, mask))
    return compose(built, max(w, h))


def icon_sprite(name: str, px: int, recolor: dict | None = None) -> Image.Image:
    if name not in ICONS:
        raise SystemExit(f"Unknown icon {name!r}. Run: python scripts/animate.py vocab")
    layers = [((recolor or {}).get(c, c), prims) for c, prims in ICONS[name]]
    return shape_sprite(layers, px)


# ---------- text ----------

def _text_mask(text: str, f: ImageFont.FreeTypeFont, pad: int) -> Image.Image:
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    x0, y0, x1, y1 = (round(v) for v in probe.multiline_textbbox((0, 0), text, font=f, align="center",
                                                                 spacing=f.size // 6))
    mask = Image.new("L", (x1 - x0 + 2 * pad, y1 - y0 + 2 * pad), 0)
    ImageDraw.Draw(mask).multiline_text((pad - x0, pad - y0), text, font=f, fill=255, align="center", spacing=f.size // 6)
    return mask


def text_sprite(text: str, style: str, px: int, color="navy", paper="cream", fkind: str | None = None,
                seed: int = 0) -> Image.Image:
    """Styles: cutout (letters cut from paper), strip (on a torn paper strip),
    ransom (every letter on its own scrap), stamp (distressed rubber-stamp ink)."""
    rnd = random.Random(seed)
    if style == "ransom":
        return _ransom(text, px, rnd)
    f = font_for(fkind or ("black" if style != "stamp" else "stencil"), px, text)
    pad = max(8, px // 3)
    mask = _text_mask(text, f, pad)
    if style == "cutout":
        return compose([(color, mask)], px, edge=max(1.0, px * 0.012))
    if style == "strip":
        w, h = mask.size
        m = max(6, round(max(w, h) * 0.06))
        big = (w + 2 * m, h + 2 * m)
        strip = Image.new("L", big, 0)
        j = lambda: rnd.uniform(-0.25, 0.25) * pad  # noqa: E731
        ImageDraw.Draw(strip).polygon([(m + j(), m + j()), (m + w + j(), m + j()), (m + w + j(), m + h + j()),
                                       (m + j(), m + h + j())], fill=255)
        text_mask = Image.new("L", big, 0)
        text_mask.paste(mask, (m, m))
        return compose([(paper, strip), (color, text_mask)], max(w, h) // 3, edge=max(1.5, px * 0.03))
    if style == "stamp":
        w, h = mask.size
        box = Image.new("L", (w + 2 * pad, h + 2 * pad), 0)
        d = ImageDraw.Draw(box)
        d.rounded_rectangle((pad // 2, pad // 2, w + pad * 1.5, h + pad * 1.5), radius=pad // 2,
                            outline=255, width=max(3, px // 12))
        box.paste(mask, (pad, pad), mask)
        holes = Image.effect_noise(box.size, 90).filter(ImageFilter.GaussianBlur(1.5)).point(lambda v: 255 if v > 70 else 0)
        box = ImageChops.multiply(rough(box, max(1.0, px * 0.015)), holes)
        ink = Image.new("RGBA", box.size, rgb(color) + (0,))
        ink.putalpha(box.point(lambda v: int(v * 0.9)))
        return ink.rotate(rnd.uniform(-9, -4), resample=Image.BICUBIC, expand=True)
    raise SystemExit(f"Unknown text style {style!r}")


def _ransom(text: str, px: int, rnd: random.Random) -> Image.Image:
    rows = [_ransom_row(row, px, rnd) for row in text.split("\n")]
    if len(rows) == 1:
        return rows[0]
    gap = -px // 8
    out = Image.new("RGBA", (max(r.width for r in rows), sum(r.height for r in rows) + gap * (len(rows) - 1)), (0, 0, 0, 0))
    y = 0
    for r in rows:
        out.alpha_composite(r, ((out.width - r.width) // 2, y))
        y += r.height + gap
    return out


def _ransom_row(text: str, px: int, rnd: random.Random) -> Image.Image:
    papers =["white", "cream", "mustard", "sky", "pink", "kraft", "navy", "red", "teal"]
    tiles = []
    for ch in text:
        if ch == " ":
            tiles.append(None)
            continue
        paper = rnd.choice(papers)
        ink = "cream" if paper in ("navy", "red", "teal") else rnd.choice(["ink", "red", "navy", "black"])
        f = font_for(rnd.choice(RANSOM_FONTS), int(px * rnd.uniform(0.82, 1.08)), ch)
        glyph = _text_mask(ch, f, max(6, px // 7))
        w, h = glyph.size
        m = max(6, px // 8)
        bg = Image.new("L", (w + 2 * m, h + 2 * m), 0)
        ImageDraw.Draw(bg).rectangle((m, m, m + w, m + h), fill=255)
        fg = Image.new("L", bg.size, 0)
        fg.paste(glyph, (m, m))
        tile = compose([(paper, bg), (ink, fg)], px // 2, edge=max(1.5, px * 0.025))
        tiles.append(tile.rotate(rnd.uniform(-8, 8), resample=Image.BICUBIC, expand=True))
    space = px // 2
    width = sum(t.width - px // 6 if t else space for t in tiles) + px // 6
    height = max(t.height for t in tiles if t) + px // 5
    out = Image.new("RGBA", (max(width, 1), height), (0, 0, 0, 0))
    x = 0
    for t in tiles:
        if t is None:
            x += space
            continue
        out.alpha_composite(t, (x, (height - t.height) // 2 + rnd.randint(-px // 14, px // 14) + px // 10))
        x += t.width - px // 6
    return out


# ---------- photos (mixed media) ----------

def photo_sprite(path: Path, w: int, h: int, treatment: str = "duotone", ink="navy", paper="cream") -> Image.Image:
    """Treatments: duotone (two-colour print), halftone (printed dots), polaroid (white frame), torn (full colour)."""
    img = ImageOps.fit(Image.open(path).convert("RGB"), (w, h), Image.LANCZOS)
    if treatment in ("duotone", "polaroid"):
        img = ImageOps.colorize(ImageOps.autocontrast(ImageOps.grayscale(img), cutoff=2), black=rgb(ink), white=rgb(paper))
    elif treatment == "halftone":
        img = _halftone(img, rgb(ink), rgb(paper), max(6, w // 70))
    m = max(8, round(max(w, h) * 0.07))
    size = (w + 2 * m, h + 2 * m)
    canvas = Image.new("RGB", size, rgb(paper))
    canvas.paste(img, (m, m))
    photo_mask = Image.new("L", size, 0)
    ImageDraw.Draw(photo_mask).rectangle((m, m, m + w, m + h), fill=255)
    if treatment == "polaroid":
        f = max(8, w // 16)
        frame = Image.new("L", size, 0)
        ImageDraw.Draw(frame).rectangle((m - f, m - f, m + w + f, m + h + f * 3), fill=255)
        size2 = (size[0], size[1] + f * 3)
        frame2, canvas2, pm2 = (Image.new("L", size2, 0), Image.new("RGB", size2, rgb(paper)), Image.new("L", size2, 0))
        frame2.paste(frame, (0, 0))
        canvas2.paste(canvas, (0, 0))
        pm2.paste(photo_mask, (0, 0))
        return compose([("white", frame2), (canvas2, pm2)], max(w, h), edge=1.0)
    return compose([(canvas, photo_mask)], max(w, h), edge=max(3.0, w * 0.012))


def _halftone(img: Image.Image, ink, paper, cell: int) -> Image.Image:
    gray = ImageOps.autocontrast(ImageOps.grayscale(img), cutoff=2)
    small = gray.resize((max(1, img.width // cell), max(1, img.height // cell)))
    out = Image.new("RGB", img.size, paper)
    d = ImageDraw.Draw(out)
    for y in range(small.height):
        for x in range(small.width):
            r = (1 - small.getpixel((x, y)) / 255) * cell * 0.72
            if r > 0.6:
                cx, cy = x * cell + cell / 2 + (cell / 2 if y % 2 else 0), y * cell + cell / 2
                d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ink)
    return out


# ---------- background ----------

def background(w: int, h: int, color="cream", seed: int = 0, scraps: int = 7) -> Image.Image:
    """Full-frame paper with a few torn scraps in the margins, so the stage sits on a desk of paper."""
    rnd = random.Random(seed)
    bg = paperize(Image.new("RGB", (w, h), rgb(color))).convert("RGBA")
    base = rgb(color)
    for _ in range(scraps):
        sw, sh = int(w * rnd.uniform(0.18, 0.4)), int(h * rnd.uniform(0.05, 0.12))
        tone = tuple(max(0, min(255, c + rnd.choice((-22, -14, 12)))) for c in base)
        mask = Image.new("L", (sw, sh), 0)
        ImageDraw.Draw(mask).polygon([(rnd.uniform(0, .1) * sw, rnd.uniform(0, .3) * sh),
                                      (rnd.uniform(.9, 1) * sw, rnd.uniform(0, .3) * sh),
                                      (rnd.uniform(.9, 1) * sw, rnd.uniform(.7, 1) * sh),
                                      (rnd.uniform(0, .1) * sw, rnd.uniform(.7, 1) * sh)], fill=255)
        m = 12
        big = Image.new("L", (sw + 2 * m, sh + 2 * m), 0)
        big.paste(mask, (m, m))
        piece = compose([(tone, big)], min(sw, sh), edge=2.5, shadow=0.18)
        piece = piece.rotate(rnd.uniform(-25, 25), resample=Image.BICUBIC, expand=True)
        edge_pos = rnd.choice(("top", "bottom", "left", "right"))
        x = {"left": -piece.width // 3, "right": w - piece.width * 2 // 3}.get(edge_pos, rnd.randint(-piece.width // 4, w - piece.width // 2))
        y = {"top": -piece.height // 3, "bottom": h - piece.height * 2 // 3}.get(edge_pos, rnd.randint(0, max(1, h - piece.height)))
        bg.paste(piece, (x, y), piece)
    return bg.convert("RGB")


# ---------- moving backgrounds ----------
PATTERNS = ("stripes", "dots", "zigzag", "diamonds", "plus", "waves", "rays", "none")
FLOATER_SHAPES = {
    "circle": [("ellipse", .1, .1, .9, .9)],
    "ring": [("ellipse", .05, .05, .95, .95), ("-ellipse", .3, .3, .7, .7)],
    "triangle": [("poly", [(.5, .06), (.95, .9), (.05, .9)])],
    "square": [("rect", .12, .12, .88, .88)],
    "star": [("poly", star(.5, .53, .48, .22, 5))],
    "plus": [("rect", .38, .05, .62, .95), ("rect", .05, .38, .95, .62)],
    "half": [("poly", [(.05, .6)] + [(.5 - .45 * math.cos(math.pi * i / 12), .6 - .45 * math.sin(math.pi * i / 12)) for i in range(13)])],
    "squiggle": [("line", [(.05 + .9 * i / 8, .5 + (.3 if i % 2 else -.3)) for i in range(9)], .16)],
}


def tone(color, delta: int) -> tuple[int, int, int]:
    return tuple(max(0, min(255, c + delta)) for c in rgb(color))


def accents(bg) -> list[str]:
    """Palette colours that stand out from the background."""
    base = rgb(bg)
    return [n for n, v in PALETTE.items() if sum(abs(a - b) for a, b in zip(rgb(v), base)) > 160 and n != "ink"]


def pattern_layer(w: int, h: int, color, pattern: str, period: int, seed: int = 0) -> Image.Image:
    """Paper background plus a tileable paper-cut pattern, `period` px larger than the frame on each axis,
    so the frame can scroll across it by cropping at an offset in [0, period)."""
    W, H = w + period, h + period
    base = paperize(Image.new("RGB", (W, H), rgb(color)))
    if pattern in ("none", "rays"):
        return base
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    p = period
    cols, rows = W // p + 2, H // p + 2
    if pattern == "stripes":
        sw = p * 0.42
        for k in range(-(H // p) - 2, cols + 1):
            x = k * p
            d.polygon([(x, 0), (x + sw, 0), (x + sw + H, H), (x + H, H)], fill=255)
    elif pattern == "dots":
        r = p * 0.17
        for j in range(rows):
            for i in range(cols):
                for ox, oy in ((0, 0), (p / 2, p / 2)):
                    cx, cy = i * p + ox, j * p + oy
                    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    elif pattern == "diamonds":
        r = p * 0.22
        for j in range(rows):
            for i in range(cols):
                for ox, oy in ((0, 0), (p / 2, p / 2)):
                    cx, cy = i * p + ox, j * p + oy
                    d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=255)
    elif pattern == "plus":
        a, b = p * 0.2, p * 0.06
        for j in range(rows):
            for i in range(cols):
                cx, cy = i * p + p / 2, j * p + p / 2
                d.rectangle((cx - a, cy - b, cx + a, cy + b), fill=255)
                d.rectangle((cx - b, cy - a, cx + b, cy + a), fill=255)
    elif pattern in ("zigzag", "waves"):
        th = p * 0.2
        steps = 16
        for j in range(rows):
            y0 = j * p
            top = []
            for i in range(cols * steps + 1):
                x = i * p / steps
                ph = (i % steps) / steps
                off = (abs(ph - 0.5) * 2 - 0.5) * p * 0.35 if pattern == "zigzag" else math.sin(ph * 2 * math.pi) * p * 0.16
                top.append((x, y0 + off))
            d.polygon(top + [(x, y + th) for x, y in reversed(top)], fill=255)
    layer = compose([(tone(color, -20 if sum(rgb(color)) > 300 else 26), mask)], p, edge=1.6, shadow=0.22)
    base = base.convert("RGBA")
    base.alpha_composite(layer)
    return base.convert("RGB")


def rays_layer(size: int, color, n: int = 18) -> Image.Image:
    """Square sunburst of alternating paper wedges, rotated per frame by the animator."""
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    c, r = size / 2, size * 0.75
    for i in range(n):
        a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 0.5) / n
        d.polygon([(c, c), (c + r * math.cos(a0), c + r * math.sin(a0)), (c + r * math.cos(a1), c + r * math.sin(a1))], fill=255)
    return compose([(tone(color, -24 if sum(rgb(color)) > 300 else 26), mask)], size // 12, edge=2.0, shadow=0.2)


def floater_sprite(shape: str, px: int, color) -> Image.Image:
    return shape_sprite([(color, FLOATER_SHAPES[shape])], px)


# ---------- torn-paper transitions ----------

def torn_edge(n: int, amp: float, seed: int) -> list[float]:
    rnd = random.Random(seed)
    vals, v = [], 0.0
    for _ in range(n + 1):
        v = max(-1.0, min(1.0, v * 0.55 + rnd.uniform(-1, 1)))
        vals.append(v * amp)
    return vals


def sheet_over(prev: Image.Image, cur: Image.Image, mask: Image.Image, shadow: float = 0.45) -> Image.Image:
    """Lay `cur` (where mask is white) over `prev` like a sheet of paper, with a soft cast shadow."""
    w, h = prev.size
    small = mask.resize((max(1, w // 4), max(1, h // 4)), Image.BILINEAR)
    sh = ImageChops.offset(small, 3, 5).filter(ImageFilter.GaussianBlur(5)).resize((w, h), Image.BILINEAR)
    sh = sh.point(lambda v: int(v * shadow))
    out = Image.composite(Image.new("RGB", (w, h), (25, 18, 10)), prev, sh)
    out.paste(cur, (0, 0), mask)
    return out
