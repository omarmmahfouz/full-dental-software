"""Time in the system (round 14): for each person, when they opened the system, how long it stayed open and how long
they worked.

- Every page opened is use. The page also asks the server every 30 seconds for new notifications (the bell); that
  check tells the system is still open, and it is use too when the person typed, tapped or scrolled since the last
  check (``?active=1``, static/js/app.js).
- Two moments of use closer than ``ACTIVE_GAP`` count as work between them; a longer pause (away from the desk) does
  not.
- No sign at all for ``OPEN_GAP`` (the page or the browser was closed): the stretch ends at the last sign and the
  next page starts a new one. Logging out, or being logged out for no use, ends it too.

What is not saved yet is kept in the person's session and written at most every ``SAVE_EVERY`` seconds, so the
pages stay as quick as before."""

import time
from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Min, Sum
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.translation import gettext as _

from .mixins import role_required
from .roles import OWNER

KEY = "work"
ACTIVE_GAP = 3 * 60
OPEN_GAP = 30 * 60
SAVE_EVERY = 30
SKIP_PREFIXES = ("/static/", "/media/", "/favicon", "/jsi18n/")


def clock():
    """Now, in whole seconds (a function of its own so the tests can move the time)."""
    return int(time.time())


def _moment(stamp):
    return datetime.fromtimestamp(stamp, tz=dt_timezone.utc)


def _save(state, **extra):
    from .models import WorkSession

    WorkSession.objects.filter(pk=state["id"]).update(
        last_seen_at=_moment(state["seen"]), last_active_at=_moment(state["act"]), active_seconds=state["secs"],
        pages=state["pages"], **extra)


def _start(request, now):
    from .models import WorkSession, branch_for_user
    from .security import client_ip

    session = WorkSession.objects.create(
        user=request.user, branch=branch_for_user(request.user), started_at=_moment(now), last_seen_at=_moment(now),
        last_active_at=_moment(now), device=(client_ip(request) or "")[:120])
    return {"id": session.pk, "seen": now, "act": now, "secs": 0, "pages": 0, "saved": now}


def note(request, active):
    """A sign that ``request.user`` has the system open; ``active``: a sign of use (a page, typing, a tap)."""
    now = clock()
    state = request.session.get(KEY)
    if state and now - state["seen"] > OPEN_GAP:  # closed for a long time: that stretch ended at its last sign
        _save(state, ended_at=_moment(state["seen"]), end="closed")
        state = None
    if not state:
        state = _start(request, now)
        if active:
            state["pages"] = 1
        request.session[KEY] = state
        return
    if active:
        gap = now - state["act"]
        if gap <= ACTIVE_GAP:
            state["secs"] += gap
        state["act"] = now
        if not request.path.startswith("/notifications/"):
            state["pages"] += 1
    state["seen"] = now
    if now - state["saved"] >= SAVE_EVERY:
        state["saved"] = now
        _save(state)
        request.session[KEY] = state  # written with the session; between saves the moments merge


def finish(request, end):
    """Logging out (or being logged out for no use) ends the stretch."""
    state = getattr(request, "session", {}).get(KEY) if request is not None else None
    if not state:
        return
    now = clock()
    if end != "idle":  # logged out by hand: that click was use
        if now - state["act"] <= ACTIVE_GAP:
            state["secs"] += now - state["act"]
        state["act"] = state["seen"] = now
    _save(state, ended_at=_moment(state["seen"]), end=end)
    request.session.pop(KEY, None)


class WorkTimeMiddleware:
    """Notes every page and every check of the bell of a logged-in person (after IdleLogoutMiddleware)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not request.path.startswith(SKIP_PREFIXES) \
                and response.status_code < 400 and hasattr(request, "session"):
            background = request.path.startswith("/notifications/poll/")
            try:
                note(request, active=not background or request.GET.get("active") == "1")
            except Exception:  # the time kept must never stop a page
                pass
        return response


# ------------------------------------------------------------ the owner's report
def duration(seconds):
    """1 h 05 min, 12 min, or "—"."""
    seconds = int(seconds or 0)
    if seconds < 60:
        return _("under a minute") if seconds else "—"
    hours, minutes = divmod(seconds // 60, 60)
    return _("%(h)d h %(m)02d min") % {"h": hours, "m": minutes} if hours else _("%(m)d min") % {"m": minutes}


def period(request):
    from .forms import DateRangeForm

    today = timezone.localdate()
    form = DateRangeForm(request.GET or None)
    date_from = date_to = None
    if form.is_valid():
        date_from, date_to = form.cleaned_data.get("date_from"), form.cleaned_data.get("date_to")
    date_from, date_to = date_from or today, date_to or date_from or today
    start = timezone.make_aware(datetime.combine(date_from, datetime.min.time()))
    end = timezone.make_aware(datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    return form, date_from, date_to, start, end


@role_required(OWNER)
def time_report(request):
    """Each person: how many times the system was opened, when first and last, how long it was open, how long they
    worked (round 14)."""
    from .models import WorkSession

    form, date_from, date_to, start, end = period(request)
    sessions = WorkSession.objects.filter(started_at__gte=start, started_at__lt=end)
    open_now = timezone.now() - timedelta(seconds=OPEN_GAP)
    people = []
    rows = (sessions.values("user").annotate(n=Count("id"), first=Min("started_at"), last=Max("last_seen_at"),
                                            worked=Sum("active_seconds"), pages=Sum("pages")).order_by())
    users = {u.pk: u for u in get_user_model().objects.filter(pk__in=[r["user"] for r in rows])}
    open_by_user = {}
    for session in sessions.only("user_id", "started_at", "last_seen_at", "ended_at"):
        open_by_user[session.user_id] = open_by_user.get(session.user_id, 0) + session.open_seconds
    here_now = set(sessions.filter(ended_at=None, last_seen_at__gte=open_now).values_list("user", flat=True))
    for row in rows:
        opened = open_by_user.get(row["user"], 0)
        people.append({
            "user": users.get(row["user"]), "sessions": row["n"], "first": row["first"], "last": row["last"],
            "open": opened, "worked": row["worked"] or 0, "pages": row["pages"] or 0,
            "share": round(100 * (row["worked"] or 0) / opened) if opened else 0, "now": row["user"] in here_now,
        })
    people.sort(key=lambda p: -p["worked"])
    return render(request, "core/time_report.html", {
        "form": form, "date_from": date_from, "date_to": date_to, "people": people,
        "total_open": sum(p["open"] for p in people), "total_worked": sum(p["worked"] for p in people),
    })


@role_required(OWNER)
def time_person(request, pk):
    """One person's stretches in the system over the period."""
    from .models import WorkSession

    person = get_object_or_404(get_user_model(), pk=pk)
    form, date_from, date_to, start, end = period(request)
    sessions = list(WorkSession.objects.filter(user=person, started_at__gte=start, started_at__lt=end)
                    .select_related("branch").order_by("started_at"))
    open_now = timezone.now() - timedelta(seconds=OPEN_GAP)
    for session in sessions:
        session.is_open = session.ended_at is None and session.last_seen_at >= open_now
    return render(request, "core/time_person.html", {
        "form": form, "date_from": date_from, "date_to": date_to, "person": person, "sessions": sessions,
        "total_open": sum(s.open_seconds for s in sessions), "total_worked": sum(s.active_seconds for s in sessions),
    })
