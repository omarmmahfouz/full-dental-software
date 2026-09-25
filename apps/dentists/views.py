import secrets
from collections import Counter

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.clinical.models import TreatmentStep
from apps.core.mixins import role_required
from apps.core.models import UserProfile, branch_for_user
from apps.core.roles import DENTIST, FRONT_DESK, OWNER, TEAM_HEAD, has_role
from apps.core.utils import normalize_phone
from apps.patients.models import Patient
from apps.surgery.models import Surgery, SurgerySite

from .forms import DentistFilterForm, DentistForm
from .models import Dentist


def _dentists_for(user):
    """The head of the CIA dentists team follows the CIA dentists, not the course candidates."""
    if has_role(user, *FRONT_DESK):
        return Dentist.objects.all()
    return Dentist.objects.exclude(kind=Dentist.Kind.CANDIDATE)


@role_required(*FRONT_DESK, TEAM_HEAD)
def dentist_list(request):
    form = DentistFilterForm(request.GET or None)
    qs = _dentists_for(request.user).select_related("candidate", "user").annotate(
        implants=Count("surgeries_as_op1__sites", filter=~Q(surgeries_as_op1__sites__implant_status=""), distinct=True),
        surgeries=Count("surgeries_as_op1", distinct=True),
        treatments=Count("treatments_operated", distinct=True),
    )
    active = "1"
    if form.is_valid():
        data = form.cleaned_data
        active = data.get("active", "1") if form.is_bound else "1"
        if data.get("q"):
            qs = qs.filter(Q(full_name__icontains=data["q"]) | Q(phone__contains=data["q"]) | Q(candidate__code__icontains=data["q"]))
        if data.get("kind"):
            qs = qs.filter(kind=data["kind"])
    if active in ("0", "1"):
        qs = qs.filter(is_active=active == "1")
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "dentists/dentist_list.html", {"page_obj": page, "filter_form": form})


def dentist_detail(request, pk):
    dentist = get_object_or_404(Dentist.objects.select_related("candidate", "user"), pk=pk)
    own = dentist.user_id == request.user.pk
    if not (own or _dentists_for(request.user).filter(pk=dentist.pk).exists()
            and has_role(request.user, *FRONT_DESK, TEAM_HEAD)):
        raise PermissionDenied
    implants_op1 = SurgerySite.objects.filter(surgery__operator_1=dentist).exclude(implant_status="")
    implants_op2 = SurgerySite.objects.filter(surgery__operator_2=dentist).exclude(implant_status="")
    status_counts = Counter(implants_op1.values_list("implant_status", flat=True))
    placed = implants_op1.count()
    failed = status_counts.get(SurgerySite.ImplantStatus.FAILED, 0)

    enrollment = required = remaining = None
    if dentist.candidate_id:
        enrollment = dentist.candidate.current_enrollment
        if enrollment is not None:
            required = enrollment.implants_required
            remaining = max(required - placed, 0) if required else None

    surgeries = Surgery.objects.filter(
        Q(operator_1=dentist) | Q(operator_2=dentist) | Q(assistant=dentist) | Q(instructor=dentist)
    ).select_related("patient", "operator_1", "operator_2", "assistant", "instructor").prefetch_related("sites")
    steps = TreatmentStep.objects.filter(Q(operator=dentist) | Q(assistant=dentist) | Q(supervisor=dentist))
    by_type = (
        steps.filter(operator=dentist).values("step_type__name_en", "step_type__name_ar")
        .annotate(n=Count("id")).order_by("-n")
    )
    grade = steps.filter(operator=dentist, grade__isnull=False).aggregate(avg=Avg("grade"))["avg"]

    patient_ids = set(surgeries.values_list("patient_id", flat=True)) | set(steps.values_list("patient_id", flat=True))
    patient_ids |= set(Patient.objects.filter(assigned_dentist=dentist).values_list("pk", flat=True))
    cases = []
    for patient in Patient.objects.filter(pk__in=patient_ids).order_by("full_name"):
        cases.append({
            "patient": patient,
            "implants": SurgerySite.objects.filter(surgery__patient=patient, surgery__operator_1=dentist)
            .exclude(implant_status="").count(),
            "roles": sorted({
                str(label) for field, label in (
                    ("operator_1", _("operator 1")), ("operator_2", _("operator 2")), ("assistant", _("assistant")),
                    ("instructor", _("instructor")),
                ) if surgeries.filter(patient=patient, **{field: dentist}).exists()
            }),
        })

    return render(request, "dentists/dentist_detail.html", {
        "dentist": dentist, "enrollment": enrollment, "required": required, "remaining": remaining,
        "placed": placed, "failed": failed, "survival": round(100 * (placed - failed) / placed, 1) if placed else None,
        "status_counts": [(label, status_counts.get(code, 0)) for code, label in SurgerySite.ImplantStatus.choices],
        "implants_op2": implants_op2.count(),
        "counts": {
            "op1": surgeries.filter(operator_1=dentist).count(),
            "op2": surgeries.filter(operator_2=dentist).count(),
            "assistant": surgeries.filter(assistant=dentist).count(),
            "instructor": surgeries.filter(instructor=dentist).count(),
            "treatments": steps.filter(operator=dentist).count(),
            "assisted": steps.filter(assistant=dentist).count(),
            "supervised": steps.filter(supervisor=dentist).count(),
        },
        "by_type": by_type, "grade": round(grade, 1) if grade else None,
        "surgeries": surgeries[:30], "implants": implants_op1.select_related("surgery__patient", "implant_system")[:60],
        "cases": cases, "can_manage": has_role(request.user, OWNER),
        "lang_en": (request.LANGUAGE_CODE or "").startswith("en"),
    })


@role_required(*FRONT_DESK)
def dentist_edit(request, pk=None):
    dentist = get_object_or_404(Dentist, pk=pk) if pk else None
    form = DentistForm(request.POST or None, instance=dentist)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if not obj.pk:
            obj.created_by = request.user
            obj.branch = obj.branch or branch_for_user(request.user)
        obj.save()
        messages.success(request, _("Dentist saved."))
        return redirect(obj)
    return render(request, "includes/form_page.html", {
        "form": form, "title": _("Edit dentist") if dentist else _("New dentist"),
        "intro": _("Course candidates are added from Academy → Candidates; they get their dentist record automatically."),
    })


@role_required(OWNER)
@require_POST
def create_login(request, pk):
    """Create a system login for a dentist and show the first password once."""
    dentist = get_object_or_404(Dentist, pk=pk)
    if dentist.user_id:
        messages.info(request, _("This dentist already has a login: %(u)s") % {"u": dentist.user.username})
        return redirect(dentist)
    if not dentist.can_have_login:
        messages.error(request, _("Only CIA dentists get a login. Candidates, training dentists and supervisors "
                                  "are chosen by name on the forms."))
        return redirect(dentist)
    User = get_user_model()
    username = normalize_phone(dentist.phone) or f"dentist{dentist.pk}"
    while User.objects.filter(username=username).exists():
        username = f"{username}-{secrets.randbelow(90) + 10}"
    password = secrets.token_urlsafe(6)
    with transaction.atomic():
        user = User.objects.create_user(username=username, password=password, first_name=dentist.full_name[:150])
        user.groups.add(Group.objects.get_or_create(name=DENTIST)[0])
        profile, _created = UserProfile.objects.get_or_create(user=user)
        profile.branch = dentist.branch or branch_for_user(request.user)
        profile.phone = dentist.phone
        profile.save()
        dentist.user = user
        dentist.save(update_fields=["user", "updated_at"])
    messages.warning(
        request,
        _("Login created. Username: %(u)s — first password: %(p)s (write it down now; it will not be shown again).")
        % {"u": username, "p": password},
    )
    return redirect(dentist)
