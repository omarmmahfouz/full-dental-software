"""Scanned or photographed ID cards: cut the card out of the background, turn it the right
way and keep it as a clean card image. Works offline with Pillow only. When the card cannot
be found clearly (e.g. the photo is already just the card), the picture is kept as it was."""

import io
import os

from django.core.files.base import ContentFile
from PIL import Image, ImageChops, ImageFilter, ImageOps

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
CARD_RATIO = (1.3, 1.9)  # ID cards are 85.6 x 54 mm (1.59); passports' photo page is about 1.42
MAX_WIDTH = 1600


def _background(image):
    """The colour around the card: the middle value of the pixels on the picture's edges."""
    width, height = image.size
    edge = [image.getpixel((x, y)) for x in range(0, width, 3) for y in (0, height - 1)]
    edge += [image.getpixel((x, y)) for y in range(0, height, 3) for x in (0, width - 1)]
    return tuple(sorted(pixel[band] for pixel in edge)[len(edge) // 2] for band in range(3))


def find_card(image):
    """The box (left, top, right, bottom) of the card in ``image``, or None."""
    small = image.copy()
    small.thumbnail((500, 500))
    difference = ImageChops.difference(small, Image.new("RGB", small.size, _background(small))).convert("L")
    mask = difference.point(lambda value: 255 if value > 35 else 0).filter(ImageFilter.MedianFilter(5))
    box = mask.getbbox()
    if box is None:
        return None
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    area = width * height / (small.width * small.height)
    ratio = max(width, height) / max(min(width, height), 1)
    if not 0.15 <= area <= 0.92 or not CARD_RATIO[0] <= ratio <= CARD_RATIO[1]:
        return None  # nothing clear to cut, or the picture is already the card
    scale = image.width / small.width
    margin = 0.01 * max(image.size)
    return (max(int(left * scale - margin), 0), max(int(top * scale - margin), 0),
            min(int(right * scale + margin), image.width), min(int(bottom * scale + margin), image.height))


def clean_card(uploaded):
    """A JPEG of the card alone, turned the right way, or None to keep the file as it is."""
    if os.path.splitext(uploaded.name)[1].lower() not in IMAGE_EXTENSIONS:
        return None
    try:
        uploaded.seek(0)
        image = ImageOps.exif_transpose(Image.open(uploaded)).convert("RGB")
    except (OSError, ValueError):
        return None
    finally:
        uploaded.seek(0)
    box = find_card(image)
    card = image.crop(box) if box else image
    if card.height > card.width:
        card = card.rotate(90, expand=True)
    if card.width > MAX_WIDTH:
        card = card.resize((MAX_WIDTH, round(card.height * MAX_WIDTH / card.width)))
    if box is None and card.size == image.size:
        return None
    output = io.BytesIO()
    card.save(output, "JPEG", quality=90)
    return ContentFile(output.getvalue(), name=f"{os.path.splitext(os.path.basename(uploaded.name))[0]}-card.jpg")
