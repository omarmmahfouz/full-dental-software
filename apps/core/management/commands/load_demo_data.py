"""Fill an EMPTY trial database with sample data so the staff can practise.

    python manage.py load_demo_data --password demo12345

Never run this on the real clinic database.
"""

import csv
import random
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

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
from apps.patients.calllists import create_call_list
from apps.patients.models import CallListEntry, Lead, MedicalCondition, MissingTeeth, Patient, ReferralSource
from apps.prescriptions.models import Prescription, PrescriptionLine
from apps.prescriptions.services import best_template, surgery_procedures
from apps.purchasing.models import Purchase, PurchaseCategory, PurchaseItem, Supplier
from apps.scheduling.models import Appointment, MessageTemplate, Room, RoomShift
from apps.scheduling.whatsapp import record
from apps.stock.importer import import_items, parse
from apps.stock.models import StockCategory, StockItem, StockMovement
from apps.stock.services import record_movement, sync_purchase
from apps.surgery.models import ImplantSystem, Surgery, SurgerySite
from apps.surgery.views import complete_plan_for_surgery, update_chart_for_surgery

STOCK_LIST = Path(__file__).resolve().parents[3] / "stock" / "data" / "cia_material_instrument_list.csv"
DEMO_USERS = ["owner", "headcia", "teamhead", "dentist1", "dentist2", "secretary", "stock"]

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
        parser.add_argument("--if-empty", action="store_true",
                            help="When the database already has patients, keep it as it is instead of failing.")

    @transaction.atomic
    def handle(self, *args, password, if_empty, **options):
        if Patient.objects.exists():
            if not if_empty:
                raise CommandError("The database already has patients. Demo data is only for an empty trial database.")
            self.stdout.write("The practice database already has data: kept as it is.")
            missing = [name for name in DEMO_USERS if not get_user_model().objects.filter(username=name).exists()]
            if missing:
                self.stdout.write(self.style.WARNING(
                    f"These practice logins are missing: {', '.join(missing)}. This practice copy was made by an "
                    "older version. To get the new sample data and logins, close this window, delete the 'data' "
                    "folder and start again."
                ))
            return
        call_command("setup_clinic", stdout=self.stdout)
        rng = random.Random(7)
        User = get_user_model()
        branch = Branch.objects.get(code="CIA")
        today = timezone.localdate()
        now = timezone.now()

        def user(username, first, last, *roles, staff=False):
            obj = User.objects.create_user(username, password=password, first_name=first, last_name=last, is_staff=staff)
            obj.groups.add(*Group.objects.filter(name__in=roles))
            obj.profile.branch = branch
            obj.profile.save()
            return obj

        def at(day, hour=12):
            return timezone.make_aware(datetime.combine(day, time(hour)))

        owner = user("owner", "Dr. Owner", "(CEO)", "owner", staff=True)
        head = user("headcia", "Dr. Tamer", "(Head of CIA)", "head_cia")
        secretary = user("secretary", "منة", "السكرتيرة", "secretary")
        stock_user = user("stock", "أشرف", "(المخازن)", "stock")
        Branch.objects.filter(pk=branch.pk).update(phone="0223456789", address="Cairo")

        # ---------------------------------------------------------- dentists
        # Only the CIA dentists log in; supervisors, candidates and training dentists are names.
        supervisor = Dentist.objects.create(full_name="Dr. Khaled Mansour", kind=Dentist.Kind.SUPERVISOR, branch=branch,
                                            phone="01000000001", created_by=owner)
        surgery_supervisor = Dentist.objects.create(full_name="Dr. Hesham Fawzy", kind=Dentist.Kind.SUPERVISOR,
                                                    branch=branch, phone="01000000002", notes="Surgery days",
                                                    created_by=owner)
        course = Course.objects.create(branch=branch, name="Implant diploma", code="IMP-2026-A",
                                       start_date=today - timedelta(days=200), fee=Decimal("45000"),
                                       implants_required=10, created_by=owner)
        candidates = []
        for i, (name, code) in enumerate([("Dr. Ahmed Samir", "C-101"), ("Dr. Nour Hassan", "C-102"),
                                          ("Dr. Karim Adel", "C-103"), ("Dr. Yasmin Ali", "C-104")], 1):
            candidate = Candidate.objects.create(
                code=code, full_name=name, certificate_name=name.replace("Dr. ", ""), phone_primary=f"0123000000{i}",
                whatsapp=f"0123000000{i}", university="Cairo University", graduation_year=2022 + i % 3,
                nationality="Egyptian", created_by=secretary,
            )
            dentist = candidate.dentist
            dentist.branch = branch
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
        Dentist.objects.create(full_name="Dr. Omar Tarek", kind=Dentist.Kind.TRAINING, branch=branch,
                               phone="01000000005", created_by=owner)
        cia_dentists = []
        for username, name, phone, roles in [("dentist1", "Dr. Mona Refaat", "01000000006", ("dentist",)),
                                              ("dentist2", "Dr. Sherif Nabil", "01000000007", ("dentist",)),
                                              ("teamhead", "Dr. Rania Adel", "01000000008", ("dentist", "team_head"))]:
            cia_dentists.append(Dentist.objects.create(
                full_name=name, kind=Dentist.Kind.FULLTIME, branch=branch, phone=phone, created_by=owner,
                user=user(username, name, "", *roles),
            ))
        fulltime = cia_dentists[0]
        treating = candidates + [fulltime]

        def recorder(dentist):
            """Who typed it in: the dentist themself, or a CIA dentist for a candidate."""
            return dentist.user or cia_dentists[dentist.pk % 2].user

        def helper(dentist):
            """The CIA dentist who assists a candidate."""
            return None if dentist.user_id else cia_dentists[dentist.pk % 2]

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
                        assistant=helper(patient.assigned_dentist), supervisor=supervisor,
                        notes=rng.choice(["", "", "Patient anxious, needs short visits.", "Good oral hygiene."]),
                        created_by=recorder(patient.assigned_dentist),
                    )
                    if rng.random() < 0.6:
                        step.verified_by, step.verified_at, step.grade = head, left, rng.randint(3, 5)
                        step.save()

        # ---------------------------------------------------------- upcoming appointments (WhatsApp reminders)
        upcoming, pick = [], random.Random(11)  # own generator: the data below stays the same
        for offset in range(1, 8):
            day = today + timedelta(days=offset)
            if day.weekday() == 4:
                continue
            for slot, patient in enumerate(pick.sample(patients, 3)):
                upcoming.append(Appointment.objects.create(
                    branch=branch, patient=patient, scheduled_at=at(day, 11 + slot), dentist=patient.assigned_dentist,
                    room=rooms[treating.index(patient.assigned_dentist) % len(rooms)],
                    purpose=pick.choice(visit_types).name_en, created_by=secretary,
                ))
        # Booked last week, except the last three: new bookings still to confirm on WhatsApp.
        Appointment.objects.filter(pk__in=[a.pk for a in upcoming[:-3]]).update(created_at=now - timedelta(days=8))

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
                implant_willingness_score=rng.randint(7, 10), created_by=recorder(operator),
            )
            exam.conditions.set(patient.medical_conditions.all())
            apply_changes(patient, exam_changes(patient, exam), recorder(operator), ToothChange.Source.EXAM,
                          examination=exam, when=at(exam_date, 11))

            plan = TreatmentPlan.objects.create(patient=patient, title="Implant treatment plan", dentist=operator,
                                                difficulty=extras.get("difficulty", Surgery.Difficulty.SIMPLE),
                                                status=TreatmentPlan.Status.APPROVED, approved_by=supervisor,
                                                approved_at=at(exam_date, 13), created_by=recorder(operator))
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
                    supervisor=supervisor, created_by=recorder(operator),
                )
                record_treatment_on_chart(step, recorder(operator))

            surgery = Surgery.objects.create(
                branch=branch, patient=patient, date=surgery_date, instructor=surgery_supervisor, operator_1=operator,
                operator_2=operator_2, assistant=cia_dentists[index % 2], suture_size="4-0", suture_material=Surgery.SutureMaterial.VICRYL,
                xray_taken=True, temporary=extras.pop("temporary", Surgery.Temporary.HEALING_COLLAR if to_extract else ""),
                created_by=recorder(operator), **extras,
            )
            system = systems[index % len(systems)]
            for tooth, procedures, diameter, length in sites:
                SurgerySite.objects.create(
                    surgery=surgery, tooth=tooth, implant_system=system, implant_diameter=Decimal(diameter),
                    implant_length=Decimal(length), insertion_torque=rng.choice([25, 30, 35, 40, 45]),
                    isq=rng.randint(58, 78), subcrestal=rng.random() < 0.3, lot_number=f"L{rng.randint(10000, 99999)}",
                    **{name: True for name in procedures},
                )
            update_chart_for_surgery(surgery, recorder(operator))
            complete_plan_for_surgery(surgery)

            # Implant life after surgery, recorded as treatments so chart and plan follow.
            if index == 2:  # one failed implant for the statistics
                fail_day = surgery_date + timedelta(days=35)
                step = TreatmentStep.objects.create(
                    patient=patient, step_type=types["Implant failure / removal"], teeth=teeth_text,
                    performed_at=at(fail_day), operator=operator, supervisor=supervisor,
                    notes="Mobile implant, no osseointegration. Removed.", created_by=recorder(operator),
                )
                record_treatment_on_chart(step, recorder(operator))
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
                    operator=operator, supervisor=supervisor, created_by=recorder(operator),
                )
                record_treatment_on_chart(step, recorder(operator))

        waiting = patients[len(CASES):len(CASES) + 6]  # planned, not operated yet
        for number, patient in enumerate(waiting):
            by = recorder(patient.assigned_dentist)
            exam = Examination.objects.create(
                patient=patient, exam_date=today - timedelta(days=5 + number * 3), examined_by=patient.assigned_dentist,
                supervisor=supervisor, chief_complaint="Wants implants for missing lower molars.", teeth_missing="36, 46",
                teeth_carious="25", created_by=by,
            )
            apply_changes(patient, exam_changes(patient, exam), by, ToothChange.Source.EXAM, examination=exam)
            guided = number % 2 == 0
            plan = TreatmentPlan.objects.create(
                patient=patient, title="Implant treatment plan", dentist=patient.assigned_dentist, created_by=by,
                difficulty=[TreatmentPlan.Difficulty.SIMPLE, TreatmentPlan.Difficulty.MODERATE][number % 3 == 1],
                status=TreatmentPlan.Status.APPROVED if number < 4 else TreatmentPlan.Status.PROPOSED,
                approved_by=supervisor if number < 4 else None,
            )
            PlanItem.objects.create(plan=plan, phase=PlanItem.Phase.PREPARATION, step_type=types["Composite restoration"], teeth="25")
            PlanItem.objects.create(plan=plan, phase=PlanItem.Phase.SURGICAL, teeth="36, 46",
                                    step_type=types["Guided implant surgery" if guided else "Implant placement"])

        # ---------------------------------------------------------- lab, complaints
        lab = Lab.objects.first()
        work_types = list(LabWorkType.objects.all())
        for number, (patient, target) in enumerate(zip(patients[:6], ["submit", "approve", "send", "receive", "deliver", None])):
            dentist = patient.assigned_dentist
            by = recorder(dentist)
            reviewed = number % 2 == 1  # the CIA dentist chose the reviewing supervisor's name
            lab_request = LabRequest.objects.create(
                branch=branch, patient=patient, lab=lab, work_type=rng.choice(work_types), teeth="36",
                shade="A2", dentist=dentist, supervisor=supervisor if reviewed else None,
                due_date=today + timedelta(days=rng.randint(-3, 7)), created_by=by,
            )
            LabRequestEvent.objects.create(request=lab_request, action=LabRequestEvent.Action.CREATED, by=by)
            for action, actor in [("submit", by), ("approve", head), ("send", secretary),
                                  ("receive", secretary), ("deliver", secretary)]:
                if action == "approve" and lab_request.status != LabRequest.Status.PENDING_REVIEW:
                    continue  # already reviewed by the named supervisor
                perform_lab_action(lab_request, action, actor, checked=True)
                if action == target:
                    break

        Complaint.objects.create(branch=branch, patient=patients[3], category=Complaint.Category.WAITING,
                                 description="انتظرت أكثر من ساعة قبل الدخول", created_by=secretary,
                                 follow_up_due=today - timedelta(days=1))
        Complaint.objects.create(branch=branch, patient=patients[5], category=Complaint.Category.PAIN,
                                 severity=Complaint.Severity.HIGH, description="ألم مستمر بعد الزرعة",
                                 concerned_dentist=patients[5].assigned_dentist, created_by=secretary)

        # ---------------------------------------------------------- stock and purchases
        with open(STOCK_LIST, newline="", encoding="utf-8") as handle:
            entries = parse(csv.reader(handle))
        import_items(entries, StockCategory.objects.get(name_en="Instruments"), stock_user, note="Opening stock")
        food = StockCategory.objects.get(name_en="Food & beverage")
        for name, unit, quantity, minimum in [("Tea", "box", 6, 2), ("Coffee", "pack", 1, 2), ("Sugar", "kg", 4, 2),
                                              ("Mineral water", "bottle", 24, 12), ("Biscuits", "pack", 10, 5)]:
            item = StockItem.objects.create(name=name, category=food, unit=unit, min_quantity=minimum, created_by=stock_user)
            record_movement(item, StockMovement.Kind.COUNT, quantity, stock_user, notes="Opening stock")
        for name, minimum in [("Carpule articaine (Spain)", 20), ("Composite A2", 1), ("Etchant tips", 5), ("Floss", 1)]:
            StockItem.objects.filter(name=name).update(min_quantity=minimum)
        for name, quantity, where in [("Carpule articaine (Spain)", 12, "Room 1"), ("Etchant tips", 6, "Room 3"),
                                      ("Composite A2", 1, "Room 2"), ("Coffee", 1, "Kitchen")]:
            record_movement(StockItem.objects.get(name=name), StockMovement.Kind.OUT, quantity, stock_user,
                            destination=where, moved_at=now - timedelta(days=rng.randint(1, 10)))

        supplier = Supplier.objects.create(name="شركة المستلزمات الطبية", phone="0223456789")
        market = Supplier.objects.create(name="سوبر ماركت الحي")
        categories = {c.name_en: c for c in PurchaseCategory.objects.all()}
        purchase = Purchase.objects.create(branch=branch, supplier=supplier, purchase_date=today - timedelta(days=3),
                                           invoice_number="INV-1001", created_by=stock_user)
        PurchaseItem.objects.create(purchase=purchase, category=categories["Consumables (gloves, masks, gauze...)"],
                                    description="جوانتي لاتكس", quantity=10, unit="علبة", unit_price=Decimal("120"))
        PurchaseItem.objects.create(purchase=purchase, category=categories["Anaesthesia"], description="Articaine carpules",
                                    quantity=50, unit="carpule", unit_price=Decimal("18"),
                                    stock_item=StockItem.objects.get(name="Carpule articaine (Spain)"))
        sync_purchase(purchase, stock_user)
        StockMovement.objects.filter(purchase_item__purchase=purchase).update(expiry_date=today + timedelta(days=45),
                                                                              lot="ART-2291")
        purchase = Purchase.objects.create(branch=branch, supplier=market, purchase_date=today - timedelta(days=1),
                                           created_by=secretary)
        PurchaseItem.objects.create(purchase=purchase, category=categories["Tea, coffee & sugar"], description="Tea",
                                    quantity=2, unit="box", unit_price=Decimal("125"), stock_item=StockItem.objects.get(name="Tea"))
        PurchaseItem.objects.create(purchase=purchase, category=categories["Food & candies"], description="بسكويت وحلويات",
                                    quantity=1, unit_price=Decimal("180"))
        sync_purchase(purchase, secretary)

        # ---------------------------------------------------------- prescription and patients to call
        last_surgery = Surgery.objects.order_by("-date").first()
        template = best_template(surgery_procedures(last_surgery))
        prescription = Prescription.objects.create(patient=last_surgery.patient, surgery=last_surgery,
                                                   prescribed_on=last_surgery.date, dentist=last_surgery.operator_1,
                                                   created_by=recorder(last_surgery.operator_1))
        for line in template.lines.all():
            PrescriptionLine.objects.create(prescription=prescription, drug=line.group.drugs.first(),
                                            dose=line.dose or line.group.dose)
        guided = [p for number, p in enumerate(waiting) if number % 2 == 0]
        call_list = create_call_list("Treatment plans: Guided implant surgery",
                                     "Please call to book the guided surgery day (Tuesday).",
                                     [(p, "Guided implant surgery 36, 46") for p in guided], head)
        first = call_list.entries.first()
        first.outcome, first.response = CallListEntry.Outcome.BOOKED, "Booked next Tuesday 11 am"
        first.attempts, first.called_at, first.called_by = 1, now, secretary
        first.save()

        # ---------------------------------------------------------- WhatsApp: one confirmation already sent
        record(MessageTemplate.Kind.CONFIRMATION, upcoming[-3], secretary)

        self.stdout.write(self.style.SUCCESS(
            "Demo data loaded (password as given). Users: owner (CEO), headcia (head of CIA), teamhead (head of the "
            "CIA dentists team), dentist1 and dentist2 (CIA dentists), secretary, stock (stock manager). "
            "Candidates, training dentists and supervisors have no login."
        ))
