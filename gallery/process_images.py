#!/usr/bin/env python3
"""
Gallery image pipeline
======================

Drop photographs into  gallery/images/  and run:

    python process_images.py

For every photograph the script will
  1. read its size and decide whether it is portrait, landscape or square,
  2. pick a compatible frame (and stickers) from  frames/  and  stickers/ ,
  3. fit the photo into the frame's window without distorting it,
  4. add a subtle light overlay, the frame, the stickers and a soft shadow,
  5. write optimised, content-hashed WebP + AVIF files in several widths to
     generated/ ,
  6. update manifest.json (the website reads it, so no frontend edits needed).

Nothing is regenerated unless it has to be: a photo is only re-rendered when
its pixels, its frame, its stickers or the render settings below change.
Frame / sticker choices are saved in the manifest, so existing photographs keep
their look when you add new ones.

Requirements:  pip install pillow numpy      (Pillow >= 10 with WebP; AVIF optional)

Design mapping (optional): gallery/design.json pins chosen photographs to exact frames,
stickers, crops and page positions (used to reproduce the design layouts). Photographs not
listed there are handled exactly as described above.

Useful options:
    --seed N         use a specific random seed (only matters for NEW photos)
    --reshuffle      throw away saved frame/sticker choices and pick again
    --force          re-render everything even if nothing changed
    --no-avif        skip AVIF (WebP only; faster)
    --dry-run        show what would happen, write nothing
    --keep-orphans   do not delete generated files that are no longer used
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter, ImageOps, UnidentifiedImageError, features
except ImportError:  # pragma: no cover
    sys.exit("This script needs Pillow and NumPy:  pip install pillow numpy")

try:                                   # optional: iPhone .heic/.heif photographs
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIC_OK = True
except ImportError:                    # pragma: no cover
    HEIC_OK = False

# ----------------------------------------------------------------------------
# Settings (change these to tune the look; changing them re-renders images)
# ----------------------------------------------------------------------------
RENDER_VERSION = 1                 # bump to force a re-render of everything

# OVERLAY_COLOR = (0, 0, 0)
# OVERLAY_OPACITY = 0.0 

SHADOW_COLOR = (62, 52, 40)        # soft shadow baked in, like the reference
SHADOW_OPACITY = 0.34
SHADOW_BLUR = 0.022                # fraction of frame width
SHADOW_OFFSET = (0.020, 0.024)     # fraction of frame width (right, down)

MAX_PHOTO_UPSCALE = 2.0            # never enlarge a photo more than this
MAX_MASTER_WIDTH = 1500            # largest generated width in px
TARGET_WIDTHS = (360, 560, 800, 1100, 1500)   # srcset ladder (capped at master)
MIN_VARIANT_WIDTH = 240

WEBP_QUALITY = 82
AVIF_QUALITY = 58
AVIF_SPEED = 7                     # 0 = slowest/best ... 10 = fastest

MAX_ASPECT_MISMATCH = math.log(1.40)   # crop at most ~29 % off one side
SQUARE_RANGE = (0.91, 1.10)            # aspect ratios treated as "square"

STICKER_CHANCES = {0: 0.30, 1: 0.70}   # one sticker per frame at most; about a third of frames have none
STICKER_WIDTH_RANGE = (0.20, 0.31)    # sticker width as a fraction of the frame
STICKER_MAX_UPSCALE = 1.6
STICKER_MAX_WINDOW_OVERLAP = 0.04     # keep stickers off the photograph
STICKER_MIN_FRAME_COVER = 0.45        # at least this share of a sticker must rest on the frame itself
STICKER_MAX_OUTSIDE = 0.30            # at most this share may stick out past the frame's outline
STICKER_ROTATION = 22                 # degrees, +/-

# "Hanging" stickers (e.g. the ivy vine) drape down from the top edge of the frame and may
# overlap the top corner of the picture, as in the design reference. They are used sparingly.
HANGING_KEYWORDS = ("vine", "ivy")
HANGING_WEIGHT = 0.35                 # relative chance compared with ordinary stickers
HANGING_HEIGHT_RANGE = (0.55, 0.78)   # of the picture window's height

SUPPORTED = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".bmp", ".tif", ".tiff", ".gif"}

# ----------------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
IMAGES_DIR = ROOT / "images"
FRAMES_DIR = ROOT / "frames"
STICKERS_DIR = ROOT / "stickers"
OUT_DIR = ROOT / "generated"
MANIFEST = ROOT / "manifest.json"
MANIFEST_JS = ROOT / "manifest.js"      # same data, for opening the page from file://
DESIGN = ROOT / "design.json"            # optional: exact photo -> frame/sticker/position mapping
CAPTIONS = IMAGES_DIR / "captions.json"  # optional: {"file.jpg": {"alt": "...", "title": "..."}}

# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------

def log(msg: str = "") -> None:
    print(msg, flush=True)


def sha(data: bytes, n: int = 16) -> str:
    return hashlib.sha256(data).hexdigest()[:n]


def file_hash(path: Path, n: int = 16) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:n]


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "image"


def natural_key(p: Path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]


def rng_for(seed: int, *parts: str) -> random.Random:
    """Deterministic RNG for (seed, name): the same photo always gets the same dice."""
    digest = hashlib.sha256("|".join([str(seed), *parts]).encode()).hexdigest()
    return random.Random(int(digest[:12], 16))


def orientation_of(aspect: float) -> str:
    if aspect > SQUARE_RANGE[1]:
        return "landscape"
    if aspect < SQUARE_RANGE[0]:
        return "portrait"
    return "square"


def config_digest() -> str:
    cfg = dict(v=RENDER_VERSION, sc=SHADOW_COLOR, so=SHADOW_OPACITY,
               sb=SHADOW_BLUR, sf=SHADOW_OFFSET, up=MAX_PHOTO_UPSCALE, mw=MAX_MASTER_WIDTH, tw=TARGET_WIDTHS,
               mv=MIN_VARIANT_WIDTH, wq=WEBP_QUALITY, aq=AVIF_QUALITY)
    return sha(json.dumps(cfg, sort_keys=True).encode(), 10)


# ----------------------------------------------------------------------------
# Frames: find the transparent "window" in each frame
# ----------------------------------------------------------------------------

@dataclass
class Frame:
    id: str
    path: Path
    hash: str
    size: tuple            # canvas (w, h)
    window_bbox: tuple     # x0, y0, x1, y1 (inclusive-exclusive)
    window_mask: np.ndarray = field(repr=False, default=None)   # bool, canvas size
    alpha_bbox: tuple = (0, 0, 0, 0)
    shape: str = "rect"    # rect | oval
    aspect: float = 1.0    # window width / height
    orientation: str = "square"

    def public(self) -> dict:
        x0, y0, x1, y1 = self.window_bbox
        return {"file": f"frames/{self.path.name}", "hash": self.hash, "canvas": list(self.size),
                "window": {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}, "aspect": round(self.aspect, 3),
                "shape": self.shape, "orientation": self.orientation}


def label_components(mask: np.ndarray):
    """4-connected component labelling. Uses SciPy when present, else a small BFS."""
    try:
        from scipy import ndimage  # optional speed-up
        lab, n = ndimage.label(mask)
        return lab, n
    except ImportError:
        pass
    from collections import deque
    h, w = mask.shape
    lab = np.zeros((h, w), dtype=np.int32)
    n = 0
    flat = mask.ravel()
    labf = lab.ravel()
    for start in np.flatnonzero(flat):
        if labf[start]:
            continue
        n += 1
        labf[start] = n
        dq = deque([start])
        while dq:
            i = dq.popleft()
            y, x = divmod(i, w)
            for j, ok in ((i - w, y > 0), (i + w, y < h - 1), (i - 1, x > 0), (i + 1, x < w - 1)):
                if ok and flat[j] and not labf[j]:
                    labf[j] = n
                    dq.append(j)
    return lab, n


def find_window(alpha: np.ndarray):
    """Largest transparent region that is NOT connected to the image border
    (i.e. the opening in the frame that the photograph shows through)."""
    lab, n = label_components(alpha < 24)
    if n == 0:
        return None
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])).tolist()) - {0}
    sizes = np.bincount(lab.ravel(), minlength=n + 1)
    inner = [(sizes[i], i) for i in range(1, n + 1) if i not in border]
    if not inner:
        return None
    return lab == max(inner)[1]


def analyse_frame(path: Path) -> Frame | None:
    try:
        img = Image.open(path).convert("RGBA")
    except (UnidentifiedImageError, OSError) as e:
        log(f"  ! frame {path.name}: cannot read ({e}), skipped")
        return None
    alpha = np.array(img)[:, :, 3]
    mask = find_window(alpha)
    if mask is None or mask.sum() < 0.02 * alpha.size:
        log(f"  ! frame {path.name}: no enclosed transparent window found, skipped")
        return None
    ys, xs = np.where(mask)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    wb = (x0, y0, x1, y1)
    fy, fx = np.where(alpha > 40)
    fill = mask.sum() / float((x1 - x0) * (y1 - y0))
    aspect = (x1 - x0) / float(y1 - y0)
    return Frame(id=path.stem, path=path, hash=file_hash(path), size=img.size, window_bbox=wb, window_mask=mask,
                 alpha_bbox=(int(fx.min()), int(fy.min()), int(fx.max()) + 1, int(fy.max()) + 1),
                 shape="oval" if fill < 0.86 else "rect", aspect=aspect, orientation=orientation_of(aspect))


def load_frames() -> dict:
    frames = {}
    if not FRAMES_DIR.is_dir():
        return frames
    for p in sorted(FRAMES_DIR.iterdir(), key=natural_key):
        if p.suffix.lower() in SUPPORTED:
            fr = analyse_frame(p)
            if fr:
                frames[fr.id] = fr
    return frames


def load_stickers() -> dict:
    out = {}
    if not STICKERS_DIR.is_dir():
        return out
    for p in sorted(STICKERS_DIR.iterdir(), key=natural_key):
        if p.suffix.lower() in SUPPORTED:
            try:
                with Image.open(p) as im:
                    im.verify()
                out[p.stem] = {"path": p, "hash": file_hash(p)}
            except Exception as e:  # noqa: BLE001
                log(f"  ! sticker {p.name}: unreadable ({e}), skipped")
    return out


# ----------------------------------------------------------------------------
# Choosing frames and stickers
# ----------------------------------------------------------------------------

def compatible_frames(frames: dict, aspect: float):
    """[(frame, mismatch)] sorted best-first; falls back to the closest ones."""
    scored = sorted(((f, abs(math.log(f.aspect / aspect))) for f in frames.values()), key=lambda t: t[1])
    ok = [t for t in scored if t[1] <= MAX_ASPECT_MISMATCH]
    return ok if ok else scored[:2]


def pick_weighted(rng: random.Random, options, weights):
    total = sum(weights)
    if total <= 0:
        return rng.choice(options)
    return rng.choices(options, weights=weights, k=1)[0]


def choose_frame(rng, frames, aspect, usage, previous_id):
    options = compatible_frames(frames, aspect)
    if not options:
        return None
    weights = []
    for fr, mismatch in options:
        w = 1.0 / (1.0 + usage.get(fr.id, 0)) ** 2.2          # give every frame its turn
        w *= math.exp(-1.2 * mismatch)                         # prefer a closer shape
        if fr.id == previous_id and len(options) > 1:
            w *= 0.02                                          # avoid back-to-back repeats
        weights.append(w)
    return pick_weighted(rng, [o[0] for o in options], weights)


def is_hanging(sticker_id: str) -> bool:
    return any(k in sticker_id.lower() for k in HANGING_KEYWORDS)


def choose_sticker_files(rng, stickers, usage, previous: list):
    if not stickers:
        return []
    r, acc, count = rng.random(), 0.0, 1
    for n, p in sorted(STICKER_CHANCES.items()):
        acc += p
        if r <= acc:
            count = n
            break
    chosen = []
    for _ in range(count):
        ids = [s for s in stickers if s not in chosen and not (is_hanging(s) and any(is_hanging(c) for c in chosen))]
        if not ids:
            break
        ws = []
        for s in ids:
            w = 1.0 / (1.0 + usage.get(s, 0)) ** 2.0
            if s in previous:
                w *= 0.05
            if is_hanging(s):
                w *= HANGING_WEIGHT
            ws.append(w)
        chosen.append(pick_weighted(rng, ids, ws))
    return chosen


def ray_boundary_points(alpha: np.ndarray, n: int = 24):
    """Points on the outer edge of the frame, found by casting rays from its centre."""
    ys, xs = np.where(alpha > 128)
    cx, cy = xs.mean(), ys.mean()
    h, w = alpha.shape
    pts = []
    for k in range(n):
        ang = 2 * math.pi * k / n
        dx, dy = math.cos(ang), math.sin(ang)
        last = None
        for step in range(0, int(max(h, w))):
            x, y = int(round(cx + dx * step)), int(round(cy + dy * step))
            if not (0 <= x < w and 0 <= y < h):
                break
            if alpha[y, x] > 128:
                last = (x, y)
        if last:
            pts.append({"angle": ang, "x": last[0], "y": last[1], "dx": dx, "dy": dy})
    return pts


def place_hanging(rng, frame: Frame, sid: str, simg: Image.Image, fw: int, fh: int):
    """Hang a sticker (vine) from the top edge of the picture window, in a left or right part."""
    wx0, wy0, wx1, wy1 = frame.window_bbox
    win_w, win_h = wx1 - wx0, wy1 - wy0
    bb = simg.getchannel("A").getbbox() or (0, 0) + simg.size
    simg = simg.crop(bb)
    target_h = win_h * rng.uniform(*HANGING_HEIGHT_RANGE)
    scale = target_h / simg.height
    tw = simg.width * scale
    rot = rng.uniform(-5, 5)
    flip = rng.random() < 0.5
    side = rng.uniform(0.12, 0.34)
    cx = wx0 + win_w * (1 - side if flip else side)
    # find where the window's top edge is at this x (ovals curve away)
    col = int(min(max(cx, wx0), wx1 - 1))
    ys = np.where(frame.window_mask[:, col])[0]
    ax0, ay0, ax1, ay1 = frame.alpha_bbox
    top = (ys.min() if len(ys) else wy0) - target_h * 0.10     # start slightly above the opening
    top = max(top, ay0 + (wy0 - ay0) * 0.35)                   # ...but never above the frame itself
    cy = top + target_h / 2
    return {"id": sid, "cx": round(cx / fw, 4), "cy": round(cy / fh, 4), "width": round(tw / fw, 4),
            "rotation": round(rot, 1), "flip": flip, "crop": list(bb)}


def place_stickers(rng, frame: Frame, sticker_ids: list, stickers: dict):
    """Attach stickers to the frame's rim, away from the photograph.

    Positions are stored relative to the frame canvas (0..1) so they survive
    any output size, and are baked into the final image so they can never drift
    when the frame is rotated or moved on the page.
    """
    if not sticker_ids:
        return []
    fimg = np.array(Image.open(frame.path).convert("RGBA"))[:, :, 3]
    fh, fw = fimg.shape
    ax0, ay0, ax1, ay1 = frame.alpha_bbox
    frame_w = ax1 - ax0
    rim = ray_boundary_points(fimg)
    wmask = frame.window_mask
    placed, used_angles = [], []
    for sid in sticker_ids:
        simg = Image.open(stickers[sid]["path"]).convert("RGBA")
        if is_hanging(sid):
            hp = place_hanging(rng, frame, sid, simg, fw, fh)
            if hp:
                placed.append(hp)
            continue
        sw0, sh0 = simg.size
        tw = min(frame_w * rng.uniform(*STICKER_WIDTH_RANGE), sw0 * STICKER_MAX_UPSCALE)
        scale = tw / sw0
        rot = rng.uniform(-STICKER_ROTATION, STICKER_ROTATION)
        flip = rng.random() < 0.5
        s_img = simg.resize((max(2, int(tw)), max(2, int(sh0 * scale))), Image.BILINEAR)
        if flip:
            s_img = ImageOps.mirror(s_img)
        s_img = s_img.rotate(rot, expand=True, resample=Image.BILINEAR)
        s_alpha = np.array(s_img)[:, :, 3] > 100
        sh, sw = s_alpha.shape
        fmask = fimg > 128
        s_area = max(1, int(s_alpha.sum()))
        cands = []
        # strict first; if the frame is too slim for that, relax a little (never past the outline)
        for cover_min, win_max, out_max in ((STICKER_MIN_FRAME_COVER, STICKER_MAX_WINDOW_OVERLAP, STICKER_MAX_OUTSIDE),
                                            (0.25, 0.10, 0.40), (0.12, 0.16, 0.50)):
            for pt in rim:
                if any(abs(math.atan2(math.sin(pt["angle"] - a), math.cos(pt["angle"] - a))) < 0.6 for a in used_angles):
                    continue
                for inward in (0.05, 0.15, 0.25, 0.35, 0.45):
                    cx = pt["x"] - pt["dx"] * sw * inward
                    cy = pt["y"] - pt["dy"] * sh * inward
                    x0, y0 = int(cx - sw / 2), int(cy - sh / 2)
                    ox0, oy0, ox1, oy1 = max(x0, 0), max(y0, 0), min(x0 + sw, fw), min(y0 + sh, fh)
                    if ox1 <= ox0 or oy1 <= oy0:
                        continue
                    sub = s_alpha[oy0 - y0:oy1 - y0, ox0 - x0:ox1 - x0]
                    ov = float((sub & wmask[oy0:oy1, ox0:ox1]).sum()) / s_area          # over the photograph
                    cover = float((sub & fmask[oy0:oy1, ox0:ox1]).sum()) / s_area       # resting on the frame
                    bx0, by0, bx1, by1 = max(ox0, ax0), max(oy0, ay0), min(ox1, ax1), min(oy1, ay1)
                    inside = 0.0
                    if bx1 > bx0 and by1 > by0:
                        inside = float(s_alpha[by0 - y0:by1 - y0, bx0 - x0:bx1 - x0].sum()) / s_area
                    if ov <= win_max and cover >= cover_min and (1.0 - inside) <= out_max:
                        ang = pt["angle"]
                        pref = 1.0 + 1.2 * max(0, math.sin(ang)) + 0.6 * max(0, math.cos(ang) * -math.sin(ang))
                        cands.append((pref * (1.0 - ov) * (0.5 + cover), pt["angle"], cx, cy))
            if cands:
                break
        if not cands:
            continue
        pick = pick_weighted(rng, cands, [c[0] for c in cands])
        used_angles.append(pick[1])
        placed.append({"id": sid, "cx": round(pick[2] / fw, 4), "cy": round(pick[3] / fh, 4),
                       "width": round(tw / fw, 4), "rotation": round(rot, 1), "flip": flip})
    return placed


# ----------------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------------

def load_photo(path: Path) -> Image.Image:
    with Image.open(path) as im:
        im.load()
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (244, 241, 232))
            bg.paste(im, mask=im.getchannel("A"))
            return bg
        if im.mode != "RGB":
            im = im.convert("RGB")
        return im.copy()


def cover_fit(photo: Image.Image, size: tuple, focus_y: float, focus_x: float = 0.5, zoom: float = 1.0) -> Image.Image:
    tw, th = size
    pw, ph = photo.size
    s = max(tw / pw, th / ph) * max(1.0, zoom)
    nw, nh = max(tw, round(pw * s)), max(th, round(ph * s))
    resized = photo.resize((nw, nh), Image.LANCZOS)
    left = int((nw - tw) * focus_x)
    top = int((nh - th) * focus_y)
    return resized.crop((left, top, left + tw, top + th))


def render(photo: Image.Image, frame: Frame, sticker_plan: list, stickers: dict, crop: dict | None = None,
           want_meta: bool = False):
    """Returns the final RGBA composite (trimmed) at its master size.
    With want_meta=True returns (image, meta) where meta records the master scale and where the
    trimmed image starts relative to the frame canvas (used to place pinned frames exactly)."""
    fw0, fh0 = frame.size
    x0, y0, x1, y1 = frame.window_bbox
    win_w, win_h = x1 - x0, y1 - y0
    # scale so the photo is never enlarged more than MAX_PHOTO_UPSCALE
    cover = max(win_w / photo.width, win_h / photo.height)       # frame-px per photo-px at native frame scale
    s = min(1.0, MAX_PHOTO_UPSCALE / cover) if cover > 0 else 1.0
    s = min(s, MAX_MASTER_WIDTH / max(1, fw0 * 1.25))
    fw, fh = max(8, round(fw0 * s)), max(8, round(fh0 * s))
    frame_img = Image.open(frame.path).convert("RGBA").resize((fw, fh), Image.LANCZOS)
    wmask = Image.fromarray((frame.window_mask * 255).astype("uint8"), "L").resize((fw, fh), Image.BILINEAR)
    wmask = wmask.filter(ImageFilter.MaxFilter(5))              # tuck the photo under the frame edge
    wx0, wy0 = round(x0 * s), round(y0 * s)
    ww, wh = max(2, round(win_w * s)), max(2, round(win_h * s))
    focus_y = 0.5 if photo.width >= photo.height else 0.36        # keep faces in portraits
    if crop:                                                      # exact crop taken from the design
        art = cover_fit(photo, (ww, wh), crop["focus"][1], crop["focus"][0], crop.get("zoom", 1.0))
    else:
        art = cover_fit(photo, (ww, wh), focus_y)
    layer = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    layer.paste(art.convert("RGBA"), (wx0, wy0))

    layer.putalpha(Image.fromarray(np.array(wmask), "L"))
    comp = Image.alpha_composite(layer, frame_img)

    # stickers go on a larger canvas so they may overhang the frame
    pad = round(fw * 0.35)
    canvas = Image.new("RGBA", (fw + 2 * pad, fh + 2 * pad), (0, 0, 0, 0))
    canvas.alpha_composite(comp, (pad, pad))
    for st in sticker_plan:
        spec = stickers.get(st["id"])
        if not spec:
            continue
        simg = Image.open(spec["path"]).convert("RGBA")
        if st.get("crop"):
            simg = simg.crop(tuple(st["crop"]))
        tw = max(4, round(st["width"] * fw))
        simg = simg.resize((tw, max(4, round(simg.height * tw / simg.width))), Image.LANCZOS)
        if st["flip"]:
            simg = ImageOps.mirror(simg)
        simg = simg.rotate(st["rotation"], expand=True, resample=Image.BICUBIC)
        cx, cy = pad + st["cx"] * fw, pad + st["cy"] * fh
        canvas.alpha_composite(simg, (int(cx - simg.width / 2), int(cy - simg.height / 2)))

    # baked drop shadow (union of frame + stickers)
    alpha = canvas.getchannel("A")
    dx, dy = round(SHADOW_OFFSET[0] * fw), round(SHADOW_OFFSET[1] * fw)
    blur = max(1.0, SHADOW_BLUR * fw)
    sh_alpha = Image.new("L", canvas.size, 0)
    sh_alpha.paste(alpha, (dx, dy))
    sh_alpha = sh_alpha.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * SHADOW_OPACITY))
    shadow = Image.new("RGBA", canvas.size, SHADOW_COLOR + (0,))
    shadow.putalpha(sh_alpha)
    final = Image.alpha_composite(shadow, canvas)
    bbox = final.getchannel("A").point(lambda v: 255 if v > 3 else 0).getbbox()
    out = final.crop(bbox) if bbox else final
    if want_meta:
        ox, oy = (bbox[0] - pad, bbox[1] - pad) if bbox else (-pad, -pad)
        return out, {"scale": s, "origin": [ox, oy]}
    return out


def encode_variants(img: Image.Image, stem: str, formats: list, out_dir: Path):
    """Write the width ladder; returns {"webp": [(file, w, bytes)], "avif": [...]}"""
    W, H = img.size
    widths = sorted({w for w in TARGET_WIDTHS if MIN_VARIANT_WIDTH <= w < W} | {W})
    result = {fmt: [] for fmt in formats}
    for w in widths:
        h = max(1, round(H * w / W))
        im = img if w == W else img.resize((w, h), Image.LANCZOS)
        for fmt in formats:
            name = f"{stem}-{w}w.{fmt}"
            path = out_dir / name
            if fmt == "webp":
                im.save(path, "WEBP", quality=WEBP_QUALITY, method=6, alpha_quality=92)
            else:
                im.save(path, "AVIF", quality=AVIF_QUALITY, speed=AVIF_SPEED)
            result[fmt].append({"src": f"generated/{name}", "w": w, "bytes": path.stat().st_size})
    return result, (W, H)


# ----------------------------------------------------------------------------
# Design mapping (design.json)
# ----------------------------------------------------------------------------

def load_design() -> dict:
    """{photo file name: entry}. Missing or invalid file -> {} (everything is then random)."""
    if not DESIGN.is_file():
        return {"canvas_width": 1440, "stage_top": 0, "items": {}}
    try:
        data = json.loads(DESIGN.read_text("utf-8"))
        data.setdefault("items", {})
        return data
    except (json.JSONDecodeError, OSError) as e:
        log(f"  ! design.json could not be read ({e}); ignoring it")
        return {"canvas_width": 1440, "stage_top": 0, "items": {}}


def design_frame(entry: dict, frames: dict):
    prefs = entry.get("frame")
    prefs = [prefs] if isinstance(prefs, str) else list(prefs or [])
    for fid in prefs:
        if fid in frames:
            if fid != prefs[0]:
                log(f"    note: frame '{prefs[0]}' is not in frames/ yet, using '{fid}' instead")
            return frames[fid]
    return None


def design_stickers(entry: dict, frame: Frame, stickers: dict) -> list:
    """Convert design coordinates (page units) into the sticker plan used by render()."""
    fx, fy, fw = entry["frame_box"]
    fh = frame.size[1] * fw / frame.size[0]
    plan = []
    for st in entry.get("stickers", []):
        sid = st["id"]
        if sid not in stickers:
            log(f"    note: sticker '{sid}' from design.json not found in stickers/, skipped")
            continue
        with Image.open(stickers[sid]["path"]) as im:
            bb = im.convert("RGBA").getchannel("A").getbbox() or (0, 0) + im.size
        cx, cy = st["center"]
        plan.append({"id": sid, "cx": round((cx - fx) / fw, 5), "cy": round((cy - fy) / fh, 5),
                     "width": round(st["width"] / fw, 5), "rotation": st.get("rotation", 0),
                     "flip": bool(st.get("flip", False)), "crop": list(bb)})
    return plan


def design_pin(entry: dict, frame: Frame, item: dict):
    """Where the trimmed image goes on the design artboard (page units)."""
    if not item.get("origin") or not item.get("master_scale"):
        return None
    fx, fy, fw = entry["frame_box"]
    k = (fw / frame.size[0]) / item["master_scale"]          # page units per master pixel
    ox, oy = item["origin"]
    return {"x": round(fx + ox * k, 2), "y": round(fy + oy * k, 2), "w": round(item["width"] * k, 2)}


# ----------------------------------------------------------------------------
# Manifest
# ----------------------------------------------------------------------------

def load_manifest() -> dict:
    if MANIFEST.is_file():
        try:
            data = json.loads(MANIFEST.read_text("utf-8"))
            if isinstance(data, dict) and isinstance(data.get("items"), list):
                return data
        except (json.JSONDecodeError, OSError):
            log("  ! manifest.json was unreadable; starting a fresh one (existing assignments are lost)")
    return {"items": []}


def write_manifest(data: dict) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False)
    for path, payload in ((MANIFEST, text), (MANIFEST_JS, "window.__GALLERY_MANIFEST__ = " + text + ";\n")):
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(payload, "utf-8")
        tmp.replace(path)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Frame, optimise and catalogue gallery photographs.")
    ap.add_argument("--seed", type=int, help="random seed for NEW photographs (saved in the manifest)")
    ap.add_argument("--reshuffle", action="store_true", help="discard saved frame/sticker choices and pick again")
    ap.add_argument("--force", action="store_true", help="re-render every image")
    ap.add_argument("--no-avif", action="store_true", help="skip AVIF output")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--keep-orphans", action="store_true", help="keep unused files in generated/")
    ap.add_argument("--allow-duplicates", action="store_true", help="process byte-identical photos separately")
    args = ap.parse_args(argv)

    t0 = time.time()
    formats = ["webp"] + ([] if args.no_avif or not features.check("avif") else ["avif"])
    if not args.no_avif and "avif" not in formats:
        log("note: this Pillow build has no AVIF support, writing WebP only")

    for d in (IMAGES_DIR, FRAMES_DIR, STICKERS_DIR):
        d.mkdir(exist_ok=True)
    if not args.dry_run:
        OUT_DIR.mkdir(exist_ok=True)

    log("Reading frames and stickers ...")
    frames = load_frames()
    stickers = load_stickers()
    design = load_design()
    dmap = design.get("items", {})
    if dmap:
        log(f"  design.json: {len(dmap)} photograph(s) are pinned to exact frames/positions")
    if not frames:
        log(f"  ! no usable frames in {FRAMES_DIR.name}/ : photographs will be shown without a frame")
    log(f"  {len(frames)} frames ({', '.join(sorted({f.orientation for f in frames.values()})) or 'none'}), {len(stickers)} stickers")

    prev = load_manifest()
    prev_items = {it["source"]: it for it in prev.get("items", []) if "source" in it}
    seed = args.seed if args.seed is not None else prev.get("seed")
    if seed is None:
        seed = random.SystemRandom().randrange(1, 2**31)
    captions = {}
    if CAPTIONS.is_file():
        try:
            captions = json.loads(CAPTIONS.read_text("utf-8"))
        except json.JSONDecodeError:
            log("  ! images/captions.json is not valid JSON, ignored")

    # --- find photographs -----------------------------------------------------
    sources, skipped = [], []
    for p in sorted(IMAGES_DIR.iterdir(), key=natural_key) if IMAGES_DIR.is_dir() else []:
        if p.name.startswith(".") or p.is_dir() or p.name == "captions.json":
            continue
        if p.suffix.lower() in (".heic", ".heif") and not HEIC_OK:
            skipped.append({"file": p.name, "reason": "HEIC/HEIF photo: install support with  pip install pillow-heif"})
            continue
        if p.suffix.lower() not in SUPPORTED and not (HEIC_OK and p.suffix.lower() in (".heic", ".heif")):
            skipped.append({"file": p.name, "reason": f"unsupported format ({p.suffix or 'no extension'})"})
            continue
        sources.append(p)
    log(f"Found {len(sources)} photograph(s) in {IMAGES_DIR.name}/")

    # keep earlier photographs in their saved order, append new ones after them
    order = {name: i for i, name in enumerate(it["source"] for it in prev.get("items", []))}
    dorder = {name: i for i, name in enumerate(dmap)}
    sources.sort(key=lambda p: (0 if p.name in dorder else 1, dorder.get(p.name, 0),
                                order.get(p.name, 10**9), natural_key(p)))

    # usage counters from saved assignments (so balancing continues across runs)
    frame_use, sticker_use = {}, {}
    if not args.reshuffle:
        for it in prev.get("items", []):
            if it.get("source") in {p.name for p in sources}:
                if it.get("frame") in frames:
                    frame_use[it["frame"]] = frame_use.get(it["frame"], 0) + 1
                for st in it.get("stickers", []):
                    if st.get("id") in stickers:
                        sticker_use[st["id"]] = sticker_use.get(st["id"], 0) + 1

    # designed photographs count towards the usage balance, so random picks fill in the gaps
    for p in sources:
        d = dmap.get(p.name)
        if d:
            f = design_frame(d, frames)
            if f:
                frame_use[f.id] = frame_use.get(f.id, 0) + 1
            for st in d.get("stickers", []):
                sticker_use[st["id"]] = sticker_use.get(st["id"], 0) + 1

    items, seen_hashes = [], {}
    previous_frame, previous_stickers = None, []
    counts = {"new": 0, "updated": 0, "unchanged": 0}
    cfg = config_digest()
    keep_files = set()

    for p in sources:
        try:
            src_hash = file_hash(p)
            dd = dmap.get(p.name) or {}
            if not args.allow_duplicates and not dd.get("allow_duplicate") and src_hash in seen_hashes:
                skipped.append({"file": p.name, "reason": f"identical to {seen_hashes[src_hash]}, skipped"})
                continue
            photo = load_photo(p)
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as e:
            skipped.append({"file": p.name, "reason": f"unreadable or corrupted ({type(e).__name__})"})
            log(f"  ! {p.name}: unreadable/corrupted, skipped")
            continue
        seen_hashes[src_hash] = p.name
        pw, ph = photo.size
        aspect = pw / ph
        orient = orientation_of(aspect)
        old_item = prev_items.get(p.name) if not args.reshuffle else None
        rng = rng_for(seed, p.name)

        # ---- decide frame + stickers (saved, so they stay put) ---------------
        dentry = dmap.get(p.name)
        frame = design_frame(dentry, frames) if dentry else None
        designed = frame is not None
        if dentry and not designed:
            log(f"    note: no frame from design.json is available for {p.name}; choosing one at random")
            dentry = None
        if designed:
            pass
        elif old_item and old_item.get("frame") in frames:
            cand = frames[old_item["frame"]]
            if abs(math.log(cand.aspect / aspect)) <= MAX_ASPECT_MISMATCH * 1.15 and cand.hash == old_item.get("frame_hash", cand.hash):
                frame = cand
        reassigned = frame is None
        if frame is None:
            frame = choose_frame(rng, frames, aspect, frame_use, previous_frame)
            if frame is not None:
                frame_use[frame.id] = frame_use.get(frame.id, 0) + 1
        plan = []
        if designed:
            plan = design_stickers(dentry, frame, stickers)
        elif frame is not None:
            if old_item and not reassigned and old_item.get("stickers") is not None and \
                    all(s["id"] in stickers for s in old_item["stickers"]):
                plan = old_item["stickers"]
            else:
                ids = choose_sticker_files(rng, stickers, sticker_use, previous_stickers)
                plan = place_stickers(rng, frame, ids, stickers)
                for s in plan:
                    sticker_use[s["id"]] = sticker_use.get(s["id"], 0) + 1
        if frame is not None and not designed and abs(math.log(frame.aspect / aspect)) > MAX_ASPECT_MISMATCH:
            log(f"    note: {p.name} has an unusual shape ({pw}x{ph}); it will be cropped a lot to fit {frame.id}. "
                f"Add a frame with a similar window shape to frames/ for a better result.")
        previous_frame = frame.id if frame else None
        previous_stickers = [s["id"] for s in plan]

        layout = (old_item or {}).get("layout") if (not reassigned or designed) else None
        if not layout:
            lr = rng_for(seed, "layout", p.name)
            layout = {"size": round(lr.random(), 3), "rotation": round(lr.uniform(-2.6, 2.6), 2),
                      "jitter_x": round(lr.uniform(-1, 1), 3), "jitter_y": round(lr.random(), 3),
                      "seed": lr.randrange(1, 2**31)}

        # ---- recipe: when does this image need re-rendering? ---------------
        sticker_sig = [[x["id"], stickers[x["id"]]["hash"], x["cx"], x["cy"], x["width"], x["rotation"], x["flip"]]
                       for x in plan]
        recipe_data = {"cfg": cfg, "src": src_hash, "frame": frame.hash if frame else None,
                       "fmts": formats, "stickers": sticker_sig}
        if designed:                                   # (only designed photos: other recipes stay as they were)
            recipe_data["design_crop"] = dentry.get("crop")
            recipe_data["design_stickers"] = [x.get("crop") for x in plan]
        recipe = sha(json.dumps(recipe_data, sort_keys=True).encode(), 10)
        stem = f"{slugify(p.stem)}-{recipe}"
        reuse = (not args.force and old_item and old_item.get("recipe") == recipe and
                 all((ROOT / v["src"]).is_file() for fmt in formats for v in old_item.get("sources", {}).get(fmt, [])) and
                 set(formats) <= set(old_item.get("sources", {})) and
                 (not designed or old_item.get("origin") is not None))

        if reuse:
            entry = old_item
            entry["layout"] = layout
            counts["unchanged"] += 1
            status = "unchanged"
        else:
            status = "updated" if old_item else "new"
            if args.dry_run:
                counts[status] += 1
                log(f"  [{status:9}] {p.name}  {orient}  ->  {frame.id if frame else 'no frame'}  "
                    f"+ {', '.join(s['id'] for s in plan) or 'no stickers'}")
                continue
            try:
                if frame is None:       # graceful fallback: no frames available
                    img = photo.copy()
                    img.thumbnail((MAX_MASTER_WIDTH, MAX_MASTER_WIDTH), Image.LANCZOS)
                    img = img.convert("RGBA")
                    meta = None
                else:
                    img, meta = render(photo, frame, plan, stickers, crop=(dentry or {}).get("crop") if designed else None,
                                       want_meta=True)
                variants, (mw, mh) = encode_variants(img, stem, formats, OUT_DIR)
            except Exception as e:  # noqa: BLE001
                skipped.append({"file": p.name, "reason": f"processing failed ({type(e).__name__}: {e})"})
                log(f"  ! {p.name}: processing failed: {e}")
                continue
            cap = captions.get(p.name, {}) if isinstance(captions, dict) else {}
            entry = {
                "id": slugify(p.stem),
                "source": p.name,
                "source_hash": src_hash,
                "orientation": orient,
                "photo_size": [pw, ph],
                "frame": frame.id if frame else None,
                "frame_hash": frame.hash if frame else None,
                "stickers": plan,
                "recipe": recipe,
                "width": mw,
                "height": mh,
                "sources": variants,
                "alt": cap.get("alt") or re.sub(r"[-_]+", " ", p.stem).strip().capitalize(),
                "title": cap.get("title") or "",
                "layout": layout,
            }
            if meta:
                entry["origin"] = meta["origin"]
                entry["master_scale"] = round(meta["scale"], 6)
            counts[status] += 1
        entry["layout"] = dict(entry.get("layout") or layout)
        entry["layout"].pop("pin", None)
        entry.pop("design", None)
        if designed:                                   # exact position from the design layout
            entry["design"] = {"label": dentry.get("label", ""), "frame_box": dentry["frame_box"]}
            pin = design_pin(dentry, frame, entry)
            if pin:
                entry["layout"]["pin"] = pin
                entry["layout"]["rotation"] = 0
        if isinstance(captions, dict) and captions.get(p.name):
            entry["alt"] = captions[p.name].get("alt", entry.get("alt"))
            entry["title"] = captions[p.name].get("title", entry.get("title", ""))
        for fmt in formats:
            keep_files |= {Path(v["src"]).name for v in entry["sources"].get(fmt, [])}
        items.append(entry)
        extra = ", ".join(s["id"].replace("sticker-", "") for s in entry["stickers"]) or "-"
        log(f"  [{status:9}] {p.name:32} {orient:9} frame={entry['frame'] or '-':20} stickers={extra}")

    if args.dry_run:
        log(f"\nDry run: {counts['new']} new, {counts['updated']} changed, {counts['unchanged']} unchanged. Nothing written.")
        return 0

    # --- tidy up + write manifest ---------------------------------------------
    removed = 0
    if not args.keep_orphans and OUT_DIR.is_dir():
        for f in OUT_DIR.iterdir():
            if f.is_file() and f.name not in keep_files and f.suffix in (".webp", ".avif", ".tmp"):
                f.unlink()
                removed += 1

    used_frames = {}
    for it in items:
        if it.get("frame"):
            used_frames[it["frame"]] = used_frames.get(it["frame"], 0) + 1
    manifest = {
        "version": 1,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "seed": seed,
        "config": cfg,
        "formats": formats,
        # "overlay": {"color": list(OVERLAY_COLOR), "opacity": OVERLAY_OPACITY},
        "frames": {fid: {**f.public(), "uses": used_frames.get(fid, 0)} for fid, f in frames.items()},
        "stickers": {sid: {"file": f"stickers/{s['path'].name}"} for sid, s in stickers.items()},
        "design": {"canvas_width": design.get("canvas_width", 1440), "stage_top": design.get("stage_top", 0)},
        "items": items,
        "skipped": skipped,
    }
    write_manifest(manifest)

    unused = [fid for fid in frames if fid not in used_frames]
    log("")
    log(f"Done in {time.time() - t0:.1f}s: {counts['new']} new, {counts['updated']} changed, {counts['unchanged']} unchanged"
        f"{', ' + str(removed) + ' old files removed' if removed else ''}.")
    if skipped:
        log("Skipped:")
        for s in skipped:
            log(f"  - {s['file']}: {s['reason']}")
    if unused and len(items) >= len(frames):
        log(f"Frames not used yet: {', '.join(unused)}")
    total = sum(v["bytes"] for it in items for fmt in formats for v in it["sources"].get(fmt, []) if fmt == "webp")
    log(f"Manifest: {MANIFEST.relative_to(ROOT.parent) if ROOT.parent in MANIFEST.parents else MANIFEST}  "
        f"({len(items)} images, {total / 1024:.0f} KB of WebP in total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
