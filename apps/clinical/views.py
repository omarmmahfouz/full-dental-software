import os
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from apps.charting.models import ToothChange
from apps.charting.plans import complete_plan_items
from apps.charting.rules import apply_changes, plan_changes
from apps.charting.teeth import parse_teeth
from apps.core.forms import clean_digits_value
from apps.billing.models import Bill, create_bill
from apps.core.approvals import needs_approval, pending_for, request_change
from apps.core.mixins import SearchMixin, role_required
from apps.core.models import ChangeRequest, ClinicSettings, branch_for_user
from apps.core.roles import CLINICAL, MANAGEMENT, PATIENT_VIEWERS, TEAM_HEAD, has_role, is_only_dentist
from apps.dentists.models import Dentist
from apps.patients.access import get_clinical_patient_or_403, get_visible_patient_or_403, visible_patients
from apps.scheduling.models import Appointment, day_bounds

from .forms import (
    LabActionForm, LabFilterForm, LabRequestForm, OutsideDoneForm, OutsideRequestForm, StepFilterForm,
    StepOperatorForm, StepReviewForm, TreatmentStepForm,
)
from .models import (
    STEP_GROUP_ICONS, STEP_SHOTS, LabRequest, LabRequestEvent, OutsideRequest, StepGroup, TreatmentStep,
    TreatmentStepType,
)
from .services import ACTION_LABELS, TRANSITIONS, available_actions, perform_lab_action

ANY_STAFF = PATIENT_VIEWERS


def _patient_and_appointment(request):
    """Pre-selected patient / visit passed as ?patient=&appointment= (validated for the user)."""
    patient = appointment = None
    source = request.POST if request.method == "POST" else request.GET
    patient_id = source.get("patient") or request.GET.get("patient")
    if patient_id and str(patient_id).isdigit():
        patient = visible_patients(request.user).filter(pk=patient_id).first()
    appointment_id = source.get("appointment") or request.GET.get("appointment")
    if patient and appointment_id and str(appointment_id).isdigit():
        appointment = Appointment.objects.filter(pk=appointment_id, patient=patient).first()
    return patient, appointment


def record_treatment_on_chart(step, user, update_chart=True):
    """Apply the treatment's chart effect (when confirmed) and tick matching plan items."""
    teeth = parse_teeth(step.teeth)
    changed = 0
    if update_chart and teeth:
        changes = plan_changes(step.patient, step.step_type.chart_effect, teeth, step.surfaces, step.material)
        changed = apply_changes(step.patient, changes, user, ToothChange.Source.TREATMENT, treatment=step,
                                when=step.performed_at)
        if changed:
            TreatmentStep.objects.filter(pk=step.pk).update(chart_updated=True)
    completed = complete_plan_items(step.patient, step.step_type, teeth, treatment=step, when=step.performed_at)
    return changed, completed


# ------------------------------------------------------------ treatment log
class StepListView(SearchMixin, ListView):
    template_name = "clinical/step_list.html"
    paginate_by = 50

    def get_queryset(self):
        if not has_role(self.request.user, *CLINICAL):
            raise PermissionDenied
        self.filter_form = StepFilterForm(self.request.GET or None)
        qs = TreatmentStep.objects.filter(patient__branch=branch_for_user(self.request.user)).select_related(
            "patient", "step_type", "operator", "assistant", "supervisor", "verified_by"
        )
        if is_only_dentist(self.request.user):
            # Their own work, and what they recorded for the course candidates.
            me = Dentist.for_user(self.request.user)
            mine = Q(created_by=self.request.user)
            if me is not None:
                mine |= Q(operator=me) | Q(assistant=me)
            qs = qs.filter(mine)
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            if data.get("date_from"):
                qs = qs.filter(performed_at__gte=day_bounds(data["date_from"])[0])
            if data.get("date_to"):
                qs = qs.filter(performed_at__lt=day_bounds(data["date_to"])[1])
            if data.get("dentist"):
                qs = qs.filter(Q(operator=data["dentist"]) | Q(assistant=data["dentist"]))
            if data.get("step_type"):
                qs = qs.filter(step_type=data["step_type"])
            if data.get("tooth"):
                qs = qs.filter(teeth__contains=data["tooth"])
            if data.get("unchecked"):
                qs = qs.filter(verified_at__isnull=True)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        return context


def step_create(request):
    if not has_role(request.user, *CLINICAL):
        raise PermissionDenied
    patient, appointment = _patient_and_appointment(request)
    me = Dentist.for_user(request.user)
    initial = {"performed_at": timezone.localtime().replace(second=0, microsecond=0)}
    # The operator is usually the candidate the patient is booked with; the CIA
    # dentist who writes it down assists.
    if appointment and appointment.dentist_id:
        initial["operator"] = appointment.dentist
    elif patient and patient.assigned_dentist_id:
        initial["operator"] = patient.assigned_dentist
    elif me is not None:
        initial["operator"] = me
    if me is not None and initial.get("operator") != me:
        initial["assistant"] = me
    form = TreatmentStepForm(request.POST or None, user=request.user, patient=patient, initial=initial)
    if "bill_service" in form.fields:  # the services of the place worked in
        from apps.billing.models import Service

        form.fields["bill_service"].queryset = Service.for_place(branch_for_user(request.user))
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            step = form.save(commit=False)
            step.patient = form.cleaned_data["patient_lookup"]
            step.appointment = appointment if appointment and appointment.patient_id == step.patient.pk else None
            step.created_by = request.user
            step.save()
            changed, completed = record_treatment_on_chart(step, request.user, form.cleaned_data.get("update_chart"))
            bill = None
            if form.cleaned_data.get("bill_service"):
                bill = create_bill(step.patient, [{"service": form.cleaned_data["bill_service"], "teeth": step.teeth,
                                                   "price": form.cleaned_data.get("bill_price")}],
                                   request.user, billed_on=timezone.localtime(step.performed_at).date(),
                                   appointment=step.appointment, dentist=step.operator, source=Bill.Source.DENTIST,
                                   notes=str(step.step_type),
                                   branch=step.appointment.branch if step.appointment_id else branch_for_user(request.user))
        message = _("Treatment saved.")
        if bill is not None:
            from apps.billing.views import send_bill_to_reception

            send_bill_to_reception(bill, request.user)
            message += " " + _("Bill %(number)s sent to the reception to collect.") % {"number": bill.number}
        if changed:
            message += " " + _("Dental chart updated for %(n)s teeth.") % {"n": changed}
        if completed:
            message += " " + _("%(n)s treatment plan items marked as done.") % {"n": len(completed)}
        messages.success(request, message)
        if "add_another" in request.POST:
            return redirect(f"{reverse('clinical:step_create')}?patient={step.patient_id}")
        if step.step_type.shots:  # then its photos and periapical X-rays
            messages.info(request, _("Now take the photos and X-rays of this step."))
            return redirect(step)
        return redirect(reverse("charting:chart", args=[step.patient_id]))
    return render(
        request, "clinical/step_form.html",
        {"form": form, "title": _("Record treatment"), "appointment": appointment, "patient": patient,
         "step_groups": step_groups(), "chosen_group": request.GET.get("group", "")},
    )


def step_groups():
    """The kinds of work with their steps, for the picker of the treatment form (only the kinds that have steps)."""
    types = list(TreatmentStepType.objects.filter(is_active=True))
    groups = []
    for code, label in StepGroup.choices:
        rows = [{"id": t.pk, "name": str(t), "shots": len(t.shot_list())} for t in types if t.group == code]
        if rows:
            groups.append({"code": code, "label": label, "icon": STEP_GROUP_ICONS.get(code, "bi-dot"), "types": rows})
    return groups


def step_detail(request, pk):
    step = get_object_or_404(
        TreatmentStep.objects.select_related(
            "patient", "step_type", "operator", "assistant", "supervisor", "verified_by", "appointment"
        ),
        pk=pk,
    )
    get_clinical_patient_or_403(request.user, step.patient_id)
    can_review = has_role(request.user, *MANAGEMENT)
    form = StepReviewForm(request.POST or None, instance=step) if can_review else None
    if request.method == "POST":
        if not can_review:
            raise PermissionDenied
        if form.is_valid():
            step = form.save(commit=False)
            step.verified_by = request.user
            step.verified_at = timezone.now()
            step.save()
            messages.success(request, _("Treatment checked."))
            return redirect("clinical:step_detail", pk=step.pk)
    photos = list(step.photos.all())
    shots = [{"code": code, "label": label, "photos": [p for p in photos if p.shot == code]}
             for code, label in step.step_type.shot_list()]
    return render(
        request, "clinical/step_detail.html",
        {"step": step, "review_form": form, "chart_changes": step.tooth_changes.all(), "shots": shots,
         "other_photos": [p for p in photos if p.shot not in {s["code"] for s in shots}],
         "can_upload": has_role(request.user, *CLINICAL),
         "operator_form": StepOperatorForm(instance=step) if has_role(request.user, *CLINICAL) else None,
         "pending_changes": pending_for(step)},
    )


@require_POST
def step_photo(request, pk):
    """A photo or a periapical X-ray of a treatment step (taken with the tablet's camera or chosen), kept with the
    patient's photos under "Treatment steps"."""
    from apps.charting.models import ClinicalPhoto, PhotoStage
    from apps.charting.views import ALLOWED_MEDIA, MAX_PHOTO_MB
    from apps.core import previews
    from apps.core.uploads import looks_right

    step = get_object_or_404(TreatmentStep.objects.select_related("step_type"), pk=pk)
    if not has_role(request.user, *CLINICAL):
        raise PermissionDenied
    get_clinical_patient_or_403(request.user, step.patient_id)
    shot = request.POST.get("shot", "")
    if shot and shot not in dict(STEP_SHOTS):
        shot = ""
    saved = 0
    for upload in request.FILES.getlist("file"):
        ext = os.path.splitext(upload.name)[1].lower()
        if ext not in ALLOWED_MEDIA or ext in ClinicalPhoto.VIDEO_EXTENSIONS or upload.size > MAX_PHOTO_MB * 1024 * 1024 \
                or not looks_right(upload):
            messages.error(request, _("%(name)s: only photos or PDF up to %(mb)s MB.") % {"name": upload.name,
                                                                                       "mb": MAX_PHOTO_MB})
            continue
        photo = ClinicalPhoto.objects.create(
            patient=step.patient, stage=PhotoStage.TREATMENT, treatment_step=step, shot=shot, file=upload,
            teeth=step.teeth, taken_on=timezone.localtime(step.performed_at).date(),
            notes=str(step.step_type)[:255], created_by=request.user)
        previews.make_previews(photo.file.name)
        saved += 1
    if saved:
        messages.success(request, _("%(n)s files uploaded.") % {"n": saved})
    return redirect(step)


@require_POST
def step_operator(request, pk):
    """The operator is chosen freely when the treatment is recorded; changing it afterwards needs the
    approval of the head of CIA (who changes it directly)."""
    step = get_object_or_404(TreatmentStep, pk=pk)
    get_clinical_patient_or_403(request.user, step.patient_id)
    form = StepOperatorForm(request.POST, instance=TreatmentStep.objects.get(pk=pk))
    if form.is_valid():
        values = {name: form.cleaned_data.get(name) for name in form.fields}
        if needs_approval(request.user):
            if request_change(ChangeRequest.Kind.OPERATOR, step, values, request.user, form.cleaned_data.get("why", "")):
                messages.success(request, _("Sent to the head of CIA for approval."))
        else:
            for name, value in values.items():
                setattr(step, name, value)
            step.save(update_fields=list(values) + ["updated_at"])
            messages.success(request, _("Operator changed."))
    return redirect(step)


# ------------------------------------------------------------ lab requests
class LabListView(SearchMixin, ListView):
    template_name = "clinical/lab_list.html"
    paginate_by = 50

    def get_queryset(self):
        user = self.request.user
        if not has_role(user, *ANY_STAFF):
            raise PermissionDenied
        self.filter_form = LabFilterForm(self.request.GET or None)
        qs = LabRequest.objects.filter(patient__branch=branch_for_user(user)).select_related(
            "patient", "work_type", "lab", "dentist")
        me = Dentist.for_user(user)
        if is_only_dentist(user):
            qs = qs.filter(Q(dentist=me) | Q(patient__assigned_dentist=me)) if me else qs.none()
        self.base_qs = qs
        if self.filter_form.is_valid():
            data = self.filter_form.cleaned_data
            q = clean_digits_value(data.get("q"))
            if q:
                qs = qs.filter(
                    Q(number__icontains=q) | Q(patient__full_name__icontains=q) | Q(patient__file_number__icontains=q)
                )
            if data.get("part") == "planned":
                qs = qs.filter(status__in=LabRequest.OPEN_STATUSES)
            elif data.get("part") == "done":
                qs = qs.filter(status=LabRequest.Status.DELIVERED)
            status = data.get("status")
            if status == "open":
                qs = qs.filter(status__in=LabRequest.OPEN_STATUSES)
            elif status:
                qs = qs.filter(status=status)
            if data.get("lab"):
                qs = qs.filter(lab=data["lab"])
            if data.get("overdue"):
                qs = qs.filter(status=LabRequest.Status.SENT, due_date__lt=timezone.localdate())
            if data.get("mine"):
                qs = qs.filter(dentist=me) if me else qs.none()
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        # The tabs: the treatment plan (in work) and the treatment done (delivered), with how many of each.
        base = getattr(self, "base_qs", None)
        if base is not None:
            counts = base.aggregate(
                planned=Count("pk", filter=Q(status__in=LabRequest.OPEN_STATUSES)),
                done=Count("pk", filter=Q(status=LabRequest.Status.DELIVERED)), every=Count("pk"))
            part = self.filter_form.cleaned_data.get("part", "") if self.filter_form.is_valid() else ""
            rest = self.request.GET.copy()
            rest.pop("page", None)
            tabs = []
            for code, label, count in (("", _("All"), counts["every"]),
                                       ("planned", _("Treatment plan: still in work"), counts["planned"]),
                                       ("done", _("Treatment done: delivered"), counts["done"])):
                rest["part"] = code
                tabs.append({"code": code, "label": label, "count": count, "active": code == part,
                             "url": "?" + rest.urlencode()})
            context["part_tabs"] = tabs
        return context


def lab_create(request):
    if not has_role(request.user, *ANY_STAFF):
        raise PermissionDenied
    patient, appointment = _patient_and_appointment(request)
    me = Dentist.for_user(request.user)
    initial = {}
    if appointment and appointment.dentist_id:
        initial["dentist"] = appointment.dentist
    elif patient and patient.assigned_dentist_id:
        initial["dentist"] = patient.assigned_dentist
    elif me is not None:
        initial["dentist"] = me
    initial.update(_shade_initial(request, patient))
    form = LabRequestForm(request.POST or None, user=request.user, patient=patient, initial=initial)
    if request.method == "POST" and form.is_valid():
        lab_request = form.save(commit=False)
        lab_request.patient = form.cleaned_data["patient_lookup"]
        lab_request.branch = branch_for_user(request.user)
        lab_request.appointment = appointment if appointment and appointment.patient_id == lab_request.patient.pk else None
        lab_request.created_by = request.user
        lab_request.save()
        LabRequestEvent.objects.create(request=lab_request, action=LabRequestEvent.Action.CREATED, by=request.user)
        if "submit_for_review" in request.POST:
            perform_lab_action(lab_request, "submit", request.user)
            if lab_request.status == LabRequest.Status.APPROVED:
                messages.success(request, _("Lab request saved as reviewed by %(supervisor)s. The secretary will send it "
                                            "to the lab.") % {"supervisor": lab_request.supervisor})
            else:
                messages.success(request, _("Lab request saved and sent for review."))
        else:
            messages.success(request, _("Lab request saved as draft."))
        return redirect(lab_request)
    return render(request, "clinical/lab_form.html", {"form": form, "title": _("New lab request")})


def _shade_initial(request, patient):
    """A lab request made from a shade record (``?shade_record=``) takes its teeth and shades."""
    from apps.specialties.models import ShadeRecord

    pk = request.GET.get("shade_record", "")
    record = ShadeRecord.objects.filter(pk=pk, patient=patient).first() if patient and pk.isdigit() else None
    if record is None:
        return {}
    return {"teeth": record.teeth, "shade_guide": record.guide, "shade": record.shade,
            "shade_cervical": record.shade_cervical, "shade_incisal": record.shade_incisal,
            "stump_shade": record.stump, "material": record.prosthesis[:100],
            "instructions": "\n".join(part for part in (
                ", ".join(str(label) for label in record.character_labels()),
                f"{record._meta.get_field('translucency').verbose_name}: {record.get_translucency_display()}"
                if record.translucency else "", record.notes) if part)}


def lab_edit(request, pk):
    lab_request = get_object_or_404(LabRequest.objects.select_related("dentist"), pk=pk)
    get_visible_patient_or_403(request.user, lab_request.patient_id)
    editable = lab_request.status in (LabRequest.Status.DRAFT, LabRequest.Status.PENDING_REVIEW)
    if not editable or not has_role(request.user, *ANY_STAFF):
        raise PermissionDenied
    form = LabRequestForm(request.POST or None, instance=lab_request, user=request.user, patient=lab_request.patient)
    if request.method == "POST" and form.is_valid():
        lab_request = form.save(commit=False)
        lab_request.patient = form.cleaned_data["patient_lookup"]
        lab_request.save()
        messages.success(request, _("Lab request updated."))
        return redirect(lab_request)
    return render(request, "clinical/lab_form.html", {"form": form, "title": _("Edit lab request"), "object": lab_request})


def lab_detail(request, pk):
    lab_request = get_object_or_404(
        LabRequest.objects.select_related(
            "patient", "work_type", "lab", "dentist", "supervisor", "reviewed_by", "sent_by", "received_by"
        ),
        pk=pk,
    )
    get_visible_patient_or_403(request.user, lab_request.patient_id)
    actions = [
        {"code": code, "label": ACTION_LABELS[code], "needs_check": TRANSITIONS[code][3], "needs_notes": TRANSITIONS[code][4]}
        for code in available_actions(lab_request, request.user)
    ]
    return render(
        request,
        "clinical/lab_detail.html",
        {
            "lab_request": lab_request,
            "events": lab_request.events.select_related("by"),
            "actions": actions,
            "can_edit": lab_request.status in (LabRequest.Status.DRAFT, LabRequest.Status.PENDING_REVIEW)
            and has_role(request.user, *ANY_STAFF),
            "fitting_url": _fitting_url(lab_request) if lab_request.status == LabRequest.Status.RECEIVED else "",
            "lab_case": _lab_case(lab_request),
            "next_appointment": Appointment.objects.filter(
                patient=lab_request.patient, status__in=Appointment.WAITING_STATUSES,
                scheduled_at__gte=timezone.now()).order_by("scheduled_at").first(),
        },
    )


def _lab_case(lab_request):
    """The case at our own lab (the last remake when there is one): its step is shown live on the request."""
    from apps.lab.models import LabCase

    return (LabCase.objects.filter(Q(request=lab_request) | Q(remake_of__request=lab_request))
            .select_related("worker").order_by("-pk").first())


def _fitting_url(lab_request):
    """Book the patient to try in / fit the work that came back from the lab."""
    fitting = TreatmentStepType.objects.filter(name_en__in=("Try-in", "Final prosthesis delivery")).order_by(
        "-name_en").first()
    params = {"patient": lab_request.patient_id, "purpose": f"{lab_request.work_type} {lab_request.teeth} "
                                                            f"({lab_request.number})"}
    if lab_request.dentist_id:
        params["dentist"] = lab_request.dentist_id
    if fitting is not None:
        params["procedure"] = fitting.pk
    return f"{reverse('scheduling:appointment_create')}?{urlencode(params)}"


@require_POST
def lab_action(request, pk):
    lab_request = get_object_or_404(LabRequest, pk=pk)
    get_visible_patient_or_403(request.user, lab_request.patient_id)
    form = LabActionForm(request.POST)
    form.is_valid()
    data = form.cleaned_data
    try:
        perform_lab_action(
            lab_request, data.get("action", ""), request.user, notes=data.get("notes", ""), checked=data.get("checked", False)
        )
    except ValidationError as error:
        for message in error.messages:
            messages.error(request, message)
    else:
        messages.success(request, _("Done: %(action)s") % {"action": ACTION_LABELS[data["action"]]})
    return redirect(lab_request)


@role_required(*ANY_STAFF)
def lab_print(request, pk):
    """The lab prescription printed with the place's letterhead: the teeth on a chart, the shade tabs in colour, the
    design, what is sent with the work, and the signatures."""
    from apps.charting.teeth import LOWER, UPPER, parse_teeth
    from apps.specialties import shades

    lab_request = get_object_or_404(LabRequest.objects.select_related(
        "patient", "work_type", "lab", "dentist", "branch", "supervisor", "reviewed_by"), pk=pk)
    get_visible_patient_or_403(request.user, lab_request.patient_id)
    chosen = set(parse_teeth(lab_request.teeth)) if lab_request.teeth else set()
    colours = [(label, getattr(lab_request, name), shades.COLOURS.get(getattr(lab_request, name), ""))
               for label, name in ((_("Cervical"), "shade_cervical"), (_("Middle"), "shade"),
                                   (_("Incisal"), "shade_incisal"), (_("Stump"), "stump_shade"))
               if getattr(lab_request, name)]
    return render(request, "clinical/lab_print.html", {
        "lab_request": lab_request, "place": lab_request.branch, "shade_colours": colours,
        "upper": [(tooth, tooth in chosen) for tooth in UPPER], "lower": [(tooth, tooth in chosen) for tooth in LOWER],
    })


# ------------------------------------------------------------ CBCT and medical lab requests
@role_required(*ANY_STAFF)
def outside_create(request):
    patient_id = request.GET.get("patient", "")
    patient = get_visible_patient_or_403(request.user, int(patient_id)) if patient_id.isdigit() else None
    if patient is None:
        raise Http404
    kind = request.GET.get("kind")
    if kind not in OutsideRequest.Kind.values:
        kind = OutsideRequest.Kind.CBCT
    me = Dentist.for_user(request.user)
    form = OutsideRequestForm(request.POST or None, kind=kind, initial={
        "requested_on": timezone.localdate(), "dentist": me or patient.assigned_dentist})
    if request.method == "POST" and form.is_valid():
        outside = form.save(commit=False)
        outside.patient, outside.kind, outside.created_by = patient, kind, request.user
        outside.save()
        nxt = request.GET.get("next", "")
        if nxt.startswith("/") and not nxt.startswith("//"):  # e.g. back to the file, step by step
            return redirect(f"{outside.get_absolute_url()}?{urlencode({'next': nxt})}")
        return redirect(outside)
    return render(request, "includes/form_page.html", {
        "form": form, "title": f"{OutsideRequest.Kind(kind).label} — {patient.full_name}",
        "cancel_url": patient.get_absolute_url(), "submit_label": _("Save and print"),
    })


@role_required(*ANY_STAFF)
def outside_print(request, pk):
    outside = get_object_or_404(OutsideRequest.objects.select_related("patient", "dentist", "result", "done_by"),
                                pk=pk)
    get_visible_patient_or_403(request.user, outside.patient_id)
    nxt = request.GET.get("next", "")
    return render(request, "clinical/outside_print.html", {
        "outside": outside, "dicom_email": ClinicSettings.get().dicom_email,
        "branch": outside.patient.branch or branch_for_user(request.user),
        "next": nxt if nxt.startswith("/") and not nxt.startswith("//") else "",
    })


@role_required(*ANY_STAFF)
def outside_done(request, pk):
    """The CBCT (or the tests) is done: here on our machine or at the centre, and where the scan is kept. It is
    added to the patient's X-rays & CBCT, and "CBCT done" then opens it."""
    from apps.patients.models import PatientDocument

    outside = get_object_or_404(OutsideRequest.objects.select_related("patient"), pk=pk)
    patient = get_visible_patient_or_403(request.user, outside.patient_id)
    place = patient.branch
    if request.method == "POST" and request.POST.get("action") == "cancel":
        outside.status = OutsideRequest.Status.CANCELLED
        outside.save(update_fields=["status", "updated_at"])
        messages.info(request, _("The request is cancelled."))
        return redirect(outside)
    form = OutsideDoneForm(request.POST or None, request.FILES or None, outside=outside, has_cbct=place.has_cbct,
                           initial={"done_on": timezone.localdate(), "where": request.GET.get("where")})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        with transaction.atomic():
            if data["location"] or data["file"]:
                is_cbct = outside.kind == OutsideRequest.Kind.CBCT
                outside.result = PatientDocument.objects.create(
                    patient=patient, kind=PatientDocument.Kind.XRAY if is_cbct else PatientDocument.Kind.OTHER,
                    location=data["location"].strip(), file=data["file"] or "", created_by=request.user,
                    notes=f"{outside.get_kind_display()} {data['done_on']:%d/%m/%Y}"[:255])
            outside.status, outside.done_on, outside.done_by = data["where"], data["done_on"], request.user
            outside.save()
        if outside.kind == OutsideRequest.Kind.CBCT:
            patient.examinations.filter(cbct_requested=True, cbct_done=False).update(cbct_done=True)
        messages.success(request, _("Saved as done.") + (
            " " + _("Write where the scan is kept when you have it, so it opens with one click.")
            if outside.result_id is None else ""))
        return redirect(outside)
    return render(request, "includes/form_page.html", {
        "form": form, "title": _("%(what)s done — %(name)s") % {"what": outside.get_kind_display(),
                                                                "name": patient.full_name},
        "title_icon": "bi-radioactive", "cancel_url": outside.get_absolute_url(),
    })


def visits_missing_notes(request):
    """The visits with nothing written in the patient's file: the dentist's own, or all for the heads."""
    from .visit_notes import visits_without_notes

    if not has_role(request.user, *CLINICAL):
        raise PermissionDenied
    me = Dentist.for_user(request.user)
    everyone = has_role(request.user, *MANAGEMENT) or has_role(request.user, TEAM_HEAD)
    if me is None and not everyone:
        raise PermissionDenied
    visits = visits_without_notes(None if everyone and not request.GET.get("mine") else me)
    return render(request, "clinical/visits_missing_notes.html", {"visits": visits, "everyone": everyone})
