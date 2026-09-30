"""The sample data of round 10: the medical follow-up (readings above the limits, letters waiting, answered), a full
arch designed with its pontics, the delivery checklists, the steps of a root canal treatment with their X-rays, and
a new patient half way through the file (load_demo_data calls load_round_ten)."""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.charting.models import ClinicalPhoto, Examination, PhotoStage, TreatmentPlan
from apps.clinical.models import TreatmentStep
from apps.core.models import Branch
from apps.patients.models import MedicalCondition, MedicalConsult, Patient

from .followup import ask_reception
from .models import DeliveryCheck, ImplantSystem, Prosthesis, Surgery, SurgerySite
from .prostheses import plan_from_surgery


def _history(patient, dentist, days_ago, today, conditions=(), **readings):
    exam = Examination.objects.create(patient=patient, history_only=True, medical_taken=True, dental_taken=True,
                                      exam_date=today - timedelta(days=days_ago), examined_by=dentist,
                                      created_by=dentist.user, **readings)
    exam.conditions.set(MedicalCondition.objects.filter(name_en__in=conditions))
    patient.medical_conditions.set(exam.conditions.all())
    return exam


def load_round_ten(today, at, patients, cia_dentists, types, secretary, owner, demo_photo):
    from .views import update_chart_for_surgery

    academy, cic = Branch.objects.get(code="CIA"), Branch.objects.get(code="CIC")
    mona, sherif = cia_dentists[0], cia_dentists[1]
    # Patients of CIA with nothing in their file yet (the earlier sample data filled many).
    cia = list(Patient.objects.filter(branch=academy, status=Patient.Status.ACTIVE, examinations__isnull=True,
                                      surgeries__isnull=True, treatment_steps__isnull=True).order_by("pk")[:7])
    diabetes = ("Diabetes",)

    # 1. The medical follow-up: readings above the limits, a letter waiting, answers fit and postponed.
    flagged = cia[0]
    _history(flagged, mona, 2, today, diabetes, hba1c=Decimal("8.4"), hba1c_date=today - timedelta(days=10),
             glucose_random_clinic=190, bp_clinic_systolic=130, bp_clinic_diastolic=85, drugs_taken="Metformin 1000 mg")
    waiting = cia[1]
    exam = _history(waiting, mona, 6, today, ("High blood pressure",), bp_clinic_systolic=172, bp_clinic_diastolic=104,
                    bp_drug="Concor 5 mg")
    MedicalConsult.objects.create(
        patient=waiting, branch=academy, dentist=mona, reasons="pressure", sent_on=exam.exam_date,
        findings="Medical history: high blood pressure.\nCurrent medicines: Concor 5 mg.\n"
                 "Readings: blood pressure in our clinic 172/104 mmHg.",
        physician="Magdy Fahmy", specialty="Cardiology", procedures="implants", procedure_details="2 implants 36, 46",
        medications="Amoxicillin + clavulanic acid 1 g (Augmentin 1 g)\nIbuprofen 400 mg (Brufen 400 mg)\n"
                    "Chlorhexidine 0.12% mouthwash (Hexitol mouthwash)",
        question="Kindly examine the patient and tell us whether he is medically fit for this surgery.",
        created_by=mona.user)
    fit = cia[2]
    exam = _history(fit, sherif, 25, today, diabetes, hba1c=Decimal("7.6"), hba1c_date=today - timedelta(days=30),
                    glucose_random_clinic=165)
    MedicalConsult.objects.create(
        patient=fit, branch=academy, dentist=sherif, reasons="hba1c", sent_on=exam.exam_date,
        findings="Medical history: diabetes.\nReadings: HbA1c 7.6%.", physician="Adel Sami",
        specialty="Endocrinology (diabetes)", procedures="implants,sinus", procedure_details="Implant 16 with sinus lift",
        bleeding=MedicalConsult.Bleeding.MODERATE, status=MedicalConsult.Status.ANSWERED,
        answer=MedicalConsult.Answer.PRECAUTIONS, answered_by="Dr. Adel Sami", answered_on=today - timedelta(days=20),
        answer_notes="Fit. Continue metformin; morning appointment after breakfast; check the sugar before surgery.",
        answer_recorded_by=secretary, created_by=sherif.user)
    held = cia[3]
    exam = _history(held, mona, 15, today, diabetes, hba1c=Decimal("9.8"), hba1c_date=today - timedelta(days=16),
                    glucose_random_clinic=260)
    MedicalConsult.objects.create(
        patient=held, branch=academy, dentist=mona, reasons="hba1c,glucose", sent_on=exam.exam_date,
        findings="Medical history: diabetes.\nReadings: HbA1c 9.8%; random blood sugar 260 mg/dl.",
        physician="Adel Sami", specialty="Endocrinology (diabetes)", procedures="full_arch",
        procedure_details="All-on-6 in the upper jaw", bleeding=MedicalConsult.Bleeding.MODERATE,
        status=MedicalConsult.Status.ANSWERED, answer=MedicalConsult.Answer.POSTPONE, answered_by="Dr. Adel Sami",
        answered_on=today - timedelta(days=8), recheck_on=today + timedelta(days=5),
        answer_notes="Postpone: insulin started; new HbA1c in 6 weeks.", answer_recorded_by=secretary,
        created_by=mona.user)
    cic_patient = Patient.objects.filter(branch=cic, status=Patient.Status.ACTIVE).order_by("pk").first()
    if cic_patient is not None and cic_patient.assigned_dentist is not None:
        doctor = cic_patient.assigned_dentist
        _history(cic_patient, doctor, 1, today, diabetes, hba1c=Decimal("8.1"), hba1c_date=today - timedelta(days=5))

    # 2. A full arch designed like on a scanner: six implants, the teeth between them pontics; the prosthesis is
    # planned by itself, and the next visit (after 1 week, the sutures) is on the reception's list.
    patient = cia[4]
    osstem = ImplantSystem.objects.filter(company="Osstem").first()
    surgery = Surgery.objects.create(branch=academy, patient=patient, date=today - timedelta(days=3), operator_1=mona,
                                     assistant=sherif, difficulty=Surgery.Difficulty.MODERATE,
                                     pontics="15, 13, 11, 21, 23, 25", suture_size="4-0",
                                     suture_material=Surgery.SutureMaterial.VICRYL, xray_taken=True,
                                     created_by=mona.user)
    for tooth, diameter, length, lot, torque in [(16, "4.5", "10", "OS-25C17", 40), (14, "4.0", "10", "OS-24A11", 35),
                                                 (12, "3.5", "11.5", "OS-22K08", 35), (22, "3.5", "11.5", "OS-22K08", 35),
                                                 (24, "4.0", "10", "OS-24A11", 40), (26, "4.5", "10", "OS-25C17", 45)]:
        SurgerySite.objects.create(surgery=surgery, tooth=tooth, simple_implant=True, implant_system=osstem,
                                   implant_diameter=Decimal(diameter), implant_length=Decimal(length), lot_number=lot,
                                   insertion_torque=torque, isq=70)
    SurgerySite.objects.filter(surgery=surgery, tooth=16).update(closed_sinus=True)
    update_chart_for_surgery(surgery, mona.user)
    plan_from_surgery(surgery, mona.user)
    ask_reception(surgery, mona.user)

    # 3. The delivery checklists: one done on a delivered prosthesis, one started for a crown to deliver.
    delivered = Prosthesis.objects.filter(status=Prosthesis.Status.DELIVERED, patient__branch=academy).first()
    if delivered is not None:
        every = [code for _group, rows in DeliveryCheck.items_for(delivered) for code, _label, _optional in rows]
        DeliveryCheck.objects.create(prosthesis=delivered, date=delivered.delivered_on or today, dentist=mona,
                                     ticked=[code for code in every if code != "night_guard"], torque_ncm=35,
                                     shade="A2", follow_up_on=(delivered.delivered_on or today) + timedelta(days=7),
                                     created_by=mona.user)
    to_deliver = Prosthesis.objects.filter(status=Prosthesis.Status.PLANNED, kind=Prosthesis.Kind.SINGLE,
                                           patient__branch=academy).first()
    if to_deliver is not None:
        Prosthesis.objects.filter(pk=to_deliver.pk).update(status=Prosthesis.Status.TRY_IN)
        DeliveryCheck.objects.create(prosthesis=to_deliver, dentist=mona, ticked=["lab_match", "shade", "parts"],
                                     shade="A3", notes="The crown came back from the lab: seat it next visit.",
                                     created_by=mona.user)

    # 4. A root canal treatment in steps, with its periapical X-rays (one still to take).
    endo = cia[5]
    now = timezone.now()
    access = TreatmentStep.objects.create(patient=endo, step_type=types["Endo: access, cleaning and shaping"],
                                          teeth="36", operator=mona, performed_at=now - timedelta(days=7),
                                          notes="4 canals; working length 21 mm", created_by=mona.user)
    obturation = TreatmentStep.objects.create(patient=endo, step_type=types["Endo: obturation"], teeth="36",
                                              operator=mona, performed_at=now - timedelta(hours=2),
                                              notes="Warm vertical; temporary filling", created_by=mona.user)
    for step, shot, label in [(access, "pa_before", "PA before 36"), (access, "pa_working", "Working length 36"),
                              (obturation, "pa_cone", "Master cone 36")]:
        ClinicalPhoto.objects.create(patient=endo, stage=PhotoStage.TREATMENT, treatment_step=step, shot=shot,
                                     teeth="36", taken_on=step.performed_at.date(), notes=str(step.step_type),
                                     created_by=mona.user, file=demo_photo(label, step.pk))

    # 5. A new patient half way: histories and examination done, the diagnostic scan taken, the CBCT next.
    journey = cia[6]
    _history(journey, sherif, 0, today, (), bp_clinic_systolic=125, bp_clinic_diastolic=80, glucose_random_clinic=110)
    Examination.objects.create(patient=journey, examined_by=sherif, teeth_missing="36, 46", teeth_filled="16",
                               chief_complaint="Wants implants for the missing lower molars", created_by=sherif.user)
    TreatmentStep.objects.create(patient=journey, step_type=types["Diagnostic intraoral scan"], operator=sherif,
                                 created_by=sherif.user)
    # A plan written after the planning on the CBCT, with the chart checked again.
    first_plans = TreatmentPlan.objects.filter(patient__branch=academy).exclude(status="cancelled").order_by("pk")[:5]
    TreatmentPlan.objects.filter(pk__in=list(first_plans.values_list("pk", flat=True))).update(
        cbct_planned=True, chart_checked=True)
