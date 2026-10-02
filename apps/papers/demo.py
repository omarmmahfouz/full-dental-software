"""Round 13 sample data: two old paper files of CIA, read in a batch (as Claude would read them; nothing is sent).

- One waits for checking: a registration form (the national ID in Arabic digits, the job under a blot, the two
  readings of the mobile differ) and the history page, scanned sideways (it was turned upright by itself; the HbA1c
  is written over, 8.2 or 6.2).
- One was already kept, pages only, in a registered patient's documents.

The pictures are made by ``demo_scans.py``."""

import io
import json
from datetime import timedelta
from pathlib import Path

from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image

from apps.core.models import Branch
from apps.dentists.models import Dentist
from apps.patients.models import MedicalCondition, ReferralSource

from .approve import approve
from .checks import build_fields, settle_pages
from .models import PaperFile, PaperPage, PaperReading, PaperSettings, new_token

HERE = Path(__file__).resolve().parent / "demo"


def _entry(name, value, boxes, certainty="sure", written=None, note=""):
    return {"name": name, "written": value if written is None else written, "value": value,
            "certainty": certainty, "box": boxes.get(name, [0, 0, 0, 0]), "note": note}


def _answers():
    boxes = json.loads((HERE / "boxes.json").read_text(encoding="utf-8"))
    one, two = boxes["1"], boxes["2"]
    facebook = ReferralSource.objects.filter(name_en="Facebook").values_list("pk", flat=True).first()
    mona = Dentist.objects.filter(full_name="Dr. Mona Refaat").values_list("pk", flat=True).first()
    conditions = ",".join(str(pk) for pk in MedicalCondition.objects.filter(
        name_en__in=("Diabetes", "High blood pressure")).order_by("sort_order", "pk").values_list("pk", flat=True))
    first = [
        _entry("full_name", "سامية عبد الرحمن محمود", one),
        _entry("national_id", "28807222103468", one, written="٢٨٨٠٧٢٢٢١٠٣٤٦٨"),
        _entry("phone_primary", "01145567781", one),
        _entry("address", "12 شارع التحرير، الدقي", one, written="١٢ شارع التحرير، الدقي"),
        _entry("city", "الدقي", one),
        _entry("occupation", "", one, certainty="unclear", written="", note="A blot covers the word."),
        _entry("referral_source", str(facebook or "Facebook"), one, written="Facebook"),
        _entry("registered_on", "12/09/2017", one, written="12/9/2017"),
    ]
    second = [
        _entry("exam_date", "12/09/2017", two),
        _entry("examined_by", str(mona or "Mona Refaat"), two, written="Mona Refaat"),
        _entry("bp_last_systolic", "140", two), _entry("bp_last_diastolic", "90", two),
        _entry("bp_last_when", "last month", two),
        _entry("conditions", conditions, two, written="✓ Diabetes  ✓ High blood pressure"),
        _entry("hba1c", "8.2", two, certainty="check", note="Written over: it may be 6.2."),
        _entry("allergy_penicillin", "yes", two, written="✓ Yes"),
        _entry("drugs_taken", "Glucophage 1000, Concor 5", two),
        _entry("smoker", "no", two, written="✓ No"),
        _entry("bruxism", "at night", two),
    ]
    page = lambda kind, turn, fields: {"page_kind": kind, "turn": turn, "cover_file_number": "", "page_notes": "",
                                       "fields": fields}
    again = [dict(item) for item in first]
    again[2] = _entry("phone_primary", "01145567787", one)  # the second reading saw a 7
    later = [dict(item) for item in second]
    later[6] = _entry("hba1c", "6.2", two, certainty="check")
    return {(1, 1): page("registration", 0, first), (1, 2): page("registration", 0, again),
            (2, 1): page("history", 90, second), (2, 2): page("history", 90, later)}


def _paper_file(branch, name, user, read_at):
    pictures = [Image.open(HERE / f"page-{number}.jpg").convert("RGB") for number in (1, 2)]
    output = io.BytesIO()
    pictures[0].save(output, "PDF", save_all=True, append_images=pictures[1:], resolution=150)
    paper = PaperFile(branch=branch, upload=new_token(), original_name=name, mode=PaperSettings.Mode.BATCH,
                      status=PaperFile.Status.READING, page_count=2, created_by=user)
    paper.original.save("scan.pdf", ContentFile(output.getvalue()), save=False)
    paper.save()
    answers = _answers()
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


def load_papers(patients, secretary):
    branch = Branch.objects.get(code="CIA")
    now = timezone.now()
    _paper_file(branch, "CIA old file 2017 - Samia Abdelrahman.pdf", secretary, now - timedelta(hours=3))
    kept = next((p for p in patients if p.branch_id == branch.pk and not p.paper_files.exists()), None)
    if kept is not None:
        paper = _paper_file(branch, f"Old file {kept.file_number}.pdf", secretary, now - timedelta(days=2))
        approve(paper, secretary, patient=kept, pages_only=True)
