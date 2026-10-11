"""The medical follow-up (CIA and CIC): a patient whose last readings are above the limits of Settings → Clinic
options (HbA1c above 7%, a high random blood sugar or blood pressure), or with a disease the dentist is not sure
about, needs a physician's opinion before the surgery. The dentist writes a ready consultation letter
(MedicalConsult: the reason, the procedure, the anaesthesia and the medicines after it), the patient takes it to
his physician and brings the answer back: fit, fit with precautions, postpone, not fit.

A physician's answer counts for CONSULT_VALID_DAYS: readings taken within that time after a letter do not ask
for a new one (the dentist can still write one)."""

from datetime import timedelta

from django.db.models import OuterRef, Q, Subquery
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.charting.models import Examination
from apps.core.models import ClinicSettings

from .models import MedicalConsult

CONSULT_VALID_DAYS = 180


def out_of_range_q(options=None):
    """The examinations with a reading above the limits."""
    options = options or ClinicSettings.get()
    return (Q(hba1c__gt=options.hba1c_limit) | Q(glucose_random_clinic__gt=options.glucose_limit)
            | Q(bp_clinic_systolic__gte=options.systolic_limit) | Q(bp_clinic_diastolic__gte=options.diastolic_limit))


def reading_flags(exam, options=None):
    """The readings of this history above the limits: [(reason code, text)]."""
    if exam is None:
        return []
    options = options or ClinicSettings.get()
    flags = []
    if exam.hba1c is not None and exam.hba1c > options.hba1c_limit:
        when = f" ({exam.hba1c_date:%d/%m/%Y})" if exam.hba1c_date else ""
        flags.append((MedicalConsult.Reason.HBA1C, _("HbA1c %(value)s%% (above %(limit)s%%)") % {
            "value": exam.hba1c, "limit": options.hba1c_limit} + when))
    if exam.glucose_random_clinic is not None and exam.glucose_random_clinic > options.glucose_limit:
        flags.append((MedicalConsult.Reason.GLUCOSE, _("Random blood sugar %(value)s mg/dl (above %(limit)s)") % {
            "value": exam.glucose_random_clinic, "limit": options.glucose_limit}))
    high_systolic = exam.bp_clinic_systolic is not None and exam.bp_clinic_systolic >= options.systolic_limit
    high_diastolic = exam.bp_clinic_diastolic is not None and exam.bp_clinic_diastolic >= options.diastolic_limit
    if high_systolic or high_diastolic:
        flags.append((MedicalConsult.Reason.PRESSURE, _("Blood pressure %(value)s (from %(limit)s)") % {
            "value": f"{exam.bp_clinic_systolic or '—'}/{exam.bp_clinic_diastolic or '—'}",
            "limit": f"{options.systolic_limit}/{options.diastolic_limit}"}))
    return flags


def latest_history(patient):
    return patient.examinations.filter(medical_taken=True).prefetch_related("conditions").first()


def covers(consult, exam):
    """True when the consultation answers for the readings of this history (see CONSULT_VALID_DAYS)."""
    return exam is None or timezone.localtime(consult.created_at).date() >= exam.exam_date - timedelta(
        days=CONSULT_VALID_DAYS)


def clearance(patient):
    """What the patient's file and the surgery chart show about his fitness for surgery, or None:
    {"state": needed / waiting / fit / not_fit / cleared, "flags": [...], "consult": the last letter or None}."""
    exam = latest_history(patient)
    flags = reading_flags(exam)
    consult = patient.medical_consults.select_related("dentist").first()
    if consult is not None and not covers(consult, exam):
        consult = None  # an old letter: it does not answer for the new readings
    if consult is None:
        return {"state": "needed", "flags": flags, "consult": None} if flags else None
    if consult.status == MedicalConsult.Status.WAITING:
        state = "waiting"
    elif consult.status == MedicalConsult.Status.NOT_NEEDED:
        state = "cleared"
    else:
        state = "fit" if consult.answer in MedicalConsult.CLEARED else "not_fit"
    return {"state": state, "flags": flags, "consult": consult}


def needing_consult(patients):
    """[(exam, flags)] of the patients whose last medical history is above the limits, without a letter that
    answers for it. ``patients`` is the place's patients (a queryset)."""
    options = ClinicSettings.get()
    latest = Examination.objects.filter(patient=OuterRef("patient"), medical_taken=True).order_by(
        "-exam_date", "-pk").values("pk")[:1]
    exams = list(Examination.objects.filter(medical_taken=True, patient__in=patients).filter(
        out_of_range_q(options)).filter(pk=Subquery(latest)).select_related(
        "patient", "patient__assigned_dentist", "examined_by").order_by("-exam_date"))
    consults = {}
    for consult in MedicalConsult.objects.filter(patient__in=[e.patient_id for e in exams]).order_by("created_at"):
        consults[consult.patient_id] = consult  # the last one
    rows = []
    for exam in exams:
        consult = consults.get(exam.patient_id)
        if consult is None or not covers(consult, exam):
            rows.append((exam, reading_flags(exam, options)))
    return rows


def letter_findings(patient, exam=None):
    """The medical history as written in the letter (English, for the physician)."""
    exam = exam if exam is not None else latest_history(patient)
    if exam is None:
        return ""
    lines = []
    diseases = [c.name_en or c.name_ar for c in exam.conditions.all()]
    if exam.other_condition:
        diseases.append(exam.other_condition)
    if diseases:
        lines.append("Medical history: " + ", ".join(diseases) + ".")
    drugs = [line.strip() for line in exam.drugs_taken.splitlines() if line.strip()]
    if exam.bp_drug:
        drugs.append(exam.bp_drug)
    if drugs:
        lines.append("Current medicines: " + ", ".join(drugs) + ".")
    readings = []
    if exam.hba1c is not None:
        readings.append(f"HbA1c {exam.hba1c}%" + (f" ({exam.hba1c_date:%d/%m/%Y})" if exam.hba1c_date else ""))
    if exam.glucose_random_clinic is not None:
        readings.append(f"random blood sugar in our clinic {exam.glucose_random_clinic} mg/dl")
    if exam.bp_clinic_systolic or exam.bp_clinic_diastolic:
        readings.append(f"blood pressure in our clinic {exam.bp_clinic_systolic or '—'}/"
                        f"{exam.bp_clinic_diastolic or '—'} mmHg")
    if readings:
        lines.append("Readings: " + "; ".join(readings) + f" (examination of {exam.exam_date:%d/%m/%Y}).")
    allergies = [name for name, on in (("penicillin", exam.allergy_penicillin), ("sulfa", exam.allergy_sulfa)) if on]
    if exam.allergy_other:
        allergies.append(exam.allergy_other)
    if allergies:
        lines.append("Allergic to: " + ", ".join(allergies) + ".")
    if exam.bleeding_or_aspirin:
        lines.append(f"Bleeding / aspirin: {exam.bleeding_or_aspirin}.")
    if exam.smoker:
        lines.append("Smoker" + (f", {exam.cigarettes_per_day} cigarettes a day." if exam.cigarettes_per_day else "."))
    return "\n".join(lines)


def usual_medications(consult):
    """The medicines after the surgery, from the prescription that fits the procedure (English names)."""
    from apps.prescriptions.services import best_template, penicillin_allergy

    template = best_template(consult.surgery_codes(), penicillin_allergy(consult.patient))
    if template is None:
        return ""
    lines = []
    for line in template.lines.select_related("group").prefetch_related("group__drugs"):
        drug = next((d for d in line.group.drugs.all() if d.is_active), None)
        name = line.group.name_en or line.group.name_ar
        lines.append(f"{name} ({drug.name})" if drug and drug.name not in name else name)
    return "\n".join(lines)


def reasons_for(patient, exam=None):
    """The reasons ticked on a new letter: the readings above the limits, and the diseases that usually need it."""
    exam = exam if exam is not None else latest_history(patient)
    codes = [code for code, _text in reading_flags(exam)]
    if exam is not None:
        names = " ".join((c.name_en or "").lower() for c in exam.conditions.all())
        if "heart" in names or "cardiac" in names:
            codes.append(MedicalConsult.Reason.HEART)
        if "aspirin" in exam.bleeding_or_aspirin.lower() or "warfarin" in exam.drugs_taken.lower():
            codes.append(MedicalConsult.Reason.BLOOD_THINNER)
    return codes


# ------------------------------------------------------------------ calls for a new test (round 15)
RECALL_REASONS = (MedicalConsult.Reason.HBA1C, MedicalConsult.Reason.GLUCOSE, MedicalConsult.Reason.PRESSURE)


def reading_value(exam, code):
    """The reading alone, the same in every language ("8.2%", "260 mg/dl", "170/100")."""
    if code == MedicalConsult.Reason.HBA1C:
        return f"{exam.hba1c}%"
    if code == MedicalConsult.Reason.GLUCOSE:
        return f"{exam.glucose_random_clinic} mg/dl"
    return f"{exam.bp_clinic_systolic or '—'}/{exam.bp_clinic_diastolic or '—'}"


def sync_recalls(patients):
    """A call for a new test for every reading above the limits of the patients' last medical history: the HbA1c
    after the days of Settings (90), the sugar and the pressure after theirs (30). A newer history without that
    reading above the limit closes the older calls (the new test was done). Few look-ups for any number of
    patients (``patients`` is a queryset)."""
    from .models import MedicalRecall

    options = ClinicSettings.get()
    latest = Examination.objects.filter(patient=OuterRef("patient"), medical_taken=True).order_by(
        "-exam_date", "-pk").values("pk")[:1]
    exams = list(Examination.objects.filter(medical_taken=True, patient__in=patients).filter(
        pk=Subquery(latest)).only("pk", "patient_id", "exam_date", "hba1c", "hba1c_date", "glucose_random_clinic",
                                  "bp_clinic_systolic", "bp_clinic_diastolic"))
    flagged, new = {}, []
    for exam in exams:
        for code, _text in reading_flags(exam, options):
            if code not in RECALL_REASONS:
                continue
            on = exam.hba1c_date if code == MedicalConsult.Reason.HBA1C and exam.hba1c_date else exam.exam_date
            days = options.hba1c_recheck_days if code == MedicalConsult.Reason.HBA1C else options.readings_recheck_days
            flagged[(exam.patient_id, code)] = on
            new.append(MedicalRecall(patient_id=exam.patient_id, reason=code, reading_on=on, reading=reading_value(exam, code),
                                     due_on=on + timedelta(days=days)))
    patient_ids = [exam.patient_id for exam in exams]
    known = set(MedicalRecall.objects.filter(patient_id__in=patient_ids).values_list(
        "patient_id", "reason", "reading_on"))
    MedicalRecall.objects.bulk_create([r for r in new if (r.patient_id, r.reason, r.reading_on) not in known],
                                      ignore_conflicts=True)
    # The open calls of a reading that is no longer the last one above the limit: a newer test was written.
    stale = [pk for pk, patient, reason, on in MedicalRecall.objects.filter(
        patient_id__in=patient_ids, status=MedicalRecall.Status.OPEN).values_list("pk", "patient_id", "reason",
                                                                                 "reading_on")
             if flagged.get((patient, reason)) != on]
    if stale:
        MedicalRecall.objects.filter(pk__in=stale).update(status=MedicalRecall.Status.DONE)


def recalls_due(patients, until=None):
    """The calls for a new test due by ``until`` (today), the late ones first."""
    from .models import MedicalRecall

    until = until or timezone.localdate()
    return MedicalRecall.objects.filter(patient__in=patients, status=MedicalRecall.Status.OPEN,
                                        due_on__lte=until).select_related("patient__branch", "last_call_by")


def recall_text(recall):
    """The WhatsApp message to the patient (Arabic, as every message to the patients)."""
    from apps.core.models import Branch

    place = recall.patient.branch if recall.patient.branch_id else Branch.default()
    tests = {MedicalConsult.Reason.HBA1C: "تحليل السكر التراكمي (HbA1c)",
             MedicalConsult.Reason.GLUCOSE: "تحليل السكر", MedicalConsult.Reason.PRESSURE: "قياس الضغط"}
    return (f"أهلًا {recall.patient.full_name}، نتمنى تكون بخير. مر وقت على آخر {tests.get(recall.reason, 'تحليل')} "
            f"({recall.reading_on:%d/%m/%Y}). برجاء عمل {tests.get(recall.reason, 'التحليل')} من جديد وإرسال النتيجة "
            f"لنا قبل العلاج القادم. — {place.name_ar if place else ''} {place.phone if place else ''}").strip()


def parse_result(reason, value):
    """The reading typed on the calls page: "6.8" for an HbA1c, "180" for a sugar, "150/95" for a pressure (Arabic
    digits too). Returns the values to write in the medical history, or raises ValueError."""
    from decimal import Decimal, InvalidOperation

    from apps.core.utils import normalize_digits

    text = normalize_digits(value or "").replace("٫", ".").replace(",", ".").replace("%", "").strip()
    if reason == MedicalConsult.Reason.HBA1C:
        try:
            number = Decimal(text)
        except InvalidOperation:
            raise ValueError
        if not Decimal("3") <= number <= Decimal("20"):
            raise ValueError
        return {"hba1c": number.quantize(Decimal("0.1"))}
    if reason == MedicalConsult.Reason.GLUCOSE:
        if not text.isdigit() or not 30 <= int(text) <= 900:
            raise ValueError
        return {"glucose_random_clinic": int(text)}
    parts = [part.strip() for part in text.replace("\\", "/").replace("-", "/").split("/")]
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError
    systolic, diastolic = int(parts[0]), int(parts[1])
    if not (60 <= systolic <= 260 and 30 <= diastolic <= 160):
        raise ValueError
    return {"bp_clinic_systolic": systolic, "bp_clinic_diastolic": diastolic}


def write_result(recall, value, on, user, photo=None):
    """The new test of a call (round 16): a new medical history is written from the last one with the new reading
    (so the rest of the history stays), the call is closed, and a reading still above the limit opens the next call
    by itself. The photo of the result is kept with the patient's documents."""
    from django.db import transaction

    from apps.charting.sync import sync_medical_history

    from .models import MedicalRecall, PatientDocument

    values = parse_result(recall.reason, value)
    patient = recall.patient
    latest = latest_history(patient)
    with transaction.atomic():
        history = Examination(patient=patient, history_only=True, medical_taken=True,
                              dental_taken=bool(latest and latest.dental_taken), created_by=user)
        if latest is not None:
            from apps.charting.forms import HISTORY_FIELDS

            for name in HISTORY_FIELDS:
                field = Examination._meta.get_field(name)
                if not field.many_to_many:
                    setattr(history, field.attname, getattr(latest, field.attname))
        for name, number in values.items():
            setattr(history, name, number)
        # The HbA1c keeps its own date; the sugar and the pressure take the day of the test (never before the
        # last history, so the new one is the last).
        if "hba1c" in values:
            history.hba1c_date, history.exam_date = on, timezone.localdate()
        else:
            history.exam_date = max(on, latest.exam_date) if latest is not None else on
        history.save()
        if latest is not None:
            history.conditions.set(latest.conditions.all())
        sync_medical_history(history)
        recall.result = reading_value(history, recall.reason)
        recall.result_on = on
        recall.status = MedicalRecall.Status.DONE
        recall.calls += 1
        recall.last_outcome, recall.last_call_at, recall.last_call_by = (
            MedicalRecall.Outcome.DONE, timezone.now(), user)
        recall.save()
        if photo:
            PatientDocument.objects.create(patient=patient, kind=PatientDocument.Kind.LAB_TEST, file=photo,
                                           notes=f"{recall.get_reason_display()} {recall.result} {on:%d/%m/%Y}",
                                           created_by=user)
    sync_recalls(type(patient).objects.filter(pk=patient.pk))
    return history
