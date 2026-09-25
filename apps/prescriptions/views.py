from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import branch_for_user
from apps.core.roles import CLINICAL, PATIENT_VIEWERS, has_role
from apps.dentists.models import Dentist
from apps.patients.access import get_visible_patient_or_403
from apps.surgery.models import Surgery

from .forms import LineFormSet, PrescriptionForm
from .models import InstructionSheet, Prescription, PrescriptionLine, PrescriptionTemplate
from .services import best_template, matching_sheets, penicillin_allergy, surgery_procedures


def _surgery_for(request, patient):
    value = request.GET.get("surgery") or request.POST.get("surgery") or ""
    if value.isdigit():
        return Surgery.objects.filter(pk=value, patient=patient).prefetch_related("sites").first()
    return None


def prescription_create(request, patient_pk):
    patient = get_visible_patient_or_403(request.user, patient_pk)
    if not has_role(request.user, *CLINICAL):
        raise PermissionDenied
    surgery = _surgery_for(request, patient)
    allergic = penicillin_allergy(patient)
    templates = PrescriptionTemplate.objects.filter(is_active=True).prefetch_related("lines__group__drugs")
    template = None
    if request.GET.get("template", "").isdigit():
        template = templates.filter(pk=request.GET["template"]).first()
    elif surgery is not None:
        template = best_template(surgery_procedures(surgery), allergic)
    lines = []
    if template is not None:
        for line in template.lines.all():
            drug = next((d for d in line.group.drugs.all() if d.is_active), None)
            if drug is not None:
                lines.append({"drug": drug.pk, "dose": line.dose or line.group.dose})
    me = Dentist.for_user(request.user)
    dentist = (surgery.operator_1 if surgery else None) or patient.assigned_dentist or me
    form = PrescriptionForm(request.POST or None, initial={"prescribed_on": timezone.localdate(), "dentist": dentist})
    formset = LineFormSet(request.POST or None, initial=lines, prefix="lines")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        chosen = [f.cleaned_data for f in formset if f.cleaned_data.get("drug")]
        if not chosen:
            messages.error(request, _("Add at least one drug."))
        else:
            with transaction.atomic():
                prescription = Prescription.objects.create(
                    patient=patient, surgery=surgery, prescribed_on=form.cleaned_data["prescribed_on"],
                    dentist=form.cleaned_data["dentist"], notes=form.cleaned_data["notes"], created_by=request.user,
                )
                PrescriptionLine.objects.bulk_create(
                    PrescriptionLine(prescription=prescription, drug=line["drug"], dose=line["dose"]) for line in chosen
                )
            return redirect(prescription)
    return render(request, "prescriptions/prescription_form.html", {
        "patient": patient, "surgery": surgery, "form": form, "formset": formset, "templates": templates,
        "template": template, "allergic": allergic,
    })


def prescription_print(request, pk):
    prescription = get_object_or_404(
        Prescription.objects.select_related("patient", "dentist", "surgery"), pk=pk
    )
    get_visible_patient_or_403(request.user, prescription.patient_id)
    return render(request, "prescriptions/prescription_print.html", {
        "prescription": prescription, "patient": prescription.patient,
        "lines": prescription.lines.select_related("drug"), "branch": branch_for_user(request.user),
    })


def instructions(request, patient_pk):
    """Post-operative instructions, filled with the patient's name and the surgery done."""
    patient = get_visible_patient_or_403(request.user, patient_pk)
    if not has_role(request.user, *PATIENT_VIEWERS):
        raise PermissionDenied
    surgery = _surgery_for(request, patient)
    if surgery is None and "surgery" not in request.GET:
        surgery = patient.surgeries.prefetch_related("sites").first()
    sheets = InstructionSheet.objects.filter(is_active=True)
    chosen_ids = [int(v) for v in request.GET.getlist("sheet") if v.isdigit()]
    if chosen_ids:
        chosen = [s for s in sheets if s.pk in chosen_ids]
    else:
        chosen = matching_sheets(surgery_procedures(surgery)) if surgery else [s for s in sheets if not s.procedure_set()]
    language = "en" if request.GET.get("language") == "en" else "ar"
    return render(request, "prescriptions/instructions_print.html", {
        "patient": patient, "surgery": surgery, "sheets": sheets, "chosen": chosen,
        "chosen_ids": {s.pk for s in chosen}, "language": language,
        "blocks": [(s, s.lines(language)) for s in chosen], "branch": branch_for_user(request.user),
        "surgeries": patient.surgeries.all()[:10], "today": timezone.localdate(),
    })
