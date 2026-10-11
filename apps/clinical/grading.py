"""Approve and grade (round 16): the supervisor of the day (or the instructor of a surgery day) sees the work that
names him, approves it and grades it; from time to time he grades each CIA junior's overall level (is he ready for
the next level?) with his notes. The grades are seen by the owner and the head of CIA only.

Who opens the page:
- a supervisor with a login (the "grader" role, or any login linked to a supervisor's dentist record): his own work;
- a CIA junior, for an instructor who comes a day or two and has no login: he chooses the instructor's name and
  writes what the instructor says (each grade keeps who wrote it);
- the owner and the head of CIA: any supervisor's list, and every grade.
"""

from datetime import timedelta

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.core.models import Notification
from apps.core.notify import notify_users
from apps.core.roles import CLINICAL, GRADE_VIEWERS, GRADER, has_role
from apps.dentists.models import Dentist

from .models import TreatmentStep, WorkGrade

DAYS_SHOWN = 60  # the work of the last two months waits on the page


def _notify_once(user, title, url, params):
    """One unread notification for the page is enough (a busy day names the supervisor many times)."""
    if user.notifications.filter(url=url, read_at__isnull=True).exists():
        return
    notify_users([user], title, gettext_lazy("Open the page, look at the work and approve it."), url,
                 Notification.Level.WARNING, params=params)


@receiver(post_save, sender=TreatmentStep, dispatch_uid="grading_step_saved")
def tell_supervisor_of_step(sender, instance, created, **kwargs):
    """A CIA junior wrote a step and named the supervisor who saw it: the supervisor (if he logs in) is told."""
    if not created or not instance.supervisor_id or instance.verified_at:
        return
    supervisor = instance.supervisor
    if supervisor.user_id and supervisor.user_id != instance.created_by_id:
        _notify_once(supervisor.user, gettext_lazy("Work to approve: %(step)s for %(patient)s"),
                     reverse("clinical:supervise"),
                     {"step": str(instance.step_type), "patient": instance.patient.full_name})


def tell_instructor_of_surgery(surgery):
    """Called when a surgery chart is saved with its instructor (surgery/views.py)."""
    instructor = surgery.instructor
    if instructor is None or not instructor.user_id or surgery.grades.exists():
        return
    _notify_once(instructor.user, gettext_lazy("Surgery to grade: %(patient)s"), reverse("clinical:supervise"),
                 {"patient": surgery.patient.full_name})


def is_supervisor_login(user):
    me = Dentist.for_user(user)
    return has_role(user, GRADER) or (me is not None and me.kind == Dentist.Kind.SUPERVISOR)


def can_open(user):
    return is_supervisor_login(user) or has_role(user, *CLINICAL)


def _whose(request):
    """The supervisor whose list is open, and whether the person writes for him (an instructor without a login)."""
    me = Dentist.for_user(request.user)
    if is_supervisor_login(request.user) and me is not None and not has_role(request.user, *GRADE_VIEWERS):
        return me, False
    supervisors = Dentist.objects.filter(kind=Dentist.Kind.SUPERVISOR, is_active=True).order_by("full_name")
    pk = request.GET.get("for") or request.POST.get("for") or ""
    chosen = supervisors.filter(pk=pk).first() if pk.isdigit() else None
    if chosen is None and me is not None and me.kind == Dentist.Kind.SUPERVISOR:
        chosen = me
    writes_for = chosen is not None and chosen != me and not has_role(request.user, *GRADE_VIEWERS)
    return chosen, writes_for


class OverallForm(forms.Form):
    """The overall level of a CIA junior (from time to time)."""

    dentist = forms.ModelChoiceField(queryset=Dentist.objects.all())
    grade = forms.TypedChoiceField(choices=[("", "—")] + WorkGrade.GRADES, coerce=int, empty_value=None,
                                   required=False)
    readiness = forms.ChoiceField(choices=[("", "—")] + list(WorkGrade.Readiness.choices), required=False)
    level = forms.CharField(max_length=60, required=False)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))


def supervise(request):
    """The work that names the supervisor (the last two months): the treatment steps to approve and grade, the
    surgeries he instructed, and the CIA juniors who worked with him (their overall level)."""
    if not can_open(request.user):
        raise PermissionDenied
    supervisor, writes_for = _whose(request)
    since = timezone.now() - timedelta(days=DAYS_SHOWN)
    steps, surgeries, juniors = [], [], []
    if supervisor is not None:
        from apps.surgery.models import Surgery

        steps = list(TreatmentStep.objects.filter(supervisor=supervisor, verified_at__isnull=True,
                                                  performed_at__gte=since)
                     .select_related("patient", "step_type", "operator", "assistant", "created_by")
                     .prefetch_related("photos").order_by("-performed_at")[:100])
        for step in steps:  # the case in short: what was done before on these teeth, and by whom
            step.before = list(TreatmentStep.objects.filter(patient=step.patient_id, performed_at__lt=step.performed_at)
                               .select_related("step_type", "operator").order_by("-performed_at")[:4])
        surgeries = list(Surgery.objects.filter(instructor=supervisor, date__gte=since.date()).exclude(
            grades__isnull=False).select_related("patient", "operator_1", "operator_2", "assistant")
            .prefetch_related("sites").order_by("-date")[:60])
        people = {}
        for step in TreatmentStep.objects.filter(supervisor=supervisor, performed_at__gte=since).select_related(
                "operator", "assistant"):
            for person in (step.operator, step.assistant):
                if person is not None and person.kind == Dentist.Kind.FULLTIME:
                    people[person.pk] = person
        for surgery in Surgery.objects.filter(instructor=supervisor, date__gte=since.date()).select_related(
                "assistant", "operator_1", "operator_2"):
            for person in (surgery.assistant, surgery.operator_1, surgery.operator_2):
                if person is not None and person.kind == Dentist.Kind.FULLTIME:
                    people[person.pk] = person
        last = {g.dentist_id: g for g in WorkGrade.objects.filter(kind=WorkGrade.Kind.OVERALL,
                                                                  dentist_id__in=people).order_by("created_at")}
        juniors = [(person, last.get(person.pk)) for person in sorted(people.values(), key=lambda d: d.full_name)]
    return render(request, "clinical/supervise.html", {
        "supervisor": supervisor, "writes_for": writes_for, "steps": steps, "surgeries": surgeries,
        "juniors": juniors, "grades": WorkGrade.GRADES, "readiness": WorkGrade.Readiness.choices,
        "supervisors": Dentist.objects.filter(kind=Dentist.Kind.SUPERVISOR, is_active=True).order_by("full_name")
        if not (is_supervisor_login(request.user) and not has_role(request.user, *GRADE_VIEWERS)) else [],
        "sees_grades": has_role(request.user, *GRADE_VIEWERS),
    })


def _grade_value(text):
    return int(text) if text in {"1", "2", "3", "4", "5"} else None


def _back(supervisor):
    return redirect(f"{reverse('clinical:supervise')}?for={supervisor.pk}" if supervisor else "clinical:supervise")


@require_POST
def grade_step(request, pk):
    """Approve a treatment step (with a grade and notes), or send it back to the dentist with what to correct."""
    if not can_open(request.user):
        raise PermissionDenied
    supervisor, writes_for = _whose(request)
    step = get_object_or_404(TreatmentStep.objects.select_related("operator__user", "assistant__user", "patient",
                                                                  "step_type"), pk=pk)
    if supervisor is None or (step.supervisor_id != supervisor.pk and not has_role(request.user, *GRADE_VIEWERS)):
        raise PermissionDenied
    notes = (request.POST.get("notes") or "").strip()
    approved = request.POST.get("action") != "correct"
    if not approved and not notes:
        messages.error(request, _("Write what must be corrected."))
        return _back(supervisor)
    grade = _grade_value(request.POST.get("grade", "")) if approved else None
    person = step.operator if step.operator.kind == Dentist.Kind.FULLTIME or not step.assistant_id else step.assistant
    WorkGrade.objects.create(dentist=person, kind=WorkGrade.Kind.STEP, step=step, approved=approved, grade=grade,
                             notes=notes, graded_by=supervisor, for_instructor=writes_for, created_by=request.user,
                             role="operator" if person == step.operator else "assistant")
    told = [d.user for d in (step.operator, step.assistant) if d is not None and d.user_id]
    if approved:
        step.verified_by, step.verified_at = request.user, timezone.now()
        step.grade, step.supervisor_comment = grade, notes
        step.save(update_fields=["verified_by", "verified_at", "grade", "supervisor_comment", "updated_at"])
        notify_users(told, gettext_lazy("Approved by %(supervisor)s: %(step)s"), "", step.get_absolute_url(),
                     Notification.Level.SUCCESS, exclude=request.user,
                     params={"supervisor": str(supervisor), "step": str(step.step_type)})
        messages.success(request, _("Approved: %(step)s for %(patient)s.") % {"step": step.step_type,
                                                                             "patient": step.patient.full_name})
    else:
        notify_users(told, gettext_lazy("To correct (%(supervisor)s): %(step)s"), notes.replace("%", "%%"),
                     step.get_absolute_url(), Notification.Level.WARNING, exclude=request.user,
                     params={"supervisor": str(supervisor), "step": str(step.step_type)})
        messages.warning(request, _("Sent back to the dentist with your notes."))
    return _back(supervisor)


@require_POST
def grade_surgery(request, pk):
    """The instructor grades a surgery: the operator(s) and the assistant, with his notes."""
    from apps.surgery.models import Surgery

    if not can_open(request.user):
        raise PermissionDenied
    supervisor, writes_for = _whose(request)
    surgery = get_object_or_404(Surgery.objects.select_related("operator_1", "operator_2", "assistant", "patient"),
                                pk=pk)
    if supervisor is None or (surgery.instructor_id != supervisor.pk and not has_role(request.user, *GRADE_VIEWERS)):
        raise PermissionDenied
    notes = (request.POST.get("notes") or "").strip()
    saved = 0
    for role, person in (("operator_1", surgery.operator_1), ("operator_2", surgery.operator_2),
                         ("assistant", surgery.assistant)):
        if person is None:
            continue
        WorkGrade.objects.create(dentist=person, kind=WorkGrade.Kind.SURGERY, surgery=surgery, role=role,
                                 grade=_grade_value(request.POST.get(f"grade_{role}", "")), notes=notes,
                                 graded_by=supervisor, for_instructor=writes_for, created_by=request.user)
        saved += 1
    messages.success(request, _("Surgery %(number)s graded.") % {"number": surgery.number})
    return _back(supervisor)


@require_POST
def grade_overall(request):
    """The overall level of a CIA junior: a grade, ready for the next level or not, and the notes."""
    if not can_open(request.user):
        raise PermissionDenied
    supervisor, writes_for = _whose(request)
    form = OverallForm(request.POST)
    if supervisor is None or not form.is_valid():
        messages.error(request, _("Choose a grade or write a note."))
        return _back(supervisor)
    data = form.cleaned_data
    if not (data.get("grade") or data.get("readiness") or data.get("notes")):
        messages.error(request, _("Choose a grade or write a note."))
        return _back(supervisor)
    WorkGrade.objects.create(dentist=data["dentist"], kind=WorkGrade.Kind.OVERALL, grade=data.get("grade"),
                             readiness=data.get("readiness") or "", level=data.get("level") or "",
                             notes=data.get("notes") or "", graded_by=supervisor, for_instructor=writes_for,
                             created_by=request.user)
    messages.success(request, _("Saved for %(name)s. Only the owner and the head of CIA see it.") % {
        "name": data["dentist"]})
    return _back(supervisor)


def grades_of(dentist):
    """Every grade of a dentist, the newest first, for the owner and the head of CIA (his page)."""
    return WorkGrade.objects.filter(dentist=dentist).select_related(
        "graded_by", "created_by", "step__step_type", "step__patient", "surgery__patient")


def grades_summary(dentist):
    rows = list(WorkGrade.objects.filter(dentist=dentist, grade__isnull=False).values_list("kind", "grade"))
    by_kind = {}
    for kind, grade in rows:
        by_kind.setdefault(kind, []).append(grade)
    overall = WorkGrade.objects.filter(dentist=dentist, kind=WorkGrade.Kind.OVERALL).first()
    return {"averages": {kind: round(sum(v) / len(v), 1) for kind, v in by_kind.items()}, "last_overall": overall,
            "corrections": WorkGrade.objects.filter(dentist=dentist, approved=False).count()}


def graded_patients(user):
    """The patients of the work that names this supervisor (to show him its photos)."""
    from apps.patients.models import Patient

    me = Dentist.for_user(user)
    if me is None:
        return Patient.objects.none()
    return Patient.objects.filter(Q(treatment_steps__supervisor=me) | Q(surgeries__instructor=me)).distinct()


def surgeries_assisted(dentist):
    """The surgeries a CIA junior assisted (counted for him as assisting, never as his cases)."""
    from apps.surgery.models import Surgery

    return Surgery.objects.filter(Q(assistant=dentist)).count()
