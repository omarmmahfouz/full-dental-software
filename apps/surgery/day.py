"""The surgery day (round 15): the CIA juniors write who supervised it, and each surgery of the day takes him as its
instructor (printed on the case report and the log book). The page lists the day's surgeries with the operator of
each tooth (two candidates on one patient: one does 36, the other 46) and the candidates and juniors in the rooms."""

from datetime import date as date_type

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.core.forms import StyledModelForm
from apps.core.models import branch_for_user
from apps.core.roles import CLINICAL, MANAGEMENT, has_role
from apps.dentists.forms import DentistChoiceField
from apps.dentists.models import Dentist

from .models import DaySupervisor, Surgery


class DaySupervisorForm(StyledModelForm):
    supervisor = DentistChoiceField(kinds=(Dentist.Kind.SUPERVISOR,), label=gettext_lazy("supervisor"))

    class Meta:
        model = DaySupervisor
        fields = ["supervisor", "from_time", "to_time", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("from_time", "to_time"):
            self.fields[name].help_text = _("Only when two supervisors share the day.")
            self.fields[name].col = "col-6 col-md-3"
        self.fields["supervisor"].col = "col-md-6"
        self.fields["notes"].col = "col-12"


def _day(request):
    text = request.GET.get("date") or request.POST.get("date") or ""
    try:
        return date_type.fromisoformat(text)
    except ValueError:
        return timezone.localdate()


def surgery_day(request):
    if not has_role(request.user, *CLINICAL):
        raise PermissionDenied
    place = branch_for_user(request.user)
    day = _day(request)
    form = DaySupervisorForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        row = form.save(commit=False)
        row.branch, row.date, row.written_by = place, day, request.user
        try:
            row.save()
        except IntegrityError:
            messages.warning(request, _("%(name)s is already written for this day.") % {"name": row.supervisor})
        else:
            filled = fill_instructor(place, day)
            messages.success(request, _("Saved: %(name)s supervised the surgery day.") % {"name": row.supervisor}
                             + (" " + _("Written on %(n)s surgeries of the day.") % {"n": filled} if filled else ""))
        return redirect(f"{reverse('surgery:day')}?date={day.isoformat()}")
    from apps.scheduling.models import RoomShift

    surgeries = list(Surgery.objects.filter(branch=place, date=day).select_related(
        "patient", "instructor", "operator_1", "operator_2", "assistant").prefetch_related("sites__operator"))
    for surgery in surgeries:
        surgery.teeth_by = {}
        for site in surgery.sites.all():
            surgery.teeth_by.setdefault(site.done_by, []).append(site.tooth)
    shifts = RoomShift.objects.filter(room__branch=place, date=day).select_related(
        "room", "dentist", "second_dentist", "supervisor").order_by("start_time", "room__sort_order")
    return render(request, "surgery/day.html", {
        "day": day, "place": place, "form": form, "surgeries": surgeries, "shifts": shifts,
        "supervisors": DaySupervisor.objects.filter(branch=place, date=day).select_related("supervisor",
                                                                                           "written_by"),
        "previous": day.fromordinal(day.toordinal() - 1), "next": day.fromordinal(day.toordinal() + 1),
        "can_remove": has_role(request.user, *MANAGEMENT),
    })


def fill_instructor(place, day):
    """The day's surgeries without an instructor take the supervisor of the day (or of their hours)."""
    filled = 0
    for surgery in Surgery.objects.filter(branch=place, date=day, instructor__isnull=True).select_related(
            "appointment"):
        at = timezone.localtime(surgery.appointment.scheduled_at).time() if surgery.appointment_id else None
        supervisor = DaySupervisor.on(place, day, at)
        if supervisor is not None:
            Surgery.objects.filter(pk=surgery.pk).update(instructor=supervisor)
            filled += 1
    return filled


@require_POST
def remove_day_supervisor(request, pk):
    if not has_role(request.user, *CLINICAL):
        raise PermissionDenied
    row = get_object_or_404(DaySupervisor, pk=pk, branch=branch_for_user(request.user))
    if not (has_role(request.user, *MANAGEMENT) or row.written_by_id == request.user.pk):
        raise PermissionDenied
    row.delete()
    messages.success(request, _("Removed."))
    return redirect(f"{reverse('surgery:day')}?date={row.date.isoformat()}")
