"""The medical follow-up page and the consultation letters to the physicians (see medical.py)."""

from datetime import datetime, timedelta

from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.core.forms import StyledForm, validate_upload
from apps.core.mixins import role_required
from apps.core.models import ClinicSettings, branch_for_user
from apps.core.notify import notify_users
from apps.core.roles import CLINICAL, FRONT_DESK, PATIENT_VIEWERS, has_role, is_only_dentist
from apps.dentists.models import Dentist
from apps.scheduling.whatsapp import whatsapp_url

from .access import get_visible_patient_or_403, visible_patients
from .forms import ConsultAnswerForm, MedicalConsultForm
from .medical import (
    latest_history, letter_findings, needing_consult, reading_flags, reasons_for, recall_text, recalls_due,
    sync_recalls, usual_medications, write_result,
)
from .models import MedicalConsult, MedicalRecall

QUESTION = ("Kindly examine the patient and tell us whether he is medically fit for this surgery under local "
            "anaesthesia, with any precautions: changes to his medicines, antibiotic cover, stopping blood thinners, "
            "or the readings he should reach first.")


@role_required(*PATIENT_VIEWERS)
def medical_followup(request):
    """The patients of this place who need a physician's opinion, the letters waiting for an answer, the surgeries
    postponed for a medical reason, and the patients cleared lately."""
    patients = visible_patients(request.user)
    mine = request.GET.get("mine") == "1" or (is_only_dentist(request.user) and "mine" not in request.GET)
    me = Dentist.for_user(request.user)
    if mine and me is not None:
        patients = patients.filter(assigned_dentist=me) | patients.filter(medical_consults__dentist=me)
        patients = patients.distinct()
    consults = MedicalConsult.objects.filter(patient__in=patients).select_related(
        "patient", "dentist", "patient__assigned_dentist")
    latest = {}
    for consult in consults.order_by("created_at"):
        latest[consult.patient_id] = consult  # only the last letter of each patient counts
    latest = list(latest.values())
    today = timezone.localdate()
    waiting = sorted((c for c in latest if c.status == MedicalConsult.Status.WAITING), key=lambda c: c.sent_on)
    held = sorted((c for c in latest if c.status == MedicalConsult.Status.ANSWERED
                   and c.answer not in MedicalConsult.CLEARED), key=lambda c: c.recheck_on or today)
    cleared = sorted((c for c in latest if c.is_cleared and (c.answered_on or c.sent_on) >= today - timedelta(days=30)),
                     key=lambda c: c.answered_on or c.sent_on, reverse=True)
    needing = needing_consult(patients)
    sync_recalls(patients)
    recalls = _with_forms(list(recalls_due(patients)[:200]))
    coming = MedicalRecall.objects.filter(patient__in=patients, status=MedicalRecall.Status.OPEN,
                                          due_on__gt=today, due_on__lte=today + timedelta(days=30)).count()
    return render(request, "patients/medical_followup.html", {
        "needing": Paginator(needing, 50).get_page(request.GET.get("page")), "needing_count": len(needing),
        "recalls": recalls, "recalls_coming": coming, "outcomes": CALL_ANSWERS,
        "recall_counts": recall_counts(patients), "can_write_result": has_role(request.user, *FRONT_DESK, *CLINICAL),
        "options": ClinicSettings.get(),
        "waiting": waiting, "held": held, "cleared": cleared,
        "mine": mine, "has_dentist": me is not None, "today": today, "is_clinical": has_role(request.user, *CLINICAL),
    })


# After each answer, the next call (days): a patient who will do the test is asked again in two weeks.
NEXT_CALL = {MedicalRecall.Outcome.WILL_DO: 14, MedicalRecall.Outcome.NO_ANSWER: 2}
# The answer buttons of a call: "he did it" is the result form beside them (round 16).
CALL_ANSWERS = [(code, label) for code, label in MedicalRecall.Outcome.choices if code != MedicalRecall.Outcome.DONE]


class RecallResultForm(StyledForm):
    """The new test of a call: the reading, its day and a photo of the paper (round 16)."""

    value = forms.CharField(label=gettext_lazy("the new result"), max_length=20)
    on = forms.DateField(label=gettext_lazy("test of"))
    photo = forms.FileField(label=gettext_lazy("photo of the result (optional)"), required=False)

    PLACEHOLDERS = {MedicalConsult.Reason.HBA1C: "6.8", MedicalConsult.Reason.GLUCOSE: "180",
                    MedicalConsult.Reason.PRESSURE: "140/90"}

    def __init__(self, *args, recall=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.recall = recall
        self.fields["value"].widget.attrs.update({
            "placeholder": self.PLACEHOLDERS.get(recall.reason, ""), "inputmode": "decimal", "dir": "ltr"})
        self.fields["photo"].widget.attrs["accept"] = "image/*,application/pdf"

    def clean_value(self):
        from .medical import parse_result

        value = self.cleaned_data["value"]
        try:
            parse_result(self.recall.reason, value)
        except ValueError:
            examples = {MedicalConsult.Reason.HBA1C: _("Write the HbA1c as a number, e.g. 6.8"),
                        MedicalConsult.Reason.GLUCOSE: _("Write the sugar in mg/dl, e.g. 180"),
                        MedicalConsult.Reason.PRESSURE: _("Write the pressure as two numbers, e.g. 140/90")}
            raise forms.ValidationError(examples.get(self.recall.reason))
        return value

    def clean_on(self):
        on = self.cleaned_data["on"]
        if on > timezone.localdate():
            raise forms.ValidationError(_("The test cannot be after today."))
        return on

    def clean_photo(self):
        return validate_upload(self.cleaned_data.get("photo"))


def _with_forms(recalls):
    """Each call with its WhatsApp message and its result form."""
    today = timezone.localdate()
    for recall in recalls:
        recall.whatsapp = whatsapp_url(recall.patient.preferred_number, recall_text(recall)) \
            if recall.patient.preferred_number else ""
        recall.result_form = RecallResultForm(recall=recall, prefix=f"r{recall.pk}", initial={"on": today})
    return recalls


def recall_counts(patients):
    """How many calls are in each tab of the calls page (one look-up)."""
    from django.db.models import Count, Q

    today = timezone.localdate()
    opened = Q(status=MedicalRecall.Status.OPEN)
    return MedicalRecall.objects.filter(patient__in=patients).aggregate(
        today=Count("pk", filter=opened & Q(due_on__lte=today)),
        will_do=Count("pk", filter=opened & Q(last_outcome=MedicalRecall.Outcome.WILL_DO)),
        no_answer=Count("pk", filter=opened & Q(last_outcome=MedicalRecall.Outcome.NO_ANSWER)),
        coming=Count("pk", filter=opened & Q(due_on__gt=today, calls=0)),
        done=Count("pk", filter=Q(status=MedicalRecall.Status.DONE, result_on__gte=today - timedelta(days=60))),
    )


RECALL_TABS = [
    ("today", gettext_lazy("To call today")),
    ("will_do", gettext_lazy("He will do it: waiting for the result")),
    ("no_answer", gettext_lazy("No answer: call again")),
    ("coming", gettext_lazy("Coming (not called yet)")),
    ("done", gettext_lazy("Results written (60 days)")),
]


@role_required(*PATIENT_VIEWERS)
def recall_list(request):
    """Calls for a new test, in tabs (round 16): to call today, the patients who will do it (each with the day he is
    asked again), no answer (called again), coming, and the results written. Each row writes the result."""
    patients = visible_patients(request.user)
    sync_recalls(patients)
    today = timezone.localdate()
    tab = request.GET.get("tab") if request.GET.get("tab") in dict(RECALL_TABS) else "today"
    calls = MedicalRecall.objects.filter(patient__in=patients).select_related("patient__branch", "last_call_by")
    if tab == "done":
        calls = calls.filter(status=MedicalRecall.Status.DONE, result_on__gte=today - timedelta(days=60)).order_by(
            "-result_on", "-pk")
    else:
        calls = calls.filter(status=MedicalRecall.Status.OPEN)
        calls = {"today": calls.filter(due_on__lte=today),
                 "will_do": calls.filter(last_outcome=MedicalRecall.Outcome.WILL_DO),
                 "no_answer": calls.filter(last_outcome=MedicalRecall.Outcome.NO_ANSWER),
                 "coming": calls.filter(due_on__gt=today, calls=0)}[tab].order_by("due_on", "pk")
    page = Paginator(calls, 50).get_page(request.GET.get("page"))
    page.object_list = _with_forms(list(page.object_list))
    return render(request, "patients/recall_list.html", {
        "page_obj": page, "tab": tab, "tabs": RECALL_TABS, "counts": recall_counts(patients),
        "outcomes": CALL_ANSWERS, "options": ClinicSettings.get(), "today": today,
        "can_write_result": has_role(request.user, *FRONT_DESK, *CLINICAL),
    })


def _back_to_calls(request):
    back = request.POST.get("next", "")
    if back.startswith("/patients/medical-follow-up/"):
        return redirect(back)
    return redirect(reverse("patients:medical_followup") + "#recalls")


@require_POST
@role_required(*FRONT_DESK, *CLINICAL)
def recall_result(request, pk):
    """He did the test: the result is written in the medical history from the calls page, the call is closed."""
    recall = get_object_or_404(MedicalRecall, pk=pk)
    patient = get_visible_patient_or_403(request.user, recall.patient_id)
    form = RecallResultForm(request.POST, request.FILES, recall=recall, prefix=f"r{recall.pk}")
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, f"{patient.full_name}: {error}")
        return _back_to_calls(request)
    write_result(recall, form.cleaned_data["value"], form.cleaned_data["on"], request.user,
                 form.cleaned_data.get("photo"))
    recall.refresh_from_db()
    flags = [text for code, text in reading_flags(latest_history(patient)) if code == recall.reason]
    if flags:
        messages.warning(request, _("%(name)s: the new result %(result)s is still above the limit: he is called "
                                    "again for the next test.") % {"name": patient.full_name, "result": recall.result})
        dentist = patient.assigned_dentist
        if dentist is not None and dentist.user_id:
            notify_users([dentist.user], gettext_lazy("%(name)s: the new test is still high (%(result)s)"), "",
                         patient.get_absolute_url(), params={"name": patient.full_name, "result": recall.result})
    else:
        messages.success(request, _("%(name)s: the new result %(result)s is written in the medical history.") % {
            "name": patient.full_name, "result": recall.result})
    return _back_to_calls(request)


@require_POST
@role_required(*PATIENT_VIEWERS)
def recall_call(request, pk):
    """The answer of a call for a new test (round 15): he will do it (asked again in two weeks), no answer (again
    in two days), he did it (the new reading is written in the medical history) or he does not want to."""
    recall = get_object_or_404(MedicalRecall, pk=pk)
    patient = get_visible_patient_or_403(request.user, recall.patient_id)
    outcome = request.POST.get("outcome", "")
    if outcome not in MedicalRecall.Outcome.values:
        messages.error(request, _("Choose what the patient said."))
        return _back_to_calls(request)
    today = timezone.localdate()
    recall.calls += 1
    recall.last_outcome, recall.last_call_at, recall.last_call_by = outcome, timezone.now(), request.user
    note = (request.POST.get("notes") or "").strip()
    if note:
        recall.notes = note[:255]
    if outcome == MedicalRecall.Outcome.DONE:
        recall.status = MedicalRecall.Status.DONE
    elif outcome == MedicalRecall.Outcome.REFUSED:
        recall.status = MedicalRecall.Status.STOPPED
    else:
        next_on = parse_date_text(request.POST.get("next_on", ""))
        recall.due_on = next_on if next_on and next_on > today else today + timedelta(days=NEXT_CALL[outcome])
    recall.save()
    if outcome == MedicalRecall.Outcome.DONE:
        messages.success(request, _("Write the new result of %(name)s in the medical history: the call is closed.")
                         % {"name": patient.full_name})
        from .access import file_parts

        if has_role(request.user, *FRONT_DESK, *CLINICAL) and "medical" in file_parts(request.user):
            return redirect(reverse("patients:medical_history", args=[patient.pk]) + "?part=medical")
    elif recall.status == MedicalRecall.Status.OPEN:
        messages.success(request, _("Saved. The next call to %(name)s is on %(date)s.")
                         % {"name": patient.full_name, "date": recall.due_on.strftime("%d/%m/%Y")})
    else:
        messages.success(request, _("Saved: %(name)s leaves the list of calls.") % {"name": patient.full_name})
    return _back_to_calls(request)


def parse_date_text(text):
    """A dd/mm/yyyy date typed (Arabic digits too), or None."""
    from apps.core.utils import normalize_digits

    try:
        return datetime.strptime(normalize_digits(text or "").strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def _dentist_for(request, patient):
    return Dentist.for_user(request.user) or patient.assigned_dentist


@role_required(*CLINICAL)
def consult_create(request, pk):
    """A new letter, ready made from the medical history: the reasons, the readings, the usual anaesthesia and
    the medicines after the procedure (from the prescription that fits it)."""
    patient = get_visible_patient_or_403(request.user, pk)
    exam = latest_history(patient)
    consult = MedicalConsult(patient=patient, branch=patient.branch, dentist=_dentist_for(request, patient))
    initial = {"reasons": reasons_for(patient, exam), "findings": letter_findings(patient, exam),
               "question": QUESTION, "procedures": request.GET.get("procedure") or "implants",
               "dentist": consult.dentist}
    consult.procedures = initial["procedures"]
    initial["medications"] = usual_medications(consult)
    return _consult_form(request, patient, consult, initial)


@role_required(*CLINICAL)
def consult_update(request, pk):
    consult = get_object_or_404(MedicalConsult, pk=pk)
    patient = get_visible_patient_or_403(request.user, consult.patient_id)
    return _consult_form(request, patient, consult, {})


def _consult_form(request, patient, consult, initial):
    form = MedicalConsultForm(request.POST or None, instance=consult, initial=initial)
    if request.method == "POST" and form.is_valid():
        consult = form.save(commit=False)
        if consult.pk is None:
            consult.created_by = request.user
        if consult.bleeding == MedicalConsult.Bleeding.MINOR and set(consult.procedure_codes) & {
                "full_arch", "sinus", "bone_graft"} and "bleeding" not in form.changed_data:
            consult.bleeding = MedicalConsult.Bleeding.MODERATE
        consult.save()
        messages.success(request, _("The consultation is ready: print it and give it to the patient."))
        return redirect(consult)
    return render(request, "patients/consult_form.html", {
        "form": form, "patient": patient, "consult": consult, "flags": reading_flags(latest_history(patient)),
        "medications_url": reverse("patients:consult_medications", args=[patient.pk]),
    })


@role_required(*CLINICAL)
def consult_medications(request, pk):
    """The usual medicines for the procedures ticked (the form asks when the procedure changes)."""
    from django.http import JsonResponse

    patient = get_visible_patient_or_403(request.user, pk)
    consult = MedicalConsult(patient=patient, procedures=",".join(request.GET.getlist("procedure")))
    return JsonResponse({"medications": usual_medications(consult)})


@role_required(*CLINICAL)
@require_POST
def consult_not_needed(request, pk):
    """The dentist looked at the readings and decides no physician's opinion is needed: the patient leaves the list."""
    patient = get_visible_patient_or_403(request.user, pk)
    exam = latest_history(patient)
    MedicalConsult.objects.create(
        patient=patient, branch=patient.branch, dentist=_dentist_for(request, patient),
        status=MedicalConsult.Status.NOT_NEEDED, reasons=",".join(reasons_for(patient, exam)),
        findings=letter_findings(patient, exam), answer_notes=request.POST.get("note", "")[:500],
        answered_on=timezone.localdate(), answer_recorded_by=request.user, created_by=request.user)
    messages.success(request, _("Noted: no consultation needed for %(name)s.") % {"name": patient.full_name})
    return redirect(request.POST.get("next") or reverse("patients:medical_followup"))


@role_required(*PATIENT_VIEWERS)
def consult_detail(request, pk):
    """The letter to print (English, for the physician), and below it the physician's answer."""
    consult = get_object_or_404(MedicalConsult.objects.select_related("patient", "dentist", "branch"), pk=pk)
    patient = get_visible_patient_or_403(request.user, consult.patient_id)
    form = ConsultAnswerForm(instance=consult, initial={"answered_by": consult.physician})
    return render(request, "patients/consult_detail.html", {
        "consult": consult, "patient": patient, "form": form, "place": consult.branch or branch_for_user(request.user),
        "can_write": has_role(request.user, *CLINICAL),
    })


@role_required(*PATIENT_VIEWERS)
@require_POST
def consult_answer(request, pk):
    """The physician's answer, as the patient brought it (the reception or the dentist copies it, with its photo).
    The dentist who wrote the letter is told."""
    consult = get_object_or_404(MedicalConsult, pk=pk)
    patient = get_visible_patient_or_403(request.user, consult.patient_id)
    if consult.status == MedicalConsult.Status.NOT_NEEDED:
        raise PermissionDenied
    form = ConsultAnswerForm(request.POST, request.FILES, instance=consult)
    if not form.is_valid():
        return render(request, "patients/consult_detail.html", {
            "consult": consult, "patient": patient, "form": form, "open_answer": True,
            "place": consult.branch or branch_for_user(request.user), "can_write": has_role(request.user, *CLINICAL),
        })
    consult = form.save(commit=False)
    consult.status, consult.answer_recorded_by = MedicalConsult.Status.ANSWERED, request.user
    consult.answered_on = consult.answered_on or timezone.localdate()
    consult.save()
    dentists = [d.user for d in (consult.dentist, patient.assigned_dentist) if d is not None and d.user_id]
    notify_users(dentists, gettext_lazy("Medical consultation answered: %(patient)s — %(answer)s"),
                 url=consult.get_absolute_url(), exclude=request.user,
                 params={"patient": patient.full_name, "answer": dict(MedicalConsult.Answer.choices)[consult.answer]})
    messages.success(request, _("The physician's answer is saved."))
    return redirect(consult)
