import os
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.clinical.models import TreatmentStep, TreatmentStepType
from apps.core.roles import CLINICAL, MANAGEMENT, has_role
from apps.dentists.models import Dentist
from apps.patients.access import get_clinical_patient_or_403

from . import odontogram, photo_files
from .forms import ExaminationForm, PhotoUploadForm, PlanItemFormSet, ToothForm, TreatmentPlanForm
from .models import ClinicalPhoto, Examination, PhotoStage, PhotoType, PlanItem, ToothChange, ToothState, TreatmentPlan
from .plans import planned_by_tooth
from .rules import DEFAULT, apply_changes, current_states, exam_changes, plan_changes, state_label
from .sync import missing_teeth, sync_medical_history
from .teeth import VALID_TEETH, format_teeth, parse_surfaces, parse_teeth

ALLOWED_MEDIA = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp", ".tif", ".tiff", ".pdf"} | ClinicalPhoto.VIDEO_EXTENSIONS
MAX_PHOTO_MB = 25
MAX_VIDEO_MB = 300


def _require_clinical(user):
    if not has_role(user, *CLINICAL):
        raise PermissionDenied


def chart_svg(patient, clickable=True):
    link = reverse("charting:tooth", args=[patient.pk, 0]).replace("/0/", "/__tooth__/") if clickable else None
    return odontogram.render(current_states(patient), planned_by_tooth(patient), link=link)


def chart(request, patient_pk):
    patient = get_clinical_patient_or_403(request.user, patient_pk)
    states = current_states(patient)
    rows = []
    for tooth, state in sorted(states.items()):
        site = state.implant_site if state.implant_site_id else None
        label = state_label(state.snapshot(), site)
        if label != state_label(DEFAULT):
            rows.append({"tooth": tooth, "label": label, "site": site, "notes": state.notes})
    return render(request, "charting/chart.html", {
        "patient": patient,
        "svg": chart_svg(patient, clickable=has_role(request.user, *CLINICAL)),
        "rows": rows,
        "exam": patient.examinations.prefetch_related("conditions").first(),
        "plans": patient.treatment_plans.filter(status__in=TreatmentPlan.OPEN_STATUSES).prefetch_related("items__step_type"),
        "changes": patient.tooth_changes.select_related("changed_by")[:25],
        "prostheses": patient.prostheses.prefetch_related("implants"),
        "steps": patient.treatment_steps.select_related("step_type", "operator", "supervisor")[:30],
        "prescriptions": patient.prescriptions.prefetch_related("lines__drug")[:5],
        "can_edit": has_role(request.user, *CLINICAL),
    })


def tooth_edit(request, patient_pk, tooth):
    patient = get_clinical_patient_or_403(request.user, patient_pk)
    _require_clinical(request.user)
    if tooth not in VALID_TEETH:
        raise PermissionDenied
    state = ToothState.objects.filter(patient=patient, tooth=tooth).select_related("implant_site").first()
    instance = state or ToothState(patient=patient, tooth=tooth)
    before = instance.snapshot()
    form = ToothForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            obj = form.save(commit=False)
            if obj.status != ToothState.Status.IMPLANT:
                obj.implant_site = None
            obj.updated_by = request.user
            after = obj.snapshot()
            if after != before:
                obj.save()
                ToothChange.objects.create(
                    patient=patient, tooth=tooth, changed_by=request.user, source=ToothChange.Source.MANUAL,
                    summary=f"{state_label(before)} → {state_label(after)}"[:255], before=before, after=after,
                )
            elif obj.pk:
                obj.save(update_fields=["notes"])
        messages.success(request, _("Tooth %(tooth)s updated.") % {"tooth": tooth})
        return redirect("charting:chart", patient_pk=patient.pk)
    tooth_str = str(tooth)
    steps = [s for s in patient.treatment_steps.select_related("step_type", "operator")
             if tooth in parse_teeth(s.teeth)]
    from apps.surgery.models import SurgerySite

    sites = SurgerySite.objects.filter(surgery__patient=patient, tooth=tooth).select_related("surgery", "implant_system")
    return render(request, "charting/tooth_form.html", {
        "patient": patient, "tooth": tooth_str, "form": form, "state": instance,
        "history": patient.tooth_changes.filter(tooth=tooth).select_related("changed_by"),
        "steps": steps, "sites": sites,
    })


def chart_preview(request):
    """JSON list of chart changes a treatment would make (shown before saving)."""
    patient_id = request.GET.get("patient")
    if not patient_id:
        from apps.patients.forms import find_patient

        found = find_patient(request.GET.get("lookup"))
        if found is None:
            return JsonResponse({"changes": []})
        patient_id = found.pk
    patient = get_clinical_patient_or_403(request.user, patient_id)
    step_type = TreatmentStepType.objects.filter(pk=request.GET.get("step_type") or 0).first()
    try:
        teeth = parse_teeth(request.GET.get("teeth"))
        surfaces = parse_surfaces(request.GET.get("surfaces"))
    except Exception as error:  # noqa: BLE001 - shown to the user as text
        return JsonResponse({"changes": [], "error": " ".join(getattr(error, "messages", [str(error)]))})
    if step_type is None or not teeth:
        return JsonResponse({"changes": []})
    material = request.GET.get("material", "") or step_type.default_material
    changes = plan_changes(patient, step_type.chart_effect, teeth, surfaces, material)
    return JsonResponse({"changes": [{"tooth": c.tooth, "summary": c.summary} for c in changes]})


# ------------------------------------------------------------ examination & history
def exam_edit(request, patient_pk=None, pk=None):
    _require_clinical(request.user)
    exam = get_object_or_404(Examination, pk=pk) if pk else None
    patient = get_clinical_patient_or_403(request.user, exam.patient_id if exam else patient_pk)
    initial = {}
    if exam is None:
        me = Dentist.for_user(request.user)
        if me is not None:
            initial["examined_by" if me.kind != Dentist.Kind.SUPERVISOR else "supervisor"] = me
        previous = patient.examinations.first()
        if previous is not None:
            # Start from the last history so only what changed needs editing.
            for field in Examination._meta.concrete_fields:
                if field.name not in ("id", "patient", "exam_date", "created_at", "updated_at", "created_by",
                                      "examined_by", "supervisor") and field.name not in Examination.TOOTH_FIELDS:
                    initial[field.attname] = getattr(previous, field.attname)
            # ...together with anything the reception wrote since (as the patient told them).
            initial["conditions"] = list(set(previous.conditions.all()) | set(patient.medical_conditions.all()))
        else:
            initial["conditions"] = list(patient.medical_conditions.all())
    form = ExaminationForm(request.POST or None, instance=exam, initial=initial)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            obj = form.save(commit=False)
            obj.patient = patient
            if not obj.pk:
                obj.created_by = request.user
            obj.save()
            form.save_m2m()
            if obj == patient.examinations.first():
                sync_medical_history(obj)
            changed = 0
            if form.cleaned_data.get("update_chart"):
                changed = apply_changes(patient, exam_changes(patient, obj), request.user,
                                        ToothChange.Source.EXAM, examination=obj)
        messages.success(request, _("Examination and history saved.") + (
            " " + _("Dental chart updated for %(n)s teeth.") % {"n": changed} if changed else ""))
        return redirect(obj)
    return render(request, "charting/exam_form.html", {
        "form": form, "patient": patient, "exam": exam,
        "title": _("Edit examination & history") if exam else _("New examination & history"),
    })


def exam_detail(request, pk):
    exam = get_object_or_404(Examination.objects.select_related("patient", "examined_by", "supervisor"), pk=pk)
    patient = get_clinical_patient_or_403(request.user, exam.patient_id)
    return render(request, "charting/exam_detail.html", {
        "exam": exam, "patient": patient, "svg": chart_svg(patient, clickable=False),
        "can_edit": has_role(request.user, *CLINICAL),
    })


# ------------------------------------------------------------ treatment plans
def plan_edit(request, patient_pk=None, pk=None):
    _require_clinical(request.user)
    plan = get_object_or_404(TreatmentPlan, pk=pk) if pk else None
    patient = get_clinical_patient_or_403(request.user, plan.patient_id if plan else patient_pk)
    initial = {}
    if plan is None:
        me = Dentist.for_user(request.user)
        if me is not None:
            initial["dentist"] = me
    form = TreatmentPlanForm(request.POST or None, instance=plan, initial=initial)
    formset = PlanItemFormSet(request.POST or None, instance=plan or TreatmentPlan(patient=patient), prefix="items")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            obj = form.save(commit=False)
            obj.patient = patient
            if not obj.pk:
                obj.created_by = request.user
            obj.save()
            formset.instance = obj
            formset.save()
        messages.success(request, _("Treatment plan saved."))
        return redirect(obj)
    return render(request, "charting/plan_form.html", {
        "form": form, "formset": formset, "patient": patient, "plan": plan,
        "sections": _plan_sections(formset), "missing": format_teeth(missing_teeth(patient)),
        "title": _("Edit treatment plan") if plan else _("New treatment plan"),
    })


def _plan_sections(formset):
    """The plan's rows in its two parts (implant first). Empty new rows are shared between them,
    and the implant part's new rows start in the surgical phase."""
    sections = [{"code": code, "label": label, "forms": [],
                 "phase": PlanItem.Phase.SURGICAL if code == TreatmentStepType.Category.IMPLANT else ""}
                for code, label in TreatmentStepType.Category.choices]
    by_code = {section["code"]: section for section in sections}
    empty = []
    for item_form in formset:
        category = item_form.category
        (by_code[category]["forms"] if category in by_code else empty).append(item_form)
    for index, item_form in enumerate(empty):
        section = sections[0] if index < (len(empty) + 1) // 2 else sections[1]
        if section["phase"] and not item_form.is_bound:
            item_form.initial["phase"] = section["phase"]
        section["forms"].append(item_form)
    return sections


def plan_detail(request, pk):
    plan = get_object_or_404(TreatmentPlan.objects.select_related("patient", "dentist", "approved_by"), pk=pk)
    patient = get_clinical_patient_or_403(request.user, plan.patient_id)
    return render(request, "charting/plan_detail.html", {
        "plan": plan, "patient": patient,
        "sections": plan.sections(plan.items.select_related("step_type", "done_treatment__operator", "done_surgery")),
        "svg": chart_svg(patient, clickable=False),
        "can_edit": has_role(request.user, *CLINICAL),
        "can_approve": has_role(request.user, *MANAGEMENT) and plan.status == TreatmentPlan.Status.PROPOSED,
    })


@require_POST
def plan_action(request, pk):
    plan = get_object_or_404(TreatmentPlan, pk=pk)
    get_clinical_patient_or_403(request.user, plan.patient_id)
    _require_clinical(request.user)
    action = request.POST.get("action")
    if action == "approve":
        if not has_role(request.user, *MANAGEMENT):
            raise PermissionDenied
        plan.status = TreatmentPlan.Status.APPROVED
        plan.approved_by = Dentist.for_user(request.user)
        plan.approved_at = timezone.now()
    elif action in ("complete", "cancel", "reopen"):
        plan.status = {"complete": TreatmentPlan.Status.COMPLETED, "cancel": TreatmentPlan.Status.CANCELLED,
                       "reopen": TreatmentPlan.Status.PROPOSED}[action]
    elif action in ("item_done", "item_cancel", "item_reopen"):
        item = get_object_or_404(PlanItem, pk=request.POST.get("item"), plan=plan)
        item.status = {"item_done": PlanItem.Status.DONE, "item_cancel": PlanItem.Status.CANCELLED,
                       "item_reopen": PlanItem.Status.PLANNED}[action]
        item.done_at = timezone.now() if action == "item_done" else None
        item.save()
    plan.save()
    messages.success(request, _("Treatment plan updated."))
    return redirect(plan)


# ------------------------------------------------------------ photo checklist
def _session_url(patient, stage, taken_on, teeth):
    return f"{reverse('charting:photos', args=[patient.pk])}?{urlencode({'stage': stage, 'on': taken_on.isoformat(), 'teeth': teeth})}"


def photos(request, patient_pk):
    """The photo checklist of one stage, for one session (a date and the teeth, e.g. the right side
    at the one-week follow-up): each session's photos are kept apart; "show all" shows every one."""
    patient = get_clinical_patient_or_403(request.user, patient_pk)
    can_upload = has_role(request.user, *CLINICAL)
    stage = request.POST.get("stage") or request.GET.get("stage") or PhotoStage.DIAGNOSTIC
    if stage not in PhotoStage.values:
        stage = PhotoStage.DIAGNOSTIC
    all_photos = list(patient.clinical_photos.select_related("photo_type"))
    sessions = sorted({(p.taken_on, p.teeth) for p in all_photos if p.stage == stage}, key=lambda s: (s[0], s[1]),
                      reverse=True)
    show_all = request.GET.get("all") == "1"
    session = None
    if request.GET.get("on"):
        chosen = parse_date(request.GET["on"])
        session = (chosen, request.GET.get("teeth", "")) if chosen else None
    elif sessions and request.GET.get("new") != "1":
        session = sessions[0]  # the latest session of this stage
    initial = {"taken_on": session[0] if session else timezone.localdate(), "teeth": session[1] if session else ""}
    form = PhotoUploadForm(request.POST or None, patient=patient, initial=initial)
    if request.method == "POST":
        if not can_upload:
            raise PermissionDenied
        if form.is_valid():
            saved, errors = 0, []
            types = {str(t.pk): t for t in PhotoType.objects.filter(stage=stage)}
            extra_name = request.POST.get("extra_name", "").strip()[:255]
            for key in request.FILES:
                type_id = key.removeprefix("type_") if key.startswith("type_") else None
                if key != "extra" and type_id not in types:
                    continue
                for upload in request.FILES.getlist(key):
                    ext = os.path.splitext(upload.name)[1].lower()
                    limit = MAX_VIDEO_MB if ext in ClinicalPhoto.VIDEO_EXTENSIONS else MAX_PHOTO_MB
                    if ext not in ALLOWED_MEDIA:
                        errors.append(_("%(name)s: only photos, PDF or videos can be uploaded.") % {"name": upload.name})
                        continue
                    if upload.size > limit * 1024 * 1024:
                        errors.append(_("%(name)s is larger than %(mb)s MB.") % {"name": upload.name, "mb": limit})
                        continue
                    ClinicalPhoto.objects.create(
                        patient=patient, stage=stage, photo_type=types.get(type_id), file=upload,
                        surgery=form.cleaned_data.get("surgery"), teeth=form.cleaned_data.get("teeth", ""),
                        taken_on=form.cleaned_data["taken_on"],
                        notes=(extra_name if key == "extra" and extra_name else form.cleaned_data.get("notes", "")),
                        created_by=request.user,
                    )
                    saved += 1
            for error in errors:
                messages.error(request, error)
            if saved:
                messages.success(request, _("%(n)s files uploaded.") % {"n": saved})
            return redirect(_session_url(patient, stage, form.cleaned_data["taken_on"],
                                         form.cleaned_data.get("teeth", "")))

    def in_session(photo):
        return show_all or session is None or (photo.taken_on, photo.teeth) == session

    stages = []
    for code, label in PhotoStage.choices:
        items = []
        for photo_type in PhotoType.objects.filter(stage=code, is_active=True):
            taken = [p for p in all_photos if p.photo_type_id == photo_type.pk and (code != stage or in_session(p))]
            items.append({"type": photo_type, "photos": taken})
        extra = [p for p in all_photos if p.stage == code and p.photo_type_id is None and (code != stage or in_session(p))]
        required = [i for i in items if not i["type"].optional]
        done = sum(1 for i in required if i["photos"])
        stages.append({"code": code, "label": label, "items": items, "extra": extra,
                       "done": done, "required": len(required)})
    return render(request, "charting/photos.html", {
        "patient": patient, "stages": stages, "stage": stage, "form": form, "can_upload": can_upload,
        "missing": format_teeth(missing_teeth(patient)), "patient_folder": photo_files.patient_folder(patient),
        "sessions": [{"on": on, "teeth": teeth, "count": sum(1 for p in all_photos if p.stage == stage
                                                             and (p.taken_on, p.teeth) == (on, teeth)),
                      "url": _session_url(patient, stage, on, teeth), "current": (on, teeth) == session and not show_all}
                     for on, teeth in sessions],
        "session": session, "show_all": show_all,
    })


@require_POST
def photo_delete(request, pk):
    photo = get_object_or_404(ClinicalPhoto, pk=pk)
    get_clinical_patient_or_403(request.user, photo.patient_id)
    stage = photo.stage
    photo.file.delete(save=False)
    photo.delete()
    messages.success(request, _("File deleted."))
    return redirect(f"{reverse('charting:photos', args=[photo.patient_id])}?stage={stage}")


# ------------------------------------------------------------ photo log book and photo folders
SURGICAL_STAGES = (PhotoStage.SURGERY, PhotoStage.SINUS_GBR, PhotoStage.SOFT_TISSUE, PhotoStage.SECOND_STAGE)
# Photo frame in mm (4:3), fixed so every page looks the same: 6 photos a page, or 12 small ones.
LOGBOOK_FRAMES = {"2": (78, 58.5), "3": (56, 42)}


def _site_text(site):
    text = f"{site.tooth}: {', '.join(site.procedure_labels())}"
    return f"{text} — {site.implant_label}" if site.has_implant else text


def _stage_description(stage, photos, surgeries, steps, plan_items):
    """What was done at this stage, written from the surgery chart, the treatment log and the plan.
    The dentist can still change the text on the page before printing."""
    dates = {photo.taken_on for photo in photos}
    lines = []
    if stage in SURGICAL_STAGES:
        linked = {photo.surgery_id for photo in photos if photo.surgery_id}
        for surgery in surgeries:
            if surgery.pk in linked or (not linked and surgery.date in dates):
                sites = "; ".join(_site_text(site) for site in surgery.sites.all())
                lines.append(f"{surgery.date:%d/%m/%Y} — {surgery.number}: {sites}")
    if stage == PhotoStage.DIAGNOSTIC and plan_items:
        planned = "; ".join(f"{item.step_type} {item.teeth}".strip() for item in plan_items)
        lines.append(f"{_('Treatment plan')}: {planned}")
    for step in steps:
        if timezone.localtime(step.performed_at).date() in dates:
            lines.append(f"{timezone.localtime(step.performed_at):%d/%m/%Y} — {step.step_type} {step.teeth}".strip())
    return "\n".join(dict.fromkeys(lines))


def logbook(request, patient_pk):
    """The case's photos on printable log-book pages: fixed frame size, one stage per page,
    each photo named, with the description of the procedure."""
    patient = get_clinical_patient_or_403(request.user, patient_pk)
    all_photos = [p for p in patient.clinical_photos.select_related("photo_type", "surgery") if not p.is_video
                  and os.path.splitext(p.file.name)[1].lower() != ".pdf"]
    available = [(code, label) for code, label in PhotoStage.choices if any(p.stage == code for p in all_photos)]
    chosen = [code for code in request.GET.getlist("stage") if code in dict(available)] or [c for c, _l in available]
    per_row = request.GET.get("per_row") if request.GET.get("per_row") in LOGBOOK_FRAMES else "2"
    surgeries = list(patient.surgeries.select_related("instructor", "operator_1").prefetch_related(
        "sites__implant_system"))
    steps = list(TreatmentStep.objects.filter(patient=patient).select_related("step_type", "operator"))
    plan_items = list(PlanItem.objects.filter(plan__patient=patient, plan__status__in=TreatmentPlan.OPEN_STATUSES)
                      .exclude(status=PlanItem.Status.CANCELLED).select_related("step_type"))
    pages = []
    for code, label in available:
        if code not in chosen:
            continue
        photos = sorted((p for p in all_photos if p.stage == code),
                        key=lambda p: (p.photo_type.sort_order if p.photo_type_id else 999, p.taken_on))
        surgery = next((p.surgery for p in photos if p.surgery_id), None)
        pages.append({
            "code": code, "label": label, "photos": photos,
            "dates": sorted({p.taken_on for p in photos}),
            "teeth": format_teeth({t for p in photos for t in parse_teeth(p.teeth)}),
            "operator": (surgery.operator_1 if surgery else None) or patient.assigned_dentist,
            "supervisor": surgery.instructor if surgery else None,
            "description": _stage_description(code, photos, surgeries, steps, plan_items),
        })
    width, height = LOGBOOK_FRAMES[per_row]
    return render(request, "charting/logbook.html", {
        "patient": patient, "pages": pages, "available": available, "chosen": chosen, "per_row": per_row,
        "frame_width": width, "frame_height": height, "fit": "contain" if request.GET.get("fit") == "contain" else "cover",
        "anonymous": request.GET.get("anonymous") == "1",
        "initials": "".join(part[0] for part in patient.full_name.split()[:3]),
    })


def photos_zip(request, patient_pk):
    """All the patient's photos in one ZIP, in the same readable folders as on the server."""
    patient = get_clinical_patient_or_403(request.user, patient_pk)
    photos = patient.clinical_photos.select_related("photo_type").order_by("stage", "taken_on")
    archive = photo_files.photos_zip(patient, photos)
    return FileResponse(archive, as_attachment=True, filename=f"{photo_files.patient_folder(patient)}.zip")


# ------------------------------------------------------------ full case report
def case_report(request, patient_pk):
    """Everything documented for one patient, printable (optionally without identity)."""
    patient = get_clinical_patient_or_403(request.user, patient_pk)
    anonymous = request.GET.get("anonymous") == "1"
    surgeries = patient.surgeries.select_related("instructor", "operator_1", "operator_2", "assistant").prefetch_related(
        "sites__implant_system", "photos"
    )
    photos_by_stage = []
    all_photos = list(patient.clinical_photos.select_related("photo_type"))
    for code, label in PhotoStage.choices:
        items = [p for p in all_photos if p.stage == code]
        if items:
            photos_by_stage.append((label, items))
    return render(request, "charting/case_report.html", {
        "patient": patient, "anonymous": anonymous,
        "initials": "".join(part[0] for part in patient.full_name.split()[:3]),
        "exam": patient.examinations.prefetch_related("conditions").first(),
        "svg": chart_svg(patient, clickable=False),
        "plans": patient.treatment_plans.prefetch_related("items__step_type"),
        "surgeries": surgeries,
        "steps": TreatmentStep.objects.filter(patient=patient).select_related(
            "step_type", "operator", "assistant", "supervisor").order_by("performed_at"),
        "photos_by_stage": photos_by_stage,
        "now": timezone.now(),
        "max_upload": settings.MAX_UPLOAD_SIZE_MB,
    })
