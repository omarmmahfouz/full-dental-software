import io
import os
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import translation

from apps.core.models import Branch, Notification
from apps.core.notify import notify_roles
from apps.core.roles import SUPERVISOR, has_role
from apps.core.testing import PASSWORD, make_user, setup_clinic
from apps.core.utils import normalize_digits, normalize_phone, parse_egyptian_national_id, validate_phone


class UtilsTests(TestCase):
    def test_arabic_digits_are_converted(self):
        self.assertEqual(normalize_digits("٠١٠٠١٢٣٤٥٦٧"), "01001234567")
        self.assertEqual(normalize_digits("۰۱۲"), "012")

    def test_phone_normalisation_makes_duplicates_comparable(self):
        expected = "01001234567"
        for typed in ["01001234567", "+20 100 123 4567", "0020-100-123-4567", "201001234567",
                      "1001234567", "٠١٠٠١٢٣٤٥٦٧", " 0100 123 4567 "]:
            with self.subTest(typed=typed):
                self.assertEqual(normalize_phone(typed), expected)
        self.assertEqual(normalize_phone("+966 50 123 4567"), "+966501234567")

    def test_validate_phone(self):
        self.assertEqual(validate_phone("01551234567"), "01551234567")
        self.assertEqual(validate_phone("+966501234567"), "+966501234567")
        with self.assertRaises(ValidationError):
            validate_phone("01301234567")  # not an Egyptian mobile prefix
        with self.assertRaises(ValidationError):
            validate_phone("0223456789")  # landline not allowed as primary
        self.assertEqual(validate_phone("0223456789", mobile_only=False), "0223456789")

    def test_national_id_parsing(self):
        data = parse_egyptian_national_id("29001150101234")  # 13th digit 3 -> male
        self.assertEqual(data["birth_date"], date(1990, 1, 15))
        self.assertEqual(data["gender"], "M")
        self.assertEqual(parse_egyptian_national_id("30105220101242")["gender"], "F")
        self.assertEqual(parse_egyptian_national_id("30105220101242")["birth_date"], date(2001, 5, 22))
        for bad in ["2900115010123", "19001150101234", "29013450101234", "abc"]:
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                parse_egyptian_national_id(bad)


class RolesAndNotificationTests(TestCase):
    def setUp(self):
        setup_clinic()

    def test_roles_and_notify(self):
        supervisor = make_user("sup", SUPERVISOR)
        other = make_user("sec", "secretary")
        self.assertTrue(has_role(supervisor, SUPERVISOR))
        self.assertFalse(has_role(other, SUPERVISOR))
        notify_roles((SUPERVISOR,), "Test %(x)s", params={"x": "1"})
        self.assertEqual(Notification.objects.get(recipient=supervisor).title, "Test 1")
        self.assertFalse(Notification.objects.filter(recipient=other).exists())

    def test_login_required_everywhere(self):
        response = self.client.get("/patients/")
        self.assertRedirects(response, "/login/?next=/patients/", fetch_redirect_response=False)

    def test_notification_open_marks_read(self):
        user = make_user("sec", "secretary")
        note = Notification.objects.create(recipient=user, title="x", url="/patients/")
        self.client.login(username="sec", password=PASSWORD)
        response = self.client.get(f"/notifications/{note.pk}/")
        self.assertRedirects(response, "/patients/", fetch_redirect_response=False)
        note.refresh_from_db()
        self.assertIsNotNone(note.read_at)

    def test_dashboard_renders_for_each_role(self):
        for index, role in enumerate(["secretary", "dentist", "supervisor", "owner"]):
            make_user(f"u{index}", role)
            self.client.login(username=f"u{index}", password=PASSWORD)
            self.assertEqual(self.client.get("/").status_code, 200)


class LanguageTests(TestCase):
    def setUp(self):
        setup_clinic()

    def language_of_page(self, username):
        self.client.logout()
        self.client.login(username=username, password=PASSWORD)
        return self.client.get("/").context["LANGUAGE_CODE"]

    def test_secretary_arabic_dentist_english(self):
        make_user("sec", "secretary")
        make_user("dentist", "dentist")
        make_user("owner", "owner")
        self.assertEqual(self.language_of_page("sec"), "ar")
        self.assertEqual(self.language_of_page("dentist"), "en")
        self.assertEqual(self.language_of_page("owner"), "en")

    def test_chosen_language_is_kept_per_user(self):
        make_user("sec", "secretary")
        make_user("dentist", "dentist")
        self.client.login(username="dentist", password=PASSWORD)
        response = self.client.post("/i18n/setlang/", {"language": "ar", "next": "/patients/"})
        self.assertRedirects(response, "/patients/", fetch_redirect_response=False)
        self.assertEqual(self.language_of_page("dentist"), "ar")
        self.assertEqual(self.language_of_page("sec"), "ar")
        self.client.login(username="sec", password=PASSWORD)
        self.client.post("/i18n/setlang/", {"language": "en", "next": "https://evil.example/"})
        self.assertEqual(self.language_of_page("sec"), "en")
        self.assertEqual(self.language_of_page("dentist"), "ar")  # one user's choice does not change another's

    def test_notifications_and_names_in_each_users_language(self):
        from django.utils.translation import gettext_lazy

        from apps.core.notify import notify_users
        from apps.scheduling.models import Room

        secretary = make_user("sec", "secretary")
        dentist = make_user("dentist", "dentist")
        notify_users([secretary, dentist], gettext_lazy("Lab request %(number)s needs your review"), params={"number": "L-1"})
        self.assertEqual(Notification.objects.get(recipient=dentist).title, "Lab request L-1 needs your review")
        self.assertNotIn("Lab request", Notification.objects.get(recipient=secretary).title)
        self.client.login(username="dentist", password=PASSWORD)
        page = self.client.get("/schedule/rooms/")
        self.assertIn("Room 1", [str(room) for room, _cells in page.context["rows"]])
        self.assertTrue(Room.objects.filter(name="غرفة 1", name_en="Room 1").exists())


class AccessAndSettingsTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.owner = make_user("owner", "owner")
        self.secretary = make_user("sec", "secretary")

    def test_read_only_person(self):
        from apps.core.models import UserProfile

        UserProfile.objects.update_or_create(user=self.secretary, defaults={"read_only": True})
        self.client.login(username="sec", password=PASSWORD)
        page = self.client.get("/patients/")
        self.assertEqual(page.status_code, 200)
        self.assertTrue(page.context["read_only_here"])
        self.assertEqual(self.client.post("/patients/calls/new/", {"full_name": "x"}).status_code, 403)
        # Changing the language is always allowed.
        self.assertEqual(self.client.post("/i18n/setlang/", {"language": "en"}).status_code, 302)

    def test_role_access_matrix(self):
        from apps.core.models import AreaAccess

        self.client.login(username="owner", password=PASSWORD)
        self.client.post("/settings/access/", {"secretary__purchases": "hidden", "secretary__complaints": "read"})
        self.assertEqual(AreaAccess.objects.get(role="secretary", area="purchases").level, "hidden")
        self.client.login(username="sec", password=PASSWORD)
        self.assertEqual(self.client.get("/purchases/").status_code, 403)
        self.assertIn("purchases", self.client.get("/").context["hidden_areas"])
        self.assertEqual(self.client.get("/complaints/").status_code, 200)
        self.assertEqual(self.client.post("/complaints/new/", {}).status_code, 403)
        self.client.login(username="owner", password=PASSWORD)  # the owner is never limited
        self.assertEqual(self.client.get("/purchases/").status_code, 200)

    def test_time_limits(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.core.models import UserProfile

        profile, _created = UserProfile.objects.get_or_create(user=self.secretary)
        self.client.login(username="sec", password=PASSWORD)
        profile.access_until = timezone.localdate() - timedelta(days=1)
        profile.save()
        response = self.client.get("/patients/")
        self.assertRedirects(response, "/login/", fetch_redirect_response=False)
        response = self.client.post("/login/", {"username": "sec", "password": PASSWORD})
        self.assertEqual(response.context["form"].non_field_errors().as_data()[0].code, "time")
        today = timezone.localdate().weekday()
        profile.access_until, profile.access_days = None, str((today + 1) % 7)
        profile.save()
        with translation.override("en"):
            self.assertIn("day", profile.access_problem())
        profile.access_days = ""
        profile.save()
        self.assertEqual(profile.access_problem(), "")

    def test_owner_manages_people_and_lists(self):
        from apps.core.models import ClinicSettings, UserProfile
        from apps.surgery.models import ImplantSystem

        self.client.login(username="owner", password=PASSWORD)
        self.client.post("/settings/users/new/", {
            "username": "newsec", "first_name": "Sara", "roles": ["secretary"], "is_active": "on",
            "new_password": "pass-12345", "read_only": "on", "access_days": ["5", "6"],
            "access_start": "09:00", "access_end": "17:00",
        })
        profile = UserProfile.objects.get(user__username="newsec")
        self.assertEqual((profile.read_only, profile.access_days), (True, "5,6"))
        self.assertTrue(profile.user.groups.filter(name="secretary").exists())
        self.client.post("/settings/lists/implant_systems/new/", {"company": "Zimmer", "line": "TSV", "is_active": "on"})
        self.assertTrue(ImplantSystem.objects.filter(company="Zimmer").exists())
        self.client.post("/settings/options/", {
            "o-day_start": "09:00", "o-day_end": "17:00", "o-surgery_days": ["3", "4"], "o-dicom_email": "ciapts@gmail.com",
            "o-late_threshold_minutes": 15, "o-default_appointment_minutes": 45, "o-complaint_follow_up_days": 3,
            "o-stock_expiry_days": 30, "o-reminder_days_before": 2, "o-whatsapp_country_code": "20",
            "o-fawry_fee_percent": "1.5", "o-hba1c_limit": "7.5", "o-glucose_limit": 200, "o-systolic_limit": 160,
            "o-diastolic_limit": 100, "o-follow_up_sinus_days": 3, "o-follow_up_graft_days": 7, "o-follow_up_days": 7,
            "o-idle_logout_minutes": 60,
            "b-name_ar": "أكاديمية القاهرة لزراعة الأسنان", "b-name_en": "Cairo Implant Academy", "b-phone": "0223456789",
            "b-address": "Cairo",
        })
        self.assertEqual(ClinicSettings.get().late_threshold_minutes, 15)
        self.assertEqual(ClinicSettings.get().fawry_fee_percent, Decimal("1.5"))
        self.assertEqual((ClinicSettings.get().hba1c_limit, ClinicSettings.get().follow_up_sinus_days), (Decimal("7.5"), 3))
        make_user("head", "head_cia")
        self.client.login(username="head", password=PASSWORD)
        self.assertEqual(self.client.get("/settings/users/").status_code, 403)
        self.assertEqual(self.client.get("/settings/lists/implant_systems/").status_code, 200)


class DemoDataTests(TestCase):
    def test_files_the_demo_data_needs_are_in_the_project(self):
        from apps.core.management.commands.load_demo_data import STOCK_LIST

        self.assertTrue(STOCK_LIST.exists(), STOCK_LIST)

    def test_existing_practice_data_is_kept_and_missing_logins_are_named(self):
        import io

        from django.core.management import CommandError, call_command

        from apps.core.testing import make_patient

        make_patient(setup_clinic())
        make_user("owner", "owner")
        with self.assertRaises(CommandError):
            call_command("load_demo_data", password="x", stdout=io.StringIO())
        out = io.StringIO()
        call_command("load_demo_data", password="x", if_empty=True, stdout=out)
        self.assertIn("kept as it is", out.getvalue())
        self.assertIn("missing: headcia, teamhead", out.getvalue())
        self.assertNotIn("owner,", out.getvalue())


class WidgetTests(TestCase):
    def test_dates_are_dd_mm_yyyy_and_times_come_in_quarters(self):
        from datetime import time

        from django import forms as dj_forms

        from apps.core.forms import StyledForm

        class Form(StyledForm):
            day = dj_forms.DateField()
            at = dj_forms.DateTimeField()
            start = dj_forms.TimeField()

        form = Form({"day": "٠٥/٠٩/٢٠٢٦", "at_0": "05/09/2026", "at_1": "09:45", "start": "10:30"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["day"], date(2026, 9, 5))
        self.assertEqual((form.cleaned_data["at"].day, form.cleaned_data["at"].month), (5, 9))
        self.assertEqual(form.cleaned_data["start"], time(10, 30))
        html = str(Form(initial={"day": date(2026, 9, 5)})["day"])
        self.assertIn('value="05/09/2026"', html)
        options = str(Form()["start"])
        self.assertIn('value="09:15"', options)
        self.assertNotIn('value="09:10"', options)


class PersonAccessTests(TestCase):
    def test_academy_for_one_secretary_only(self):
        from apps.core.models import AreaAccess, PersonAreaAccess

        setup_clinic()
        make_user("owner", "owner")
        first, second = make_user("sec1", "secretary"), make_user("sec2", "secretary")
        self.client.login(username="owner", password=PASSWORD)
        form = self.client.get(f"/settings/users/{second.pk}/").context["form"]
        self.assertIn("area__academy", form.fields)
        data = {"username": "sec2", "first_name": "Sara", "roles": ["secretary"], "is_active": "on",
                "area__academy": "hidden"}
        self.client.post(f"/settings/users/{second.pk}/", data)
        self.assertEqual(PersonAreaAccess.objects.get(user=second).level, "hidden")
        self.client.login(username="sec2", password=PASSWORD)
        self.assertEqual(self.client.get("/academy/candidates/").status_code, 403)
        self.assertNotIn("overdue_installments", self.client.get("/").context)
        self.client.login(username="sec1", password=PASSWORD)
        self.assertEqual(self.client.get("/academy/candidates/").status_code, 200)
        # A person rule opens again what the role matrix closed, but never more than the role allows.
        AreaAccess.objects.create(role="secretary", area="academy", level="hidden")
        PersonAreaAccess.objects.create(user=first, area="academy", level="full")
        self.assertEqual(self.client.get("/academy/candidates/").status_code, 200)
        PersonAreaAccess.objects.create(user=first, area="surgery", level="full")
        self.assertEqual(self.client.get("/surgery/").status_code, 403)


class ApprovalTests(TestCase):
    def setUp(self):
        from apps.core.testing import make_patient

        self.branch = setup_clinic()
        self.secretary = make_user("sec", "secretary")
        self.head = make_user("head", "head_cia")
        self.patient = make_patient(self.branch, phone="01001234567")

    def patient_data(self, **changes):
        from apps.patients.models import ReferralSource

        data = {"full_name": self.patient.full_name, "id_type": "nid", "national_id": self.patient.national_id,
                "phone_primary": self.patient.phone_primary, "preferred_phone": "primary", "missing_teeth": "unknown",
                "referral_source": ReferralSource.objects.filter(asks_for_patient=False).first().pk, "status": "active",
                # required since round 13
                "phone_secondary": "01501234567", "marital_status": "single", "occupation": "طالب", "city": "شبرا"}
        data.update(changes)
        return data

    def test_reception_edits_wait_for_the_head_of_cia(self):
        from apps.core.models import ChangeRequest
        from apps.patients.models import MedicalCondition

        diabetes = MedicalCondition.objects.first()
        self.client.login(username="sec", password=PASSWORD)
        self.client.post(f"/patients/{self.patient.pk}/edit/",
                         self.patient_data(phone_primary="01101234567", medical_conditions=[diabetes.pk]))
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.phone_primary, "01001234567")  # nothing changes yet
        change = ChangeRequest.objects.get()
        self.assertLessEqual({"phone_primary", "medical_conditions"}, {c["field"] for c in change.changes})
        self.assertTrue(Notification.objects.filter(recipient=self.head).exists())
        self.assertContains(self.client.get(f"/patients/{self.patient.pk}/"), "01101234567")  # shown as waiting
        self.assertEqual(self.client.get("/approvals/").status_code, 403)

        self.client.login(username="head", password=PASSWORD)
        self.assertEqual(self.client.get("/").context["pending_approvals"], 1)
        self.client.post(f"/approvals/{change.pk}/", {"action": "approve", "note": "ok 100%"})
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.phone_primary, "01101234567")
        self.assertEqual(list(self.patient.medical_conditions.all()), [diabetes])
        self.assertTrue(Notification.objects.filter(recipient=self.secretary).exists())
        # The head of CIA edits directly.
        self.client.post(f"/patients/{self.patient.pk}/edit/", self.patient_data(phone_primary="01201234567",
                                                                              medical_conditions=[diabetes.pk]))
        self.patient.refresh_from_db()
        self.assertEqual((self.patient.phone_primary, ChangeRequest.objects.count()), ("01201234567", 1))

    def test_forgotten_visit_times_are_corrected_after_approval(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.core.models import ChangeRequest
        from apps.scheduling.models import Appointment

        # Yesterday at 10:00, so the visit never crosses midnight whatever time the tests run.
        start = timezone.localtime().replace(hour=10, minute=0, second=0, microsecond=0) - timedelta(days=1)
        appointment = Appointment.objects.create(branch=self.branch, patient=self.patient, scheduled_at=start)
        appointment.mark_arrived(start)
        appointment.save()
        local = timezone.localtime(start)
        times = {"arrived_at_0": local.strftime("%d/%m/%Y"), "arrived_at_1": local.strftime("%H:%M"),
                 "entered_room_at_0": local.strftime("%d/%m/%Y"),
                 "entered_room_at_1": (local + timedelta(minutes=20)).strftime("%H:%M"),
                 "left_at_0": local.strftime("%d/%m/%Y"), "left_at_1": (local + timedelta(minutes=80)).strftime("%H:%M"),
                 "reason": "forgot to press Left"}
        self.client.login(username="sec", password=PASSWORD)
        self.client.post(f"/schedule/appointments/{appointment.pk}/times/", times)
        appointment.refresh_from_db()
        self.assertIsNone(appointment.left_at)
        change = ChangeRequest.objects.get(kind="visit_times")
        self.client.login(username="head", password=PASSWORD)
        self.client.post(f"/approvals/{change.pk}/", {"action": "approve"})
        appointment.refresh_from_db()
        self.assertEqual((appointment.status, appointment.chair_minutes), ("completed", 60))
        bad = dict(times, left_at_1=local.strftime("%H:%M"))  # left before entering
        self.client.post(f"/schedule/appointments/{appointment.pk}/times/", bad)
        self.assertEqual(ChangeRequest.objects.count(), 1)

    def test_rejected_changes_do_nothing(self):
        from apps.core.models import ChangeRequest

        self.client.login(username="sec", password=PASSWORD)
        self.client.post(f"/patients/{self.patient.pk}/edit/", self.patient_data(full_name="اسم آخر جديد"))
        change = ChangeRequest.objects.get()
        self.client.login(username="head", password=PASSWORD)
        self.client.post(f"/approvals/{change.pk}/", {"action": "reject"})
        self.patient.refresh_from_db()
        change.refresh_from_db()
        self.assertEqual((change.status, self.patient.full_name == "اسم آخر"), ("rejected", False))


class ProblemReportTests(TestCase):
    def setUp(self):
        setup_clinic()
        self.owner = make_user("owner", "owner")
        self.secretary = make_user("sec", "secretary")

    def test_staff_report_a_problem_and_the_owner_answers(self):
        from apps.core.models import ProblemReport

        self.secretary.profile.read_only = True  # even read-only staff can report a problem
        self.secretary.profile.save()
        self.client.login(username="sec", password=PASSWORD)
        response = self.client.post("/problems/report/", {"description": "The print button does nothing",
                                                          "page": "/patients/1/"},
                                    headers={"X-Requested-With": "XMLHttpRequest"})
        self.assertTrue(response.json()["ok"])
        self.assertFalse(self.client.post("/problems/report/", {"description": ""},
                                          headers={"X-Requested-With": "XMLHttpRequest"}).json()["ok"])
        report = ProblemReport.objects.get()
        self.assertEqual((report.page, report.reported_by, report.kind), ("/patients/1/", self.secretary, "reported"))
        self.assertTrue(Notification.objects.filter(recipient=self.owner, url="/problems/").exists())
        self.assertEqual(self.client.get("/problems/").status_code, 403)  # only the owner and head of CIA read them
        self.client.login(username="owner", password=PASSWORD)
        self.assertContains(self.client.get("/problems/"), "The print button does nothing")
        self.client.post(f"/problems/{report.pk}/", {"status": "solved", "answer": "Fixed in the new version"})
        report.refresh_from_db()
        self.assertEqual((report.status, report.handled_by), ("solved", self.owner))
        self.assertTrue(Notification.objects.filter(recipient=self.secretary, message="Fixed in the new version").exists())
        export = self.client.get("/problems/export/")
        self.assertIn("The print button does nothing", export.content.decode("utf-8-sig"))

    def test_page_errors_are_recorded_once_and_counted(self):
        from django.http import Http404
        from django.test import RequestFactory

        from apps.core.middleware import ErrorRecorderMiddleware
        from apps.core.models import ProblemReport

        middleware = ErrorRecorderMiddleware(lambda request: None)
        request = RequestFactory().get("/patients/5/")
        request.user = self.secretary
        for _ in range(3):
            self.assertIsNone(middleware.process_exception(request, ValueError("bad value")))
        middleware.process_exception(request, Http404())  # a missing page is not a software problem
        report = ProblemReport.objects.get()
        self.assertEqual((report.kind, report.times, report.page), ("automatic", 3, "/patients/5/"))
        self.assertIn("ValueError: bad value", report.error)
        self.assertEqual(Notification.objects.filter(recipient=self.owner, level="danger").count(), 1)

    def test_pages_have_the_leave_warning_and_report_pop_ups(self):
        self.client.login(username="sec", password=PASSWORD)
        page = self.client.get("/")
        self.assertContains(page, 'id="leave-warning"')
        self.assertContains(page, 'id="report-problem"')


class BackupAndExportTests(TestCase):
    def setUp(self):
        import shutil
        import tempfile

        from django.test import override_settings

        self.folder = folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=f"{folder}/media", BACKUP_DIR=f"{folder}/backups",
                                     FILES_BACKUP_DIR=f"{folder}/other-disk/files")
        override.enable()
        self.addCleanup(override.disable)
        from apps.core.testing import make_dentist, make_patient

        self.branch = setup_clinic()
        self.owner = make_user("owner", "owner")
        make_user("head", "head_cia")
        make_user("sec", "secretary")
        make_dentist("dentist", kind="candidate")
        self.patient = make_patient(self.branch, name="مريض النسخة")

    def test_full_backup_has_data_excel_csv_and_files(self):
        import io
        import zipfile

        from django.core.files.base import ContentFile
        from openpyxl import load_workbook

        from apps.core.backup import create_backup
        from apps.patients.models import PatientDocument

        PatientDocument.objects.create(patient=self.patient, kind="other",
                                       file=ContentFile(b"%PDF-1.4", name="scan.pdf"))
        with zipfile.ZipFile(create_backup(with_files=True)) as bundle:
            self.assertTrue(any(n.startswith("media/") and n.endswith(".pdf") for n in bundle.namelist()))
        with zipfile.ZipFile(create_backup()) as bundle:  # the nightly ZIP: the data only, the photos are copied apart
            names = bundle.namelist()
            self.assertTrue({"database.json", "excel/all-data.xlsx", "README.txt", "csv/patients.patient.csv"} <= set(names))
            self.assertFalse(any(n.startswith("media/") for n in names))
            self.assertIn("other-disk", bundle.read("README.txt").decode())
            self.assertIn("مريض النسخة", bundle.read("csv/patients.patient.csv").decode("utf-8-sig"))
            self.assertNotIn("pbkdf2", bundle.read("csv/auth.user.csv").decode("utf-8-sig"))  # no passwords
            workbook = load_workbook(io.BytesIO(bundle.read("excel/all-data.xlsx")), read_only=True)
            self.assertIn("Patients", workbook.sheetnames)
            rows = list(workbook["Patients"].iter_rows(values_only=True))
            self.assertIn("full name (as on ID)", rows[0])
            self.assertIn("مريض النسخة", rows[1])

    def test_restore_puts_the_backup_back(self):
        from apps.core.backup import create_backup, list_backups, restore_backup
        from apps.core.testing import make_patient
        from apps.patients.models import Patient

        backup = create_backup()
        make_patient(self.branch, name="بعد النسخة", nid="29001011234568", phone="01001234568")
        restore_backup(backup)
        self.assertEqual(list(Patient.objects.values_list("full_name", flat=True)), ["مريض النسخة"])
        self.assertTrue(self.client.login(username="owner", password=PASSWORD))  # logins come back too
        self.assertEqual(len(list_backups()), 2)  # the state before restoring was saved first

    def document(self, name, content=b"%PDF-1.4"):
        from django.core.files.base import ContentFile

        from apps.patients.models import PatientDocument

        return PatientDocument.objects.create(patient=self.patient, kind="other", file=ContentFile(content, name=name))

    def test_the_nightly_backup_copies_only_new_photos_and_never_deletes(self):
        import os

        from django.core.management import call_command

        from apps.core.models import BackupRun

        first = self.document("first.pdf")
        os.makedirs(f"{self.folder}/media/previews/small")
        open(f"{self.folder}/media/previews/small/x.jpg.jpg", "wb").close()  # previews are made again, not copied
        call_command("backup", stdout=io.StringIO())
        copy = f"{self.folder}/other-disk/files"
        self.assertTrue(os.path.exists(os.path.join(copy, first.file.name)))
        self.assertFalse(os.path.exists(f"{copy}/previews"))
        run = BackupRun.objects.filter(kind="files").get()
        self.assertEqual((run.ok, run.files_copied), (True, 1))
        self.assertTrue(BackupRun.objects.get(kind="database").ok)
        second = self.document("second.pdf")
        call_command("backup", stdout=io.StringIO())
        self.assertEqual(BackupRun.objects.filter(kind="files").first().files_copied, 1)  # only the new one
        os.remove(first.file.path)  # deleted by mistake: still in the copy, and it can be put back
        call_command("backup", stdout=io.StringIO())
        self.assertTrue(os.path.exists(os.path.join(copy, first.file.name)))
        call_command("restore_files", stdout=io.StringIO())
        self.assertTrue(os.path.exists(first.file.path))
        self.assertTrue(os.path.exists(second.file.path))

    def test_the_owner_is_warned_when_the_backup_fails_or_is_old(self):
        from datetime import timedelta
        from unittest import mock

        from django.core.management import call_command
        from django.utils import timezone

        from apps.core.models import BackupRun, Notification

        self.client.login(username="owner", password=PASSWORD)
        self.assertContains(self.client.get("/"), "Check the backup")  # never done yet
        call_command("backup", stdout=io.StringIO())
        home = self.client.get("/")
        self.assertNotContains(home, "Check the backup")
        self.assertContains(home, "Backup OK")
        with mock.patch("apps.core.backup.copy_new_files", side_effect=OSError("No space left on device")):
            with self.assertRaises(OSError):
                call_command("backup", stdout=io.StringIO())
        self.assertTrue(Notification.objects.filter(recipient=self.owner, level="danger").exists())
        self.assertContains(self.client.get("/"), "the last try failed")
        self.assertContains(self.client.get("/settings/backup/"), "No space left on device")
        call_command("backup", stdout=io.StringIO())
        BackupRun.objects.update(started_at=timezone.now() - timedelta(days=3))  # the nightly task stopped
        self.assertContains(self.client.get("/"), "Check the backup")
        self.client.login(username="head", password=PASSWORD)
        self.assertNotContains(self.client.get("/"), "backup")

    def test_backup_page_is_for_the_owner(self):
        self.client.login(username="head", password=PASSWORD)
        self.assertEqual(self.client.get("/settings/backup/").status_code, 403)
        self.client.login(username="owner", password=PASSWORD)
        self.assertEqual(self.client.get("/settings/backup/").status_code, 200)
        self.client.post("/settings/backup/")
        page = self.client.get("/settings/backup/")
        name = page.context["backups"][0]["name"]
        self.assertEqual(self.client.get(f"/settings/backup/{name}/").status_code, 200)
        self.assertEqual(self.client.get("/settings/backup/../../etc/").status_code, 404)
        excel = self.client.get("/settings/backup/excel/")
        self.assertTrue(b"".join(excel.streaming_content).startswith(b"PK"))

    def test_patient_file_as_word(self):
        self.client.login(username="dentist", password=PASSWORD)
        response = self.client.get(f"/patients/{self.patient.pk}/word/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(".docx", response["Content-Disposition"])
        self.client.login(username="sec", password=PASSWORD)
        self.assertEqual(self.client.get(f"/patients/{self.patient.pk}/word/").status_code, 403)


class LookAndHintsTests(TestCase):
    """The new look: the bar at the bottom on tablets, the page hints, the colour of each part."""

    def setUp(self):
        setup_clinic()
        self.secretary = make_user("sec", "secretary")
        self.dentist = make_user("dent", "dentist")
        make_user("store", "stock")
        make_user("boss", "owner")

    def labels(self, username, path="/"):
        self.client.login(username=username, password=PASSWORD)
        return [(str(item["label"]), item["url"], item["active"]) for item in self.client.get(path).context["bottom_nav"]]

    def test_bottom_bar_holds_each_persons_main_places(self):
        def urls(username, path="/"):
            return [url for _label, url, _active in self.labels(username, path)]

        self.assertEqual(urls("sec"), ["/", "/schedule/today/", "/patients/", "/schedule/appointments/new/"])
        self.assertEqual(urls("dent"), ["/", "/schedule/appointments/", "/patients/?mine=on", "/clinical/steps/"])
        self.assertEqual(urls("store"), ["/", "/stock/", "/stock/take-out/", "/purchases/"])
        marked = [url for _label, url, active in self.labels("store", "/stock/take-out/") if active]
        self.assertEqual(marked, ["/stock/take-out/"])
        self.assertEqual(urls("boss"), ["/", "/schedule/today/", "/patients/", "/dashboard/"])
        # The place of the page shown is marked, the longest address first; "Home" only on the home page.
        marked = [url for _label, url, active in self.labels("sec", "/schedule/appointments/new/") if active]
        self.assertEqual(marked, ["/schedule/appointments/new/"])
        marked = [url for _label, url, active in self.labels("sec", "/schedule/day/") if active]
        self.assertEqual(marked, ["/schedule/today/"])
        marked = [url for _label, url, active in self.labels("sec") if active]
        self.assertEqual(marked, ["/"])
        page = self.client.get("/").content.decode()
        self.assertIn('class="bottom-bar', page)
        self.assertIn('data-bs-target="#mainNav"', page)  # "Menu" opens the side menu

    def test_bottom_bar_follows_closed_parts(self):
        from apps.core.models import AreaAccess, PersonAreaAccess

        PersonAreaAccess.objects.create(user=self.secretary, area="patients", level=AreaAccess.Level.HIDDEN)
        urls = [url for _label, url, _active in self.labels("sec")]
        self.assertNotIn("/patients/", urls)

    def test_each_part_of_the_system_has_its_colour(self):
        self.client.login(username="sec", password=PASSWORD)
        self.assertIn('class="sec-patients', self.client.get("/patients/").content.decode())
        self.assertIn('class="sec-scheduling', self.client.get("/schedule/today/").content.decode())
        self.assertIn('class="sec-core', self.client.get("/").content.decode())

    def test_hints_by_page_and_role_and_switched_off_per_person(self):
        from apps.core.hints import HINTS

        self.client.login(username="sec", password=PASSWORD)
        with translation.override("en"):
            hint = self.client.get("/").context["page_hint"]
            self.assertEqual(hint["key"], "core:dashboard")
            self.assertEqual(hint["text"], HINTS["core:dashboard"]["front_desk"])
        self.assertContains(self.client.get("/patients/"), 'data-hint-key="patients:list"')
        self.client.login(username="dent", password=PASSWORD)
        self.assertEqual(self.client.get("/").context["page_hint"]["text"], HINTS["core:dashboard"]["dentist"])
        # Switching hints off is kept on the person's profile; switching them on brings back the closed ones.
        self.client.post("/hints/", {"next": "/patients/"})
        self.assertIsNone(self.client.get("/patients/").context["page_hint"])
        self.assertFalse(self.dentist.profile.__class__.objects.get(user=self.dentist).show_hints)
        self.client.login(username="sec", password=PASSWORD)
        self.assertIsNotNone(self.client.get("/patients/").context["page_hint"])  # others keep theirs
        self.client.login(username="dent", password=PASSWORD)
        self.client.post("/hints/", {"next": "/"})
        page = self.client.get("/")
        self.assertTrue(page.context["hints_reset"])
        self.assertIn("data-hints-reset", page.content.decode())
        self.assertFalse(self.client.get("/").context["hints_reset"])  # only once
        # An address outside the system is not followed.
        self.assertEqual(self.client.post("/hints/", {"next": "https://example.com/"})["Location"], "/")

    def test_a_read_only_person_can_still_switch_hints(self):
        from apps.core.models import UserProfile

        UserProfile.objects.update_or_create(user=self.secretary, defaults={"read_only": True})
        self.client.login(username="sec", password=PASSWORD)
        self.assertEqual(self.client.post("/hints/").status_code, 302)
        self.assertFalse(UserProfile.objects.get(user=self.secretary).show_hints)

    def test_every_hint_is_for_a_real_page_and_is_in_arabic(self):
        from django.urls import get_resolver

        from apps.core.hints import HINTS

        names = set()

        def collect(resolver, prefix=""):
            for pattern in resolver.url_patterns:
                if hasattr(pattern, "url_patterns"):
                    collect(pattern, prefix + (pattern.namespace + ":" if pattern.namespace else ""))
                elif pattern.name:
                    names.add(prefix + pattern.name)

        collect(get_resolver())
        for key, hint in HINTS.items():
            self.assertIn(key, names)
            for text in (hint.values() if isinstance(hint, dict) else [hint]):
                with translation.override("ar"):
                    arabic = str(text)
                with translation.override("en"):
                    self.assertNotEqual(arabic, str(text), key)

    def test_home_greets_by_the_time_of_day(self):
        self.client.login(username="sec", password=PASSWORD)
        page = self.client.get("/")
        self.assertIn(page.context["greeting_icon"], ("bi-sunrise", "bi-sun", "bi-moon-stars"))
        self.assertIn(self.secretary.get_full_name() or "sec", page.context["greeting"])


class SpeedTests(TestCase):
    """With clinic-sized data a page must read the database a few times, not once per patient, visit or bill:
    a page that does would take seconds, then minutes, as the clinic grows. Each page has a budget of
    look-ups that does not depend on the number of patients."""

    PERIOD = "date_from=01/01/2020&date_to=31/12/2030"
    PAGES = [
        ("secretary", "/", 60),
        ("secretary", "/patients/", 40),
        ("secretary", "/patients/?q=محمد", 40),
        ("secretary", "/schedule/today/", 60),
        ("secretary", "/schedule/day/", 40),
        ("secretary", "/schedule/appointments/", 40),
        ("secretary", f"/billing/bills/?{PERIOD}", 40),
        ("secretary", f"/billing/payments/?{PERIOD}", 40),
        ("dentist", "/", 60),
        ("dentist", "/clinical/steps/", 40),
        ("owner", "/", 130),  # grows with the number of doctors at CIC, not of patients
        ("owner", f"/reports/visits/?{PERIOD}", 40),
        ("owner", f"/reports/dentists/?{PERIOD}", 60),
        ("owner", f"/reports/money/?{PERIOD}", 60),
        ("owner", f"/reports/balance/?{PERIOD}", 60),
        ("owner", f"/clinics/?place=CIC&{PERIOD}", 120),
        ("owner", f"/clinics/report/?place=CIC&{PERIOD}", 120),
        ("owner", "/surgery/finder/", 60),
        ("secretary", "/billing/day/", 40),
        ("owner", "/billing/month/", 40),
        ("secretary", "/schedule/whatsapp/", 60),
        ("owner", "/stock/", 40),
        ("owner", "/stock/categories/", 40),
        ("secretary", "/schedule/day/?by=doctor", 40),
        ("owner", "/specialists/", 40),
        ("owner", "/specialists/referrals/", 40),
        ("owner", "/clinics/prices/?place=CIC", 40),
        ("owner", "/dashboard/", 60),
        ("owner", f"/dashboard/?{PERIOD}", 60),
        ("owner", "/lab/", 60),
        ("owner", "/lab/cases/", 40),
        ("owner", "/lab/cases/?step=open", 40),
        ("owner", f"/lab/report/?{PERIOD}", 60),
        ("owner", "/lab/clients/", 40),
        ("owner", "/lab/whatsapp/", 40),
        ("owner", "/lab/blocks/", 40),
        ("dentist", "/patients/medical-follow-up/?mine=0", 40),
        ("secretary", "/patients/medical-follow-up/", 40),
        ("owner", "/settings/security/", 40),
        ("owner", "/settings/security/deleted/", 30),
        # Round 13
        ("owner", "/stock/prices/", 40),
        ("owner", "/purchases/returns/", 40),
        ("owner", "/clinical/restorative-finder/", 60),
        ("owner", "/chart/plans/restorative/", 60),
        ("secretary", "/complaints/", 40),
        ("secretary", "/billing/fawry/", 40),
        ("owner", "/billing/fawry/", 40),
        ("owner", "/settings/", 70),  # one count for each list and each place, not per patient
        ("owner", "/settings/users/?place=LAB", 40),
        ("owner", "/settings/access/", 30),
        ("owner", f"/time/?{PERIOD}", 30),
        ("owner", "/lab/day/", 40),
        ("owner", "/lab/day/month/", 30),
        # Round 15
        ("secretary", "/clinical/lab/", 40),
        ("secretary", "/clinical/lab/?part=planned", 40),
        ("secretary", "/schedule/whatsapp/many/", 30),
        ("secretary", "/schedule/whatsapp/many/new/", 40),
        ("secretary", "/complaints/new/", 40),
        ("owner", "/settings/backup/", 40),
    ]

    @classmethod
    def setUpTestData(cls):
        from decimal import Decimal

        from apps.clinics.models import FeeRule
        from apps.core.bigdata import fill
        from apps.core.models import Branch
        from apps.core.testing import make_dentist

        setup_clinic()
        cic = Branch.objects.get(code="CIC")
        make_user("owner", "owner")
        make_user("secretary", "secretary")
        doctors = [make_dentist("dentist", kind="training")] + [make_dentist(f"doc{n}", login=False) for n in range(5)]
        for doctor in doctors[:3]:
            FeeRule.objects.create(dentist=doctor, branch=cic, method=FeeRule.Method.PERCENT, value=Decimal("30"),
                                   starts_on=date(2020, 1, 1))
        FeeRule.objects.create(dentist=doctors[3], branch=cic, method=FeeRule.Method.PER_VISIT, value=Decimal("150"),
                               starts_on=date(2020, 1, 1))
        cls.added = fill(patients=1500, visits_per_patient=4, bills_per_patient=2, photos_per_patient=1)

    def setUp(self):
        from django.core.cache import cache

        cache.set("dashboard-alerts", True, 600)  # the visit-notes alerts have their own tests

    def test_pages_stay_quick_with_many_patients(self):
        import time

        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from apps.patients.models import Patient

        from apps.lab.models import LabCase

        self.assertEqual(self.added["patients"], 1500)
        self.assertEqual(self.added["lab cases"], 300)
        patient = Patient.objects.order_by("-pk").first()
        lab_case = LabCase.objects.exclude(step="delivered").order_by("-pk").first()
        pages = self.PAGES + [("secretary", f"/patients/{patient.pk}/", 60),
                              ("secretary", f"/billing/patient/{patient.pk}/", 60),
                              ("dentist", f"/chart/patient/{patient.pk}/photos/", 60),
                              ("dentist", f"/chart/patient/{patient.pk}/case-report/?per_page=4", 80),
                              ("owner", f"/lab/cases/{lab_case.pk}/", 40),
                              ("dentist", f"/patients/{patient.pk}/", 80)]
        for username, url, budget in pages:
            with self.subTest(user=username, page=url):
                self.client.login(username=username, password=PASSWORD)
                with CaptureQueriesContext(connection) as queries:
                    started = time.perf_counter()
                    response = self.client.get(url)
                    seconds = time.perf_counter() - started
                self.assertEqual(response.status_code, 200)
                self.assertLessEqual(len(queries), budget, f"{url} read the database {len(queries)} times")
                if os.environ.get("SHOW_QUERIES"):
                    print(f"{len(queries):4d} {seconds:5.2f}s {username} {url}")
                self.assertLess(seconds, 10, f"{url} took {seconds:.1f} s")  # generous: GitHub's machines are slow

    def test_bulk_balances_agree_with_each_patient_account(self):
        from apps.billing.models import Bill, account, balances, bill_totals, paid_by_charge
        from apps.patients.models import Patient

        some = list(Patient.objects.filter(charges__isnull=False).distinct().order_by("pk")[:40])
        paid, owe = paid_by_charge([p.pk for p in some]), balances()
        for patient in some:
            current = account(patient)
            self.assertEqual(owe[patient.pk], current["balance"])
            self.assertEqual(paid[patient.pk], {row["charge"].pk: row["paid"] for row in current["rows"]})
        bills = list(Bill.objects.filter(patient__in=some))
        together = bill_totals(bills)
        for bill in bills:
            alone = bill.totals()
            self.assertEqual({k: v for k, v in together[bill.pk].items() if k != "rows"},
                             {k: v for k, v in alone.items() if k != "rows"})

    def test_the_quick_doctor_totals_agree_with_the_statement(self):
        from apps.clinics.models import FeeRule
        from apps.clinics.shares import statement, totals
        from apps.core.models import Branch

        cic = Branch.objects.get(code="CIC")
        for rule in FeeRule.objects.filter(branch=cic).select_related("dentist"):
            full = statement(rule.dentist, cic, date(2020, 1, 1), date(2030, 12, 31))
            quick = totals(rule.dentist, cic, date(2020, 1, 1), date(2030, 12, 31))
            for key in ("billed", "collected", "share", "visit_count", "chair_minutes", "patient_count"):
                self.assertEqual(quick[key], full[key], key)
            self.assertGreater(full["share"], 0)


class SafetyTests(TestCase):
    """The slow-page log, the test copy and its banner."""

    def setUp(self):
        self.branch = setup_clinic()
        make_user("owner", "owner")
        self.client.login(username="owner", password=PASSWORD)

    def test_slow_pages_are_written_down(self):
        from django.test import override_settings

        with override_settings(SLOW_PAGE_SECONDS=0), self.assertLogs("clinic.slow", level="WARNING") as logs:
            self.client.get("/reports/")
        self.assertIn("GET /reports/", logs.output[0])
        self.assertIn("(owner)", logs.output[0])

    def test_a_test_copy_has_todays_data_and_shows_a_banner(self):
        import shutil
        import sqlite3
        import tempfile

        from django.core.management import call_command
        from django.test import override_settings

        from apps.core.testing import make_patient

        make_patient(self.branch, name="مريض النسخة التجريبية")
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        with override_settings(BACKUP_DIR=f"{folder}/backups", MEDIA_ROOT=f"{folder}/media"):
            call_command("make_test_copy", folder=f"{folder}/copy", stdout=io.StringIO())
        with sqlite3.connect(f"{folder}/copy/db.sqlite3") as copy:
            names = [row[0] for row in copy.execute("select full_name from patients_patient")]
        self.assertEqual(names, ["مريض النسخة التجريبية"])
        self.assertNotContains(self.client.get("/"), "TEST COPY")
        with override_settings(TEST_COPY=True):
            self.assertContains(self.client.get("/"), "TEST COPY")


class ForgottenPasswordTests(TestCase):
    """No e-mail on the clinic's network: the owner gives a temporary password, then the person chooses their own."""

    def setUp(self):
        setup_clinic()
        self.owner = make_user("owner", "owner")
        self.secretary = make_user("sec", "secretary")
        self.secretary.profile.phone = "01001234567"
        self.secretary.profile.save()

    def test_ask_give_and_choose_a_new_password(self):
        from apps.core.models import PasswordHelp

        self.assertContains(self.client.get("/login/"), "/password/forgot/")
        page = self.client.post("/password/forgot/", {"username": "SEC", "note": "at the reception"})
        self.assertTrue(page.context["sent"])
        asked = PasswordHelp.objects.get()
        self.assertEqual((asked.user, asked.status), (self.secretary, "new"))
        self.assertTrue(Notification.objects.filter(recipient=self.owner, url__contains="password-requests").exists())
        # An unknown username gets the same answer, and nobody is told.
        self.assertTrue(self.client.post("/password/forgot/", {"username": "nobody"}).context["sent"])
        self.assertEqual(Notification.objects.count(), 1)
        for _i in range(5):  # no more than three a day
            self.client.post("/password/forgot/", {"username": "sec"})
        self.assertEqual(PasswordHelp.objects.filter(username__iexact="sec").count(), 3)

        self.client.login(username="owner", password=PASSWORD)
        self.assertIn(asked, list(self.client.get("/settings/users/").context["password_requests"]))
        self.client.post(f"/settings/users/password/{asked.pk}/give/")
        page = self.client.get("/settings/users/")
        password = page.context["given_password"]["password"]
        self.assertContains(page, "wa.me/201001234567")
        self.assertFalse(page.context["password_requests"])
        self.assertEqual(PasswordHelp.objects.filter(status="done").count(), 3)
        self.client.logout()

        self.assertFalse(self.client.login(username="sec", password=PASSWORD))  # the old password stops
        self.assertTrue(self.client.login(username="sec", password=password))
        self.assertRedirects(self.client.get("/"), "/password/")  # must choose a new password first
        self.client.post("/password/", {"old_password": password, "new_password1": "Clinic-2026-new",
                                        "new_password2": "Clinic-2026-new"})
        self.secretary.profile.refresh_from_db()
        self.assertFalse(self.secretary.profile.must_change_password)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_only_the_owner_gives_passwords(self):
        from apps.core.models import PasswordHelp

        asked = PasswordHelp.objects.create(username="sec", user=self.secretary)
        make_user("head", "head_cia")
        self.client.login(username="head", password=PASSWORD)
        self.assertEqual(self.client.post(f"/settings/users/password/{asked.pk}/give/").status_code, 403)


class PlaceLogoTests(TestCase):
    """Round 10: CIC and the lab (GDIL) have their own logos: the login page, the top bar and the printed papers."""

    def test_the_logos_of_the_places(self):
        from apps.core.models import Branch

        setup_clinic()
        cic, lab, cia = (Branch.objects.get(code=code) for code in ("CIC", "LAB", "CIA"))
        self.assertTrue(cic.has_mark and lab.has_mark)
        self.assertFalse(cia.has_mark)  # CIA prints its own full logo
        self.assertIn("img/cic-logo.jpg", cic.mark_url)
        self.assertIn("img/gdil-logo.jpg", lab.mark_url)
        self.assertEqual((lab.name_en, lab.tagline), ("GDIL Dental Lab", "The art of dentistry"))
        page = self.client.get("/login/?place=CIC")
        self.assertContains(page, "img/cic-logo.jpg")
        self.assertContains(self.client.get("/login/"), "img/gdil-logo.jpg")  # the lab's tile


class SecurityTests(TestCase):
    """Round 11: wrong passwords close a login, a PC left open logs out, only the clinic's network gets in, the
    security log, files checked by what they hold, deleted records kept, and the owner's Security page."""

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.branch = setup_clinic()
        self.owner = make_user("owner", "owner")
        self.secretary = make_user("sec", "secretary")

    def assertLocked(self, page):
        self.assertEqual([error.code for error in page.context["form"].non_field_errors().as_data()], ["locked"])
        self.assertContains(page, "15")  # how many minutes to wait, in the page's language

    def wrong(self, username="sec", times=1, **extra):
        for _i in range(times):
            page = self.client.post("/login/", {"username": username, "password": "wrong-password"}, **extra)
        return page

    def test_wrong_passwords_close_the_login_and_the_owner_opens_it(self):
        from apps.core.models import SecurityEvent

        self.wrong(times=4)
        self.assertEqual(SecurityEvent.objects.filter(kind="login_failed", username="sec").count(), 4)
        self.assertFalse(SecurityEvent.objects.filter(kind="locked").exists())
        page = self.wrong()  # the fifth
        self.assertTrue(SecurityEvent.objects.filter(kind="locked", username="sec").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.owner, url="/settings/security/",
                                                    level="danger").exists())
        # Even the right password is refused now, with how long to wait; the tries do not count again.
        page = self.client.post("/login/", {"username": "SEC", "password": PASSWORD})
        self.assertLocked(page)
        self.assertFalse(page.wsgi_request.user.is_authenticated)
        self.wrong(times=3)
        self.assertEqual(SecurityEvent.objects.filter(kind="login_failed", username="sec").count(), 5)
        self.assertEqual(SecurityEvent.objects.filter(kind="locked").count(), 1)
        # The admin pages are closed too.
        page = self.client.post("/admin/login/", {"username": "sec", "password": PASSWORD})
        self.assertFalse(page.wsgi_request.user.is_authenticated)

        self.client.login(username="owner", password=PASSWORD)
        page = self.client.get("/settings/security/")
        self.assertEqual([row["username"] for row in page.context["locked"]], ["sec"])
        self.assertEqual(page.context["failed_today"], 5)
        self.client.post("/settings/security/unlock/", {"username": "sec"})
        self.assertFalse(self.client.get("/settings/security/").context["locked"])
        self.client.logout()
        page = self.client.post("/login/", {"username": "sec", "password": PASSWORD})
        self.assertEqual(page.status_code, 302)
        self.assertTrue(SecurityEvent.objects.filter(kind="login", username="sec").exists())

    def test_the_lock_ends_by_itself(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.core.models import SecurityEvent
        from apps.core.security import LOCK_MINUTES, minutes_locked

        self.wrong(times=5)
        self.assertGreater(minutes_locked("sec"), 0)
        SecurityEvent.objects.update(at=timezone.now() - timedelta(minutes=LOCK_MINUTES + 1))
        self.assertEqual(minutes_locked("sec"), 0)
        self.assertEqual(self.client.post("/login/", {"username": "sec", "password": PASSWORD}).status_code, 302)

    def test_a_device_trying_many_usernames_is_closed(self):
        from django.test import override_settings

        from apps.core import security
        from apps.core.models import SecurityEvent

        with override_settings(ALLOWED_NETWORKS=["*"]):
            security.IP_LOCK_AFTER, old = 6, security.IP_LOCK_AFTER
            self.addCleanup(setattr, security, "IP_LOCK_AFTER", old)
            for name in ("a", "b", "c", "d", "e", "f"):
                self.wrong(name, REMOTE_ADDR="192.168.1.50")
            self.assertTrue(SecurityEvent.objects.filter(kind="locked", username="", ip="192.168.1.50").exists())
            page = self.client.post("/login/", {"username": "owner", "password": PASSWORD},
                                    REMOTE_ADDR="192.168.1.50")
            self.assertLocked(page)
            # Another device is not closed.
            page = self.client.post("/login/", {"username": "owner", "password": PASSWORD},
                                    REMOTE_ADDR="192.168.1.51")
            self.assertEqual(page.status_code, 302)
            self.client.post("/settings/security/unlock/", {"ip": "192.168.1.50"}, REMOTE_ADDR="192.168.1.51")
            self.client.logout()
            page = self.client.post("/login/", {"username": "owner", "password": PASSWORD},
                                    REMOTE_ADDR="192.168.1.50")
            self.assertEqual(page.status_code, 302)

    def test_a_pc_left_open_logs_out_by_itself(self):
        import time

        from apps.core.models import ClinicSettings, SecurityEvent

        options = ClinicSettings.get()
        options.idle_logout_minutes = 30
        options.save()
        self.client.login(username="sec", password=PASSWORD)
        self.assertEqual(self.client.get("/").status_code, 200)
        session = self.client.session
        session["seen"] = int(time.time()) - 31 * 60
        session.save()
        self.assertEqual(self.client.get("/notifications/poll/").status_code, 401)  # the bell: a short answer
        self.assertTrue(SecurityEvent.objects.filter(kind="idle_logout", username="sec").exists())
        self.client.login(username="sec", password=PASSWORD)
        session = self.client.session
        session["seen"] = int(time.time()) - 31 * 60
        session.save()
        page = self.client.get("/patients/")
        self.assertRedirects(page, "/login/?next=%2Fpatients%2F", fetch_redirect_response=False)
        # The bell's own checks do not keep a PC awake; a page used does.
        self.client.login(username="sec", password=PASSWORD)
        session = self.client.session
        session["seen"] = int(time.time()) - 20 * 60
        session.save()
        self.client.get("/notifications/poll/")
        self.assertEqual(self.client.session["seen"], session["seen"])
        self.client.get("/")
        self.assertGreater(self.client.session["seen"], session["seen"])
        options.idle_logout_minutes = 0  # never
        options.save()
        session = self.client.session
        session["seen"] = int(time.time()) - 600 * 60
        session.save()
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_only_the_clinics_network_gets_in(self):
        from django.test import override_settings

        from apps.core.models import SecurityEvent

        with override_settings(ALLOWED_NETWORKS=["127.0.0.0/8", "192.168.0.0/16"], TRUSTED_PROXIES=["172.18.0.0/16"]):
            page = self.client.get("/login/", REMOTE_ADDR="8.8.8.8")
            self.assertEqual(page.status_code, 403)
            self.assertContains(page, "clinic's network", status_code=403)
            self.client.get("/login/", REMOTE_ADDR="8.8.8.8")
            self.assertEqual(SecurityEvent.objects.filter(kind="outside", ip="8.8.8.8").count(), 1)  # once an hour
            self.assertEqual(self.client.get("/login/", REMOTE_ADDR="192.168.1.9").status_code, 200)
            # Behind our nginx the device's address is the one nginx saw; a device cannot send it itself.
            self.assertEqual(self.client.get("/login/", REMOTE_ADDR="172.18.0.2", HTTP_X_REAL_IP="8.8.4.4").status_code,
                             403)
            self.assertEqual(self.client.get("/login/", REMOTE_ADDR="172.18.0.2",
                                             HTTP_X_REAL_IP="192.168.1.9").status_code, 200)
            self.assertEqual(self.client.get("/login/", REMOTE_ADDR="8.8.8.8",
                                             HTTP_X_REAL_IP="192.168.1.9").status_code, 403)
            # Meta's WhatsApp messages to the lab still arrive.
            hook = self.client.get("/lab/whatsapp/hook/", REMOTE_ADDR="8.8.8.8")
            self.assertNotContains(hook, "clinic's network", status_code=hook.status_code)

    def test_headers_and_files_that_cannot_run(self):
        import shutil
        import tempfile

        from django.test import override_settings

        page = self.client.get("/login/")
        self.assertIn("frame-ancestors 'self'", page["Content-Security-Policy"])
        self.assertIn("object-src 'none'", page["Content-Security-Policy"])
        self.assertIn("geolocation=()", page["Permissions-Policy"])
        self.assertEqual(page["X-Content-Type-Options"], "nosniff")
        self.client.login(username="owner", password=PASSWORD)
        self.assertEqual(self.client.get("/")["Cache-Control"], "private")
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        with override_settings(MEDIA_ROOT=folder):
            os.makedirs(f"{folder}/problems")
            with open(f"{folder}/problems/page.html", "w") as handle:
                handle.write("<script>alert(1)</script>")
            with open(f"{folder}/problems/scan.jpg", "wb") as handle:
                handle.write(b"\xff\xd8\xff photo")
            page = self.client.get("/media/problems/page.html")
            self.assertEqual(page["Content-Type"], "application/octet-stream")
            self.assertTrue(page["Content-Disposition"].startswith("attachment"))
            self.assertIn("sandbox", page["Content-Security-Policy"])
            page = self.client.get("/media/problems/scan.jpg")
            self.assertEqual(page["Content-Type"], "image/jpeg")
            self.assertTrue(page["Content-Disposition"].startswith("inline"))
            self.assertIn("sandbox", page["Content-Security-Policy"])
            page.close()

    def test_uploads_are_checked_by_what_they_hold(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.core.forms import validate_upload
        from apps.core.uploads import is_blocked, looks_right

        self.assertTrue(looks_right(SimpleUploadedFile("a.jpg", b"\xff\xd8\xff\xe0 photo")))
        self.assertTrue(looks_right(SimpleUploadedFile("a.PNG", b"\x89PNG\r\n\x1a\n...")))
        self.assertTrue(looks_right(SimpleUploadedFile("a.pdf", b"%PDF-1.7 ...")))
        self.assertFalse(looks_right(SimpleUploadedFile("a.jpg", b"<html><script>")))
        self.assertFalse(looks_right(SimpleUploadedFile("a.pdf", b"MZ\x90\x00 program")))
        self.assertTrue(is_blocked(SimpleUploadedFile("scan.stl", b"MZ\x90\x00 program")))
        self.assertTrue(is_blocked(SimpleUploadedFile("page.html", b"<html>")))
        self.assertFalse(is_blocked(SimpleUploadedFile("scan.stl", b"solid scan")))
        with self.assertRaises(ValidationError):
            validate_upload(SimpleUploadedFile("photo.jpg", b"<svg onload=alert(1)>", "image/jpeg"))
        upload = SimpleUploadedFile("photo.jpg", b"\xff\xd8\xff\xe0 photo", "image/jpeg")
        self.assertIs(validate_upload(upload), upload)
        self.assertEqual(upload.read(4), b"\xff\xd8\xff\xe0")  # the check leaves the file at its start

    def test_deleted_records_are_kept_with_who_deleted_them(self):
        import shutil
        import tempfile

        from django.core.files.base import ContentFile
        from django.test import override_settings

        from apps.core.models import DeletedRecord
        from apps.core.testing import make_patient
        from apps.patients.models import PatientDocument

        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        with override_settings(MEDIA_ROOT=folder):
            patient = make_patient(self.branch)
            document = PatientDocument.objects.create(patient=patient, kind="other", notes="Old referral letter",
                                                      file=ContentFile(b"%PDF-1.4", name="letter.pdf"))
            self.client.login(username="owner", password=PASSWORD)
            self.client.post(f"/patients/{patient.pk}/documents/{document.pk}/delete/")
        self.assertFalse(PatientDocument.objects.exists())
        kept = DeletedRecord.objects.get()
        self.assertEqual((kept.object_id, kept.deleted_by, kept.page),
                         (str(document.pk), self.owner, f"/patients/{patient.pk}/documents/{document.pk}/delete/"))
        self.assertEqual(kept.data["notes"], "Old referral letter")
        self.assertEqual(kept.data["patient"], patient.pk)
        page = self.client.get("/settings/security/deleted/?q=تجربة")  # the patient's name
        self.assertEqual(list(page.context["page_obj"]), [kept])
        page = self.client.get(f"/settings/security/deleted/{kept.pk}/")
        self.assertContains(page, "Old referral letter")
        self.assertIn(("Patient", str(patient)), page.context["fields"])  # in plain words, not a number
        # The log itself and the notifications are not kept twice.
        Notification.objects.all().delete()
        self.assertEqual(DeletedRecord.objects.count(), 1)

    def test_files_taken_out_are_written_in_the_log(self):
        from apps.core.models import SecurityEvent
        from apps.core.testing import make_patient

        patient = make_patient(self.branch, name="مريض الملف")
        self.client.login(username="owner", password=PASSWORD)
        page = self.client.get(f"/patients/{patient.pk}/excel/")
        self.assertEqual(page.status_code, 200)
        event = SecurityEvent.objects.get(kind="export")
        self.assertEqual(event.user, self.owner)
        self.assertIn("مريض الملف", event.details)
        self.assertEqual(self.client.get("/settings/security/?kind=export").context["page_obj"][0], event)

    def test_easy_passwords_are_noted_and_may_be_forced_to_change(self):
        from apps.core.models import ClinicSettings

        self.secretary.set_password("demo12345")
        self.secretary.save()
        self.client.post("/login/", {"username": "sec", "password": "demo12345"})
        self.secretary.profile.refresh_from_db()
        self.assertTrue(self.secretary.profile.weak_password)
        self.assertContains(self.client.get("/"), "/password/")
        self.assertFalse(self.secretary.profile.must_change_password)
        self.client.logout()
        options = ClinicSettings.get()
        options.force_strong_passwords = True
        options.save()
        self.client.post("/login/", {"username": "sec", "password": "demo12345"})
        self.assertRedirects(self.client.get("/"), "/password/")
        self.client.post("/password/", {"old_password": "demo12345", "new_password1": "Reception-2026-strong",
                                        "new_password2": "Reception-2026-strong"})
        self.secretary.profile.refresh_from_db()
        self.assertFalse(self.secretary.profile.weak_password)
        self.assertFalse(self.secretary.profile.must_change_password)
        self.client.login(username="owner", password=PASSWORD)
        checks = {check["title"]: check["ok"] for check in self.client.get("/settings/security/").context["checks"]}
        self.assertTrue(checks["Nobody logs in with an easy password"])

    def test_the_security_page_is_the_owners(self):
        from apps.core.models import SecurityEvent

        make_user("head", "head_cia")
        head, other = self.client_class(), self.client_class()
        head.login(username="head", password=PASSWORD)
        other.login(username="sec", password=PASSWORD)
        for client in (head, other):
            self.assertEqual(client.get("/settings/security/").status_code, 403)
            self.assertEqual(client.get("/settings/security/deleted/").status_code, 403)
        self.assertTrue(SecurityEvent.objects.filter(kind="denied", username="sec").exists())
        self.client.login(username="owner", password=PASSWORD)
        page = self.client.get("/settings/security/")
        self.assertEqual(sorted(row["user"].username for row in page.context["sessions"]), ["head", "owner", "sec"])
        self.client.post("/settings/security/logout/", {"user": self.secretary.pk})
        self.assertEqual(other.get("/").status_code, 302)  # logged out on that device
        self.assertTrue(SecurityEvent.objects.filter(kind="forced_logout", username="sec").exists())
        self.client.post("/settings/security/logout/")
        self.assertEqual([row["user"].username for row in self.client.get("/settings/security/").context["sessions"]],
                         ["owner"])

    def test_every_page_asks_for_a_login(self):
        from django.urls import URLPattern, URLResolver, get_resolver

        public = set()

        def walk(patterns, prefix=""):
            for entry in patterns:
                if isinstance(entry, URLResolver):
                    walk(entry.url_patterns, prefix + str(entry.pattern))
                elif isinstance(entry, URLPattern) and getattr(entry.callback, "login_required", True) is False:
                    public.add(prefix + str(entry.pattern))

        walk(get_resolver().url_patterns)
        self.assertEqual({p for p in public if not p.startswith("admin/")},
                         {"login/", "password/forgot/", "i18n/setlang/", "lab/whatsapp/hook/", "place/<str:code>/logo/"})
        for url in ("/", "/patients/", "/settings/security/", "/billing/bills/", "/lab/", "/reports/money/"):
            self.assertRedirects(self.client.get(url), f"/login/?next={url.replace('/', '%2F')}",
                                 fetch_redirect_response=False)

    def test_saved_forms_leave_a_mark_for_the_drafts(self):
        self.client.login(username="owner", password=PASSWORD)
        page = self.client.post("/password/", {"old_password": "wrong"})  # an error: the typed data is not saved
        self.assertEqual(page.status_code, 200)
        self.assertNotIn("saved", page.cookies)
        page = self.client.post("/notifications/read-all/")
        self.assertEqual(page.status_code, 302)
        self.assertIn("saved", page.cookies)
        self.assertEqual(page.cookies["saved"]["max-age"], 120)

    def test_pages_are_sent_compressed_but_files_are_not(self):
        self.client.login(username="owner", password=PASSWORD)
        page = self.client.get("/", HTTP_ACCEPT_ENCODING="gzip")
        self.assertEqual(page["Content-Encoding"], "gzip")
        page = self.client.get(f"/patients/{self.make_patient().pk}/excel/", HTTP_ACCEPT_ENCODING="gzip")
        self.assertNotIn("Content-Encoding", page)

    def make_patient(self):
        from apps.core.testing import make_patient

        return make_patient(self.branch)

    def test_backups_are_checked_and_copied_to_a_second_disk(self):
        import shutil
        import tempfile
        import zipfile
        from pathlib import Path

        from django.core.management import call_command
        from django.test import override_settings

        from apps.core.backup import create_backup, verify_backup
        from apps.core.models import BackupRun

        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        with override_settings(MEDIA_ROOT=f"{folder}/media", BACKUP_DIR=f"{folder}/backups",
                               BACKUP_COPY_DIR=f"{folder}/second-disk"):
            path = create_backup()
            run = BackupRun.objects.get(kind="database")
            self.assertTrue(run.verified)
            self.assertGreater(run.records, 10)
            self.assertEqual(run.copy_where, str(Path(folder) / "second-disk" / path.name))
            self.assertEqual(Path(run.copy_where).read_bytes(), path.read_bytes())
            # A damaged backup is found.
            broken = Path(folder) / "broken.zip"
            with zipfile.ZipFile(path) as source, zipfile.ZipFile(broken, "w") as target:
                target.writestr("database.json", source.read("database.json")[:-20])
            with self.assertRaises(ValueError):
                verify_backup(broken)
            output = io.StringIO()
            self.client.login(username="owner", password=PASSWORD)
            checks = {c["title"]: c["ok"] for c in self.client.get("/settings/security/").context["checks"]}
            self.assertTrue(checks["The last backup was opened again and checked"])
            self.assertTrue(checks["A second copy of each backup is kept on another disk"])
            call_command("security_check", stdout=output)
            self.assertIn("OK   The last backup was opened again and checked", output.getvalue())
        with override_settings(MEDIA_ROOT=f"{folder}/media", BACKUP_DIR=f"{folder}/backups",
                               BACKUP_COPY_DIR=f"{folder}/backups"):
            create_backup()  # the "second copy" in the same folder: refused, the owner is told
            run = BackupRun.objects.filter(kind="database").first()
            self.assertTrue(run.ok and run.copy_error)
            self.assertTrue(Notification.objects.filter(recipient=self.owner, url="/settings/backup/").exists())

    def test_old_log_lines_are_cleaned_after_a_year(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.core.models import SecurityEvent
        from apps.core.security import clean_old_records

        SecurityEvent.objects.create(kind="login", username="old", at=timezone.now() - timedelta(days=400))
        SecurityEvent.objects.create(kind="login", username="new")
        self.assertEqual(clean_old_records(), 1)
        self.assertEqual(list(SecurityEvent.objects.values_list("username", flat=True)), ["new"])


class InterfaceTests(TestCase):
    """Round 12: the side rail and the new home page."""

    def setUp(self):
        setup_clinic()

    def home(self, username, role):
        make_user(username, role)
        self.client.login(username=username, password=PASSWORD)
        return self.client.get("/").content.decode()

    def test_reception_home_has_the_welcome_band_with_the_search(self):
        page = self.home("sec", "secretary")
        self.assertIn('class="home-hero"', page)
        self.assertIn("hero-search", page)
        self.assertEqual(page.count('name="q"'), 2)  # the rail's search and the big one, no third copy
        self.assertIn('class="quick-actions', page)

    def test_dentist_home_has_the_band_without_the_reception_search(self):
        page = self.home("dentist", "dentist")
        self.assertIn('class="home-hero"', page)
        self.assertNotIn("hero-search", page)
        self.assertNotIn('class="quick-actions', page)

    def test_menu_keeps_the_side_rail_hooks(self):
        page = self.home("owner", "owner")
        self.assertIn("app-navbar", page)
        self.assertIn('class="navbar-nav me-auto"', page)
        self.assertIn('class="navbar-nav user-menu"', page)

    def test_rail_switch_is_on_every_page(self):
        page = self.home("owner2", "owner")
        self.assertIn("data-rail-toggle", page)
        self.assertIn('localStorage.getItem("rail")', page)

    def test_patient_file_opens_with_the_identity_card(self):
        from apps.core.testing import make_patient

        branch = Branch.objects.get(code="CIA")
        patient = make_patient(branch, birth_date=date(1990, 5, 1))
        make_user("own", "owner")
        self.client.login(username="own", password=PASSWORD)
        page = self.client.get(f"/patients/{patient.pk}/").content.decode()
        self.assertIn("patient-header", page)
        self.assertIn("patient-avatar", page)
        self.assertIn('class="patient-facts"', page)

    def test_planner_arrows_follow_the_language(self):
        make_user("own", "owner")
        self.client.login(username="own", password=PASSWORD)
        page = self.client.get("/schedule/day/").content.decode()
        self.assertIn("title=\"Previous day\"><i class=\"bi bi-chevron-left\"></i>", page)
        self.assertIn("title=\"Next day\"><i class=\"bi bi-chevron-right\"></i>", page)


class Round13CoreTests(TestCase):
    """WhatsApp allowed after a form, the signature pad, the four places on the owner's home page and a video
    with a problem report."""

    def setUp(self):
        self.branch = setup_clinic()

    def test_whatsapp_and_the_id_reader_are_allowed_by_the_security_header(self):
        from apps.core.security import CSP

        make_user("sec", "secretary")
        self.client.login(username="sec", password=PASSWORD)
        header = self.client.get("/").headers["Content-Security-Policy"]
        self.assertEqual(header, CSP)
        form_action = next(part for part in CSP.split(";") if part.strip().startswith("form-action"))
        for address in ("'self'", "https://wa.me", "https://api.whatsapp.com", "https://web.whatsapp.com"):
            self.assertIn(address, form_action)
        self.assertIn("'wasm-unsafe-eval'", CSP)
        self.assertNotIn("'unsafe-eval'", CSP)

    def test_my_signature_is_drawn_once_and_checked(self):
        import base64

        from apps.core.models import UserProfile
        from apps.core.signatures import clean_signature

        user = make_user("sec", "secretary")
        self.client.login(username="sec", password=PASSWORD)
        self.assertEqual(self.client.get("/signature/").status_code, 200)
        png = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 40).decode()
        self.client.post("/signature/?next=/patients/", {"signature": png})
        self.assertEqual(UserProfile.objects.get(user=user).signature, png)
        for bad in ("", "data:image/svg+xml;base64,PHN2Zz4=", "data:image/png;base64," +
                    base64.b64encode(b"<script>").decode(), "javascript:alert(1)"):
            with self.assertRaises(ValidationError):
                clean_signature(bad)
        response = self.client.post("/signature/?next=https://evil.example/", {"clear": "1"})
        self.assertEqual(response["Location"], "/")  # never sent to another site
        self.assertEqual(UserProfile.objects.get(user=user).signature, "")

    def test_owner_sees_the_four_places_whatever_place_is_chosen(self):
        from apps.core.models import Branch

        make_user("owner", "owner")
        self.client.login(username="owner", password=PASSWORD)
        self.client.post("/place/", {"place": "PVT", "next": "/"})
        self.assertNotIn("places_now", self.client.get("/").context)  # round 14: one place chosen, that place only
        self.client.post("/place/all/")
        cards = self.client.get("/").context["places_now"]
        self.assertEqual([card["place"].code for card in cards], ["CIA", "PVT", "CIC", "LAB"])
        self.assertTrue(cards[3]["lab"])
        self.assertEqual(len({len(card["stats"]) for card in cards[:3]}), 1)  # the clinics show the same numbers
        self.assertEqual(Branch.objects.filter(is_active=True).count(), 4)
        make_user("sec", "secretary")
        self.client.login(username="sec", password=PASSWORD)
        self.assertNotIn("places_now", self.client.get("/").context)

    def test_a_problem_can_be_reported_with_a_video_of_the_screen(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.core.models import ProblemReport

        make_user("sec", "secretary")
        self.client.login(username="sec", password=PASSWORD)
        video = SimpleUploadedFile("screen.webm", b"\x1a\x45\xdf\xa3" + b"0" * 64, content_type="video/webm")
        answer = self.client.post("/problems/report/", {"description": "The page closes", "video": video},
                                  HTTP_X_REQUESTED_WITH="XMLHttpRequest").json()
        self.assertTrue(answer["ok"])
        self.assertTrue(ProblemReport.objects.get().video.name.endswith(".webm"))
        fake = SimpleUploadedFile("screen.webm", b"MZ not a video", content_type="video/webm")
        answer = self.client.post("/problems/report/", {"description": "x", "video": fake},
                                  HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(answer.status_code, 400)


class Round14CoreTests(TestCase):
    """The owner's home on All places or one place, the lab's own menus, the Up button, access one role at a time,
    the settings of each place, and the time each person spends in the system."""

    def setUp(self):
        self.branch = setup_clinic()
        self.owner = make_user("owner", "owner")

    def test_the_owner_sees_all_places_then_only_the_place_chosen(self):
        self.client.login(username="owner", password=PASSWORD)
        home = self.client.get("/")
        self.assertTrue(home.context["all_places"])
        self.assertEqual([card["place"].code for card in home.context["places_now"]], ["CIA", "PVT", "CIC", "LAB"])
        self.assertNotIn("appointment_counts", home.context)  # a place's details wait until it is chosen
        self.assertEqual([p.code for p in home.context["place_tabs"]], ["CIA", "PVT", "CIC", "LAB"])
        self.client.post("/place/", {"place": "LAB", "next": "/"})
        lab = self.client.get("/")
        self.assertNotIn("places_now", lab.context)
        self.assertIn("lab_numbers", lab.context)
        for clinic_part in ("patient_totals", "appointment_counts", "overdue_installments", "low_stock"):
            self.assertNotIn(clinic_part, lab.context)
        self.assertTrue(lab.context["at_lab"])
        self.assertFalse(lab.context["sees_patients"])  # the clinics' menus are not shown at the lab
        self.assertNotContains(lab, 'href="/patients/create/"')
        self.client.post("/place/", {"place": "PVT", "next": "/"})
        khadem = self.client.get("/")
        self.assertIn("appointment_counts", khadem.context)
        self.assertNotIn("overdue_installments", khadem.context)  # the academy is CIA's
        self.assertFalse(khadem.context["academy_here"])
        self.client.post("/place/all/")
        self.assertIn("places_now", self.client.get("/").context)
        make_user("sec", "secretary")
        self.client.login(username="sec", password=PASSWORD)
        self.assertEqual(self.client.post("/place/all/").status_code, 403)

    def test_the_owner_logs_in_on_all_places(self):
        self.client.post("/login/?place=CIC", {"username": "owner", "password": PASSWORD})
        self.assertTrue(self.client.session["all_places"])

    def test_up_goes_to_the_page_above(self):
        from apps.core.navigation import up_target
        from apps.core.testing import make_patient

        patient = make_patient(self.branch)
        self.assertEqual(up_target(f"/patients/{patient.pk}/edit/", patient)["url"], patient.get_absolute_url())
        with translation.override("en"):
            self.assertEqual(str(up_target(f"/patients/{patient.pk}/", patient)["name"]), "Patients")
        self.assertEqual(up_target(f"/chart/patient/{patient.pk}/photos/logbook/", patient)["url"],
                         f"/chart/patient/{patient.pk}/photos/")
        self.assertEqual(up_target("/settings/users/")["url"], "/settings/")
        self.client.login(username="owner", password=PASSWORD)
        page = self.client.get("/settings/users/")
        self.assertContains(page, 'href="/settings/" data-up')
        self.assertNotContains(page, "data-back")

    def test_access_is_set_one_role_at_a_time(self):
        from apps.core.models import AreaAccess

        self.client.login(username="owner", password=PASSWORD)
        page = self.client.get("/settings/access/")
        panels = {panel["code"]: panel for panel in page.context["panels"]}
        self.assertNotIn("owner", panels)
        self.assertTrue(panels["lab_secretary"]["lab"])
        self.assertContains(page, 'name="secretary__academy" value="hidden"')
        self.client.post("/settings/access/", {"secretary__academy": "hidden", "dentist__billing": "read"})
        self.assertEqual(set(AreaAccess.objects.values_list("role", "area", "level")),
                         {("secretary", "academy", "hidden"), ("dentist", "billing", "read")})
        panels = {panel["code"]: panel for panel in self.client.get("/settings/access/").context["panels"]}
        self.assertEqual(panels["secretary"]["limits"], 1)

    def test_people_and_lists_by_place(self):
        from apps.lab.models import LabWorker
        from apps.scheduling.models import Room

        make_user("sec", "secretary")
        make_user("labsec", "lab_secretary")
        designer = make_user("drlab", "dentist")
        LabWorker.objects.create(name="Dr. Lab", user=designer, jobs=["design"])  # designs, without a lab role
        self.client.login(username="owner", password=PASSWORD)
        lab = self.client.get("/settings/users/?place=LAB")
        names = {row[0].username for row in lab.context["rows"]}
        self.assertEqual(names, {"labsec", "drlab"})
        cia = {row[0].username for row in self.client.get("/settings/users/?place=CIA").context["rows"]}
        self.assertIn("sec", cia)
        self.assertNotIn("labsec", cia)
        home = self.client.get("/settings/")
        self.assertEqual([card["place"].code for card in home.context["place_cards"]], ["CIA", "PVT", "CIC", "LAB"])
        rooms = self.client.get("/settings/lists/rooms/?place=CIC")
        self.assertEqual(len(rooms.context["rows"]), Room.objects.filter(branch__code="CIC").count())
        self.assertEqual(rooms.context["place"].code, "CIC")

    def test_the_time_in_the_system_is_kept_for_each_person(self):
        from unittest import mock

        from apps.core.models import WorkSession
        from apps.core.worktime import duration

        sec = make_user("sec", "secretary", first_name="Mona")
        clock = [1_800_000_000]
        with mock.patch("apps.core.worktime.clock", lambda: clock[0]):
            self.client.login(username="sec", password=PASSWORD)
            self.client.get("/")  # opens the system
            clock[0] += 60
            self.client.get("/patients/")  # one minute of work
            clock[0] += 30
            self.client.get("/notifications/poll/?since=0")  # open, nothing touched
            clock[0] += 600
            self.client.get("/notifications/poll/?since=0&active=1")  # back after 10 minutes away: not work
            clock[0] += 30
            self.client.get("/patients/")
            session = WorkSession.objects.get(user=sec)
            self.assertEqual(session.active_seconds, 90)
            self.assertEqual(session.pages, 3)
            self.client.post("/logout/")
            session.refresh_from_db()
            self.assertEqual(session.end, "logout")
            self.assertEqual(session.open_seconds, 720)
            # A page closed and opened again after more than half an hour: a new stretch.
            self.client.login(username="sec", password=PASSWORD)
            self.client.get("/")
            clock[0] += 31 * 60
            self.client.get("/")
        self.assertEqual(WorkSession.objects.filter(user=sec).count(), 3)
        self.assertEqual(WorkSession.objects.filter(user=sec, end="closed").count(), 1)
        self.client.login(username="owner", password=PASSWORD)
        report = self.client.get("/time/?date_from=01/01/2020&date_to=31/12/2030")
        row = next(p for p in report.context["people"] if p["user"] == sec)
        self.assertEqual((row["sessions"], row["worked"]), (3, 90))
        self.assertEqual(self.client.get(f"/time/{sec.pk}/?date_from=01/01/2020&date_to=31/12/2030").status_code, 200)
        self.assertEqual(str(duration(3900)), "1 h 05 min")
        self.client.login(username="sec", password=PASSWORD)
        self.assertEqual(self.client.get("/time/").status_code, 403)


class Round15CoreTests(TestCase):
    """Round 15: one device per login, the folder of the photos, the counts of the menu at each place."""

    def setUp(self):
        self.branch = setup_clinic()
        self.owner = make_user("owner", "owner")
        self.secretary = make_user("sec", "secretary")

    def test_a_login_on_another_device_logs_out_the_first(self):
        from django.test import Client

        from apps.core.models import SecurityEvent

        first, second = Client(), Client()
        first.login(username="sec", password=PASSWORD)
        self.assertEqual(first.get("/").status_code, 200)
        second.post("/login/", {"username": "sec", "password": PASSWORD}, REMOTE_ADDR="127.0.0.1")
        self.assertEqual(second.get("/").status_code, 200)
        event = SecurityEvent.objects.get(kind=SecurityEvent.Kind.REPLACED)
        self.assertEqual(event.user, self.secretary)
        self.assertTrue(event.session)
        response = first.get("/", follow=True)  # the first device is logged out, and its login page says why
        self.assertEqual(response.redirect_chain[0][1], 302)
        self.assertIn("login", response.redirect_chain[-1][0])
        self.assertEqual(len([m for m in response.context["messages"]]), 1)
        self.assertEqual(first.get("/login/").status_code, 200)  # told once

    def test_one_device_per_login_can_be_switched_off(self):
        from django.test import Client

        from apps.core.models import ClinicSettings

        ClinicSettings.objects.update_or_create(pk=ClinicSettings.get().pk, defaults={"one_device_per_login": False})
        first, second = Client(), Client()
        first.login(username="sec", password=PASSWORD)
        second.post("/login/", {"username": "sec", "password": PASSWORD})
        self.assertEqual(first.get("/").status_code, 200)

    def test_the_photos_folder_is_shown_and_another_one_checked(self):
        import tempfile

        from django.test import override_settings

        from apps.core import photo_folder

        with tempfile.TemporaryDirectory() as media, tempfile.TemporaryDirectory() as other:
            with override_settings(MEDIA_ROOT=media):
                os.makedirs(os.path.join(media, "Patient photos", "CIA-00001"))
                with open(os.path.join(media, "Patient photos", "CIA-00001", "a.jpg"), "wb") as handle:
                    handle.write(b"\xff\xd8\xff" + b"x" * 100)
                from django.core.cache import cache

                cache.delete(photo_folder.CACHE_KEY)
                self.client.login(username="owner", password=PASSWORD)
                response = self.client.get("/settings/backup/")
                self.assertContains(response, media)
                target = os.path.join(other, "photos")
                response = self.client.post("/settings/backup/", {"check_folder": target})
                self.assertTrue(response.context["folder_ok"])
                self.assertContains(response, "move_photos")
                self.assertFalse(dict(photo_folder.check("relative/folder")).get(True))
                self.assertFalse(all(ok for ok, _t in photo_folder.check(os.path.join(media, "inside"))))
                copied, skipped, problems = photo_folder.copy_all(target, say=lambda text: None)
                self.assertEqual((copied, skipped, problems), (1, 0, []))
                self.assertTrue(os.path.exists(os.path.join(target, "Patient photos", "CIA-00001", "a.jpg")))
                self.assertEqual(photo_folder.copy_all(target, say=lambda text: None)[:2], (0, 1))

    def test_the_menu_counts_this_places_patients_only(self):
        from apps.core.testing import make_dentist, make_patient
        from apps.scheduling.models import PatientRequest

        cic = Branch.objects.get(code="CIC")
        self.secretary.profile.places.add(cic)
        dentist = make_dentist("doc")
        patient = make_patient(self.branch)
        from apps.clinical.models import TreatmentStepType

        PatientRequest.objects.create(dentist=dentist, patient=patient, status=PatientRequest.Status.APPROVED,
                                      minutes=30, step_type=TreatmentStepType.objects.first())
        self.client.login(username="sec", password=PASSWORD)
        self.assertEqual(self.client.get("/").context["requests_to_call"], 1)
        self.client.post("/place/", {"place": "CIC", "next": "/"})
        self.assertEqual(self.client.get("/").context["requests_to_call"], 0)
        response = self.client.get("/schedule/patient-lists/")
        self.assertEqual([(place.code, n) for place, n in response.context["elsewhere"]], [("CIA", 1)])

    def test_hours_and_minutes_box(self):
        from apps.core.utils import hours_minutes
        from apps.core.widgets import HoursMinutesWidget

        widget = HoursMinutesWidget()
        self.assertEqual(widget.value_from_datadict({"t_0": "2", "t_1": "15"}, {}, "t"), "135")
        self.assertEqual(widget.value_from_datadict({"t_0": "", "t_1": "45"}, {}, "t"), "45")
        self.assertEqual(widget.value_from_datadict({"t_0": "", "t_1": ""}, {}, "t"), "")
        self.assertEqual(widget.value_from_datadict({"t": "90"}, {}, "t"), "90")
        self.assertEqual(widget.decompress(135), [2, 15])
        with translation.override("en"):
            self.assertEqual(hours_minutes(90), "1 h 30 min")
            self.assertEqual(hours_minutes(120), "2 h")
            self.assertEqual(hours_minutes(45), "45 min")
