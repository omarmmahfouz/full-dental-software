from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.academy.forms import add_months, split_amount
from apps.academy.models import Candidate, Course, Enrollment, Installment, Payment
from apps.core.testing import PASSWORD, make_user, setup_clinic


class HelperTests(TestCase):
    def test_split_and_months(self):
        self.assertEqual(split_amount(Decimal("10000"), 3), [Decimal("3333"), Decimal("3333"), Decimal("3334")])
        self.assertEqual(add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(add_months(date(2026, 11, 15), 3), date(2027, 2, 15))


class InstallmentTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        make_user("sec", "secretary")
        self.dentist = make_user("dentist", "dentist")
        self.client.login(username="sec", password=PASSWORD)
        self.course = Course.objects.create(branch=self.branch, name="Implant diploma", code="IMP-1", fee=Decimal("40000"))
        self.candidate = Candidate.objects.create(full_name="Dr. Test", phone_primary="01001234567")

    def enroll(self, **overrides):
        today = timezone.localdate()
        data = {
            "course": self.course.pk, "enrolled_on": today.isoformat(), "discount": "4000",
            "down_payment": "6000", "down_payment_method": "cash", "installments_count": 3,
            "first_due_date": (today + timedelta(days=30)).isoformat(),
        }
        data.update(overrides)
        return self.client.post(f"/academy/candidates/{self.candidate.pk}/enroll/", data)

    def test_enrollment_creates_plan_and_down_payment(self):
        self.enroll()
        enrollment = Enrollment.objects.get()
        self.assertEqual(enrollment.agreed_fee, Decimal("40000"))  # taken from the course
        self.assertEqual(enrollment.net_fee, Decimal("36000"))
        amounts = list(enrollment.installments.values_list("amount", flat=True))
        self.assertEqual(amounts, [Decimal("6000"), Decimal("10000"), Decimal("10000"), Decimal("10000")])
        self.assertEqual(enrollment.total_paid, Decimal("6000"))
        self.assertEqual(enrollment.balance, Decimal("30000"))
        self.assertEqual(enrollment.overdue_amount(), Decimal("0"))

    def test_duplicate_enrollment_rejected(self):
        self.enroll()
        response = self.enroll()
        self.assertEqual(Enrollment.objects.count(), 1)
        self.assertTrue(response.context["form"].non_field_errors())

    def test_payments_fill_oldest_installments_and_overdue(self):
        enrollment = Enrollment.objects.create(candidate=self.candidate, course=self.course, agreed_fee=Decimal("30000"))
        today = timezone.localdate()
        for n, days in enumerate([-60, -30, 30], start=1):
            Installment.objects.create(enrollment=enrollment, number=n, due_date=today + timedelta(days=days), amount=Decimal("10000"))
        Payment.objects.create(enrollment=enrollment, amount=Decimal("15000"), method="cash")
        states = [row["state"] for row in enrollment.installment_schedule()]
        self.assertEqual(states, ["paid", "overdue", "due"])
        self.assertEqual(enrollment.overdue_amount(), Decimal("5000"))
        overdue_page = self.client.get("/academy/overdue/")
        self.assertEqual(overdue_page.context["total"], Decimal("5000"))

    def test_payment_rules(self):
        enrollment = Enrollment.objects.create(candidate=self.candidate, course=self.course, agreed_fee=Decimal("1000"))
        url = f"/academy/enrollments/{enrollment.pk}/"
        response = self.client.post(url, {"amount": "1500", "paid_on": "2026-09-25", "method": "cash"})
        self.assertIn("amount", response.context["payment_form"].errors)
        response = self.client.post(url, {"amount": "500", "paid_on": "2026-09-25", "method": "instapay"})
        self.assertIn("reference", response.context["payment_form"].errors)
        response = self.client.post(url, {"amount": "500", "paid_on": "2026-09-25", "method": "instapay", "reference": "IP123"})
        payment = Payment.objects.get()
        self.assertRedirects(response, f"/academy/payments/{payment.pk}/receipt/", fetch_redirect_response=False)
        self.assertTrue(payment.receipt_number.startswith("RC-"))
        self.assertEqual(enrollment.balance, Decimal("500"))

    def test_dentist_has_no_access(self):
        self.client.login(username="dentist", password=PASSWORD)
        self.assertEqual(self.client.get("/academy/candidates/").status_code, 403)


class InstallmentReminderTests(TestCase):
    def test_monthly_list_and_whatsapp_reminder(self):
        from datetime import date as day
        from urllib.parse import unquote

        from apps.academy.models import Enrollment, Installment
        from apps.scheduling.models import SentMessage

        branch = setup_clinic()
        make_user("sec", "secretary")
        course = Course.objects.create(branch=branch, name="Implant diploma", code="IMP-1", fee=Decimal("30000"),
                                       start_date=day(2026, 1, 1))
        candidate = Candidate.objects.create(code="C-1", full_name="د. أحمد", phone_primary="01001234567")
        enrollment = Enrollment.objects.create(candidate=candidate, course=course, agreed_fee=Decimal("30000"),
                                               study_mode=Enrollment.StudyMode.ONLINE)
        today = timezone.localdate()
        installment = Installment.objects.create(enrollment=enrollment, number=1, due_date=today, amount=Decimal("5000"))
        self.client.login(username="sec", password=PASSWORD)
        page = self.client.get("/academy/installments/")
        self.assertEqual(page.context["totals"]["remaining"], Decimal("5000"))
        response = self.client.post(f"/academy/installments/{installment.pk}/whatsapp/")
        text = unquote(response["Location"].split("text=", 1)[1])
        self.assertIn("5,000", text)
        self.assertIn("د. أحمد", text)
        self.assertEqual(SentMessage.objects.get().installment, installment)
        self.assertEqual(len(self.client.get("/schedule/whatsapp/").context["installments"]), 1)
