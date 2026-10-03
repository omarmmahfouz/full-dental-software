"""The Paper Reader's tests (cd reader; python manage.py test reading). Claude is never called: a fake client
answers like the Anthropic API (now and in batches), so the whole road is tested without the internet and without
cost. The lists come from the dental system's demo (``demo/lists-CIA.json``), as the real lists file would."""

import io
import json
import os
import shutil
import tempfile
import zipfile
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone, translation
from PIL import Image, ImageDraw

from reading import worker
from reading.catalogue import by_name, specs
from reading.checks import build_fields, clean_value
from reading.exchange import PACKAGE_KIND, import_lists
from reading.models import (Export, KnownPatient, PaperField, PaperFile, PaperPage, PaperReading, ReaderSettings,
                            SystemLists, month_cost)
from reading.pages import clean_box, turn_box

PASSWORD = "a-long-test-password"
NID = "29001150101234"  # born 15/01/1990, Cairo, a man
LISTS = json.loads((Path(__file__).resolve().parent / "demo" / "lists-CIA.json").read_text(encoding="utf-8"))


def lists_data(patients=()):
    data = deepcopy(LISTS)
    data["patients"] = list(patients)
    return data


def code_of(name, english):
    row = next(row for row in LISTS["fields"] if row["name"] == name)
    return next(code for code, en, _ar in row["choices"] if en == english)


DIABETES = code_of("conditions", "Diabetes")
MONA = code_of("examined_by", "Dr. Mona Refaat")


def make_pdf(pages=3, size=(1240, 1754)):
    """A scanned file of ``pages`` pages (A4 at 150 dpi)."""
    images = []
    for number in range(pages):
        image = Image.new("RGB", size, (250, 250, 247))
        ImageDraw.Draw(image).text((100, 100), f"page {number + 1}", fill=(20, 20, 20))
        images.append(image)
    output = io.BytesIO()
    images[0].save(output, "PDF", save_all=True, append_images=images[1:], resolution=150)
    return output.getvalue()


def entry(name, value, certainty="sure", box=(100, 200, 400, 240), written=None, note=""):
    return {"name": name, "written": value if written is None else written, "value": value,
            "certainty": certainty, "box": list(box), "note": note}


REGISTRATION = [
    entry("full_name", "محمد أحمد علي حسن"), entry("national_id", NID, written="٢٩٠٠١١٥٠١٠١٢٣٤"),
    entry("phone_primary", "01001234567"), entry("occupation", "Engineer"), entry("city", "Nasr City"),
    entry("registered_on", "03/04/2016"),
]
HISTORY = [
    entry("exam_date", "03/04/2016"), entry("examined_by", "mona refaat"), entry("bp_last_systolic", "130"),
    entry("bp_last_diastolic", "85"), entry("conditions", "Diabetes, gout"), entry("allergy_penicillin", "yes"),
    entry("smoker", "yes"), entry("cigarettes_per_day", "20"), entry("hba1c", "7.8", certainty="check"),
]


def answers(page_number, reading):
    """What the fake Claude reads on each page (the second reading reads a digit of the mobile differently)."""
    if page_number == 1:
        fields = [dict(item) for item in REGISTRATION]
        if reading == 2:
            fields[2] = entry("phone_primary", "01001234561")
        return {"page_kind": "registration", "turn": 0, "cover_file_number": "", "page_notes": "", "fields": fields}
    if page_number == 2:
        return {"page_kind": "history", "turn": 90, "cover_file_number": "", "page_notes": "",
                "fields": [dict(item) for item in HISTORY]}
    return {"page_kind": "xray", "turn": 0, "cover_file_number": "", "page_notes": "", "fields": []}


def message(answer, model="claude-opus-5-5", stop="end_turn"):
    return SimpleNamespace(
        stop_reason=stop, model=model,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=json.dumps(answer))],
        usage=SimpleNamespace(input_tokens=2000, output_tokens=2500, cache_read_input_tokens=3000,
                              cache_creation_input_tokens=0))


class FakeAnthropic:
    """Answers like the Anthropic client: messages now (beta, with the fallback) and batches."""

    def __init__(self, reader=answers, refuse=()):
        self.reader, self.refuse = reader, set(refuse)
        self.sent, self.batches, self.polls = [], {}, 0
        self.seen = {}
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create_now))
        self.messages = SimpleNamespace(batches=SimpleNamespace(create=self.create_batch, retrieve=self.retrieve,
                                                                results=self.results))
        self.models = SimpleNamespace(retrieve=lambda model: SimpleNamespace(id=model))

    def _answer(self, params):
        text = params["messages"][0]["content"][1]["text"]
        page_number = int(text.split()[1])
        self.seen[page_number] = self.seen.get(page_number, 0) + 1
        if page_number in self.refuse:
            return message({}, stop="refusal")
        return message(self.reader(page_number, self.seen[page_number]))

    def create_now(self, **params):
        self.sent.append(params)
        return self._answer(params)

    def create_batch(self, requests):
        batch_id = f"msgbatch_{len(self.batches) + 1}"
        self.batches[batch_id] = list(requests)
        return SimpleNamespace(id=batch_id)

    def retrieve(self, batch_id):
        self.polls += 1
        return SimpleNamespace(processing_status="ended" if self.polls > 1 else "in_progress")

    def results(self, batch_id):
        for request in self.batches[batch_id]:
            yield SimpleNamespace(custom_id=request["custom_id"], result=SimpleNamespace(
                type="succeeded", message=self._answer(request["params"])))


def post_data(*forms):
    """What the review page sends back unchanged (the values read, as the forms show them)."""
    data = {}
    for form in forms:
        for field in form:
            value = field.value()
            if isinstance(value, bool) or field.widget_type == "checkbox":
                if value:
                    data[field.html_name] = "on"
            elif isinstance(value, (list, tuple)):
                data[field.html_name] = [str(v) for v in value]
            elif value is not None:
                data[field.html_name] = value.strftime("%d/%m/%Y") if hasattr(value, "strftime") else str(value)
    return data


class ReaderTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        # A folder of its own for each class: the tests run in several processes at once.
        cls.media = tempfile.mkdtemp()
        cls.media_setting = override_settings(MEDIA_ROOT=cls.media)
        cls.media_setting.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.media_setting.disable()
        shutil.rmtree(cls.media, ignore_errors=True)

    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user("owner", password=PASSWORD, is_staff=True)
        self.secretary = User.objects.create_user("sec", password=PASSWORD, first_name="منة")
        import_lists(lists_data(), self.owner)
        options = ReaderSettings.get()
        options.enabled = True
        options.save()
        self.fake = FakeAnthropic()
        for patcher in (mock.patch("reading.claude.client", return_value=self.fake),
                        mock.patch.object(worker, "AT_ONCE", 1),  # the fake answers in the order asked
                        mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"})):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client.login(username="sec", password=PASSWORD)

    def send(self, pages=3, mode="now"):
        response = self.client.post("/send/", {"files": [SimpleUploadedFile("old file.pdf", make_pdf(pages),
                                                                             "application/pdf")], "mode": mode})
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and
                         response.context["form"].errors)
        return PaperFile.objects.latest("pk")

    def read(self):
        worker.run_until_done(sleep=lambda seconds: None)

    def approve(self, paper, **changes):
        page = self.client.get(paper.get_absolute_url())
        data = post_data(page.context["target_form"], page.context["patient_form"], page.context["history_form"])
        data.update({"t-target": "new", "action": "approve"})
        data.update(changes)
        return self.client.post(paper.get_absolute_url(), data)


class ReadingTests(ReaderTestCase):
    def test_a_file_is_read_twice_checked_approved_and_sent_to_the_system(self):
        paper = self.send()
        self.assertEqual((paper.status, paper.place_code), (PaperFile.Status.WAITING, "CIA"))
        self.read()
        paper.refresh_from_db()
        self.assertEqual(paper.status, PaperFile.Status.REVIEW)
        self.assertEqual(paper.page_count, 3)
        self.assertEqual(PaperReading.objects.filter(page__file=paper, status="done").count(), 6)  # two readings
        request = self.fake.sent[0]
        self.assertEqual(request["model"], "claude-opus-5-5")
        self.assertEqual(request["fallbacks"], "default")
        self.assertEqual(request["output_config"]["effort"], "medium")
        self.assertEqual(request["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(request["messages"][0]["content"][0]["source"]["media_type"], "image/jpeg")
        # The values: cleaned, compared and marked.
        fields = {row.name: row for row in paper.fields.all()}
        self.assertEqual(fields["full_name"].certainty, "sure")
        self.assertEqual(fields["national_id"].value, NID)
        self.assertEqual(fields["phone_primary"].certainty, "check")  # the two readings differ
        self.assertIn("01001234561", " ".join(fields["phone_primary"].reasons()))
        self.assertEqual(fields["hba1c"].certainty, "check")  # Claude was not sure
        self.assertEqual(fields["birth_date"].value, "15/01/1990")  # from the national ID
        self.assertEqual(fields["gender"].value, "M")
        self.assertEqual(fields["conditions"].value, DIABETES)
        self.assertEqual(fields["other_condition"].value, "gout")  # not in the list
        self.assertEqual(fields["examined_by"].value, MONA)  # the dentist's name matched to the list
        self.assertEqual(fields["allergy_penicillin"].value, "yes")
        # The history page was turned upright, and its places with it.
        history = paper.pages.get(number=2)
        self.assertEqual((history.kind, history.turned), ("history", 90))
        self.assertGreater(history.width, history.height)
        self.assertEqual(fields["bp_last_systolic"].box, turn_box([100, 200, 400, 240], 90, history.height,
                                                                  history.width))
        self.assertEqual(self.client.get(f"/values/{fields['hba1c'].pk}/paper.jpg").status_code, 200)
        # The review page, then approve as it is.
        self.assertContains(self.client.get(paper.get_absolute_url()), "/values/")
        response = self.approve(paper, **{"p-referral_source": ""})
        self.assertEqual(response.status_code, 302, getattr(response, "context", None)
                         and response.context["patient_form"].errors)
        paper.refresh_from_db()
        self.assertEqual(paper.status, PaperFile.Status.APPROVED)
        self.assertEqual(paper.approved["target"], "new")
        self.assertEqual(paper.approved["patient"]["national_id"], NID)
        self.assertEqual(paper.approved["patient"]["phone_primary"], "01001234567")
        self.assertEqual(paper.approved["history"]["hba1c"], "7.8")
        self.assertEqual(paper.approved["history"]["conditions"], DIABETES)
        self.assertEqual(paper.approved["history"]["allergy_penicillin"], "yes")
        # The package for the dental system.
        self.assertEqual(self.client.post("/to-the-system/").status_code, 302)
        made = Export.objects.get()
        paper.refresh_from_db()
        self.assertEqual((paper.status, paper.exported_in), (PaperFile.Status.EXPORTED, made))
        download = self.client.get(f"/to-the-system/{made.pk}/download/")
        self.assertIn("attachment", download["Content-Disposition"])
        package = zipfile.ZipFile(io.BytesIO(b"".join(download.streaming_content)))
        manifest = json.loads(package.read("manifest.json"))
        self.assertEqual((manifest["kind"], manifest["version"], manifest["place"]), (PACKAGE_KIND, 1, "CIA"))
        row = manifest["files"][0]
        self.assertEqual(row["token"], paper.token)
        self.assertEqual(row["patient"]["full_name"], "محمد أحمد علي حسن")
        self.assertEqual(row["documents"], {"file": f"files/{paper.token}/file.pdf",
                                            "xray": f"files/{paper.token}/xray.pdf"})
        self.assertTrue(package.read(row["documents"]["file"]).startswith(b"%PDF"))
        # Nothing approved is left to send.
        self.client.post("/to-the-system/")
        self.assertEqual(Export.objects.count(), 1)

    def test_a_big_package_is_split(self):
        from reading.exchange import build_package

        first, second = self.send(pages=1), self.send(pages=1)
        self.read()
        for paper, nid in ((first, NID), (second, "29001150101252")):
            response = self.approve(paper, **{"p-national_id": nid})
            self.assertEqual(response.status_code, 302, getattr(response, "context", None)
                             and response.context["patient_form"].errors)
        ready = list(PaperFile.objects.filter(status="approved").order_by("pk"))
        self.assertEqual(len(ready), 2)
        made = build_package(ready, self.owner, limit_mb=0)  # the first file is already "too big"
        self.assertEqual(made.count, 1)
        self.assertEqual(list(PaperFile.objects.filter(status="approved")), [second])
        self.assertEqual(build_package([second], self.owner, limit_mb=0).count, 1)

    def test_the_clean_pdf_is_in_order_and_upright(self):
        import pypdfium2 as pdfium

        from reading.pages import clean_pdf

        paper = self.send()
        self.read()
        pages = sorted(PaperPage.objects.filter(file=paper), key=lambda page: page.place_in_file)
        self.assertEqual([page.kind for page in pages], ["registration", "history", "xray"])
        document = pdfium.PdfDocument(clean_pdf(PaperFile.objects.get(pk=paper.pk), pages))
        self.assertEqual(len(document), 3)
        self.assertEqual([document[i].get_rotation() for i in range(3)], [0, 90, 0])

    def test_a_batch_costs_half_and_is_collected_when_it_ends(self):
        paper = self.send(pages=2, mode="batch")
        worker.run_once()  # pages made
        worker.run_once()  # sent in one batch
        self.assertEqual(len(self.fake.batches), 1)
        self.assertEqual(len(self.fake.batches["msgbatch_1"]), 4)
        self.assertNotIn("fallbacks", self.fake.batches["msgbatch_1"][0]["params"])  # not taken by batches
        self.assertEqual(PaperFile.objects.get(pk=paper.pk).status, "reading")
        self.read()
        paper.refresh_from_db()
        self.assertEqual(paper.status, "review")
        reading = PaperReading.objects.filter(page__file=paper).first()
        self.assertTrue(reading.batched)
        full = (Decimal(2000) * 4 + Decimal(2500) * 20 + Decimal(3000) * Decimal("0.2")) / 1000000
        self.assertEqual(reading.cost, full / 2)
        self.assertEqual(month_cost(), full / 2 * 4)

    def test_nothing_is_sent_while_reading_is_off_or_without_a_key(self):
        ReaderSettings.objects.update(enabled=False)
        paper = self.send()
        self.read()
        paper.refresh_from_db()
        self.assertEqual((paper.status, paper.page_count), ("waiting", 3))  # the pages are made offline
        self.assertEqual(paper.error, "off")
        with translation.override("en"):
            self.assertIn("switched off", paper.problem)
        self.assertEqual(self.fake.sent, [])
        ReaderSettings.objects.update(enabled=True)
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            self.read()
            self.assertEqual(PaperFile.objects.get(pk=paper.pk).error, "no_key")
        self.assertEqual(self.fake.sent, [])
        self.read()
        self.assertEqual(PaperFile.objects.get(pk=paper.pk).status, "review")

    def test_the_monthly_limit_stops_the_sending(self):
        ReaderSettings.objects.update(monthly_limit=Decimal("0.15"))  # the first file fits, not the second
        first = self.send(pages=1)
        self.read()
        self.assertEqual(PaperFile.objects.get(pk=first.pk).status, "review")
        sent = len(self.fake.sent)
        second = self.send(pages=1)
        self.read()
        self.assertEqual(len(self.fake.sent), sent)
        self.assertEqual(PaperFile.objects.get(pk=second.pk).error, "limit")

    def test_the_limit_is_kept_inside_a_batch_too(self):
        ReaderSettings.objects.update(monthly_limit=Decimal("0.11"))  # about three readings at the batch price
        paper = self.send(pages=2, mode="batch")
        self.read()
        self.assertEqual(sum(len(requests) for requests in self.fake.batches.values()), 3)
        self.assertEqual(PaperReading.objects.filter(page__file=paper, status="waiting").count(), 1)
        paper.refresh_from_db()
        self.assertEqual(paper.status, "reading")  # waits for next month, or a higher limit
        self.assertEqual(paper.error, "limit")
        ReaderSettings.objects.update(monthly_limit=Decimal("0"))  # no limit
        self.read()
        self.assertEqual(PaperFile.objects.get(pk=paper.pk).status, "review")

    def test_a_file_is_finished_by_one_reader_only(self):
        paper = self.send(pages=2)
        PaperFile.objects.filter(pk=paper.pk).update(claimed_at=timezone.now())  # another reader has it
        self.read()
        paper.refresh_from_db()
        self.assertEqual((paper.status, paper.page_count), ("waiting", 0))  # not cut twice
        PaperFile.objects.filter(pk=paper.pk).update(claimed_at=timezone.now() - timedelta(minutes=20))
        self.read()  # the other one stopped long ago: taken again
        paper.refresh_from_db()
        self.assertEqual(paper.status, "review")
        self.assertEqual(paper.pages.get(number=2).turned, 90)  # turned once
        self.assertIsNone(paper.claimed_at)

    def test_a_page_claude_declines_is_marked_and_a_file_never_read_fails(self):
        self.fake.refuse = {3}
        paper = self.send()
        self.read()
        page = self.client.get(PaperFile.objects.get(pk=paper.pk).get_absolute_url())
        self.assertEqual([p.number for p in page.context["failed_pages"]], [3])
        self.fake.refuse = {1}
        lost = self.send(pages=1)
        self.read()
        self.assertEqual(PaperFile.objects.get(pk=lost.pk).status, "failed")

    def test_a_refused_key_stops_the_sending(self):
        import anthropic
        import httpx2

        refused = anthropic.AuthenticationError("invalid x-api-key", body=None, response=httpx2.Response(
            401, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")))
        self.fake.beta.messages.create = mock.Mock(side_effect=refused)
        paper = self.send()
        self.read()
        self.assertEqual(PaperReading.objects.filter(page__file=paper, status="waiting").count(), 6)
        self.assertEqual(PaperFile.objects.get(pk=paper.pk).error.split(":")[0], "key_refused")

    def test_read_again_and_set_aside(self):
        paper = self.send(pages=1)
        self.read()
        calls = len(self.fake.sent)
        self.client.post(f"/files/{paper.pk}/again/")
        self.read()
        self.assertEqual(len(self.fake.sent), calls * 2)
        self.assertEqual(PaperFile.objects.get(pk=paper.pk).status, "review")
        self.client.post(paper.get_absolute_url(), {"action": "set_aside"})
        self.assertEqual(PaperFile.objects.get(pk=paper.pk).status, "set_aside")

    def test_the_instructions_and_the_answer_form(self):
        from reading.claude import instructions, schema

        text = instructions()
        names = [spec.name for spec in specs()]
        for name in names:
            self.assertIn(f"- {name} (", text)
        self.assertIn("Diabetes", text)
        self.assertIn("Dr. Mona Refaat", text)  # the dentists' names, to match "taken by"
        self.assertIn("01 = Cairo", text)
        self.assertEqual(instructions(), text)  # the same every time: kept ready (cached) by Anthropic
        form = schema()
        self.assertEqual(form["properties"]["fields"]["items"]["properties"]["name"]["enum"], names)
        self.assertFalse(form["additionalProperties"])

    def test_photos_of_the_pages_make_one_file(self):
        def photo(name):
            output = io.BytesIO()
            Image.new("RGB", (900, 1200), "white").save(output, "JPEG")
            return SimpleUploadedFile(name, output.getvalue(), "image/jpeg")

        self.client.post("/send/", {"files": [photo("1.jpg"), photo("2.jpg")], "mode": "now"})
        paper = PaperFile.objects.get()
        self.read()
        self.assertEqual(PaperFile.objects.get(pk=paper.pk).page_count, 2)
        bad = SimpleUploadedFile("x.pdf", b"MZ not a pdf", "application/pdf")
        response = self.client.post("/send/", {"files": [bad], "mode": "now"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PaperFile.objects.count(), 1)


class ReviewTests(ReaderTestCase):
    def known(self, **values):
        row = {"file_number": "CIA-00042", "full_name": "محمد أحمد علي حسن", "national_id": NID,
               "phone_primary": "01009998887", "phone_secondary": "",
               "values": {"full_name": "محمد أحمد علي حسن", "national_id": NID, "phone_primary": "01009998887"}}
        row.update(values)
        import_lists(lists_data([row]), self.owner)
        return KnownPatient.objects.get()

    def test_a_registered_patient_is_suggested_and_only_ticked_values_replace(self):
        known = self.known()
        paper = self.send(pages=1)
        self.read()
        paper.refresh_from_db()
        self.assertEqual((paper.suggested, paper.suggested_reason), ("CIA-00042", "national_id"))
        page = self.client.get(paper.get_absolute_url())
        self.assertIn("phone_primary", page.context["differs"])  # the paper says another mobile
        self.assertEqual(page.context["known"], known)
        response = self.approve(paper, **{"t-target": "existing", "t-file_number": "cia-00042",
                                          "replace": ["phone_primary", "not_a_field"]})
        self.assertEqual(response.status_code, 302)
        paper.refresh_from_db()
        self.assertEqual((paper.approved["target"], paper.approved["file_number"]), ("existing", "CIA-00042"))
        self.assertEqual(paper.approved["replace"], ["phone_primary"])

    def test_a_new_patient_whose_id_is_registered_is_refused(self):
        self.known()
        paper = self.send(pages=1)
        self.read()
        response = self.approve(paper, **{"t-target": "new"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("national_id", response.context["patient_form"].errors)
        self.assertEqual(PaperFile.objects.get(pk=paper.pk).status, "review")

    def test_an_unknown_file_number_is_refused_and_pages_only_needs_a_patient(self):
        paper = self.send(pages=1)
        self.read()
        response = self.approve(paper, **{"t-target": "existing", "t-file_number": "CIA-99999"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("file_number", response.context["target_form"].errors)
        self.approve(paper, **{"t-target": "new", "action": "pages_only"})
        self.assertEqual(PaperFile.objects.get(pk=paper.pk).status, "review")

    def test_pages_only_and_open_it_again(self):
        self.known()
        paper = self.send(pages=1)
        self.read()
        self.approve(paper, **{"t-target": "existing", "t-file_number": "CIA-00042", "action": "pages_only"})
        paper.refresh_from_db()
        self.assertEqual(paper.status, "approved")
        self.assertTrue(paper.approved["pages_only"])
        self.assertEqual(paper.approved["patient"], {})
        self.client.post(paper.get_absolute_url(), {"action": "reopen"})
        self.assertEqual(PaperFile.objects.get(pk=paper.pk).status, "review")

    def test_a_wrong_value_is_not_approved(self):
        paper = self.send(pages=1)
        self.read()
        response = self.approve(paper, **{"p-national_id": "2900115010123", "p-phone_primary": "0100"})
        self.assertEqual(response.status_code, 200)
        errors = response.context["patient_form"].errors
        self.assertIn("national_id", errors)
        self.assertIn("phone_primary", errors)
        self.assertIsNone(PaperFile.objects.get(pk=paper.pk).approved)

    def test_save_for_later_keeps_what_was_typed(self):
        paper = self.send(pages=1)
        self.read()
        page = self.client.get(paper.get_absolute_url())
        data = post_data(page.context["target_form"], page.context["patient_form"], page.context["history_form"])
        data.update({"action": "save", "p-phone_primary": "01001234560"})
        self.client.post(paper.get_absolute_url(), data)
        row = PaperField.objects.get(file=paper, name="phone_primary")
        self.assertEqual((row.value, row.checked), ("01001234560", True))
        self.assertFalse(row.needs_look)

    def test_the_suggested_patient_comes_from_the_cover_sheet(self):
        self.known(national_id="28512120101245", phone_primary="01112223334")

        def cover(page_number, reading):
            if page_number == 1:
                return {"page_kind": "cover", "turn": 0, "cover_file_number": "cia-00042", "page_notes": "",
                        "fields": []}
            return answers(page_number, reading)

        self.fake.reader = cover
        paper = self.send(pages=2)
        self.read()
        paper.refresh_from_db()
        self.assertEqual((paper.suggested, paper.suggested_reason), ("CIA-00042", "cover"))
        self.assertContains(self.client.get(paper.get_absolute_url()), "CIA-00042")
        self.assertEqual(self.client.get("/patients/lookup/?q=00042").json()["results"][0]["value"], "CIA-00042")

    def test_turning_a_page_turns_its_places(self):
        paper = self.send(pages=1)
        self.read()
        page = paper.pages.get()
        row = PaperField.objects.get(file=paper, name="full_name")
        before, size = row.box, (page.width, page.height)
        self.client.post(f"/files/{paper.pk}/pages/{page.pk}/", {"turn": "right", "kind": "registration"})
        page.refresh_from_db()
        row.refresh_from_db()
        self.assertEqual((page.width, page.height), (size[1], size[0]))
        self.assertEqual(row.box, turn_box(before, 90, *size))


class SetUpTests(ReaderTestCase):
    def test_the_lists_file_is_brought_in(self):
        self.client.login(username="owner", password=PASSWORD)
        data = lists_data([{"file_number": "CIA-00007", "full_name": "سعاد محمود", "national_id": "28512120101245",
                            "phone_primary": "01112223334", "phone_secondary": "", "values": {}}])
        upload = SimpleUploadedFile("lists.json", json.dumps(data, ensure_ascii=False).encode(), "application/json")
        response = self.client.post("/settings/lists/", {"lists": upload})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(KnownPatient.objects.values_list("file_number", flat=True)), ["CIA-00007"])
        self.assertEqual(SystemLists.get().place_code, "CIA")
        self.assertEqual(len(specs()), len(LISTS["fields"]))
        self.assertEqual(by_name()["gender"].choice_label("F"), "أنثى" if translation.get_language() == "ar"
                         else "Female")
        bad = SimpleUploadedFile("x.json", b'{"kind": "something else"}', "application/json")
        self.client.post("/settings/lists/", {"lists": bad})
        self.assertEqual(KnownPatient.objects.count(), 1)  # the lists in use stay

    def test_no_files_before_the_lists(self):
        SystemLists.objects.all().delete()
        response = self.client.post("/send/", {"files": [SimpleUploadedFile("a.pdf", make_pdf(1),
                                                                            "application/pdf")], "mode": "now"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(PaperFile.objects.exists())

    def test_the_first_run_makes_the_person_in_charge(self):
        get_user_model().objects.all().delete()
        self.client.logout()
        self.assertRedirects(self.client.get("/login/"), "/setup/")
        response = self.client.post("/setup/", {"username": "boss", "first_name": "Dr. Ahmed",
                                                "password": "a-good-long-password",
                                                "again": "a-good-long-password"})
        self.assertEqual(response.status_code, 302, getattr(response, "context", None)
                         and response.context["form"].errors)
        self.assertTrue(get_user_model().objects.get(username="boss").is_staff)
        self.client.logout()
        self.assertEqual(self.client.get("/setup/").status_code, 302)  # only once
        self.assertEqual(self.client.get("/login/").status_code, 200)

    def test_only_the_person_in_charge_sets_it_up(self):
        for url in ("/settings/", "/settings/lists/", "/settings/people/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        paper = self.send(pages=1)
        self.assertEqual(self.client.post(f"/files/{paper.pk}/delete/").status_code, 403)
        self.client.login(username="owner", password=PASSWORD)
        for url in ("/settings/", "/settings/lists/", "/settings/people/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        response = self.client.post("/settings/", {"enabled": "on", "model": "claude-sonnet-5-5", "effort": "high",
                                                   "default_mode": "now", "monthly_limit": "50"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ReaderSettings.get().model, "claude-sonnet-5-5")
        self.assertFalse(ReaderSettings.get().two_readings)
        self.client.post("/settings/people/", {"username": "sec2", "first_name": "Sara",
                                               "password": "another-long-password", "active": "on"})
        self.assertFalse(get_user_model().objects.get(username="sec2").is_staff)
        self.client.post(f"/files/{paper.pk}/delete/")
        self.assertFalse(PaperFile.objects.exists())

    def test_logged_out_people_see_nothing(self):
        paper = self.send(pages=1)
        self.read()
        page = PaperPage.objects.filter(file=paper).first()
        self.client.logout()
        for url in ("/", paper.get_absolute_url(), f"/media/{page.image.name}", f"/media/{paper.original.name}"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn("/login/", response["Location"])
        self.client.login(username="sec", password=PASSWORD)
        self.assertEqual(self.client.get(f"/media/{page.image.name}").status_code, 200)
        self.assertEqual(self.client.get("/media/../site_config/settings.py").status_code, 404)

    @override_settings(ALLOWED_NETWORKS=["192.168.1.0/24"])
    def test_only_the_clinics_network(self):
        self.assertEqual(self.client.get("/login/", REMOTE_ADDR="8.8.8.8").status_code, 403)
        self.assertEqual(self.client.get("/login/", REMOTE_ADDR="192.168.1.20").status_code, 200)

    def test_the_demo(self):
        from reading.demo import load_reader

        get_user_model().objects.all().delete()
        load_reader(PASSWORD)
        statuses = set(PaperFile.objects.values_list("status", flat=True))
        self.assertEqual(statuses, {"review", "approved"})
        samia = PaperFile.objects.get(status="review")
        self.assertEqual(samia.fields.get(name="hba1c").certainty, "check")
        self.assertEqual(samia.fields.get(name="phone_primary").certainty, "check")
        self.client.login(username="secretary", password=PASSWORD)
        self.assertEqual(self.client.get(samia.get_absolute_url()).status_code, 200)
        self.client.post("/to-the-system/")
        self.assertEqual(Export.objects.get().count, 1)


class CheckTests(ReaderTestCase):
    def test_values_are_cleaned_and_checked(self):
        known = by_name()

        def check(name, raw):
            return clean_value(known[name], raw)

        self.assertEqual(check("national_id", "٢٩٠٠١١٥٠١٠١٢٣٤"), (NID, []))
        self.assertEqual(check("national_id", "2900115010123")[1][0][0], "bad_id")  # 13 digits
        self.assertEqual(check("phone_primary", "+20 100 123 4567"), ("01001234567", []))
        self.assertEqual(check("phone_primary", "0100123456")[1][0][0], "bad_phone")
        self.assertEqual(check("birth_date", "٣/٤/١٩٨٠"), ("03/04/1980", []))
        self.assertEqual(check("registered_on", "03/04/2090")[1][0][0], "date_range")
        self.assertEqual(check("bp_last_systolic", "13O")[0], "13")
        self.assertEqual(check("bp_last_systolic", "330")[1][0][0], "out_of_range")
        self.assertEqual(check("hba1c", "7,5"), ("7.5", []))
        self.assertEqual(check("gender", "ذكر"), ("M", []))
        self.assertEqual(check("governorate", "Giza"), ("21", []))
        self.assertEqual(check("pregnant", "No"), ("no", []))
        self.assertEqual(check("smoker", "✓"), ("yes", []))
        self.assertEqual(check("full_name", "Mohamed Ahmed")[1][0][0], "bad_name")
        self.assertEqual(check("examined_by", "mona refaat")[0], MONA)
        self.assertEqual(check("examined_by", "Dr. Nobody")[1][0][0], "unknown_dentist")

    def test_the_national_id_is_compared_with_the_paper(self):
        paper = PaperFile.objects.create(original_name="x.pdf", original="files/x/original.pdf", page_count=1)
        page = PaperPage.objects.create(file=paper, number=1, width=1000, height=1400, kind="registration",
                                        image="files/x/page.jpg")
        PaperReading.objects.create(page=page, number=1, status="done", result={
            "page_kind": "registration", "turn": 0, "fields": [
                entry("national_id", NID), entry("birth_date", "16/01/1990"), entry("gender", "F"),
                entry("phone_primary", "01001234567", box=(5000, 1, 6000, 2))]})
        rows = build_fields(paper)
        self.assertEqual(rows["birth_date"].certainty, "check")
        self.assertEqual(rows["gender"].certainty, "check")
        self.assertEqual(rows["governorate"].value, "01")  # filled from the ID
        self.assertEqual(rows["governorate"].certainty, "sure")
        self.assertEqual(rows["national_id"].certainty, "check")
        self.assertIsNone(rows["phone_primary"].box)  # outside the picture: no cut-out
        self.assertEqual(rows["phone_primary"].certainty, "sure")  # one reading only

    def test_boxes(self):
        box = [10, 20, 110, 60]
        self.assertEqual(turn_box(turn_box(turn_box(turn_box(box, 90, 400, 300), 90, 300, 400), 90, 400, 300),
                                  90, 300, 400), box)
        self.assertEqual(turn_box(box, 180, 400, 300), [290, 240, 390, 280])
        self.assertEqual(turn_box(box, 90, 400, 300), [240, 10, 280, 110])
        self.assertEqual(turn_box(box, 270, 400, 300), [20, 290, 60, 390])
        self.assertIsNone(clean_box([1, 2, 3], 100, 100))
        self.assertEqual(clean_box([90, 50, 10, 5000], 100, 100), [10, 50, 90, 100])
