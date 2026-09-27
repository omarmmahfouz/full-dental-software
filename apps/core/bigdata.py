"""Clinic-sized test data: thousands of patients with two years of visits, bills, payments and photo records.

Used by the speed tests (so a page that becomes slow with many patients fails a test before it reaches the
clinic) and by ``manage.py fill_big_data`` on a test copy, to try the system with 10,000 patients.
It needs the lists of ``setup_clinic`` and at least one dentist. The records are written in bulk (a few
seconds for 10,000 patients); their file numbers start at 90000, their bills with "BX-" and their receipts
with "PX-", so they are easy to recognise. Never run it on the clinic's real database."""

import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

FIRST = ["محمد", "أحمد", "محمود", "مصطفى", "علي", "حسن", "إبراهيم", "يوسف", "سارة", "منى", "هبة", "فاطمة", "نادية"]
LAST = ["عبد الله", "السيد", "حسين", "عبد الرحمن", "إبراهيم", "مصطفى", "الشريف", "عثمان", "سليمان", "فؤاد"]
FIRST_NUMBER = 90000


def fill(patients=10_000, visits_per_patient=6, bills_per_patient=3, photos_per_patient=3, days=730, seed=3):
    """Add the patients and their records; returns the numbers added."""
    from apps.billing.models import Bill, Charge, PatientPayment, Service
    from apps.charting.models import ClinicalPhoto, PhotoStage
    from apps.core.models import Branch
    from apps.dentists.models import Dentist
    from apps.patients.models import Patient
    from apps.scheduling.models import Appointment, Room

    rng = random.Random(seed)
    places = list(Branch.objects.filter(code__in=("CIA", "CIC")).order_by("code")) or list(Branch.objects.all()[:1])
    dentists = list(Dentist.objects.filter(is_active=True)) or list(Dentist.objects.all())
    if not places or not dentists:
        raise ValueError("Run setup_clinic and add at least one dentist first.")
    rooms = {place.pk: list(Room.objects.filter(branch=place)) or [None] for place in places}
    services = list(Service.objects.filter(is_active=True, price__gt=0)) or list(Service.objects.all())
    if not services:
        raise ValueError("The list of services is empty: run setup_clinic first.")
    today = timezone.localdate()
    start = Patient.objects.filter(file_number__regex=r"-9\d{4,}$").count()  # a second run adds more
    with transaction.atomic():
        new = []
        for n in range(start, start + patients):
            place = places[n % len(places)] if n % 4 == 0 else places[0]
            new.append(Patient(
                branch=place, full_name=f"{rng.choice(FIRST)} {rng.choice(FIRST)} {rng.choice(LAST)}",
                national_id=f"3{n:013d}", phone_primary=f"0109{n:07d}", file_number=f"{place.code}-{FIRST_NUMBER + n}",
                assigned_dentist=rng.choice(dentists)))
        Patient.objects.bulk_create(new, batch_size=1000)
        numbers = [p.file_number for p in new]
        people = list(Patient.objects.filter(file_number__in=numbers).only("pk", "branch_id"))

        def moment():
            day = today - timedelta(days=rng.randint(0, days))
            return day, timezone.make_aware(datetime.combine(day, time(rng.randint(9, 19), rng.choice([0, 15, 30, 45]))))

        visits = []
        for _ in range(patients * visits_per_patient):
            patient, place = rng.choice(people), rng.choice(places)
            _day, when = moment()
            visits.append(Appointment(
                branch=place, patient_id=patient.pk, dentist=rng.choice(dentists), room=rng.choice(rooms[place.pk]),
                scheduled_at=when, duration_minutes=30, status=Appointment.Status.COMPLETED, arrived_at=when,
                entered_room_at=when + timedelta(minutes=rng.randint(0, 30)),
                left_at=when + timedelta(minutes=rng.randint(35, 90))))
        Appointment.objects.bulk_create(visits, batch_size=2000)

        prefix = f"BX{start:05d}-"
        bills = []
        for n in range(patients * bills_per_patient):
            patient, place = rng.choice(people), rng.choice(places)
            day, _when = moment()
            bills.append(Bill(patient_id=patient.pk, branch=place, number=f"{prefix}{n:06d}", billed_on=day,
                              dentist=rng.choice(dentists)))
        Bill.objects.bulk_create(bills, batch_size=2000)
        charges, payments = [], []
        for n, bill in enumerate(Bill.objects.filter(number__startswith=prefix).order_by("pk")):
            for _ in range(rng.choice([1, 1, 2])):
                service = rng.choice(services)
                charges.append(Charge(patient_id=bill.patient_id, bill=bill, branch_id=bill.branch_id, service=service,
                                      dentist_id=bill.dentist_id, charged_on=bill.billed_on, teeth=rng.choice(["", "36", "46, 47"]),
                                      price=service.price or Decimal("500"), discount_percent=rng.choice([0, 0, 10])))
            if rng.random() < 0.9:
                payments.append(PatientPayment(
                    patient_id=bill.patient_id, bill=bill, branch_id=bill.branch_id, paid_on=bill.billed_on,
                    amount=Decimal(rng.choice([200, 500, 1000, 3000])), method="cash",
                    receipt_number=f"PX{start:05d}-{n:06d}"))
        Charge.objects.bulk_create(charges, batch_size=2000)
        PatientPayment.objects.bulk_create(payments, batch_size=2000)

        photos = []
        for _ in range(patients * photos_per_patient):
            patient = rng.choice(people)
            photos.append(ClinicalPhoto(patient_id=patient.pk, stage=PhotoStage.FOLLOW_UP, teeth="36",
                                        file=f"Patient photos/test/{rng.randint(1, 10**9)}.jpg",
                                        taken_on=today - timedelta(days=rng.randint(0, days))))
        ClinicalPhoto.objects.bulk_create(photos, batch_size=2000)
    return {"patients": len(new), "visits": len(visits), "bills": len(bills), "services": len(charges),
            "payments": len(payments), "photos": len(photos)}
