"""Calls today (round 18): everyone the reception has to call, in one queue.

There were four lists on four pages: the people who called and are not patients yet, the calls for a new medical
test, the lists of patients to call sent by the dentists and the heads, and the patients the dentists asked for.
This page puts the calls due today (and the late ones) together, the longest waiting first; each row has the mobile,
WhatsApp, the usual answers and the booking. Each kind keeps its own page for the rest (the result of a test, a new
list...)."""

from datetime import datetime, time, timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.core.mixins import role_required
from apps.core.models import branch_for_user
from apps.core.roles import FRONT_DESK

from .models import CallListEntry, Lead, LeadCall, MedicalRecall

# The kinds of call, in the order of the tabs: code, name, icon, the page of the kind.
KINDS = [
    ("lead", gettext_lazy("New callers"), "bi-telephone-inbound", "patients:lead_list"),
    ("test", gettext_lazy("A new test"), "bi-clipboard2-pulse", "patients:recall_list"),
    ("list", gettext_lazy("Call lists"), "bi-list-check", "patients:calllist_list"),
    ("doctor", gettext_lazy("Asked for by a dentist"), "bi-person-badge", "scheduling:requests_reception"),
]
KIND_LABELS = {code: label for code, label, _icon, _page in KINDS}
KIND_ICONS = {code: icon for code, _label, icon, _page in KINDS}
PER_KIND = 150  # read for one page: the kind's own page has them all
PER_PAGE = 40
COUNT_SECONDS = 60

# The quick answers of each kind: (code, label, final). A final answer takes him off the calls.
ANSWERS = {
    "lead": [("no_answer", gettext_lazy("No answer"), False), ("later", gettext_lazy("Call back later"), False),
             ("stop", gettext_lazy("Not interested"), True)],
    "test": [("no_answer", gettext_lazy("No answer"), False), ("later", gettext_lazy("He will do the test"), False),
             ("stop", gettext_lazy("He does not want to"), True)],
    "list": [("no_answer", gettext_lazy("No answer"), False), ("later", gettext_lazy("Call again later"), False),
             ("stop", gettext_lazy("Not interested"), True)],
    "doctor": [("no_answer", gettext_lazy("No answer"), False), ("stop", gettext_lazy("Cannot come"), True)],
}
# Called again after (days) when no day is written.
AGAIN = {"lead": {"no_answer": 1, "later": 3}, "doctor": {"no_answer": 1}}


def _queries(place, today):
    """The calls due today at ``place``, one query for each kind."""
    from apps.scheduling.models import PatientRequest

    end = timezone.make_aware(datetime.combine(today + timedelta(days=1), time.min))
    return {
        "lead": Lead.objects.filter(branch=place, status__in=(Lead.Status.NEW, Lead.Status.FOLLOW_UP)).filter(
            Q(next_call_at__isnull=True) | Q(next_call_at__lt=end)),
        "test": MedicalRecall.objects.filter(patient__branch=place, status=MedicalRecall.Status.OPEN,
                                             due_on__lte=today),
        "list": CallListEntry.objects.filter(call_list__branch=place, outcome__in=CallListEntry.OPEN).filter(
            Q(next_call_on__isnull=True) | Q(next_call_on__lte=today)),
        "doctor": PatientRequest.objects.filter(patient__branch=place, status=PatientRequest.Status.APPROVED).filter(
            Q(call_again_on__isnull=True) | Q(call_again_on__lte=today)),
    }


def counts(place, today=None):
    """How many calls of each kind are due: {"lead": n, ..., "total": n}."""
    today = today or timezone.localdate()
    numbers = {kind: query.count() for kind, query in _queries(place, today).items()}
    numbers["total"] = sum(numbers.values())
    return numbers


def _count_key(place):
    return f"calls-due-{getattr(place, 'pk', place)}"


def total_due(place):
    """The number beside "Calls today" in the menu, on every page of the reception: kept for a minute."""
    if place is None:
        return 0
    key = _count_key(place)
    total = cache.get(key)
    if total is None:
        total = counts(place)["total"]
        cache.set(key, total, COUNT_SECONDS)
    return total


def forget_count(place):
    cache.delete(_count_key(place))


def _local_day(moment):
    return timezone.localtime(moment).date() if moment else None


def _row(kind, pk, name, phone, since, why, today, **more):
    days = (today - since).days if since else 0
    return {"kind": kind, "pk": pk, "key": f"{kind}{pk}", "label": KIND_LABELS[kind], "icon": KIND_ICONS[kind],
            "name": name, "phone": phone, "since": since, "late": max(days, 0), "why": why,
            "answers": ANSWERS[kind], **more}


def rows(place, today=None, kind="", limit=None):
    """The calls due, the longest waiting first: a list of dicts ready for the page. ``limit``: only the first ones
    (the card of the home page)."""
    from apps.scheduling.whatsapp import whatsapp_url

    from .medical import recall_text

    today = today or timezone.localdate()
    queries = _queries(place, today)
    wanted = [kind] if kind in queries else list(queries)
    found = []
    if "lead" in wanted:
        for lead in queries["lead"].order_by("next_call_at", "first_call_on", "pk")[:limit or PER_KIND]:
            why = lead.get_missing_teeth_display() if lead.missing_teeth != "unknown" else ""
            why = " · ".join(part for part in (why, lead.missing_teeth_notes, lead.notes) if part)
            found.append(_row(
                "lead", lead.pk, lead.full_name, lead.preferred_number, _local_day(lead.next_call_at) or lead.first_call_on,
                why or _("He called and has no file yet."), today, url=lead.get_absolute_url(),
                last=lead.get_status_display() if lead.status == Lead.Status.FOLLOW_UP else "",
                book_post=reverse("patients:lead_book", args=[lead.pk])))
    if "test" in wanted:
        for recall in queries["test"].select_related("patient__branch", "last_call_by").order_by("due_on", "pk")[:limit or PER_KIND]:
            patient = recall.patient
            found.append(_row(
                "test", recall.pk, patient.full_name, patient.preferred_number, recall.due_on,
                _("%(test)s %(reading)s of %(day)s: a new test is due.") % {
                    "test": recall.get_reason_display(), "reading": recall.reading,
                    "day": recall.reading_on.strftime("%d/%m/%Y")},
                today, file=patient.file_number, url=patient.get_absolute_url(),
                last=recall.get_last_outcome_display() if recall.calls else "", calls=recall.calls,
                whatsapp=whatsapp_url(patient.preferred_number, recall_text(recall)) if patient.preferred_number else "",
                result_url=f"{reverse('patients:recall_list')}?tab=today#recall{recall.pk}"))
    if "list" in wanted:
        entries = queries["list"].select_related("patient", "call_list").order_by("next_call_on", "call_list__created_at", "pk")
        for entry in entries[:limit or PER_KIND]:
            patient = entry.patient
            book = {"patient": patient.pk, "call_entry": entry.pk}
            found.append(_row(
                "list", entry.pk, patient.full_name, patient.preferred_number,
                entry.next_call_on or _local_day(entry.call_list.created_at),
                " · ".join(part for part in (entry.call_list.title, entry.reason) if part), today,
                file=patient.file_number, url=patient.get_absolute_url(), calls=entry.attempts,
                last=entry.get_outcome_display() if entry.attempts else "", note=entry.response,
                more_url=f"{entry.call_list.get_absolute_url()}#e{entry.pk}",
                book_url=f"{reverse('scheduling:appointment_create')}?{urlencode(book)}"))
    if "doctor" in wanted:
        items = queries["doctor"].select_related("patient", "dentist", "step_type").order_by(
            "call_again_on", "decided_at", "dentist__full_name", "-kind", "priority", "pk")
        for item in items[:limit or PER_KIND]:
            patient = item.patient
            book = {"patient": patient.pk, "dentist": item.dentist_id, "duration": item.time_given,
                    "procedure": item.step_type_id, "purpose": item.teeth, "request": item.pk}
            why = _("%(dentist)s asked for him: %(step)s %(teeth)s, %(minutes)s min") % {
                "dentist": item.dentist, "step": item.step_type, "teeth": item.teeth, "minutes": item.time_given}
            if item.kind != item.Kind.MAIN:
                why += " · " + str(_("backup list"))
            found.append(_row(
                "doctor", item.pk, patient.full_name, patient.preferred_number,
                item.call_again_on or _local_day(item.decided_at) or _local_day(item.created_at), why, today,
                file=patient.file_number, url=patient.get_absolute_url(), note=item.reception_note,
                more_url=reverse("scheduling:requests_reception"),
                book_url=f"{reverse('scheduling:appointment_create')}?{urlencode(book)}"))
    order = {code: index for index, (code, _label, _icon, _page) in enumerate(KINDS)}
    found.sort(key=lambda row: (row["since"] or today, order[row["kind"]]))
    return found[:limit] if limit else found


@role_required(*FRONT_DESK)
def calls_today(request):
    place = branch_for_user(request.user)
    today = timezone.localdate()
    kind = request.GET.get("kind", "")
    kind = kind if kind in KIND_LABELS else ""
    numbers = counts(place, today)
    cache.set(_count_key(place), numbers["total"], COUNT_SECONDS)
    found = rows(place, today, kind)
    shown = numbers[kind] if kind else numbers["total"]
    page = Paginator(found, PER_PAGE).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "patients/calls_today.html", {
        "page_obj": page, "kind": kind, "counts": numbers, "today": today, "query_string": params.urlencode(),
        "tabs": [{"code": code, "label": label, "icon": icon, "count": numbers[code], "page": reverse(page_name)}
                 for code, label, icon, page_name in KINDS],
        "not_shown": max(shown - len(found), 0),
        "kind_page": next((reverse(page_name) for code, _l, _i, page_name in KINDS if code == kind), ""),
    })


def _next_day(kind, outcome, typed, today):
    days = AGAIN.get(kind, {}).get(outcome)
    return typed if typed and typed > today else (today + timedelta(days=days) if days else None)


def save_answer(kind, pk, outcome, note, next_on, user, place):
    """Write a quick answer from the calls page; returns (name, the day he is called again or None)."""
    from apps.scheduling.models import PatientRequest
    from apps.scheduling.patient_requests import mark_cannot_come

    from .calllists import save_entry_answer
    from .consults import save_recall_answer

    today = timezone.localdate()
    note = (note or "").strip()
    if kind == "lead":
        lead = get_object_or_404(Lead, pk=pk, branch=place)
        result = {"no_answer": LeadCall.Outcome.NO_ANSWER, "later": LeadCall.Outcome.CALL_BACK,
                  "stop": LeadCall.Outcome.ANSWERED}[outcome]
        LeadCall.objects.create(lead=lead, called_at=timezone.now(), outcome=result, notes=note, created_by=user)
        again = None if outcome == "stop" else _next_day(kind, outcome, next_on, today)
        if outcome == "stop":
            lead.status, lead.next_call_at = Lead.Status.NOT_INTERESTED, None
        else:
            lead.status = Lead.Status.FOLLOW_UP
            lead.next_call_at = timezone.make_aware(datetime.combine(again, time(10)))
        lead.save(update_fields=["status", "next_call_at", "updated_at"])
        return lead.full_name, again
    if kind == "test":
        recall = get_object_or_404(MedicalRecall.objects.select_related("patient"), pk=pk, patient__branch=place)
        result = {"no_answer": MedicalRecall.Outcome.NO_ANSWER, "later": MedicalRecall.Outcome.WILL_DO,
                  "stop": MedicalRecall.Outcome.REFUSED}[outcome]
        save_recall_answer(recall, result, note, next_on, user)
        return recall.patient.full_name, recall.due_on if recall.status == MedicalRecall.Status.OPEN else None
    if kind == "list":
        entry = get_object_or_404(CallListEntry.objects.select_related("patient", "call_list__created_by"), pk=pk,
                                  call_list__branch=place)
        result = {"no_answer": CallListEntry.Outcome.NO_ANSWER, "later": CallListEntry.Outcome.CALL_BACK,
                  "stop": CallListEntry.Outcome.NOT_INTERESTED}[outcome]
        save_entry_answer(entry, result, note or entry.response, next_on if next_on and next_on > today else None, user)
        return entry.patient.full_name, entry.next_call_on
    item = get_object_or_404(PatientRequest.objects.select_related("patient", "dentist__user"), pk=pk,
                             patient__branch=place, status=PatientRequest.Status.APPROVED)
    if outcome == "stop":
        mark_cannot_come(item, note)
        return item.patient.full_name, None
    item.call_again_on = _next_day(kind, outcome, next_on, today)
    item.reception_note = (note or str(_("No answer on %(day)s")) % {"day": today.strftime("%d/%m")})[:255]
    item.save(update_fields=["call_again_on", "reception_note", "updated_at"])
    return item.patient.full_name, item.call_again_on


@role_required(*FRONT_DESK)
@require_POST
def calls_answer(request):
    """One answer of the calls page: no answer, later, or a final answer, for any kind of call."""
    from .consults import parse_date_text

    place = branch_for_user(request.user)
    kind, outcome = request.POST.get("kind", ""), request.POST.get("outcome", "")
    back = request.POST.get("next") or reverse("patients:calls_today")
    if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
        back = reverse("patients:calls_today")
    allowed = {code for code, _label, _final in ANSWERS.get(kind, [])}
    if outcome not in allowed or not request.POST.get("pk", "").isdigit():
        messages.error(request, _("Choose what the patient said."))
        return redirect(back)
    name, again = save_answer(kind, int(request.POST["pk"]), outcome, request.POST.get("note", ""),
                              parse_date_text(request.POST.get("next_on", "")), request.user, place)
    forget_count(place)
    if again:
        messages.success(request, _("Saved. The next call to %(name)s is on %(date)s.") % {
            "name": name, "date": again.strftime("%d/%m/%Y")})
    else:
        messages.success(request, _("Answer saved for %(name)s.") % {"name": name})
    return redirect(back)
