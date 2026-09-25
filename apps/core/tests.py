from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import translation

from apps.core.models import Notification
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
            "o-late_threshold_minutes": 15, "o-default_appointment_minutes": 45, "o-complaint_follow_up_days": 3,
            "o-stock_expiry_days": 30, "o-reminder_days_before": 2, "o-whatsapp_country_code": "20",
            "b-name_ar": "أكاديمية القاهرة لزراعة الأسنان", "b-name_en": "Cairo Implant Academy", "b-phone": "0223456789",
            "b-address": "Cairo",
        })
        self.assertEqual(ClinicSettings.get().late_threshold_minutes, 15)
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
