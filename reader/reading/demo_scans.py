"""Draws the made-up scanned pages of the sample data (reading/demo/*.jpg) and where their values are
(demo/boxes.json). Run once when the pages change: ``python -m reading.demo_scans`` from the reader's folder (it
needs Pillow with Arabic shaping, e.g. on Linux). The sample data only copies the pictures, so it works on any PC.
The dental system keeps a copy of the two pictures for its own sample import."""

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
FONTS = HERE.parent.parent.parent / "static" / "vendor" / "cairo" / "files"  # the dental system's fonts
SIZE = (1240, 1754)  # A4 at 150 dpi
INK = (24, 45, 120)  # the blue pen
PRINT = (40, 40, 40)


def font(size, weight="400", script="arabic"):
    return ImageFont.truetype(str(FONTS / f"cairo-{script}-{weight}-normal.woff2"), size)


def paper(seed):
    rng = random.Random(seed)
    image = Image.new("RGB", SIZE, (247, 245, 238))
    draw = ImageDraw.Draw(image)
    for _ in range(9000):  # the grain of a scan
        x, y = rng.randrange(SIZE[0]), rng.randrange(SIZE[1])
        shade = rng.randint(222, 240)
        draw.point((x, y), fill=(shade, shade, shade - 6))
    return image, draw


def write(draw, xy, text, size=30, ink=INK, rtl=False, weight="600"):
    """Handwriting (in blue); returns its box."""
    script = "arabic" if rtl else "latin"
    face = font(size, weight, script)
    if rtl:
        box = draw.textbbox(xy, text, font=face, direction="rtl", anchor="ra")
        draw.text(xy, text, font=face, fill=ink, direction="rtl", anchor="ra")
    else:
        box = draw.textbbox(xy, text, font=face)
        draw.text(xy, text, font=face, fill=ink)
    return [int(box[0]) - 4, int(box[1]) - 4, int(box[2]) + 4, int(box[3]) + 4]


def label(draw, xy, english, arabic=""):
    draw.text(xy, english, font=font(24, "400", "latin"), fill=PRINT)
    if arabic:
        draw.text((SIZE[0] - 70, xy[1]), arabic, font=font(24, "400"), fill=PRINT, direction="rtl", anchor="ra")
    draw.line((xy[0], xy[1] + 70, SIZE[0] - 70, xy[1] + 70), fill=(150, 150, 150), width=1)


def tick(draw, xy, ticked):
    x, y = xy
    draw.rectangle((x, y, x + 26, y + 26), outline=PRINT, width=2)
    if ticked:
        draw.line((x + 3, y + 14, x + 11, y + 23, x + 30, y - 6), fill=INK, width=5)
    return [x - 4, y - 10, x + 34, y + 30]


def registration():
    image, draw = paper(1)
    draw.text((70, 60), "Cairo Implant Academy", font=font(40, "700", "latin"), fill=PRINT)
    draw.text((SIZE[0] - 70, 60), "أكاديمية القاهرة للزرع", font=font(36, "700"), fill=PRINT, direction="rtl",
              anchor="ra")
    draw.text((70, 125), "PATIENT REGISTRATION", font=font(28, "600", "latin"), fill=PRINT)
    draw.text((SIZE[0] - 70, 125), "تسجيل مريض", font=font(28, "600"), fill=PRINT, direction="rtl", anchor="ra")
    boxes, y = {}, 220
    rows = [
        ("full_name", "Full name (as on ID)", "الاسم بالكامل", "سامية عبد الرحمن محمود", True),
        ("national_id", "National ID", "الرقم القومي", "٢٨٨٠٧٢٢٢١٠٣٤٦٨", True),
        ("phone_primary", "Mobile", "الموبايل", "01145567781", False),
        ("address", "Address", "العنوان", "١٢ شارع التحرير، الدقي", True),
        ("city", "Area", "المنطقة", "الدقي", True),
        ("occupation", "Job", "الوظيفة", "مدرسة", True),
        ("referral_source", "How did you hear about us?", "عرفتنا منين؟", "Facebook", False),
        ("registered_on", "Date", "التاريخ", "12/9/2017", False),
    ]
    for name, english, arabic, value, rtl in rows:
        label(draw, (70, y), english, arabic)
        boxes[name] = write(draw, (SIZE[0] - 330, y + 28) if rtl else (420, y + 26), value, 34, rtl=rtl)
        y += 150
    # The job was smudged: a blot over it.
    blot = Image.new("L", SIZE, 0)
    ImageDraw.Draw(blot).ellipse(boxes["occupation"], fill=170)
    blot = blot.filter(ImageFilter.GaussianBlur(14))
    image.paste((150, 160, 185), (0, 0), blot)
    draw.text((70, SIZE[1] - 120), "Signature: ______________", font=font(24, "400", "latin"), fill=PRINT)
    return image, boxes


def history():
    image, draw = paper(2)
    draw.text((70, 60), "CIA paper chart  -  Medical and dental history", font=font(32, "700", "latin"), fill=PRINT)
    boxes = {}
    label(draw, (70, 140), "Date", "")
    boxes["exam_date"] = write(draw, (260, 162), "12/09/2017", 32)
    draw.text((640, 140), "Dr.", font=font(24, "400", "latin"), fill=PRINT)
    boxes["examined_by"] = write(draw, (700, 162), "Mona Refaat", 32)
    label(draw, (70, 260), "Last blood pressure reading", "")
    boxes["bp_last_systolic"] = write(draw, (520, 282), "140", 34)
    draw.text((600, 282), "/", font=font(34, "600", "latin"), fill=INK)
    boxes["bp_last_diastolic"] = write(draw, (630, 282), "90", 34)
    boxes["bp_last_when"] = write(draw, (800, 282), "last month", 30)
    draw.text((70, 400), "Did you ever have:", font=font(26, "700", "latin"), fill=PRINT)
    ticks = [("Diabetes", True), ("High blood pressure", True), ("Heart disease", False), ("Asthma", False)]
    tick_boxes = []
    for index, (disease, ticked) in enumerate(ticks):
        x, y = 90 + (index % 2) * 560, 460 + (index // 2) * 70
        box = tick(draw, (x, y), ticked)
        draw.text((x + 45, y - 6), disease, font=font(26, "400", "latin"), fill=PRINT)
        if ticked:
            tick_boxes.append(box)
    boxes["conditions"] = [min(b[0] for b in tick_boxes), min(b[1] for b in tick_boxes),
                           max(b[2] for b in tick_boxes) + 300, max(b[3] for b in tick_boxes)]
    label(draw, (70, 640), "HbA1c (%)", "")
    boxes["hba1c"] = write(draw, (330, 662), "8.2", 34)
    draw.line((330, 700, 390, 668), fill=INK, width=3)  # written over: 8 or 6?
    label(draw, (70, 760), "Allergic to penicillin?", "")
    draw.text((600, 780), "Yes", font=font(26, "400", "latin"), fill=PRINT)
    boxes["allergy_penicillin"] = tick(draw, (660, 784), True)
    draw.text((760, 780), "No", font=font(26, "400", "latin"), fill=PRINT)
    tick(draw, (810, 784), False)
    label(draw, (70, 880), "Drugs taken", "")
    boxes["drugs_taken"] = write(draw, (330, 902), "Glucophage 1000, Concor 5", 32)
    label(draw, (70, 1000), "Smoker?", "")
    draw.text((600, 1020), "Yes", font=font(26, "400", "latin"), fill=PRINT)
    tick(draw, (660, 1024), False)
    draw.text((760, 1020), "No", font=font(26, "400", "latin"), fill=PRINT)
    boxes["smoker"] = tick(draw, (810, 1024), True)
    label(draw, (70, 1120), "Clench or grind teeth?", "")
    boxes["bruxism"] = write(draw, (450, 1142), "at night", 32)
    return image, boxes


def turned_back(box, width, height):
    """A box on a page scanned sideways (turned 90 degrees to the left): where it is on the sideways picture."""
    left, top, right, bottom = box
    return [top, width - right, bottom, width - left]


def main():
    out = HERE / "demo"
    out.mkdir(exist_ok=True)
    first, first_boxes = registration()
    second, second_boxes = history()
    first.save(out / "page-1.jpg", quality=72, optimize=True)
    # The second page was scanned sideways: Claude says to turn it, and the system does.
    second.transpose(Image.Transpose.ROTATE_90).save(out / "page-2.jpg", quality=72, optimize=True)
    second_boxes = {name: turned_back(box, *SIZE) for name, box in second_boxes.items()}
    (out / "boxes.json").write_text(json.dumps({"1": first_boxes, "2": second_boxes}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
