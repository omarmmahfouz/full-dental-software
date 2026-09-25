from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.academy.models import Candidate, Course, Enrollment
from apps.core.testing import PASSWORD, make_dentist, make_patient, make_user, setup_clinic
from apps.dentists.models import Dentist
from apps.surgery.models import ImplantSystem, Surgery, SurgerySite


class DentistTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.owner = make_user("owner", "owner")
        make_user("sec", "secretary")
        make_user("sup", "supervisor")
        self.course = Course.objects.create(branch=self.branch, name="Implant diploma", code="IMP-1",
                                            fee=Decimal("40000"), implants_required=10)
        self.candidate = Candidate.objects.create(full_name="Dr. Candidate", phone_primary="01001234567", code="C-1")

    def place_implants(self, dentist, count, failed=0):
        patient = make_patient(self.branch)
        surgery = Surgery.objects.create(branch=self.branch, patient=patient, operator_1=dentist)
        for index in range(count):
            site = SurgerySite.objects.create(surgery=surgery, tooth=[36, 46, 37, 47, 35][index], simple_implant=True,
                                              implant_system=ImplantSystem.objects.first(),
                                              implant_diameter=Decimal("4"), implant_length=Decimal("10"))
            if index < failed:
                SurgerySite.objects.filter(pk=site.pk).update(implant_status=SurgerySite.ImplantStatus.FAILED)
        return patient

    def test_every_candidate_gets_a_dentist_record(self):
        dentist = self.candidate.dentist
        self.assertEqual((dentist.kind, dentist.full_name), (Dentist.Kind.CANDIDATE, "Dr. Candidate"))
        self.candidate.full_name = "Dr. Candidate Renamed"
        self.candidate.save()
        dentist.refresh_from_db()
        self.assertEqual(dentist.full_name, "Dr. Candidate Renamed")
        self.assertEqual(Dentist.objects.count(), 1)

    def test_portfolio_counts_implants_left_for_the_course(self):
        enrollment = Enrollment.objects.create(candidate=self.candidate, course=self.course,
                                               enrolled_on=timezone.localdate(), agreed_fee=self.course.fee)
        dentist = self.candidate.dentist
        self.place_implants(dentist, 3, failed=1)
        self.client.login(username="sec", password=PASSWORD)
        page = self.client.get(f"/dentists/{dentist.pk}/")
        self.assertEqual((page.context["placed"], page.context["required"], page.context["remaining"]), (3, 10, 7))
        self.assertEqual(page.context["failed"], 1)
        self.assertEqual(len(page.context["cases"]), 1)
        enrollment.implants_required_override = 3
        enrollment.save()
        page = self.client.get(f"/dentists/{dentist.pk}/")
        self.assertEqual(page.context["remaining"], 0)
        # The academy file shows the same progress.
        self.assertEqual(self.client.get(self.candidate.get_absolute_url()).context["implants_placed"], 3)

    def test_who_sees_a_portfolio(self):
        mine = make_dentist("dentist")
        other = make_dentist("dentist2")
        self.client.login(username="dentist", password=PASSWORD)
        self.assertEqual(self.client.get(f"/dentists/{mine.pk}/").status_code, 200)
        self.assertEqual(self.client.get(f"/dentists/{other.pk}/").status_code, 403)
        self.assertEqual(self.client.get("/dentists/").status_code, 403)
        self.client.login(username="sec", password=PASSWORD)
        self.assertEqual(self.client.get("/dentists/").status_code, 200)

    def test_front_desk_adds_training_dentist_and_owner_creates_login(self):
        self.client.login(username="sec", password=PASSWORD)
        self.client.post("/dentists/new/", {"full_name": "Dr. Helper", "kind": "training", "phone": "01112223334",
                                            "is_active": "on"})
        dentist = Dentist.objects.get(full_name="Dr. Helper")
        self.assertEqual(dentist.kind, Dentist.Kind.TRAINING)
        self.assertEqual(self.client.post(f"/dentists/{dentist.pk}/login/").status_code, 403)
        self.client.login(username="owner", password=PASSWORD)
        self.client.post(f"/dentists/{dentist.pk}/login/")
        dentist.refresh_from_db()
        self.assertEqual(dentist.user.username, "01112223334")
        self.assertTrue(dentist.user.groups.filter(name="dentist").exists())

    def test_candidate_kind_cannot_be_chosen_by_hand(self):
        self.client.login(username="sec", password=PASSWORD)
        response = self.client.post("/dentists/new/", {"full_name": "Dr. X", "kind": "candidate", "is_active": "on"})
        self.assertIn("kind", response.context["form"].errors)
