"""The Paper Reader's sample data (python manage.py load_reader_demo): two people, the lists of CIA from the dental
system's demo, and two old paper files read in a batch as Claude would read them (nothing is sent, no key needed).

- One waits for checking: a registration form (the national ID in Arabic digits, the job under a blot, the two
  readings of the mobile differ) and the history page, scanned sideways (it was turned upright by itself; the HbA1c
  is written over, 8.2 or 6.2).
- One is approved, pages only, for a registered patient: it goes with the next package to the dental system.

The pictures are made by ``demo_scans.py``; ``lists-CIA.json`` is the dental demo's Old paper files → Lists for the
reader."""

import io
import json
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image

from .checks import build_fields, settle_pages
from .exchange import import_lists
from .models import KnownPatient, PaperFile, PaperPage, PaperReading, ReaderSettings, SystemLists, new_token

HERE = Path(__file__).resolve().parent / "demo"


def _code(lists, name, english):
    """The code of a choice in the lists file, by its English words."""
    for row in lists.data.get("fields", []):
        if row["name"] == name:
            return next((code for code, en, _ar in row.get("choices", []) if en in english), "")
    return ""


def _entry(name, value, boxes, certainty="sure", written=None, note=""):
    return {"name": name, "written": value if written is None else written, "value": value,
            "certainty": certainty, "box": boxes.get(name, [0, 0, 0, 0]), "note": note}


def _answers(lists):
    boxes = json.loads((HERE / "boxes.json").read_text(encoding="utf-8"))
    one, two = boxes["1"], boxes["2"]
    conditions = ",".join(code for code in (_code(lists, "conditions", ("Diabetes",)),
                                            _code(lists, "conditions", ("High blood pressure",))) if code)
    first = [
        _entry("full_name", "سامية عبد الرحمن محمود", one),
        _entry("national_id", "28807222103468", one, written="٢٨٨٠٧٢٢٢١٠٣٤٦٨"),
        _entry("phone_primary", "01145567781", one),
        _entry("address", "12 شارع التحرير، الدقي", one, written="١٢ شارع التحرير، الدقي"),
        _entry("city", "الدقي", one),
        _entry("occupation", "", one, certainty="unclear", written="", note="A blot covers the word."),
        _entry("referral_source", _code(lists, "referral_source", ("Facebook",)) or "Facebook", one,
               written="Facebook"),
        _entry("registered_on", "12/09/2017", one, written="12/9/2017"),
    ]
    second = [
        _entry("exam_date", "12/09/2017", two),
        _entry("examined_by", _code(lists, "examined_by", ("Dr. Mona Refaat",)) or "Mona Refaat", two,
               written="Mona Refaat"),
        _entry("bp_last_systolic", "140", two), _entry("bp_last_diastolic", "90", two),
        _entry("bp_last_when", "last month", two),
        _entry("conditions", conditions, two, written="✓ Diabetes  ✓ High blood pressure"),
        _entry("hba1c", "8.2", two, certainty="check", note="Written over: it may be 6.2."),
        _entry("allergy_penicillin", "yes", two, written="✓ Yes"),
        _entry("drugs_taken", "Glucophage 1000, Concor 5", two),
        _entry("smoker", "no", two, written="✓ No"),
        _entry("bruxism", "at night", two),
    ]

    def page(kind, turn, fields):
        return {"page_kind": kind, "turn": turn, "cover_file_number": "", "page_notes": "", "fields": fields}

    again = [dict(item) for item in first]
    again[2] = _entry("phone_primary", "01145567787", one)  # the second reading saw a 7
    later = [dict(item) for item in second]
    later[6] = _entry("hba1c", "6.2", two, certainty="check")
    return {(1, 1): page("registration", 0, first), (1, 2): page("registration", 0, again),
            (2, 1): page("history", 90, second), (2, 2): page("history", 90, later)}


def _scan(pictures):
    output = io.BytesIO()
    pictures[0].save(output, "PDF", save_all=True, append_images=pictures[1:], resolution=150)
    return output.getvalue()


def _paper_file(lists, name, user, read_at):
    """A file read in a batch, waiting to be checked."""
    pictures = [Image.open(HERE / f"page-{number}.jpg").convert("RGB") for number in (1, 2)]
    paper = PaperFile(upload=new_token(), place_code=lists.place_code, original_name=name,
                      mode=ReaderSettings.Mode.BATCH, status=PaperFile.Status.READING, page_count=2, created_by=user)
    paper.original.save("scan.pdf", ContentFile(_scan(pictures)), save=False)
    paper.save()
    answers = _answers(lists)
    for number, picture in enumerate(pictures, 1):
        page = PaperPage(file=paper, number=number, width=picture.width, height=picture.height)
        page.image.save("page.jpg", ContentFile((HERE / f"page-{number}.jpg").read_bytes()), save=False)
        page.save()
        for reading in (1, 2):
            PaperReading.objects.create(
                page=page, number=reading, status=PaperReading.Status.DONE, batch_id="msgbatch_demo", batched=True,
                model="claude-opus-5-5", result=answers[(number, reading)], input_tokens=2100, output_tokens=2400,
                cache_read_tokens=3800, sent_at=read_at - timedelta(minutes=40), done_at=read_at)
    build_fields(paper, settle_pages(paper))
    PaperFile.objects.filter(pk=paper.pk).update(status=PaperFile.Status.REVIEW, read_at=read_at)
    paper.refresh_from_db()
    return paper


def _pages_only(lists, known, user, read_at):
    """A registered patient's file, approved as pages only (kept in the patient's documents)."""
    first = Image.open(HERE / "page-1.jpg").convert("RGB")
    second = Image.open(HERE / "page-2.jpg").convert("RGB").transpose(Image.Transpose.ROTATE_270)  # upright
    paper = PaperFile(upload=new_token(), place_code=lists.place_code, original_name=f"Old file {known.file_number}.pdf",
                      mode=ReaderSettings.Mode.BATCH, status=PaperFile.Status.APPROVED, page_count=2,
                      created_by=user, read_at=read_at, suggested=known.file_number, suggested_reason="cover",
                      cover_number=known.file_number)
    paper.original.save("scan.pdf", ContentFile(_scan([first, second])), save=False)
    paper.save()
    for number, (picture, kind, turned) in enumerate(((first, "registration", 0), (second, "history", 90)), 1):
        output = io.BytesIO()
        picture.save(output, "JPEG", quality=85)
        page = PaperPage(file=paper, number=number, width=picture.width, height=picture.height, kind=kind,
                         turned=turned)
        page.image.save("page.jpg", ContentFile(output.getvalue()), save=False)
        page.save()
    PaperFile.objects.filter(pk=paper.pk).update(
        approved={"target": "existing", "file_number": known.file_number, "patient": {}, "history": {},
                  "replace": [], "pages_only": True},
        approved_by=user, approved_at=read_at + timedelta(hours=2))
    return paper


def load_reader(password):
    User = get_user_model()
    owner = User.objects.create_user("owner", password=password, first_name="Dr. Ahmed", is_staff=True)
    secretary = User.objects.create_user("secretary", password=password, first_name="منة")
    import_lists(json.loads((HERE / "lists-CIA.json").read_text(encoding="utf-8")), owner)
    lists = SystemLists.get()
    ReaderSettings.get()  # switched off: the owner switches it on after the patients' consent and the key
    now = timezone.now()
    _paper_file(lists, "CIA old file 2017 - Samia Abdelrahman.pdf", secretary, now - timedelta(hours=3))
    known = KnownPatient.objects.order_by("file_number").first()
    if known is not None:
        _pages_only(lists, known, secretary, now - timedelta(days=1))
