"""Fill an EMPTY trial database with sample data so the staff can practise.

    python manage.py load_demo_data --password demo12345

Never run this on the real clinic database.
"""

import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.academy.models import Candidate, Course, Enrollment, Installment, Payment, PaymentMethod
from apps.clinical.models import Lab, LabRequest, LabRequestEvent, LabWorkType, TreatmentStep, TreatmentStepType
from apps.clinical.services import perform_lab_action
from apps.complaints.models import Complaint
from apps.core.models import Branch
from apps.patients.models import Lead, MedicalCondition, MissingTeeth, Patient, ReferralSource
from apps.purchasing.models import Purchase, PurchaseCategory, PurchaseItem, Supplier
from apps.scheduling.models import Appointment, Room, RoomShift

FIRST = ["محمد", "أحمد", "محمود", "مصطفى", "علي", "حسن", "إبراهيم", "يوسف", "سارة", "منى", "هبة", "فاطمة", "نادية", "سعاد", "أمل"]
LAST = ["عبد الله", "السيد", "حسين", "عبد الرحمن", "إبراهيم", "مصطفى", "الشريف", "عثمان", "سليمان", "فؤاد"]


class Command(BaseCommand):
    help = "Load sample data into an empty trial database (users, patients, visits, lab, installments...)."

    def add_arguments(self, parser):
        parser.add_argument("--password", required=True, help="Password given to every demo user.")

    @transaction.atomic
    def handle(self, *args, password, **options):
        if Patient.objects.exists():
            raise CommandError("The database already has patients. Demo data is only for an empty trial database.")
        call_command("setup_clinic", stdout=self.stdout)
        rng = random.Random(7)
        User = get_user_model()
        branch = Branch.objects.get(code="CIA")

        def user(username, first, last, role, staff=False):
            obj = User.objects.create_user(username, password=password, first_name=first, last_name=last, is_staff=staff)
            obj.groups.add(Group.objects.get(name=role))
            obj.profile.branch = branch
            obj.profile.save()
            return obj

        owner = user("owner", "د. المدير", "", "owner", staff=True)
        secretary = user("secretary", "منة", "السكرتيرة", "secretary")
        supervisor = user("supervisor", "د. خالد", "المشرف", "supervisor")
        interns = [user(f"intern{i}", f"د. {name}", "", "intern") for i, name in enumerate(["أحمد سمير", "نور حسن", "كريم عادل", "ياسمين علي"], 1)]

        sources = list(ReferralSource.objects.all())
        conditions = list(MedicalCondition.objects.all())
        teeth = [MissingTeeth.SINGLE, MissingTeeth.MULTIPLE, MissingTeeth.FULL_ARCH]

        def name():
            return f"{rng.choice(FIRST)} {rng.choice(FIRST)} {rng.choice(LAST)}"

        patients = []
        for i in range(24):
            year = rng.randint(55, 99)
            gender_digit = rng.choice([1, 2, 3, 4, 5, 6, 7, 8, 9])
            nid = f"2{year:02d}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}01{100 + i:03d}{gender_digit}{rng.randint(0, 9)}"
            source = rng.choice(sources)
            patient = Patient.objects.create(
                branch=branch, full_name=name(), national_id=nid, phone_primary=f"010{10000000 + i * 7919:08d}",
                missing_teeth=rng.choice(teeth), referral_source=source,
                referred_by=patients[0] if source.asks_for_patient and patients else None,
                assigned_intern=interns[i % len(interns)], created_by=secretary,
            )
            patient.medical_conditions.set(rng.sample(conditions, rng.randint(0, 2)))
            patients.append(patient)

        for i in range(10):
            Lead.objects.create(
                branch=branch, full_name=name(), phone_primary=f"011{20000000 + i * 3571:08d}", age=rng.randint(35, 75),
                missing_teeth=rng.choice(teeth), referral_source=rng.choice(sources),
                status=rng.choice([Lead.Status.NEW, Lead.Status.FOLLOW_UP, Lead.Status.BOOKED]),
                next_call_at=timezone.now() + timedelta(hours=rng.randint(-24, 48)), created_by=secretary,
            )

        rooms = list(Room.objects.filter(branch=branch))
        today = timezone.localdate()
        for offset in range(-14, 7):
            day = today + timedelta(days=offset)
            if day.weekday() == 4:  # Friday off
                continue
            for room, intern in zip(rooms, interns):
                RoomShift.objects.create(room=room, date=day, start_time=time(10), end_time=time(16), intern=intern,
                                         supervisor=supervisor, created_by=secretary)

        step_types = list(TreatmentStepType.objects.all())
        now = timezone.now()
        for offset in range(-14, 1):
            day = today + timedelta(days=offset)
            if day.weekday() == 4:
                continue
            for slot, patient in enumerate(rng.sample(patients, 6)):
                start = timezone.make_aware(datetime.combine(day, time(10 + slot)))
                room = rooms[interns.index(patient.assigned_intern) % len(rooms)]
                appointment = Appointment(branch=branch, patient=patient, scheduled_at=start, room=room,
                                          intern=patient.assigned_intern, purpose=rng.choice(step_types).name_ar,
                                          created_by=secretary)
                if start > now:
                    appointment.save()
                    continue
                if rng.random() < 0.1:
                    appointment.status = Appointment.Status.NO_SHOW
                    appointment.save()
                    continue
                arrived = start + timedelta(minutes=rng.randint(-10, 35))
                entered = arrived + timedelta(minutes=rng.randint(5, 40))
                left = entered + timedelta(minutes=rng.randint(20, 90))
                appointment.mark_arrived(arrived)
                if entered < now:
                    appointment.mark_entered_room(entered)
                if left < now:
                    appointment.mark_left(left)
                appointment.save()
                if appointment.left_at:
                    step = TreatmentStep.objects.create(
                        patient=patient, appointment=appointment, step_type=rng.choice(step_types),
                        teeth=rng.choice(["36", "46", "11, 21", "14-16"]), performed_at=entered,
                        performed_by=patient.assigned_intern, created_by=patient.assigned_intern,
                    )
                    if rng.random() < 0.6:
                        step.verified_by, step.verified_at, step.grade = supervisor, left, rng.randint(3, 5)
                        step.save()

        lab = Lab.objects.first()
        work_types = list(LabWorkType.objects.all())
        for patient, target in zip(patients[:6], ["submit", "approve", "send", "receive", "deliver", None]):
            lab_request = LabRequest.objects.create(
                branch=branch, patient=patient, lab=lab, work_type=rng.choice(work_types), teeth="36",
                shade="A2", requested_by=patient.assigned_intern, due_date=today + timedelta(days=rng.randint(-3, 7)),
                created_by=patient.assigned_intern,
            )
            LabRequestEvent.objects.create(request=lab_request, action=LabRequestEvent.Action.CREATED, by=patient.assigned_intern)
            for action, actor in [("submit", patient.assigned_intern), ("approve", supervisor), ("send", secretary),
                                  ("receive", secretary), ("deliver", secretary)]:
                perform_lab_action(lab_request, action, actor, checked=True)
                if action == target:
                    break

        Complaint.objects.create(branch=branch, patient=patients[3], category=Complaint.Category.WAITING,
                                 description="انتظرت أكثر من ساعة قبل الدخول", created_by=secretary,
                                 follow_up_due=today - timedelta(days=1))
        Complaint.objects.create(branch=branch, patient=patients[5], category=Complaint.Category.PAIN,
                                 severity=Complaint.Severity.HIGH, description="ألم مستمر بعد الزرعة",
                                 concerned_staff=patients[5].assigned_intern, created_by=secretary)

        course = Course.objects.create(branch=branch, name="دبلومة زراعة الأسنان", code="IMP-2026-A",
                                       start_date=today - timedelta(days=60), fee=Decimal("45000"), created_by=owner)
        for intern in interns:
            candidate = Candidate.objects.create(full_name=str(intern), phone_primary=f"012{30000000 + intern.pk:08d}",
                                                 university="جامعة القاهرة", graduation_year=2024, user=intern)
            enrollment = Enrollment.objects.create(candidate=candidate, course=course, enrolled_on=today - timedelta(days=60),
                                                   agreed_fee=course.fee, discount=Decimal("5000"))
            Installment.objects.create(enrollment=enrollment, number=1, due_date=today - timedelta(days=60), amount=Decimal("10000"))
            for n in range(3):
                Installment.objects.create(enrollment=enrollment, number=n + 2, due_date=today - timedelta(days=30) + timedelta(days=30 * n),
                                           amount=Decimal("10000"))
            Payment.objects.create(enrollment=enrollment, amount=Decimal("10000"), paid_on=today - timedelta(days=60),
                                   method=PaymentMethod.CASH, created_by=secretary)
            if rng.random() < 0.5:
                Payment.objects.create(enrollment=enrollment, amount=Decimal("10000"), paid_on=today - timedelta(days=25),
                                       method=PaymentMethod.INSTAPAY, reference=f"IP{rng.randint(10000, 99999)}", created_by=secretary)

        supplier = Supplier.objects.create(name="شركة المستلزمات الطبية", phone="0223456789")
        market = Supplier.objects.create(name="سوبر ماركت الحي")
        categories = {c.name_en: c for c in PurchaseCategory.objects.all()}
        purchase = Purchase.objects.create(branch=branch, supplier=supplier, purchase_date=today - timedelta(days=3),
                                           invoice_number="INV-1001", created_by=secretary)
        PurchaseItem.objects.create(purchase=purchase, category=categories["Consumables (gloves, masks, gauze...)"],
                                    description="جوانتي لاتكس", quantity=10, unit="علبة", unit_price=Decimal("120"))
        PurchaseItem.objects.create(purchase=purchase, category=categories["Anaesthesia"], description="بنج", quantity=5,
                                    unit="علبة", unit_price=Decimal("450"))
        purchase = Purchase.objects.create(branch=branch, supplier=market, purchase_date=today - timedelta(days=1), created_by=secretary)
        PurchaseItem.objects.create(purchase=purchase, category=categories["Tea, coffee & sugar"], description="شاي وسكر",
                                    quantity=1, unit_price=Decimal("250"))
        PurchaseItem.objects.create(purchase=purchase, category=categories["Food & candies"], description="بسكويت وحلويات",
                                    quantity=1, unit_price=Decimal("180"))

        self.stdout.write(self.style.SUCCESS(
            "Demo data loaded. Users: owner, secretary, supervisor, intern1..intern4 (password as given)."
        ))
