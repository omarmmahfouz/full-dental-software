from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase

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
        for index, role in enumerate(["secretary", "intern", "supervisor", "owner"]):
            make_user(f"u{index}", role)
            self.client.login(username=f"u{index}", password=PASSWORD)
            self.assertEqual(self.client.get("/").status_code, 200)
