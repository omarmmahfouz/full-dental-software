"""The draft list of the surgery days (round 16): the patients called for the coming Thursdays and Fridays, before
any time is given or anything goes on the calendar. Each row keeps what the patient said (no answer, still
thinking, ready for the surgery, agreed); "Book" opens the booking page with the patient, the candidate and the day,
and the patient leaves the draft as booked."""

from datetime import datetime, time, timedelta
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.core.forms import StyledModelForm
from apps.core.models import ClinicSettings, branch_for_user
from apps.core.roles import CLINICAL, FRONT_DESK, has_role
from apps.dentists.forms import DentistChoiceField
from apps.dentists.models import Dentist
from apps.patients.forms import PatientLookupField

from .models import DraftBooking

# The order of the groups on the page: the closest to a booking first.
GROUPS = [DraftBooking.Status.AGREED, DraftBooking.Status.READY, DraftBooking.Status.THINKING,
          DraftBooking.Status.NOT_READY, DraftBooking.Status.NO_ANSWER, DraftBooking.Status.TO_CALL]


def coming_surgery_days(count=8, start=None):
    """The next surgery days (Settings → Clinic options: usually Thursday and Friday)."""
    weekdays = ClinicSettings.get().surgery_weekdays or {3, 4}
    day, days = start or timezone.localdate(), []
    while len(days) < count:
        if day.weekday() in weekdays:
            days.append(day)
        day += timedelta(days=1)
    return days


class DraftForm(StyledModelForm):
    patient_lookup = PatientLookupField(label=gettext_lazy("patient"))
    candidate = DentistChoiceField(kinds=(Dentist.Kind.CANDIDATE, Dentist.Kind.FULLTIME),
                                   label=gettext_lazy("operator (candidate)"), required=False)

    class Meta:
        model = DraftBooking
        fields = ["day", "candidate", "what", "status", "notes"]

    def __init__(self, *args, days=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["day"] = forms.TypedChoiceField(
            label=gettext_lazy("surgery day"), required=False, empty_value=None,
            coerce=lambda text: datetime.strptime(text, "%Y-%m-%d").date(),
            choices=[("", _("Any coming surgery day"))] + [(d.isoformat(), d.strftime("%a %d/%m/%Y")) for d in days])
        self.fields["status"].choices = [c for c in DraftBooking.Status.choices
                                         if c[0] not in (DraftBooking.Status.BOOKED,)]
        for name in ("day", "candidate", "status"):
            self.fields[name].col = "col-md-4"
        self.fields["patient_lookup"].col = "col-md-6"
        self.fields["what"].col = "col-md-6"
        self.fields["notes"].col = "col-12"


def _allowed(user):
    if not has_role(user, *FRONT_DESK, *CLINICAL):
        raise PermissionDenied


def draft_list(request):
    _allowed(request.user)
    place = branch_for_user(request.user)
    days = coming_surgery_days()
    form = DraftForm(request.POST or None, days=days)
    if request.method == "POST" and form.is_valid():
        draft = form.save(commit=False)
        draft.branch, draft.patient, draft.created_by = place, form.cleaned_data["patient_lookup"], request.user
        draft.save()
        messages.success(request, _("%(name)s is on the draft list.") % {"name": draft.patient.full_name})
        return redirect(f"{reverse('scheduling:drafts')}?day={request.POST.get('day', '')}")
    chosen = request.GET.get("day", "")
    rows = DraftBooking.objects.filter(branch=place).select_related("patient", "candidate", "appointment",
                                                                      "created_by")
    if chosen:
        rows = rows.filter(day=chosen) | rows.filter(day__isnull=True, status__in=DraftBooking.OPEN)
    open_rows = list(rows.filter(status__in=DraftBooking.OPEN).order_by("day", "pk"))
    groups = [(code, DraftBooking.Status(code).label, [r for r in open_rows if r.status == code]) for code in GROUPS]
    for row in open_rows:
        params = {"patient": row.patient_id, "purpose": row.what, "draft": row.pk}
        if row.candidate_id:
            params["dentist"] = row.candidate_id
        if row.day:
            params["at"] = datetime.combine(row.day, time(10)).isoformat()
        row.book_url = f"{reverse('scheduling:appointment_create')}?{urlencode(params)}"
    closed = rows.exclude(status__in=DraftBooking.OPEN).filter(
        updated_at__gte=timezone.now() - timedelta(days=30)).order_by("-updated_at")[:40]
    per_day = dict(DraftBooking.objects.filter(branch=place, status__in=DraftBooking.OPEN, day__in=days)
                   .values_list("day").annotate(n=Count("pk")))
    return render(request, "scheduling/drafts.html", {
        "form": form, "groups": groups, "closed": closed, "chosen": chosen,
        "days": [(d, per_day.get(d, 0)) for d in days], "statuses": DraftBooking.Status.choices,
        "open_count": len(open_rows),
    })


@require_POST
def draft_update(request, pk):
    """What the patient said on the phone: the new status, a note, another day."""
    _allowed(request.user)
    draft = get_object_or_404(DraftBooking, pk=pk, branch=branch_for_user(request.user))
    status = request.POST.get("status", "")
    if status in DraftBooking.Status.values and status != DraftBooking.Status.BOOKED:
        if status != draft.status or status == DraftBooking.Status.NO_ANSWER:
            draft.calls += 1
            draft.last_call_at = timezone.now()
        draft.status = status
    note = (request.POST.get("notes") or "").strip()
    if note:
        draft.notes = note[:255]
    day = request.POST.get("day")
    if day is not None:
        try:
            draft.day = datetime.strptime(day, "%Y-%m-%d").date() if day else None
        except ValueError:
            pass
    draft.save()
    messages.success(request, _("%(name)s: %(status)s.") % {"name": draft.patient.full_name,
                                                             "status": draft.get_status_display()})
    return redirect(request.POST.get("next") or reverse("scheduling:drafts"))


def link_draft(request, appointment):
    """Booking from the draft list (?draft=<pk>): the patient leaves it as booked."""
    pk = request.GET.get("draft", "")
    if not pk.isdigit():
        return None
    draft = DraftBooking.objects.filter(pk=pk, patient=appointment.patient).first()
    if draft is not None:
        draft.status, draft.appointment = DraftBooking.Status.BOOKED, appointment
        draft.save(update_fields=["status", "appointment", "updated_at"])
    return draft
