import base64
import io
import random
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "captcha"
_BACKGROUND_PATHS = sorted(p for p in _ASSET_DIR.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png"))

CANVAS_WIDTH = 320
CANVAS_HEIGHT = 180
PIECE_WIDTH = 48
TAB_RADIUS = 9
# The piece's full bounding box is taller than PIECE_WIDTH alone - the top
# tab bump adds TAB_RADIUS of extra height above the square body.
PIECE_HEIGHT = PIECE_WIDTH + TAB_RADIUS
_MARGIN = 12

# A tolerance is needed because the frontend submits wherever the user's
# pointer/keyboard release lands, not necessarily the exact pixel.
CAPTCHA_TOLERANCE_PX = 5


@dataclass
class Puzzle:
    background_image: str  # data: URL, JPEG - the photo with a hole cut in it
    piece_image: str  # data: URL, PNG w/ alpha - the floating jigsaw piece
    canvas_width: int
    canvas_height: int
    piece_width: int
    piece_height: int
    piece_top: int  # y offset to render the piece at (not secret)
    target_x: int  # the x offset that solves it - kept server-side only


def _piece_mask() -> Image.Image:
    """A jigsaw-piece silhouette: a square body with a round tab bump on
    its top edge and a matching notch cut from its bottom edge, so
    dragging the piece back over its own outline reads as fitting a
    puzzle piece rather than just sliding a plain square."""
    mask = Image.new("L", (PIECE_WIDTH, PIECE_HEIGHT), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, TAB_RADIUS, PIECE_WIDTH, PIECE_HEIGHT], radius=6, fill=255)
    cx = PIECE_WIDTH // 2
    draw.ellipse([cx - TAB_RADIUS, 0, cx + TAB_RADIUS, 2 * TAB_RADIUS], fill=255)
    draw.ellipse(
        [cx - TAB_RADIUS, PIECE_HEIGHT - TAB_RADIUS, cx + TAB_RADIUS, PIECE_HEIGHT + TAB_RADIUS],
        fill=0,
    )
    return mask


def _outline_ring(mask: Image.Image) -> Image.Image:
    """A thin ring just outside the piece silhouette, used to draw a
    visible edge around both the hole and the floating piece - without it,
    a piece that closely matches the photo's own colors is hard to see."""
    dilated = mask.filter(ImageFilter.MaxFilter(5))
    return ImageChops.subtract(dilated, mask)


def _fit_and_crop(source: Image.Image) -> Image.Image:
    """Scales the source photo up to cover CANVAS_WIDTH x CANVAS_HEIGHT
    and center-crops the overflow, so every challenge has identical
    geometry regardless of the source photo's own aspect ratio."""
    src_ratio = source.width / source.height
    canvas_ratio = CANVAS_WIDTH / CANVAS_HEIGHT
    if src_ratio > canvas_ratio:
        new_height = CANVAS_HEIGHT
        new_width = round(new_height * src_ratio)
    else:
        new_width = CANVAS_WIDTH
        new_height = round(new_width / src_ratio)
    source = source.resize((new_width, new_height), Image.LANCZOS)
    left = (new_width - CANVAS_WIDTH) // 2
    top = (new_height - CANVAS_HEIGHT) // 2
    return source.crop((left, top, left + CANVAS_WIDTH, top + CANVAS_HEIGHT))


def _to_data_url(image: Image.Image, fmt: str) -> str:
    buf = io.BytesIO()
    image.save(buf, format=fmt, quality=82 if fmt == "JPEG" else None)
    mime = "image/jpeg" if fmt == "JPEG" else "image/png"
    return f"data:{mime};base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"


def generate_puzzle() -> Puzzle:
    canvas = _fit_and_crop(Image.open(random.choice(_BACKGROUND_PATHS)).convert("RGB"))

    target_x = random.randint(_MARGIN, CANVAS_WIDTH - PIECE_WIDTH - _MARGIN)
    target_y = random.randint(_MARGIN, CANVAS_HEIGHT - PIECE_HEIGHT - _MARGIN)

    mask = _piece_mask()
    ring = _outline_ring(mask)

    # The floating piece: real pixels lifted from the target spot, cut to
    # the jigsaw silhouette with a white edge so it reads clearly even
    # against a similarly-toned part of the photo.
    piece = Image.new("RGBA", (PIECE_WIDTH, PIECE_HEIGHT), (0, 0, 0, 0))
    piece.paste(canvas.crop((target_x, target_y, target_x + PIECE_WIDTH, target_y + PIECE_HEIGHT)), (0, 0), mask)
    piece.paste(Image.new("RGBA", (PIECE_WIDTH, PIECE_HEIGHT), (255, 255, 255, 235)), (0, 0), ring)

    # The background: darken the same silhouette so a "hole" shows where
    # the piece belongs. target_x/target_y are never sent as numbers
    # anywhere in the response - only baked into these pixels, which is
    # what actually makes this harder than a plain arithmetic captcha.
    hole = Image.new("RGBA", (PIECE_WIDTH, PIECE_HEIGHT), (0, 0, 0, 0))
    hole.paste(Image.new("RGBA", (PIECE_WIDTH, PIECE_HEIGHT), (10, 15, 30, 165)), (0, 0), mask)
    hole.paste(Image.new("RGBA", (PIECE_WIDTH, PIECE_HEIGHT), (255, 255, 255, 220)), (0, 0), ring)
    background = canvas.convert("RGBA")
    background.paste(hole, (target_x, target_y), hole)

    return Puzzle(
        background_image=_to_data_url(background.convert("RGB"), "JPEG"),
        piece_image=_to_data_url(piece, "PNG"),
        canvas_width=CANVAS_WIDTH,
        canvas_height=CANVAS_HEIGHT,
        piece_width=PIECE_WIDTH,
        piece_height=PIECE_HEIGHT,
        piece_top=target_y,
        target_x=target_x,
    )
