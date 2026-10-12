"""Papers for the patient (round 16): the professional sick leave (the doctor certifies the treatment and the days
of rest) and the consents (the procedure, its risks and other options, signed by the patient on the tablet or on
paper)."""

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.core.forms import StyledModelForm, validate_upload
from apps.core.roles import CLINICAL, FRONT_DESK, has_role
from apps.core.signatures import clean_signature
from apps.dentists.forms import DentistChoiceField
from apps.dentists.models import Dentist
from apps.patients.access import get_visible_patient_or_403

from .models import ConsentTemplate, PatientConsent, SickLeave


def _today_work(patient):
    """What was done today (the diagnosis and treatment of a sick leave): the steps and surgeries of the day."""
    from apps.clinical.models import TreatmentStep
    from apps.surgery.models import Surgery

    today = timezone.localdate()
    steps = [f"{s.step_type} {s.teeth}".strip() for s in TreatmentStep.objects.filter(
        patient=patient, performed_at__date=today).select_related("step_type")]
    for surgery in Surgery.objects.filter(patient=patient, date=today).prefetch_related("sites"):
        teeth = ", ".join(str(site.tooth) for site in surgery.sites.all())
        steps.append(f"{_('Dental surgery')} {teeth}".strip())
    return "، ".join(steps)


class SickLeaveForm(StyledModelForm):
    dentist = DentistChoiceField(label=gettext_lazy("doctor"))

    class Meta:
        model = SickLeave
        fields = ["dentist", "seen_on", "diagnosis", "treatment", "days", "starts_on", "purpose", "advice"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["days"].widget.attrs.update({"min": 1, "max": 30})
        for name in ("seen_on", "days", "starts_on", "purpose"):
            self.fields[name].col = "col-6 col-md-3"

    def clean_days(self):
        days = self.cleaned_data["days"]
        if not 1 <= days <= 30:
            raise forms.ValidationError(_("Between 1 and 30 days."))
        return days


def sick_leave_create(request, patient_pk):
    """The doctor writes the sick leave; it opens ready to print."""
    if not has_role(request.user, *CLINICAL):
        raise PermissionDenied
    patient = get_visible_patient_or_403(request.user, patient_pk)
    me = Dentist.for_user(request.user)
    done = _today_work(patient)
    with translation.override("ar"):  # the paper is the patient's: Arabic, like his instructions
        advice = _("Rest at home, no hard effort, soft food, and the medicines as prescribed.")
    form = SickLeaveForm(request.POST or None, initial={
        "dentist": me or patient.assigned_dentist, "treatment": done, "days": 3 if done else 1, "advice": advice})
    if request.method == "POST" and form.is_valid():
        leave = form.save(commit=False)
        leave.patient, leave.branch, leave.created_by = patient, patient.branch, request.user
        leave.save()
        messages.success(request, _("Sick leave %(number)s written: print it for the patient.") % {
            "number": leave.number})
        return redirect(leave)
    return render(request, "prescriptions/sick_leave_form.html", {"form": form, "patient": patient})


def sick_leave_print(request, pk):
    leave = get_object_or_404(SickLeave.objects.select_related("patient", "dentist", "branch"), pk=pk)
    patient = get_visible_patient_or_403(request.user, leave.patient_id)
    language = request.GET.get("lang") if request.GET.get("lang") in ("ar", "en") else "ar"
    with translation.override(language):
        return render(request, "prescriptions/sick_leave_print.html", {
            "leave": leave, "patient": patient, "place": leave.branch, "print_language": language,
            "LANGUAGE_BIDI": language == "ar"})


def suggested_consent(patient):
    """The consent form that fits the patient's open treatment plan best (implant, extraction, root canal...)."""
    from apps.charting.models import PlanItem

    words = " ".join(str(item.step_type.name_en).lower() for item in PlanItem.objects.filter(
        plan__patient=patient, status=PlanItem.Status.PLANNED).select_related("step_type"))
    best = None
    for template in ConsentTemplate.objects.filter(is_active=True):
        keys = [word.strip().lower() for word in template.procedures.split(",") if word.strip()]
        if keys and any(key in words for key in keys):
            return template
        if not keys and best is None:
            best = template
    return best


class ConsentForm(StyledModelForm):
    dentist = DentistChoiceField(label=gettext_lazy("doctor"), required=False)

    class Meta:
        model = PatientConsent
        fields = ["template", "procedure", "teeth", "dentist", "language", "signed_by", "witness"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["template"].queryset = ConsentTemplate.objects.filter(is_active=True)
        self.fields["teeth"].widget.attrs.update({"data-teeth-picker": "multi", "data-digits": "1"})
        for name in ("teeth", "dentist", "language"):
            self.fields[name].col = "col-md-4"


def consent_create(request, patient_pk):
    """Choose the consent form (the one that fits the plan comes first) and the procedure; the next page is signed."""
    if not has_role(request.user, *CLINICAL, *FRONT_DESK):
        raise PermissionDenied
    patient = get_visible_patient_or_403(request.user, patient_pk)
    template = suggested_consent(patient)
    form = ConsentForm(request.POST or None, initial={
        "template": template, "dentist": Dentist.for_user(request.user) or patient.assigned_dentist,
        "language": "ar", "procedure": str(template) if template else ""})
    if request.method == "POST" and form.is_valid():
        consent = form.save(commit=False)
        consent.patient, consent.branch, consent.created_by = patient, patient.branch, request.user
        consent.save()
        return redirect(consent)
    return render(request, "prescriptions/consent_form.html", {"form": form, "patient": patient})


def consent_detail(request, pk):
    """The consent to read with the patient, his signature drawn on the tablet (or a photo of the paper signed), and
    the print."""
    consent = get_object_or_404(PatientConsent.objects.select_related("patient", "template", "dentist", "branch"),
                                pk=pk)
    patient = get_visible_patient_or_403(request.user, consent.patient_id)
    error = None
    if request.method == "POST":
        if not has_role(request.user, *CLINICAL, *FRONT_DESK):
            raise PermissionDenied
        if request.FILES.get("paper"):
            try:
                consent.paper = validate_upload(request.FILES["paper"])
            except forms.ValidationError as problem:
                error = problem.messages[0]
            else:
                consent.signed_at = consent.signed_at or timezone.now()
                consent.save()
                messages.success(request, _("The photo of the signed paper is kept."))
                return redirect(consent)
        else:
            try:
                consent.signature = clean_signature(request.POST.get("signature"))
            except forms.ValidationError as problem:
                error = problem.messages[0]
            else:
                consent.signed_at = timezone.now()
                consent.save()
                messages.success(request, _("Signed. Print it or keep it in the file."))
                return redirect(consent)
    return render(request, "prescriptions/consent_detail.html", {
        "consent": consent, "patient": patient, "place": consent.branch, "error": error,
        "lines": consent.template.lines(consent.language), "paper_rtl": consent.language == "ar",
        "doctor_signature": consent.dentist.signature_image if consent.dentist else ""})
