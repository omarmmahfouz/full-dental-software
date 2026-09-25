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
from apps.charting.models import Examination, PlanItem, ToothChange, TreatmentPlan
from apps.charting.rules import apply_changes, exam_changes
from apps.clinical.models import ChartEffect, Lab, LabRequest, LabRequestEvent, LabWorkType, TreatmentStep, TreatmentStepType
from apps.clinical.services import perform_lab_action
from apps.clinical.views import record_treatment_on_chart
from apps.complaints.models import Complaint
from apps.core.models import Branch
from apps.dentists.models import Dentist
from apps.patients.models import Lead, MedicalCondition, MissingTeeth, Patient, ReferralSource
from apps.purchasing.models import Purchase, PurchaseCategory, PurchaseItem, Supplier
from apps.scheduling.models import Appointment, Room, RoomShift
from apps.surgery.models import ImplantSystem, Surgery, SurgerySite
from apps.surgery.views import complete_plan_for_surgery, update_chart_for_surgery

FIRST = ["محمد", "أحمد", "محمود", "مصطفى", "علي", "حسن", "إبراهيم", "يوسف", "سارة", "منى", "هبة", "فاطمة", "نادية", "سعاد", "أمل"]
LAST = ["عبد الله", "السيد", "حسين", "عبد الرحمن", "إبراهيم", "مصطفى", "الشريف", "عثمان", "سليمان", "فؤاد"]

# Implant cases: (sites, surgery extras). Each site: (tooth, procedures, diameter, length)
CASES = [
    ([(36, ["flap", "simple_implant"], "4.5", "10")], {}),
    ([(46, ["flap", "simple_implant"], "5.0", "8.5"), (47, ["flap", "simple_implant"], "5.0", "8.5")], {}),
    ([(11, ["extraction", "immediate_implant"], "3.5", "13")], {"temporary": Surgery.Temporary.CROWN}),
    ([(26, ["flap", "simple_implant", "open_sinus"], "4.5", "10")],
     {"difficulty": Surgery.Difficulty.ADVANCED, "sinus_approach": "Lateral window", "sinus_fill_material": "Xenograft",
      "membrane_used": True, "membrane_material": "Collagen", "membrane_size": "20 x 30"}),
    ([(16, ["flap", "simple_implant", "closed_sinus"], "5.0", "8")], {"difficulty": Surgery.Difficulty.MODERATE}),
    ([(35, ["flap", "simple_implant", "gbr"], "3.8", "11.5"), (36, ["flap", "simple_implant", "gbr"], "4.5", "10")],
     {"difficulty": Surgery.Difficulty.ADVANCED, "bone_particle": Surgery.Particle.MIX, "autogenous_percent": 50,
      "membrane_used": True, "membrane_material": "Collagen", "tacks_count": 4}),
    ([(14, ["flap", "simple_implant", "expansion"], "3.5", "11.5"), (15, ["flap", "simple_implant", "expansion"], "3.5", "11.5")],
     {"difficulty": Surgery.Difficulty.MODERATE}),
    ([(45, ["extraction", "immediate_implant"], "4.0", "11.5")], {}),
    ([(12, ["flap", "simple_implant", "splitting"], "3.0", "13"), (22, ["flap", "simple_implant", "splitting"], "3.0", "13")],
     {"difficulty": Surgery.Difficulty.MODERATE}),
    ([(37, ["flap", "simple_implant"], "5.0", "8.5")], {}),
    ([(24, ["guided", "simple_implant"], "3.8", "11.5"), (25, ["guided", "simple_implant"], "4.0", "10")], {}),
    ([(46, ["extraction", "immediate_implant", "gbr"], "5.0", "10")],
     {"difficulty": Surgery.Difficulty.MODERATE, "bone_particle": Surgery.Particle.XENOGRAFT}),
    ([(36, ["flap", "simple_implant"], "4.5", "11.5"), (46, ["flap", "simple_implant"], "4.5", "11.5")], {}),
    ([(21, ["flap", "simple_implant", "gbr"], "3.5", "13")],
     {"difficulty": Surgery.Difficulty.ADVANCED, "block_graft": True, "block_donor": Surgery.BlockDonor.RAMUS,
      "cut_by": Surgery.CutBy.PIEZO, "screws_count": 2}),
]


class Command(BaseCommand):
    help = "Load sample data into an empty trial database (users, patients, visits, charts, surgeries, lab, installments...)."

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
        today = timezone.localdate()
        now = timezone.now()

        def user(username, first, last, role, staff=False):
            obj = User.objects.create_user(username, password=password, first_name=first, last_name=last, is_staff=staff)
            obj.groups.add(Group.objects.get(name=role))
            obj.profile.branch = branch
            obj.profile.save()
            return obj

        def at(day, hour=12):
            return timezone.make_aware(datetime.combine(day, time(hour)))

        owner = user("owner", "Dr. Owner", "", "owner", staff=True)
        secretary = user("secretary", "منة", "السكرتيرة", "secretary")
        supervisor_user = user("supervisor", "Dr. Khaled", "(Supervisor)", "supervisor")

        # ---------------------------------------------------------- dentists
        supervisor = Dentist.objects.create(full_name="Dr. Khaled Mansour", kind=Dentist.Kind.SUPERVISOR, branch=branch,
                                            user=supervisor_user, phone="01000000001", created_by=owner)
        surgery_supervisor = Dentist.objects.create(full_name="Dr. Hesham Fawzy", kind=Dentist.Kind.SUPERVISOR,
                                                    branch=branch, phone="01000000002", notes="Surgery days",
                                                    created_by=owner)
        course = Course.objects.create(branch=branch, name="Implant diploma", code="IMP-2026-A",
                                       start_date=today - timedelta(days=200), fee=Decimal("45000"),
                                       implants_required=10, created_by=owner)
        candidates = []
        for i, (name, code) in enumerate([("Dr. Ahmed Samir", "C-101"), ("Dr. Nour Hassan", "C-102"),
                                          ("Dr. Karim Adel", "C-103"), ("Dr. Yasmin Ali", "C-104")], 1):
            login = user(f"dentist{i}", name, "", "dentist")
            candidate = Candidate.objects.create(
                code=code, full_name=name, certificate_name=name.replace("Dr. ", ""), phone_primary=f"0123000000{i}",
                whatsapp=f"0123000000{i}", university="Cairo University", graduation_year=2022 + i % 3,
                nationality="Egyptian", created_by=secretary,
            )
            dentist = candidate.dentist
            dentist.user, dentist.branch = login, branch
            dentist.save()
            candidates.append(dentist)
            enrollment = Enrollment.objects.create(candidate=candidate, course=course, enrolled_on=today - timedelta(days=200),
                                                   agreed_fee=course.fee, discount=Decimal("5000"))
            Installment.objects.create(enrollment=enrollment, number=1, due_date=today - timedelta(days=200), amount=Decimal("10000"))
            for n in range(3):
                Installment.objects.create(enrollment=enrollment, number=n + 2,
                                           due_date=today - timedelta(days=40) + timedelta(days=30 * n), amount=Decimal("10000"))
            Payment.objects.create(enrollment=enrollment, amount=Decimal("10000"), paid_on=today - timedelta(days=200),
                                   method=PaymentMethod.CASH, created_by=secretary)
            if i % 2:
                Payment.objects.create(enrollment=enrollment, amount=Decimal("10000"), paid_on=today - timedelta(days=35),
                                       method=PaymentMethod.INSTAPAY, reference=f"IP{rng.randint(10000, 99999)}",
                                       created_by=secretary)
        training = Dentist.objects.create(full_name="Dr. Omar Tarek", kind=Dentist.Kind.TRAINING, branch=branch,
                                          user=user("dentist5", "Dr. Omar Tarek", "", "dentist"), phone="01000000005",
                                          created_by=owner)
        fulltime = Dentist.objects.create(full_name="Dr. Mona Refaat", kind=Dentist.Kind.FULLTIME, branch=branch,
                                          user=user("dentist6", "Dr. Mona Refaat", "", "dentist"), phone="01000000006",
                                          created_by=owner)
        treating = candidates + [fulltime]

        # ---------------------------------------------------------- patients & leads
        sources = list(ReferralSource.objects.all())
        conditions = {c.name_en: c for c in MedicalCondition.objects.all()}
        teeth_ranges = [MissingTeeth.SINGLE, MissingTeeth.MULTIPLE, MissingTeeth.FULL_ARCH]

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
                missing_teeth=rng.choice(teeth_ranges), referral_source=source,
                referred_by=patients[0] if source.asks_for_patient and patients else None,
                assigned_dentist=treating[i % len(treating)], created_by=secretary,
            )
            told = rng.sample(["Diabetes", "High blood pressure", "Smoker", "Heart disease"], rng.randint(0, 2))
            patient.medical_conditions.set([conditions[c] for c in told if c in conditions])
            patients.append(patient)

        for i in range(10):
            Lead.objects.create(
                branch=branch, full_name=name(), phone_primary=f"011{20000000 + i * 3571:08d}", age=rng.randint(35, 75),
                missing_teeth=rng.choice(teeth_ranges), referral_source=rng.choice(sources),
                status=rng.choice([Lead.Status.NEW, Lead.Status.FOLLOW_UP, Lead.Status.BOOKED]),
                next_call_at=now + timedelta(hours=rng.randint(-24, 48)), created_by=secretary,
            )

        # ---------------------------------------------------------- room schedule (Tuesday = surgery day)
        rooms = list(Room.objects.filter(branch=branch))
        for offset in range(-14, 7):
            day = today + timedelta(days=offset)
            if day.weekday() == 4:  # Friday off
                continue
            surgery_day = day.weekday() == 1
            for room, dentist in zip(rooms, treating):
                RoomShift.objects.create(
                    room=room, date=day, start_time=time(10), end_time=time(16), dentist=dentist,
                    supervisor=surgery_supervisor if surgery_day else supervisor,
                    day_type=RoomShift.DayType.SURGERY if surgery_day else RoomShift.DayType.REGULAR, created_by=secretary,
                )

        types = {t.name_en: t for t in TreatmentStepType.objects.all()}
        visit_types = list(TreatmentStepType.objects.filter(chart_effect=ChartEffect.NONE, surgery_procedure=""))
        for offset in range(-14, 1):
            day = today + timedelta(days=offset)
            if day.weekday() == 4:
                continue
            for slot, patient in enumerate(rng.sample(patients, 6)):
                start = at(day, 10 + slot)
                room = rooms[treating.index(patient.assigned_dentist) % len(rooms)]
                appointment = Appointment(branch=branch, patient=patient, scheduled_at=start, room=room,
                                          dentist=patient.assigned_dentist, purpose=rng.choice(visit_types).name_en,
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
                        patient=patient, appointment=appointment, step_type=rng.choice(visit_types),
                        teeth=rng.choice(["", "36", "11, 21"]), performed_at=entered, operator=patient.assigned_dentist,
                        assistant=training if rng.random() < 0.4 else None, supervisor=supervisor,
                        created_by=patient.assigned_dentist.user,
                    )
                    if rng.random() < 0.6:
                        step.verified_by, step.verified_at, step.grade = supervisor_user, left, rng.randint(3, 5)
                        step.save()

        # ---------------------------------------------------------- charts, plans and implant surgeries
        systems = list(ImplantSystem.objects.all()[:5])
        for index, (sites, extras) in enumerate(CASES):
            extras = dict(extras)
            patient = patients[index]
            operator = candidates[index % len(candidates)]
            operator_2 = candidates[(index + 1) % len(candidates)]
            surgery_date = today - timedelta(days=210 - index * 14)
            exam_date = surgery_date - timedelta(days=21)
            implant_teeth = [tooth for tooth, procedures, _d, _l in sites]
            to_extract = [tooth for tooth, procedures, _d, _l in sites if "extraction" in procedures]
            carious = [t for t in (17, 27, 34, 44) if t not in implant_teeth][: 1 + index % 2]
            smoker = index % 4 == 0

            exam = Examination.objects.create(
                patient=patient, exam_date=exam_date, examined_by=operator, supervisor=supervisor,
                chief_complaint="Missing teeth, wants fixed teeth (implants).",
                teeth_missing=", ".join(str(t) for t in implant_teeth if t not in to_extract),
                teeth_hopeless=", ".join(str(t) for t in to_extract), teeth_carious=", ".join(str(t) for t in carious),
                teeth_filled="16" if 16 not in implant_teeth else "", cbct_requested=True, cbct_done=True,
                smoker=smoker, cigarettes_per_day=15 if smoker else None, bp_clinic_systolic=rng.randint(110, 145),
                bp_clinic_diastolic=rng.randint(70, 95), cooperation_score=rng.randint(6, 10),
                implant_willingness_score=rng.randint(7, 10), created_by=operator.user,
            )
            exam.conditions.set(patient.medical_conditions.all())
            apply_changes(patient, exam_changes(patient, exam), operator.user, ToothChange.Source.EXAM,
                          examination=exam, when=at(exam_date, 11))

            plan = TreatmentPlan.objects.create(patient=patient, title="Implant treatment plan", dentist=operator,
                                                status=TreatmentPlan.Status.APPROVED, approved_by=supervisor,
                                                approved_at=at(exam_date, 13), created_by=operator.user)
            teeth_text = ", ".join(str(t) for t in implant_teeth)
            if carious:
                PlanItem.objects.create(plan=plan, phase=PlanItem.Phase.PREPARATION, step_type=types["Composite restoration"],
                                        teeth=", ".join(str(t) for t in carious))
            implant_type = types["Immediate implant"] if to_extract else types["Implant placement"]
            PlanItem.objects.create(plan=plan, phase=PlanItem.Phase.SURGICAL, step_type=implant_type, teeth=teeth_text)
            for step_name in ("Second stage / healing abutment", "Digital scan", "Final prosthesis delivery"):
                if step_name == "Second stage / healing abutment" and to_extract:
                    continue
                PlanItem.objects.create(plan=plan, phase=PlanItem.Phase.PROSTHETIC, step_type=types[step_name], teeth=teeth_text)

            for tooth in carious:  # fillings done before surgery: caries -> filled on the chart
                step = TreatmentStep.objects.create(
                    patient=patient, step_type=types["Composite restoration"], teeth=str(tooth), surfaces="MO",
                    material="composite", performed_at=at(exam_date + timedelta(days=7)), operator=operator,
                    supervisor=supervisor, created_by=operator.user,
                )
                record_treatment_on_chart(step, operator.user)

            surgery = Surgery.objects.create(
                branch=branch, patient=patient, date=surgery_date, instructor=surgery_supervisor, operator_1=operator,
                operator_2=operator_2, assistant=training, suture_size="4-0", suture_material=Surgery.SutureMaterial.VICRYL,
                xray_taken=True, temporary=extras.pop("temporary", Surgery.Temporary.HEALING_COLLAR if to_extract else ""),
                created_by=operator.user, **extras,
            )
            system = systems[index % len(systems)]
            for tooth, procedures, diameter, length in sites:
                SurgerySite.objects.create(
                    surgery=surgery, tooth=tooth, implant_system=system, implant_diameter=Decimal(diameter),
                    implant_length=Decimal(length), insertion_torque=rng.choice([25, 30, 35, 40, 45]),
                    isq=rng.randint(58, 78), subcrestal=rng.random() < 0.3, lot_number=f"L{rng.randint(10000, 99999)}",
                    **{name: True for name in procedures},
                )
            update_chart_for_surgery(surgery, operator.user)
            complete_plan_for_surgery(surgery)

            # Implant life after surgery, recorded as treatments so chart and plan follow.
            if index == 2:  # one failed implant for the statistics
                fail_day = surgery_date + timedelta(days=35)
                step = TreatmentStep.objects.create(
                    patient=patient, step_type=types["Implant failure / removal"], teeth=teeth_text,
                    performed_at=at(fail_day), operator=operator, supervisor=supervisor,
                    notes="Mobile implant, no osseointegration. Removed.", created_by=operator.user,
                )
                record_treatment_on_chart(step, operator.user)
                surgery.sites.update(failure_reason="No osseointegration")
                continue
            uncover = rng.randint(75, 100)
            scan = uncover + rng.randint(10, 25)
            timeline = [("Second stage / healing abutment", uncover), ("Digital scan", scan),
                        ("Final prosthesis delivery", scan + rng.randint(14, 30))]
            if to_extract:
                timeline = timeline[1:]
            for step_name, days in timeline:
                day = surgery_date + timedelta(days=days)
                if day >= today:
                    break
                step = TreatmentStep.objects.create(
                    patient=patient, step_type=types[step_name], teeth=teeth_text, performed_at=at(day),
                    operator=operator, supervisor=supervisor, created_by=operator.user,
                )
                record_treatment_on_chart(step, operator.user)

        for patient in patients[len(CASES):len(CASES) + 4]:  # planned, not operated yet
            exam = Examination.objects.create(
                patient=patient, exam_date=today - timedelta(days=5), examined_by=patient.assigned_dentist,
                chief_complaint="Wants implants for missing lower molars.", teeth_missing="36, 46",
                teeth_carious="25", created_by=secretary,
            )
            apply_changes(patient, exam_changes(patient, exam), secretary, ToothChange.Source.EXAM, examination=exam)
            plan = TreatmentPlan.objects.create(patient=patient, title="Implant treatment plan",
                                                dentist=patient.assigned_dentist, created_by=secretary)
            PlanItem.objects.create(plan=plan, phase=PlanItem.Phase.PREPARATION, step_type=types["Composite restoration"], teeth="25")
            PlanItem.objects.create(plan=plan, phase=PlanItem.Phase.SURGICAL, step_type=types["Implant placement"], teeth="36, 46")

        # ---------------------------------------------------------- lab, complaints, purchases
        lab = Lab.objects.first()
        work_types = list(LabWorkType.objects.all())
        for patient, target in zip(patients[:6], ["submit", "approve", "send", "receive", "deliver", None]):
            dentist = patient.assigned_dentist
            lab_request = LabRequest.objects.create(
                branch=branch, patient=patient, lab=lab, work_type=rng.choice(work_types), teeth="36",
                shade="A2", dentist=dentist, due_date=today + timedelta(days=rng.randint(-3, 7)), created_by=dentist.user,
            )
            LabRequestEvent.objects.create(request=lab_request, action=LabRequestEvent.Action.CREATED, by=dentist.user)
            for action, actor in [("submit", dentist.user), ("approve", supervisor_user), ("send", secretary),
                                  ("receive", secretary), ("deliver", secretary)]:
                perform_lab_action(lab_request, action, actor, checked=True)
                if action == target:
                    break

        Complaint.objects.create(branch=branch, patient=patients[3], category=Complaint.Category.WAITING,
                                 description="انتظرت أكثر من ساعة قبل الدخول", created_by=secretary,
                                 follow_up_due=today - timedelta(days=1))
        Complaint.objects.create(branch=branch, patient=patients[5], category=Complaint.Category.PAIN,
                                 severity=Complaint.Severity.HIGH, description="ألم مستمر بعد الزرعة",
                                 concerned_dentist=patients[5].assigned_dentist, created_by=secretary)

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
            "Demo data loaded. Users: owner, secretary, supervisor, dentist1..dentist4 (course candidates), "
            "dentist5 (training dentist), dentist6 (full-time dentist) - password as given."
        ))
