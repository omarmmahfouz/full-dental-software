"""The pages of a paper file as pictures: made from the PDF (or the photos) when the file is uploaded, turned upright
after reading, cut around a value for the review page, and put back in order as one clean PDF for the patient's
documents. Works offline with pypdfium2 and Pillow."""

import io
import math

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

# The pictures sent to Claude: sharp enough for handwriting, within what the model reads at full resolution
# (2576 pixels on the long side, 3.75 million pixels), so the places it gives map 1:1 to the picture's pixels.
LONG_SIDE = 2300
MAX_PIXELS = 3_600_000
QUALITY = 82
MAX_PAGES = 80
IMAGE_TYPES = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")

# Turning clockwise by these degrees, as Pillow does it.
TURNS = {90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_90}


class PagesProblem(Exception):
    """The upload cannot be made into pages (not a real PDF, a password on it, too many pages)."""


def _fit(image):
    """The picture scaled to what is sent to Claude (never larger than it was)."""
    width, height = image.size
    scale = min(1.0, LONG_SIDE / max(width, height), math.sqrt(MAX_PIXELS / (width * height)))
    if scale < 1.0:
        image = image.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.LANCZOS)
    return image.convert("RGB")


def jpeg(image, quality=QUALITY):
    output = io.BytesIO()
    image.save(output, "JPEG", quality=quality, optimize=True)
    return output.getvalue()


def pictures_from_pdf(data):
    """[PIL image] for each page of a PDF, scaled for reading."""
    import pypdfium2 as pdfium

    try:
        document = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as error:
        raise PagesProblem(str(error)) from error
    try:
        count = len(document)
        if count == 0:
            raise PagesProblem("no pages")
        if count > MAX_PAGES:
            raise PagesProblem(f"{count} pages")
        pictures = []
        for index in range(count):
            page = document[index]
            width, height = page.get_size()  # points (1/72 inch), after the page's own rotation
            scale = min(LONG_SIDE / max(width, height), math.sqrt(MAX_PIXELS / (width * height)))
            pictures.append(_fit(page.render(scale=scale).to_pil()))
            page.close()
        return pictures
    finally:
        document.close()


def pdf_from_pictures(files):
    """One PDF made of photos of the pages (kept as the original scan), and the pictures scaled for reading."""
    images = []
    for upload in files:
        upload.seek(0)
        try:
            image = ImageOps.exif_transpose(Image.open(upload)).convert("RGB")
        except (OSError, ValueError) as error:
            raise PagesProblem(str(error)) from error
        images.append(image)
    if not images:
        raise PagesProblem("no pictures")
    if len(images) > MAX_PAGES:
        raise PagesProblem(f"{len(images)} pages")
    output = io.BytesIO()
    images[0].save(output, "PDF", save_all=True, append_images=images[1:], resolution=200, quality=88)
    return output.getvalue(), [_fit(image) for image in images]


def make_pages(paper):
    """Cut an uploaded paper file into pages (PaperPage rows with their pictures)."""
    from .models import PaperPage

    paper.original.open("rb")
    try:
        data = paper.original.read()
    finally:
        paper.original.close()
    pictures = pictures_from_pdf(data)
    pages = []
    for number, picture in enumerate(pictures, 1):
        page = PaperPage(file=paper, number=number, width=picture.width, height=picture.height)
        page.image.save("page.jpg", ContentFile(jpeg(picture)), save=False)
        page.save()
        pages.append(page)
    paper.page_count = len(pages)
    type(paper).objects.filter(pk=paper.pk).update(page_count=len(pages))
    return pages


def turn_box(box, degrees, width, height):
    """A box [left, top, right, bottom] on a picture of width x height, after the picture is turned clockwise."""
    left, top, right, bottom = box
    if degrees == 90:
        return [height - bottom, left, height - top, right]
    if degrees == 180:
        return [width - right, height - bottom, width - left, height - top]
    if degrees == 270:
        return [top, width - right, bottom, width - left]
    return list(box)


def clean_box(box, width, height):
    """A box Claude gave, checked: four numbers inside the picture, else None."""
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        left, top, right, bottom = (int(round(float(value))) for value in box)
    except (TypeError, ValueError):
        return None
    left, right = sorted((max(0, min(left, width)), max(0, min(right, width))))
    top, bottom = sorted((max(0, min(top, height)), max(0, min(bottom, height))))
    if right - left < 3 or bottom - top < 3:
        return None
    return [left, top, right, bottom]


def turn_page(page, degrees):
    """Turn a page's picture upright (clockwise by ``degrees``); returns the new size."""
    degrees = degrees % 360
    if degrees not in TURNS:
        return page.width, page.height
    page.image.open("rb")
    try:
        image = Image.open(page.image)
        image.load()
    finally:
        page.image.close()
    turned = image.transpose(TURNS[degrees])
    old = page.image.name
    page.image.save("page.jpg", ContentFile(jpeg(turned)), save=False)
    page.image.storage.delete(old)
    page.width, page.height = turned.size
    page.turned = (page.turned + degrees) % 360
    page.save(update_fields=["image", "width", "height", "turned"])
    return turned.size


def cut_out(page, box, margin=0.35, least=60):
    """The part of a page around ``box`` (a little larger, so the words around it show), as a JPEG."""
    page.image.open("rb")
    try:
        image = Image.open(page.image)
        image.load()
    finally:
        page.image.close()
    left, top, right, bottom = box
    pad_x = max(least, int((right - left) * margin))
    pad_y = max(least, int((bottom - top) * margin * 2))
    piece = image.crop((max(0, left - pad_x), max(0, top - pad_y), min(image.width, right + pad_x),
                        min(image.height, bottom + pad_y)))
    if piece.width < 500:  # small writing is shown larger
        factor = min(3, 500 / max(piece.width, 1))
        piece = piece.resize((round(piece.width * factor), round(piece.height * factor)), Image.LANCZOS)
    return jpeg(piece.convert("RGB"), quality=86)


def clean_pdf(paper, pages):
    """One PDF of the file's pages in order (``pages``: PaperPage rows), each turned upright, from the original
    scan (so nothing is lost by making pictures again)."""
    import pypdfium2 as pdfium

    paper.original.open("rb")
    try:
        source = pdfium.PdfDocument(paper.original.read())
    finally:
        paper.original.close()
    target = pdfium.PdfDocument.new()
    try:
        for index, page in enumerate(pages):
            original = source[page.number - 1]
            rotation = original.get_rotation()
            original.close()
            target.import_pages(source, [page.number - 1])
            imported = target[index]
            imported.set_rotation((rotation + page.turned) % 360)
            imported.close()
        output = io.BytesIO()
        target.save(output)
        return output.getvalue()
    finally:
        target.close()
        source.close()
