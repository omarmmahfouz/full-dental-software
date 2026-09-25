"""Lists of patients for the reception to call, and the answers they write down."""

from django import forms
from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.core.forms import StyledForm
from apps.core.mixins import role_required
from apps.core.models import Notification, branch_for_user
from apps.core.notify import notify_roles, notify_users
from apps.core.roles import FRONT_DESK, MANAGEMENT, SECRETARY, TEAM_HEAD, has_role

from .models import CallList, CallListEntry, Patient

SENDERS = MANAGEMENT + (TEAM_HEAD,)


class EntryForm(StyledForm):
    outcome = forms.ChoiceField(label=gettext_lazy("result"), choices=CallListEntry.Outcome.choices)
    response = forms.CharField(label=gettext_lazy("patient's answer"), required=False,
                               widget=forms.Textarea(attrs={"rows": 1}))


def create_call_list(title, message, rows, user):
    """``rows`` is a list of (patient, reason). Notifies the secretaries."""
    seen = set()
    with transaction.atomic():
        call_list = CallList.objects.create(title=title[:150], message=message, created_by=user,
                                            branch=branch_for_user(user))
        entries = []
        for patient, reason in rows:
            if patient.pk in seen:
                continue
            seen.add(patient.pk)
            entries.append(CallListEntry(call_list=call_list, patient=patient, reason=reason[:255]))
        CallListEntry.objects.bulk_create(entries)
    notify_roles(
        (SECRETARY,), gettext_lazy("Patients to call: %(title)s"), gettext_lazy("%(n)s patients. %(message)s"),
        call_list.get_absolute_url(), Notification.Level.WARNING, exclude=user,
        params={"title": call_list.title, "n": len(entries), "message": message[:200]},
    )
    return call_list


@role_required(*SENDERS)
@require_POST
def calllist_create(request):
    """Posted from the treatment plan finder or the case finder with the chosen patients."""
    ids = [int(v) for v in request.POST.getlist("patient") if v.isdigit()]
    patients = Patient.objects.in_bulk(ids)
    rows = [(patients[pk], request.POST.get(f"reason_{pk}", "")) for pk in ids if pk in patients]
    back = request.POST.get("next") or "/"
    if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
        back = "/"
    title = request.POST.get("title", "").strip()
    if not rows or not title:
        messages.error(request, _("Write a title and choose at least one patient."))
        return redirect(back)
    call_list = create_call_list(title, request.POST.get("message", "").strip(), rows, request.user)
    messages.success(request, _("%(n)s patients sent to the reception to call.") % {"n": call_list.entries.count()})
    return redirect(call_list)


@role_required(*FRONT_DESK, TEAM_HEAD)
def calllist_list(request):
    lists = CallList.objects.select_related("created_by").prefetch_related("entries")
    rows = [(c, *c.progress) for c in lists[:200]]
    return render(request, "patients/calllist_list.html", {
        "open_lists": [r for r in rows if r[1] < r[2]], "done_lists": [r for r in rows if r[1] >= r[2]][:30],
    })


@role_required(*FRONT_DESK, TEAM_HEAD)
def calllist_detail(request, pk):
    call_list = get_object_or_404(CallList.objects.select_related("created_by"), pk=pk)
    entries = call_list.entries.select_related("patient", "called_by")
    if request.GET.get("pending"):
        entries = entries.filter(outcome=CallListEntry.Outcome.PENDING)
    rows = [(e, EntryForm(initial={"outcome": e.outcome, "response": e.response}, prefix=f"e{e.pk}")) for e in entries]
    done, total = call_list.progress
    return render(request, "patients/calllist_detail.html", {
        "call_list": call_list, "rows": rows, "done": done, "total": total,
        "can_call": has_role(request.user, *FRONT_DESK),
    })


@role_required(*FRONT_DESK)
@require_POST
def calllist_answer(request, pk):
    entry = get_object_or_404(CallListEntry.objects.select_related("call_list__created_by"), pk=pk)
    form = EntryForm(request.POST, prefix=f"e{entry.pk}")
    if form.is_valid():
        entry.outcome = form.cleaned_data["outcome"]
        entry.response = form.cleaned_data["response"]
        entry.attempts += 1
        entry.called_at, entry.called_by = timezone.now(), request.user
        entry.save()
        call_list = entry.call_list
        done, total = call_list.progress
        if done == total and call_list.created_by_id:
            notify_users([call_list.created_by], gettext_lazy("The reception called every patient of %(title)s"), "",
                         call_list.get_absolute_url(), Notification.Level.SUCCESS, exclude=request.user,
                         params={"title": call_list.title})
        messages.success(request, _("Answer saved for %(name)s.") % {"name": entry.patient.full_name})
    return redirect(f"{entry.call_list.get_absolute_url()}#e{entry.pk}")
