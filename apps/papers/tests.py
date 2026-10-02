"""Old paper files read by Claude (round 13). Claude is never called by the tests: a fake client answers like the
Anthropic API (now and in batches), so the whole road is tested without the internet and without cost."""

import io
import json
import os
import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.core.cache import cache
from django.utils import timezone, translation
from PIL import Image, ImageDraw

from apps.core.testing import PASSWORD, make_dentist, make_patient, make_user, setup_clinic
from apps.papers import worker
from apps.papers.checks import build_fields, clean_value
from apps.papers.fields import BY_NAME, NAMES
from apps.papers.models import PaperField, PaperFile, PaperPage, PaperReading, PaperSettings, month_cost
from apps.papers.pages import clean_box, turn_box
from apps.patients.models import MedicalCondition, Patient, PatientDocument

NID = "29001150101234"  # born 15/01/1990, Cairo, a man


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
    entry("exam_date", "03/04/2016"), entry("bp_last_systolic", "130"), entry("bp_last_diastolic", "85"),
    entry("conditions", "Diabetes, gout"), entry("allergy_penicillin", "yes"), entry("smoker", "yes"),
    entry("cigarettes_per_day", "20"), entry("hba1c", "7.8", certainty="check"),
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


class PaperFileTestCase(TestCase):
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
        cache.clear()  # the owner is told once a month or once an hour: each test starts afresh
        self.branch = setup_clinic()
        self.owner = make_user("owner", "owner")
        self.secretary = make_user("sec", "secretary")
        self.dentist = make_dentist("mona", kind="fulltime", name="Dr. Mona Adel")
        options = PaperSettings.get()
        options.enabled = True
        options.save()
        self.fake = FakeAnthropic()
        patcher = mock.patch("apps.papers.claude.client", return_value=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        one_at_a_time = mock.patch.object(worker, "AT_ONCE", 1)  # the fake answers in the order asked
        one_at_a_time.start()
        self.addCleanup(one_at_a_time.stop)
        environment = mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"})
        environment.start()
        self.addCleanup(environment.stop)
        self.client.login(username="sec", password=PASSWORD)

    def send(self, pages=3, mode="now", **extra):
        url = "/patients/papers/send/" + (f"?patient={extra['patient'].pk}" if "patient" in extra else "")
        response = self.client.post(url, {"files": [SimpleUploadedFile("old file.pdf", make_pdf(pages),
                                                                        "application/pdf")], "mode": mode})
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and
                         response.context["form"].errors)
        return PaperFile.objects.latest("pk")

    def read(self):
        worker.run_until_done(sleep=lambda seconds: None)


class ReadingTests(PaperFileTestCase):
    def test_a_file_is_read_twice_checked_and_approved_into_a_new_patient(self):
        paper = self.send()
        self.assertEqual(paper.status, PaperFile.Status.WAITING)
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
        diabetes = MedicalCondition.objects.get(name_en="Diabetes")
        self.assertEqual(fields["conditions"].value, str(diabetes.pk))
        self.assertEqual(fields["other_condition"].value, "gout")  # not in the list
        self.assertEqual(fields["allergy_penicillin"].value, "yes")
        # The history page was turned upright, and its places with it.
        history = paper.pages.get(number=2)
        self.assertEqual((history.kind, history.turned), ("history", 90))
        self.assertGreater(history.width, history.height)
        self.assertEqual(fields["bp_last_systolic"].box, turn_box([100, 200, 400, 240], 90, history.height,
                                                                  history.width))
        self.assertEqual(self.client.get(f"/patients/papers/values/{fields['hba1c'].pk}/paper.jpg").status_code, 200)
        # The secretary is told.
        self.assertTrue(self.secretary.notifications.filter(url=f"/patients/papers/{paper.pk}/").exists())
        # The review page, then approve as it is.
        page = self.client.get(paper.get_absolute_url())
        self.assertContains(page, "papers/values/")
        data = post_data(page.context["target_form"], page.context["patient_form"], page.context["history_form"])
        data.update({"t-target": "new", "action": "approve", "p-referral_source": ""})
        response = self.client.post(paper.get_absolute_url(), data)
        patient = Patient.objects.get(national_id=NID)
        self.assertRedirects(response, patient.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual((patient.full_name, patient.phone_primary, patient.occupation),
                         ("محمد أحمد علي حسن", "01001234567", "Engineer"))
        self.assertEqual(patient.registered_on, date(2016, 4, 3))
        self.assertEqual(patient.birth_date, date(1990, 1, 15))
        exam = patient.examinations.get()
        self.assertTrue(exam.history_only and exam.medical_taken and exam.dental_taken)
        self.assertEqual((exam.exam_date, exam.bp_last_systolic, exam.hba1c), (date(2016, 4, 3), 130, Decimal("7.8")))
        self.assertTrue(exam.allergy_penicillin and exam.smoker)
        self.assertEqual(list(patient.medical_conditions.all()), [diabetes])
        # The pages kept in the patient's documents: the whole file, and the X-ray in its own place.
        kinds = set(patient.documents.values_list("kind", flat=True))
        self.assertEqual(kinds, {PatientDocument.Kind.OLD_FILE, PatientDocument.Kind.XRAY})
        whole = patient.documents.get(kind="old_file")
        self.assertTrue(whole.file.read(4) == b"%PDF")
        paper.refresh_from_db()
        self.assertEqual((paper.status, paper.patient, paper.document), ("approved", patient, whole))

    def test_the_clean_pdf_is_in_order_and_upright(self):
        import pypdfium2 as pdfium

        from apps.papers.pages import clean_pdf

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
        PaperSettings.objects.update(enabled=False)
        paper = self.send()
        self.read()
        paper.refresh_from_db()
        self.assertEqual((paper.status, paper.page_count), ("waiting", 3))  # the pages are made offline
        self.assertEqual(paper.error, "off")
        with translation.override("en"):
            self.assertIn("switched off", paper.problem)
        self.assertEqual(self.fake.sent, [])
        PaperSettings.objects.update(enabled=True)
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            self.read()
        self.assertEqual(self.fake.sent, [])
        self.read()
        self.assertEqual(PaperFile.objects.get(pk=paper.pk).status, "review")

    def test_the_monthly_limit_stops_the_sending(self):
        PaperSettings.objects.update(monthly_limit=Decimal("0.15"))  # the first file fits, not the second
        first = self.send(pages=1)
        self.read()
        self.assertEqual(PaperFile.objects.get(pk=first.pk).status, "review")
        sent = len(self.fake.sent)
        second = self.send(pages=1)
        self.read()
        self.assertEqual(len(self.fake.sent), sent)
        self.assertEqual(PaperFile.objects.get(pk=second.pk).error, "limit")
        self.assertTrue(self.owner.notifications.filter(url="/patients/papers/settings/").exists())

    def test_the_limit_is_kept_inside_a_batch_too(self):
        PaperSettings.objects.update(monthly_limit=Decimal("0.11"))  # about three readings at the batch price
        paper = self.send(pages=2, mode="batch")
        self.read()
        self.assertEqual(sum(len(requests) for requests in self.fake.batches.values()), 3)
        self.assertEqual(PaperReading.objects.filter(page__file=paper, status="waiting").count(), 1)
        paper.refresh_from_db()
        self.assertEqual(paper.status, "reading")  # waits for next month, or a higher limit
        self.assertEqual(paper.error, "limit")
        PaperSettings.objects.update(monthly_limit=Decimal("0"))  # no limit
        self.read()
        self.assertEqual(PaperFile.objects.get(pk=paper.pk).status, "review")

    def test_a_file_is_finished_by_one_reader_only(self):
        paper = self.send(pages=2)
        PaperFile.objects.filter(pk=paper.pk).update(claimed_at=timezone.now())  # another server has it
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

    def test_a_refused_key_stops_and_tells_the_owner(self):
        import anthropic
        import httpx2

        refused = anthropic.AuthenticationError("invalid x-api-key", body=None, response=httpx2.Response(
            401, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")))
        self.fake.beta.messages.create = mock.Mock(side_effect=refused)
        paper = self.send()
        self.read()
        self.assertEqual(PaperReading.objects.filter(page__file=paper, status="waiting").count(), 6)
        self.assertTrue(self.owner.notifications.filter(url="/patients/papers/settings/").exists())

    def test_read_again_and_set_aside(self):
        paper = self.send(pages=1)
        self.read()
        calls = len(self.fake.sent)
        self.client.post(f"/patients/papers/{paper.pk}/again/")
        self.read()
        self.assertEqual(len(self.fake.sent), calls * 2)
        self.assertEqual(PaperFile.objects.get(pk=paper.pk).status, "review")
        self.client.post(paper.get_absolute_url(), {"action": "set_aside"})
        self.assertEqual(PaperFile.objects.get(pk=paper.pk).status, "set_aside")

    def test_the_instructions_and_the_answer_form(self):
        from apps.papers.claude import instructions, schema

        text = instructions()
        for name in NAMES:
            self.assertIn(f"- {name} (", text)
        self.assertIn("Diabetes", text)
        self.assertIn("Dr. Mona Adel", text)  # the dentists' names, to match "taken by"
        self.assertIn("01 = Cairo", text)
        self.assertEqual(instructions(), text)  # the same every time: kept ready (cached) by Anthropic
        form = schema()
        self.assertEqual(form["properties"]["fields"]["items"]["properties"]["name"]["enum"], NAMES)
        self.assertFalse(form["additionalProperties"])


class ReviewTests(PaperFileTestCase):
    def test_into_a_registered_patient_only_empty_fields_are_filled_and_a_change_waits_for_approval(self):
        from apps.core.models import ChangeRequest

        patient = make_patient(self.branch, name="محمد أحمد علي حسن", nid=NID, phone="01009998887",
                               occupation="")
        paper = self.send(pages=1, patient=patient)
        self.read()
        paper.refresh_from_db()
        self.assertEqual(paper.patient, patient)
        page = self.client.get(paper.get_absolute_url())
        self.assertIn("phone_primary", page.context["differs"])  # the paper says another mobile
        data = post_data(page.context["patient_form"], page.context["history_form"])
        data.update({"t-target": "existing", "t-patient": patient.file_number, "action": "approve",
                     "replace": ["phone_primary"]})
        response = self.client.post(paper.get_absolute_url(), data)
        self.assertEqual(response.status_code, 302, response.context and response.context["patient_form"].errors)
        patient.refresh_from_db()
        self.assertEqual(patient.occupation, "Engineer")  # empty: filled
        self.assertEqual(patient.phone_primary, "01009998887")  # replaced only after the head approves
        change = ChangeRequest.objects.get()
        self.assertEqual(change.changes[0]["field"], "phone_primary")
        self.assertEqual(Patient.objects.count(), 1)

    def test_the_suggested_patient_comes_from_the_cover_sheet(self):
        patient = make_patient(self.branch, name="سعاد محمود عبد الله", nid="28512120101245", phone="01112223334")

        def cover(page_number, reading):
            if page_number == 1:
                return {"page_kind": "cover", "turn": 0, "cover_file_number": patient.file_number.lower(),
                        "page_notes": "", "fields": []}
            return answers(page_number, reading)

        self.fake.reader = cover
        paper = self.send(pages=2)
        self.read()
        paper.refresh_from_db()
        self.assertEqual((paper.suggested, paper.suggested_reason), (patient, "cover"))
        self.assertContains(self.client.get(paper.get_absolute_url()), patient.file_number)

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

    def test_turning_a_page_turns_its_places(self):
        paper = self.send(pages=1)
        self.read()
        page = paper.pages.get()
        row = PaperField.objects.get(file=paper, name="full_name")
        before, size = row.box, (page.width, page.height)
        self.client.post(f"/patients/papers/{paper.pk}/pages/{page.pk}/", {"turn": "right", "kind": "registration"})
        page.refresh_from_db()
        row.refresh_from_db()
        self.assertEqual((page.width, page.height), (size[1], size[0]))
        self.assertEqual(row.box, turn_box(before, 90, *size))

    def test_who_sees_the_paper_files(self):
        from apps.core.models import Branch, UserProfile

        paper = self.send(pages=1)
        self.read()
        make_dentist("dentist")
        self.client.login(username="dentist", password=PASSWORD)
        self.assertEqual(self.client.get("/patients/papers/").status_code, 403)
        self.assertEqual(self.client.get(paper.original.url).status_code, 403)
        # A secretary of another place does not open the file, nor its pictures.
        cic = Branch.objects.get(code="CIC")
        other = make_user("cicsec", "secretary")
        UserProfile.objects.update_or_create(user=other, defaults={"branch": cic})
        self.client.login(username="cicsec", password=PASSWORD)
        self.assertEqual(self.client.get(paper.get_absolute_url()).status_code, 403)
        self.assertEqual(self.client.get(paper.original.url).status_code, 403)
        row = PaperField.objects.filter(file=paper).exclude(box=None).first()
        self.assertEqual(self.client.get(f"/patients/papers/values/{row.pk}/paper.jpg").status_code, 403)
        self.client.login(username="sec", password=PASSWORD)
        self.assertEqual(self.client.get(paper.original.url).status_code, 200)
        # The settings are the owner's.
        self.assertEqual(self.client.get("/patients/papers/settings/").status_code, 403)
        self.client.login(username="owner", password=PASSWORD)
        self.assertEqual(self.client.get("/patients/papers/settings/").status_code, 200)
        response = self.client.post("/patients/papers/settings/", {
            "enabled": "on", "model": "claude-sonnet-5-5", "effort": "high", "default_mode": "now",
            "monthly_limit": "50"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PaperSettings.get().model, "claude-sonnet-5-5")
        self.assertFalse(PaperSettings.get().two_readings)

    def test_cover_sheets(self):
        patient = make_patient(self.branch)
        page = self.client.get(f"/patients/papers/covers/?patient={patient.file_number}&blank=2")
        self.assertContains(page, patient.file_number)
        self.assertEqual(page.content.decode().count('class="cover-sheet"'), 3)

    def test_photos_of_the_pages_make_one_file(self):
        def photo(name):
            output = io.BytesIO()
            Image.new("RGB", (900, 1200), "white").save(output, "JPEG")
            return SimpleUploadedFile(name, output.getvalue(), "image/jpeg")

        self.client.post("/patients/papers/send/", {"files": [photo("1.jpg"), photo("2.jpg")], "mode": "now"})
        paper = PaperFile.objects.get()
        self.read()
        self.assertEqual(PaperFile.objects.get(pk=paper.pk).page_count, 2)
        bad = SimpleUploadedFile("x.pdf", b"MZ not a pdf", "application/pdf")
        response = self.client.post("/patients/papers/send/", {"files": [bad], "mode": "now"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PaperFile.objects.count(), 1)


class CheckTests(TestCase):
    def setUp(self):
        setup_clinic()
        make_dentist("sherif", kind="fulltime", login=False, name="Dr. Sherif Nabil")

    def test_values_are_cleaned_and_checked(self):
        def check(name, raw):
            return clean_value(BY_NAME[name], raw)

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
        from apps.dentists.models import Dentist

        self.assertEqual(check("examined_by", "sherif nabil")[0], str(Dentist.objects.get(full_name="Dr. Sherif Nabil").pk))
        self.assertEqual(check("examined_by", "Dr. Nobody")[1][0][0], "unknown_dentist")

    def test_the_national_id_is_compared_with_the_paper(self):
        from apps.core.models import Branch

        paper = PaperFile.objects.create(branch=Branch.objects.get(code="CIA"), original_name="x.pdf",
                                         original="papers/CIA/x/original.pdf", page_count=1)
        page = PaperPage.objects.create(file=paper, number=1, width=1000, height=1400, kind="registration",
                                        image="papers/CIA/x/page.jpg")
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
