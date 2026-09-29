"""Sample data of El Khadem Dental Clinic for the practice copy (called by ``load_demo_data``): Dr. Amr El Khadem
and his reception, the visiting specialists, patients of the clinic and a doctor's own patients, a month of visits
in the four shared rooms with bills and payments, referrals, an endodontic case, a TMJ examination, an orthodontic
case, a shade taken and its lab request, and a comprehensive treatment plan."""

import random
from datetime import timedelta
from decimal import Decimal

from apps.academy.models import PaymentMethod
from apps.billing.models import FawryMachine, PatientPayment, Service, create_bill
from apps.charting.models import PlanItem, TreatmentPlan
from apps.clinical.models import Lab, LabRequest, LabRequestEvent, LabWorkType
from apps.clinics.models import DoctorPayout, DoctorPrice, FeeRule
from apps.core.models import Branch
from apps.dentists.models import Dentist
from apps.patients.models import Patient
from apps.scheduling.models import Appointment, Room

from .models import (
    EndoCanal, EndoCase, EndoVisit, OrthoCase, OrthoVisit, Referral, ShadeRecord, TMJExam, TMJVisit,
)
from .services import finish_endo

SERVICES = [  # English, Arabic, price, usual lab / implant cost, quick button
    ("El Khadem examination", "كشف عيادة الخادم", 500, 0, True),
    ("Root canal (molar)", "علاج عصب ضرس", 3500, 0, False),
    ("Root canal (front tooth)", "علاج عصب سن أمامي", 2500, 0, False),
    ("Zirconia crown", "طربوش زيركون", 6000, 1500, False),
    ("Implant (El Khadem)", "زرعة (عيادة الخادم)", 18000, 5500, False),
    ("Crown on implant (El Khadem)", "تركيبة على زرعة (عيادة الخادم)", 7000, 2000, False),
    ("Occlusal splint", "جبيرة إطباق", 4000, 900, False),
    ("Orthodontics (monthly)", "تقويم (شهري)", 1500, 0, False),
    ("Surgical extraction", "خلع جراحي", 2000, 0, False),
]


def load_khadem(today, at, make_user, secretary, stock_user, owner, types):
    """Fill El Khadem (PVT). ``make_user(username, first, last, *roles)`` makes a login."""
    rng = random.Random(31)
    place = Branch.objects.get(code="PVT")
    Branch.objects.filter(pk=place.pk).update(
        phone="0233334444", address="Mohandessin, Giza", email="reception@elkhadem.example",
        opens_at=at(today, 12).time(), closes_at=at(today, 22).time(), closed_days="4")
    place.refresh_from_db()
    rooms = list(Room.objects.filter(branch=place, is_extra=False).order_by("sort_order"))

    # People: Dr. Amr runs the clinic (a doctor and its manager); El Khadem has its own reception.
    amr_user = make_user("amr", "Dr. Amr", "El Khadem", "dentist", "moderator")
    reception = make_user("khadem", "هدى", "(استقبال الخادم)", "secretary")
    endo_user = make_user("endo", "Dr. Yasser", "Hamed", "dentist")
    for person in (amr_user, reception, endo_user):
        person.profile.branch = place
        person.profile.save()
        person.profile.places.set([place])

    def doctor(name, name_ar, specialty, title, kind=Dentist.Kind.SPECIALIST, user=None, phone=""):
        dentist = Dentist.objects.create(full_name=name, name_ar=name_ar, kind=kind, specialty=specialty, title=title,
                                         user=user, branch=place, phone=phone, created_by=owner)
        dentist.places.set([place])
        return dentist

    S = Dentist.Specialty
    amr = doctor("Dr. Amr El Khadem", "د. عمرو الخادم", S.PROSTHODONTIST,
                 "Consultant of prosthodontics and implants — founder", user=amr_user, phone="01000000020")
    endo = doctor("Dr. Yasser Hamed", "د. ياسر حامد", S.ENDODONTIST, "Lecturer of endodontics",
                  user=endo_user, phone="01000000021")
    tmj = doctor("Dr. Hazem Fathy", "د. حازم فتحي", S.TMJ, "Consultant of oral surgery and TMJ disorders",
                 phone="01000000022")
    ortho = doctor("Dr. Dina Sami", "د. دينا سامي", S.ORTHODONTIST, "Specialist of orthodontics", phone="01000000023")
    surgeon = doctor("Dr. Tarek Nour", "د. طارق نور", S.ORAL_SURGEON, "Oral and maxillofacial surgeon",
                     kind=Dentist.Kind.FREELANCER, phone="01000000024")
    prostho = doctor("Dr. Laila Fouad", "د. ليلى فؤاد", S.PROSTHODONTIST, "Specialist of fixed prosthodontics",
                     kind=Dentist.Kind.FREELANCER, phone="01000000025")

    # El Khadem's price list, each doctor's own prices, and how each doctor is paid: 40% of his own patients and 30%
    # of the patients the clinic refers to him, after the lab and implant cost.
    services = {}
    for order, (name_en, name_ar, price, cost, quick) in enumerate(SERVICES, start=1):
        services[name_en] = Service.objects.create(name_en=name_en, name_ar=name_ar, price=price, cost=cost,
                                                   branch=place, quick_button=quick, sort_order=80 + order)
    exam = services["El Khadem examination"]
    for dentist, service, price, cost in [(tmj, exam, 1200, None), (amr, exam, 800, None),
                                          (ortho, exam, 600, None), (endo, services["Root canal (molar)"], 4000, None),
                                          (prostho, services["Zirconia crown"], 6500, 1700)]:
        DoctorPrice.objects.create(dentist=dentist, branch=place, service=service, price=price, cost=cost,
                                   created_by=amr_user)
    start = today - timedelta(days=90)
    for dentist in (endo, tmj, ortho, surgeon, prostho):
        FeeRule.objects.create(dentist=dentist, branch=place, method=FeeRule.Method.PERCENT, value=Decimal("40"),
                               patient_source=FeeRule.OWN, deduct_costs=True, starts_on=start, created_by=amr_user,
                               notes="His own patients")
        FeeRule.objects.create(dentist=dentist, branch=place, method=FeeRule.Method.PERCENT, value=Decimal("30"),
                               patient_source=FeeRule.CLINIC, deduct_costs=True, starts_on=start,
                               created_by=amr_user, notes="Referred by Dr. Amr")

    # Patients: new files numbered EK-…; two are Dr. Tarek's own patients.
    people = [
        ("كريم مصطفى عبد الحميد", "M", "28905011234561", "01101000001", None),
        ("نهى أحمد السيد", "F", "29206021234562", "01101000002", None),
        ("ياسمين عادل فريد", "F", "30503031234563", "01101000003", None),
        ("مروان حسام الدين علي", "M", "30807041234564", "01101000004", None),
        ("سلوى محمود رشاد", "F", "27102051234565", "01101000005", None),
        ("طارق وليد منصور", "M", "28511061234566", "01101000006", surgeon),
        ("رنا سمير إبراهيم", "F", "29609071234567", "01101000007", surgeon),
        ("هشام فاروق عزت", "M", "27704081234568", "01101000008", None),
    ]
    patients = []
    for name, gender, nid, phone, brought_by in people:
        patients.append(Patient.objects.create(
            branch=place, full_name=name, national_id=nid, phone_primary=phone, gender=gender, brought_by=brought_by,
            assigned_dentist=amr, created_by=reception, referral_notes="Dr. Tarek's patient" if brought_by else ""))
    karim, noha, yasmin, marwan, salwa, tarek_p, rana, hisham = patients

    # A month of visits in the four shared rooms: the doctors move between the rooms.
    machine = FawryMachine.objects.order_by("sort_order").first()
    visits = [  # days ago, hour, patient, doctor, room, services [(name, teeth)], paid part, method
        (27, 13, karim, amr, 0, [("El Khadem examination", "")], 1, PaymentMethod.CASH),
        (25, 17, karim, endo, 2, [("Root canal (molar)", "36")], 1, PaymentMethod.FAWRY),
        (24, 14, noha, tmj, 1, [("El Khadem examination", "")], 1, PaymentMethod.CASH),
        (20, 18, noha, tmj, 3, [("Occlusal splint", "")], 1, PaymentMethod.INSTAPAY),
        (18, 15, tarek_p, surgeon, 0, [("Surgical extraction", "38")], 1, PaymentMethod.CASH),
        (16, 19, rana, surgeon, 1, [("Implant (El Khadem)", "46")], Decimal("0.5"), PaymentMethod.FAWRY),
        (13, 16, yasmin, ortho, 2, [("El Khadem examination", ""), ("Orthodontics (monthly)", "")], 1,
         PaymentMethod.CASH),
        (10, 20, salwa, prostho, 0, [("Zirconia crown", "11, 21")], Decimal("0.7"), PaymentMethod.CASH),
        (6, 14, hisham, amr, 3, [("El Khadem examination", "")], 1, PaymentMethod.FAWRY),
        (3, 18, marwan, endo, 1, [("Root canal (front tooth)", "11")], 1, PaymentMethod.CASH),
    ]
    for days_ago, hour, patient, dentist, room, lines, part, method in visits:
        day = today - timedelta(days=days_ago)
        visit = Appointment.objects.create(branch=place, patient=patient, scheduled_at=at(day, hour), room=rooms[room],
                                           dentist=dentist, duration_minutes=45, created_by=reception)
        arrived = at(day, hour) + timedelta(minutes=rng.randint(-5, 10))
        visit.mark_arrived(arrived)
        visit.mark_entered_room(arrived + timedelta(minutes=rng.randint(3, 12)))
        visit.mark_left(visit.entered_room_at + timedelta(minutes=rng.randint(25, 70)))
        visit.save()
        bill = create_bill(patient, [{"service": services[name], "teeth": teeth} for name, teeth in lines], reception,
                           billed_on=day, appointment=visit, dentist=dentist, branch=place)
        amount = (bill.totals()["net"] * Decimal(part)).quantize(Decimal("1"))
        PatientPayment.objects.create(patient=patient, bill=bill, branch=place, amount=amount, paid_on=day,
                                      method=method, fawry_machine=machine if method == PaymentMethod.FAWRY else None,
                                      reference=f"IP{rng.randint(10000, 99999)}" if method == PaymentMethod.INSTAPAY
                                      else "", created_by=reception)
    DoctorPayout.objects.create(dentist=endo, branch=place, paid_on=today - timedelta(days=2), amount=Decimal("600"),
                                method=PaymentMethod.CASH, created_by=amr_user, notes="Part of this month")

    # Today and tomorrow: the same room with different doctors through the day.
    for day_offset, hour, patient, dentist, room, state in [
            (0, 13, hisham, amr, 0, "left"), (0, 13, noha, tmj, 1, "in_room"), (0, 14, marwan, endo, 2, "arrived"),
            (0, 15, yasmin, ortho, 0, "booked"), (0, 16, salwa, prostho, 1, "booked"), (0, 18, karim, amr, 0, "booked"),
            (1, 13, rana, surgeon, 3, "booked"), (1, 17, tarek_p, amr, 2, "booked")]:
        day = today + timedelta(days=day_offset)
        visit = Appointment.objects.create(branch=place, patient=patient, scheduled_at=at(day, hour), room=rooms[room],
                                           dentist=dentist, duration_minutes=45, created_by=reception)
        if state in ("left", "in_room", "arrived"):
            visit.mark_arrived(at(day, hour) - timedelta(minutes=5))
        if state in ("left", "in_room"):
            visit.mark_entered_room(at(day, hour) + timedelta(minutes=2))
        if state == "left":
            visit.mark_left(at(day, hour) + timedelta(minutes=40))
        visit.save()

    # Referrals from Dr. Amr: answered, booked, to book, and one outside the clinic.
    done = Referral.objects.create(branch=place, patient=karim, from_dentist=amr, to_dentist=endo,
                                   specialty=S.ENDODONTIST, teeth="36", urgency=Referral.Urgency.SOON,
                                   reason="Deep caries with lingering pain on cold. Please assess and treat the root "
                                          "canals before a zirconia crown.", created_by=amr_user,
                                   status=Referral.Status.DONE, replied_by=endo_user,
                                   replied_at=at(today - timedelta(days=12), 20),
                                   reply="Symptomatic irreversible pulpitis, normal apical tissues. RCT done in two "
                                         "visits (Ca(OH)2 between them), 3 canals obturated. Ready for the crown; "
                                         "fibre post not needed.")
    Referral.objects.create(branch=place, patient=noha, from_dentist=amr, to_dentist=tmj, specialty=S.TMJ,
                            reason="Limited opening and clicking on the left for 2 months. Please examine the TMJ.",
                            status=Referral.Status.BOOKED, created_by=amr_user,
                            appointment=noha.appointments.filter(dentist=tmj).order_by("-scheduled_at").first())
    Referral.objects.create(branch=place, patient=hisham, from_dentist=amr, to_dentist=ortho, specialty=S.ORTHODONTIST,
                            reason="Crowding of the lower front teeth before the veneers: orthodontic opinion, please.",
                            created_by=amr_user)
    Referral.objects.create(branch=place, patient=rana, from_dentist=surgeon, to_outside="Cairo Scan radiology centre",
                            teeth="46", reason="CBCT of the lower right side for implant planning.",
                            created_by=amr_user)

    # Endodontics: 36 finished (the chart shows the root canal), 11 in treatment with calcium hydroxide.
    case = EndoCase.objects.create(
        patient=karim, branch=place, dentist=endo, referral=done, tooth=36, started_on=today - timedelta(days=25),
        chief_complaint="Pain on cold drinks, lasting minutes, for a week.", pain=EndoCase.Pain.MODERATE,
        pain_kinds=["provoked", "lingering", "night"], cold_test=EndoCase.Test.LINGERING,
        percussion=EndoCase.Tender.NORMAL, palpation=EndoCase.Tender.NORMAL, mobility=0, swelling="none",
        radiographic="Deep distal caries close to the pulp, normal PDL.",
        pulpal_diagnosis=EndoCase.Pulp.SYMPTOMATIC_IRREVERSIBLE, apical_diagnosis=EndoCase.Apical.NORMAL,
        difficulty=EndoCase.Difficulty.MODERATE, difficulty_factors=["curvature"],
        treatment=EndoCase.Treatment.INITIAL, anaesthesia="Articaine 4% IANB + buccal infiltration",
        magnification="Loupes 3.5×", instruments="ProTaper Gold to F2", irrigants=["naocl_525", "edta"],
        activation=EndoCase.Activation.ULTRASONIC, obturation=EndoCase.Obturation.WARM_VERTICAL,
        sealer=EndoCase.Sealer.AH_PLUS, restoration=EndoCase.Restoration.CROWN,
        prognosis=EndoCase.Prognosis.FAVOURABLE, recall="X-ray after 6 and 12 months", created_by=endo_user)
    for name, reference, length, file, cone in [("MB", "MB cusp", "21.5", "25/.08", "F2"),
                                                ("ML", "ML cusp", "21.0", "25/.08", "F2"),
                                                ("D", "DB cusp", "22.0", "30/.09", "F3")]:
        EndoCanal.objects.create(case=case, name=name, reference=reference, working_length=Decimal(length),
                                 method=EndoCanal.Method.BOTH, master_file=file, master_cone=cone,
                                 curvature=EndoCanal.Curve.MODERATE if name == "MB" else EndoCanal.Curve.MILD)
    EndoVisit.objects.create(case=case, date=today - timedelta(days=25), work=["access", "wl", "shaping", "medication"],
                             medication=EndoVisit.Medication.CAOH, temporary=EndoVisit.Temporary.CAVIT, pain=6,
                             created_by=endo_user)
    EndoVisit.objects.create(case=case, date=today - timedelta(days=12), work=["obturation"],
                             medication=EndoVisit.Medication.NONE, temporary=EndoVisit.Temporary.GIC, pain=0,
                             created_by=endo_user)
    case.obturated_on = today - timedelta(days=12)
    finish_endo(case, endo_user)
    front = EndoCase.objects.create(
        patient=marwan, branch=place, dentist=endo, tooth=11, started_on=today - timedelta(days=3),
        chief_complaint="Darkened front tooth after a fall years ago.", pain=EndoCase.Pain.NONE,
        cold_test=EndoCase.Test.NONE, percussion=EndoCase.Tender.TENDER, sinus_tract=True,
        radiographic="Periapical radiolucency 4 × 5 mm.", pulpal_diagnosis=EndoCase.Pulp.NECROSIS,
        apical_diagnosis=EndoCase.Apical.CHRONIC_ABSCESS, difficulty=EndoCase.Difficulty.MINIMAL,
        treatment=EndoCase.Treatment.INITIAL, instruments="WaveOne Gold Primary", irrigants=["naocl_525", "edta"],
        created_by=endo_user)
    EndoCanal.objects.create(case=front, name="Single", reference="Incisal edge", working_length=Decimal("23.5"),
                             method=EndoCanal.Method.APEX_LOCATOR, master_file="35/.06")
    EndoVisit.objects.create(case=front, date=today - timedelta(days=3), work=["access", "wl", "shaping", "medication"],
                             medication=EndoVisit.Medication.CAOH, temporary=EndoVisit.Temporary.CAVIT, pain=2,
                             created_by=endo_user)

    # TMJ: limited opening getting better with a splint.
    exam = TMJExam.objects.create(
        patient=noha, branch=place, dentist=tmj, exam_date=today - timedelta(days=24),
        chief_complaint="Cannot open the mouth fully; pain in front of the left ear.", since="2 months", pain_vas=7,
        pain_sites=["joint_l", "ear", "cheek"], headache=True, bruxism=TMJExam.Bruxism.SLEEP, opening=28,
        opening_max=33, opening_pain=True, right_lateral=9, left_lateral=4, protrusion=5,
        path=TMJExam.Path.DEFLECTION_L, sound_right=TMJExam.Sound.NONE, sound_left=TMJExam.Sound.OPENING,
        locking=TMJExam.Locking.CLOSED_PAST, joint_tender_left=True,
        muscles=["masseter_l", "temporalis_l", "lat_pterygoid_l"], occlusion="Missing 36, 46; slight deep bite",
        imaging="Panorama: normal condyles.", diagnoses=["dd_nr_limited", "myalgia", "bruxism"],
        plan=["counselling", "stabilization", "physio", "nsaids"], splint="Hard upper stabilization splint at night",
        created_by=amr_user)
    TMJVisit.objects.create(exam=exam, date=today - timedelta(days=20), opening=34, pain_vas=4,
                            done="Splint delivered and adjusted; jaw exercises shown", created_by=amr_user)
    TMJVisit.objects.create(exam=exam, date=today, opening=38, pain_vas=2, done="Splint adjusted", created_by=amr_user)

    # Orthodontics: Class II division 1, fixed MBT brackets for 3 months.
    ortho_case = OrthoCase.objects.create(
        patient=yasmin, branch=place, dentist=ortho, status=OrthoCase.Status.ACTIVE,
        records_on=today - timedelta(days=100), chief_complaint="Upper front teeth stick out.",
        profile=OrthoCase.Profile.CONVEX, lips=OrthoCase.Lips.INCOMPETENT, smile_line=OrthoCase.Smile.AVERAGE,
        molar_right=OrthoCase.Relation.CLASS_II, molar_left=OrthoCase.Relation.CLASS_II_HALF,
        canine_right=OrthoCase.Relation.CLASS_II, canine_left=OrthoCase.Relation.CLASS_II,
        overjet=Decimal("7"), overbite=Decimal("5"), crowding_upper=Decimal("2"), crowding_lower=Decimal("3.5"),
        midline="Upper centred, lower 1 mm to the left", habits="Mouth breathing", sna=Decimal("83"),
        snb=Decimal("77"), anb=Decimal("6"), fma=Decimal("27"), u1_sn=Decimal("112"), impa=Decimal("96"),
        wits=Decimal("4"), skeletal=OrthoCase.Skeletal.CLASS_II, vertical=OrthoCase.Vertical.NORMAL,
        diagnosis="Class II division 1 on a mild skeletal Class II, increased overjet and deep bite.",
        appliance=OrthoCase.Appliance.METAL, prescription=OrthoCase.Prescription.MBT, anchorage=["elastics"],
        months=20, retention=OrthoCase.Retention.COMBINED, bonded_on=today - timedelta(days=90), created_by=amr_user)
    for days_ago, upper, lower, elastics, done_text in [
            (90, "0.014 NiTi", "0.014 NiTi", "", "Bonded upper and lower"),
            (60, "0.016 NiTi", "0.016 NiTi", "", "Wire change"),
            (30, "0.017×0.025 NiTi", "0.016×0.022 NiTi", "", "Rebond 25"),
            (13, "0.019×0.025 SS", "0.017×0.025 NiTi", "Class II 3/16\" 6 oz", "Elastics started")]:
        OrthoVisit.objects.create(case=ortho_case, date=today - timedelta(days=days_ago), upper_wire=upper,
                                  lower_wire=lower, elastics=elastics, done=done_text, next_weeks=4,
                                  hygiene=OrthoVisit.Hygiene.GOOD, created_by=amr_user)

    # The shade of two front crowns, and their lab request sent with it.
    shade = ShadeRecord.objects.create(
        patient=salwa, branch=place, dentist=prostho, taken_on=today - timedelta(days=10), teeth="11, 21",
        prosthesis="Zirconia crowns 11, 21", guide="classical", shade="A2", shade_cervical="A3", shade_incisal="A1",
        stump="ND2", translucency=ShadeRecord.Translucency.HIGH, surface=ShadeRecord.Surface.MEDIUM,
        characters=["halo", "mamelons"], light=ShadeRecord.Light.DAYLIGHT, created_by=amr_user)
    lab = Lab.objects.filter(is_active=True).order_by("pk").first()
    work = LabWorkType.objects.filter(name_en="Zirconia crown").first() or LabWorkType.objects.first()
    request = LabRequest.objects.create(
        branch=place, patient=salwa, lab=lab, work_type=work, teeth="11, 21", units=2, dentist=prostho,
        shade_guide="classical", shade=shade.shade, shade_cervical=shade.shade_cervical,
        shade_incisal=shade.shade_incisal, stump_shade=shade.stump, material="Multilayer zirconia",
        margin=LabRequest.Margin.CHAMFER, occlusion=LabRequest.Occlusion.LIGHT, stage=LabRequest.Stage.FINAL,
        enclosures=["impression", "opposing", "bite", "shade_photo", "photos"],
        instructions="Incisal halo and soft mamelons as the photo; high translucency at the incisal third.",
        status=LabRequest.Status.SENT, due_date=today + timedelta(days=4), lab_cost=Decimal("3400"),
        created_by=amr_user)
    LabRequestEvent.objects.create(request=request, action=LabRequestEvent.Action.CREATED, by=amr_user)
    LabRequestEvent.objects.create(request=request, action=LabRequestEvent.Action.SENT, by=reception)

    # A comprehensive treatment plan: Dr. Amr plans it, each specialist does his part.
    plan = TreatmentPlan.objects.create(
        patient=karim, title="Full rehabilitation", dentist=amr, comprehensive=True, created_by=amr_user,
        difficulty=TreatmentPlan.Difficulty.MODERATE, duration="5 to 6 months",
        diagnosis="Irreversible pulpitis of 36, a hopeless 46 and a missing 46 space to restore; generalised "
                  "gingivitis.",
        alternatives="A three-unit bridge 45–47 instead of the implant at 46 (needs cutting two healthy teeth).")
    for phase, step, teeth, dentist, fee, details in [
            (PlanItem.Phase.URGENT, "Scaling", "", amr, 800, "Scaling and polishing"),
            (PlanItem.Phase.PREPARATION, "Root canal treatment", "36", endo, 4000, "Three canals"),
            (PlanItem.Phase.PREPARATION, "Extraction", "46", surgeon, 2000, "Surgical extraction"),
            (PlanItem.Phase.SURGICAL, "Implant placement", "46", amr, 18000, "Implant 4.5 × 10"),
            (PlanItem.Phase.PROSTHETIC, "Crown cementation (natural tooth)", "36", prostho, 6500, "Zirconia crown"),
            (PlanItem.Phase.PROSTHETIC, "Final prosthesis delivery", "46", amr, 7000, "Screw-retained zirconia crown"),
            (PlanItem.Phase.MAINTENANCE, "Follow-up", "", amr, None, "Every 6 months")]:
        item = PlanItem.objects.create(plan=plan, phase=phase, step_type=types[step], teeth=teeth, dentist=dentist,
                                       fee=fee, details=details)
        if step == "Root canal treatment":
            item.status, item.done_at, item.done_treatment = PlanItem.Status.DONE, case.treatment_step.performed_at, \
                case.treatment_step
            item.save()

    # The stock is shared: El Khadem takes out what it uses, and each movement says so.
    from apps.stock.models import StockItem, StockMovement
    from apps.stock.services import record_movement

    for item in StockItem.objects.filter(branch__isnull=True, quantity__gte=10).order_by("pk")[:3]:
        record_movement(item, StockMovement.Kind.OUT, 2, stock_user, branch=place, destination="El Khadem room 1",
                        notes="El Khadem")
    return {"place": place, "amr": amr, "reception": reception}
