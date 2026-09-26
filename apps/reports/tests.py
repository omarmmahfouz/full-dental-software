from datetime import datetime, time, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.clinical.models import TreatmentStep, TreatmentStepType
from apps.core.testing import PASSWORD, make_dentist, make_patient, make_user, setup_clinic
from apps.scheduling.models import Appointment


class ReportTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.owner = make_user("owner", "owner")
        self.supervisor = make_user("sup", "supervisor")
        self.secretary = make_user("sec", "secretary")
        self.dentist = make_dentist("dentist", kind="candidate")
        patient = make_patient(self.branch, assigned_dentist=self.dentist)
        day = timezone.localdate() - timedelta(days=1)

        def at(hour, minute=0):
            return timezone.make_aware(datetime.combine(day, time(hour, minute)))

        late = Appointment(branch=self.branch, patient=patient, dentist=self.dentist, scheduled_at=at(10))
        late.mark_arrived(at(10, 30))
        late.mark_entered_room(at(10, 50))
        late.mark_left(at(11, 50))
        late.save()
        on_time = Appointment(branch=self.branch, patient=patient, dentist=self.dentist, scheduled_at=at(13))
        on_time.mark_arrived(at(12, 55))
        on_time.mark_entered_room(at(13, 5))
        on_time.mark_left(at(13, 45))
        on_time.save()
        Appointment.objects.create(branch=self.branch, patient=patient, dentist=self.dentist, scheduled_at=at(15),
                                   status=Appointment.Status.NO_SHOW)
        TreatmentStep.objects.create(patient=patient, step_type=TreatmentStepType.objects.first(), operator=self.dentist,
                                     performed_at=at(11), grade=4, verified_by=self.supervisor, verified_at=at(12))

    def test_visit_statistics(self):
        self.client.login(username="sup", password=PASSWORD)
        summary = self.client.get("/reports/visits/").context["summary"]
        self.assertEqual(summary["arrived"], 2)
        self.assertEqual(summary["late"], 1)
        self.assertEqual(summary["late_pct"], 50)
        self.assertEqual(summary["avg_late"], 30)
        # (20 + 5) / 2: the early patient (12:55 for 13:00) waits from the appointment time, not from arrival
        self.assertEqual(summary["avg_wait"], 12)
        self.assertEqual(summary["avg_chair"], 50)  # (60 + 40) / 2
        self.assertEqual(summary["no_show"], 1)

    def test_dentist_report(self):
        self.client.login(username="sup", password=PASSWORD)
        row = self.client.get("/reports/dentists/").context["rows"][0]
        self.assertEqual(row["dentist"], self.dentist)
        self.assertEqual((row["steps"], row["checked"], row["grade"], row["no_shows"]), (1, 1, 4.0, 1))

    def test_access(self):
        self.client.login(username="sec", password=PASSWORD)
        self.assertEqual(self.client.get("/reports/visits/").status_code, 403)
        self.client.login(username="sup", password=PASSWORD)
        self.assertEqual(self.client.get("/reports/money/").status_code, 403)  # money is owner-only
        self.client.login(username="owner", password=PASSWORD)
        for url in ["/reports/", "/reports/money/", "/reports/lab/", "/reports/patients/", "/reports/dentists/"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)
