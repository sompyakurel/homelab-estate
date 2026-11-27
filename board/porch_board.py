#!/usr/bin/env python3
"""Generate the Echo Show 11 board image (1280x800) for the Memory Wall / Who's Here board.

Usage:
  porch_board.py --name Som --photo /tmp/porch_snap.jpg \
      --visitors 0 --strangers 0 --deliveries 0 --door Locked \
      --out /tmp/porch-board-som.jpg

The board shows: "Namaste, welcome home, <name>" + the person's photo
(Memory Wall) + a Who's Here strip (today's visitors/strangers/deliveries
and front-door state). Designed for Echo Show 11 (1280x800).

Single photo (JPEG, as before):
  porch_board.py --name Som --photo /tmp/porch_snap.jpg ... --out /tmp/board.jpg

Multiple photos (animated GIF, rotating — 2026-11-26, Som asked for 8):
  porch_board.py --name Som --photos /tmp/a.jpg,/tmp/b.jpg,/tmp/c.jpg \
      ... --out /tmp/board.gif [--duration 3000]
Each frame is a full board with a different photo; the GIF loops forever.
"""
import argparse
import sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance


W, H = 1280, 800
BG = (17, 17, 17)
CARD = (34, 34, 34)
BORDER = (68, 68, 68)
GOLD = (255, 210, 125)
WHITE = (255, 255, 255)
MUTED = (170, 170, 170)
GIF_DURATION_MS = 3000  # per photo


def font(size, bold=True):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def fit_blur(photo, box_w, box_h):
    """Fit `photo` inside a box_w x box_h box WITHOUT cropping, so the
    whole image is visible at its correct proportions. The leftover space
    is filled with a blurred, darkened copy of the same photo, so the box
    still looks full and wide instead of black bars.
    This replaces the old cover-crop, which mangled photos: a centre crop
    cut heads off, and a top-biased crop made some photos worse (Som,
    2026-11-26 — "look at each individual image's sizing and fit it
    accordingly"). Every photo is now sized to its own aspect ratio."""
    # Background: the photo scaled to COVER the box, blurred + darkened.
    w, h = photo.size
    scale = max(box_w / w, box_h / h)
    nw, nh = round(w * scale), round(h * scale)
    bg = photo.resize((nw, nh), Image.LANCZOS)
    bg = bg.crop(((nw - box_w) // 2, (nh - box_h) // 2,
                  (nw - box_w) // 2 + box_w, (nh - box_h) // 2 + box_h))
    bg = bg.filter(ImageFilter.GaussianBlur(radius=28))
    bg = ImageEnhance.Brightness(bg).enhance(0.55)
    # Foreground: the photo fitted INSIDE the box (contain), whole image.
    scale = min(box_w / w, box_h / h)
    fw, fh = round(w * scale), round(h * scale)
    fg = photo.resize((fw, fh), Image.LANCZOS)
    out = bg.copy()
    out.paste(fg, ((box_w - fw) // 2, (box_h - fh) // 2))
    return out


def build_frame(name, photo_path, visitors, strangers, deliveries, door):
    """One full board (RGB image) with the given photo."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Title — compact, so the photo gets maximum height (portrait photos
    # are height-limited; a taller photo box makes them bigger).
    title = f"Namaste, welcome home, {name}"
    tf = font(44, bold=True)
    tb = d.textbbox((0, 0), title, font=tf)
    d.text(((W - (tb[2] - tb[0])) // 2, 12), title, font=tf, fill=WHITE)
    sub = "Memory Wall  ·  Who's Here"
    sf = font(22, bold=False)
    sb = d.textbbox((0, 0), sub, font=sf)
    d.text(((W - (sb[2] - sb[0])) // 2, 62), sub, font=sf, fill=GOLD)

    # Photo — tall box so portrait photos (most of them) render big.
    # Each photo is fitted whole (fit-inside, no cropping) over a blurred
    # copy of itself. Box 1220x580: a portrait 3:4 photo renders 435x580
    # (was 345x460 in the 1220x460 box — Som: "bit too small").
    photo = Image.open(photo_path).convert("RGB")
    box_w, box_h = 1220, 580
    photo = fit_blur(photo, box_w, box_h)
    px, py = 30, 90
    # border
    d.rounded_rectangle([px - 6, py - 6, px + photo.width + 6, py + photo.height + 6],
                        radius=16, outline=BORDER, width=4)
    img.paste(photo, (px, py))

    # Stat cards row
    cards = [
        (str(visitors), "visitors today"),
        (str(strangers), "strangers today"),
        (str(deliveries), "deliveries today"),
        (str(door), "front door"),
    ]
    card_w, card_h, gap = 270, 100, 20
    total = card_w * len(cards) + gap * (len(cards) - 1)
    x = (W - total) // 2
    y = py + photo.height + 16
    nf = font(44, bold=True)
    lf = font(20, bold=False)
    for value, label in cards:
        d.rounded_rectangle([x, y, x + card_w, y + card_h], radius=14, fill=CARD, outline=BORDER, width=2)
        vb = d.textbbox((0, 0), value, font=nf)
        d.text((x + (card_w - (vb[2] - vb[0])) // 2, y + 10), value, font=nf, fill=WHITE)
        lb = d.textbbox((0, 0), label, font=lf)
        d.text((x + (card_w - (lb[2] - lb[0])) // 2, y + 62), label, font=lf, fill=MUTED)
        x += card_w + gap

    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--photo", default=None, help="path to the person's photo (JPEG/PNG) — single-photo JPEG board")
    ap.add_argument("--photos", default=None, help="comma-separated photo paths — animated GIF board, one frame per photo")
    ap.add_argument("--duration", type=int, default=GIF_DURATION_MS, help="ms per GIF frame (default 3000)")
    ap.add_argument("--visitors", default="0")
    ap.add_argument("--strangers", default="0")
    ap.add_argument("--deliveries", default="0")
    ap.add_argument("--door", default="Locked")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.photos:
        photo_list = [p.strip() for p in args.photos.split(",") if p.strip()]
        if not photo_list:
            print("no photos given", file=sys.stderr)
            return 1
        frames = []
        for p in photo_list:
            try:
                frames.append(build_frame(args.name, p, args.visitors, args.strangers, args.deliveries, args.door))
            except Exception as e:
                print(f"cannot open photo {p}: {e}", file=sys.stderr)
                return 1
        # Animated GIF: each frame is quantised with its own adaptive
        # palette (photos differ, so a shared palette would mangle colours).
        # loop=0 means loop forever.
        frames[0].save(
            args.out, "GIF", save_all=True, append_images=frames[1:],
            duration=args.duration, loop=0, optimize=True,
        )
        print(f"wrote {args.out} ({W}x{H}, {len(frames)} frames x {args.duration}ms, loop)")
        return 0

    if not args.photo:
        print("need --photo or --photos", file=sys.stderr)
        return 1
    try:
        img = build_frame(args.name, args.photo, args.visitors, args.strangers, args.deliveries, args.door)
    except Exception as e:
        print(f"cannot open photo {args.photo}: {e}", file=sys.stderr)
        return 1
    img.save(args.out, "JPEG", quality=88)
    print(f"wrote {args.out} ({W}x{H})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
