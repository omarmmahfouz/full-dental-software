"""Settings → Security and health (the owner): the checks, who is logged in now, the logins closed after wrong
passwords, the security log and the deleted records (see security.py and health.py)."""

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .health import health, security_checks, short_device
from .mixins import role_required
from .models import DeletedRecord, SecurityEvent
from .roles import OWNER
from .security import end_sessions, locked_logins, open_sessions, unlock


@role_required(OWNER)
def security_home(request):
    events = SecurityEvent.objects.select_related("user")
    kind = request.GET.get("kind", "")
    if kind in SecurityEvent.Kind.values:
        events = events.filter(kind=kind)
    who = request.GET.get("who", "").strip()
    if who:
        events = events.filter(Q(username__icontains=who) | Q(ip__startswith=who))
    sessions = open_sessions()
    for row in sessions:
        row["short_device"] = short_device(row["device"])
        row["mine"] = row["key"] == request.session.session_key
    day = timezone.now() - timedelta(hours=24)
    week = timezone.now() - timedelta(days=7)
    counts = dict(SecurityEvent.objects.filter(at__gte=day).values_list("kind").annotate(n=Count("pk")))
    checks = security_checks()
    return render(request, "settings/security.html", {
        "checks": checks, "to_fix": sum(1 for check in checks if not check["ok"]), "health": health(),
        "sessions": sessions, "locked": locked_logins(),
        "page_obj": Paginator(events, 50).get_page(request.GET.get("page")), "kinds": SecurityEvent.Kind.choices,
        "kind": kind, "who": who, "failed_today": counts.get(SecurityEvent.Kind.LOGIN_FAILED, 0),
        "exports_week": SecurityEvent.objects.filter(kind=SecurityEvent.Kind.EXPORT, at__gte=week).count(),
        "deleted_week": DeletedRecord.objects.filter(deleted_at__gte=week).count(),
    })


@role_required(OWNER)
@require_POST
def security_unlock(request):
    username, ip = request.POST.get("username", "").strip(), request.POST.get("ip", "").strip()
    if username or ip:
        unlock(request, username=username, ip=ip or None)
        messages.success(request, _("Opened again: %(what)s.") % {"what": username or ip})
    return redirect("settings:security")


@role_required(OWNER)
@require_POST
def security_logout(request):
    """Log out one person on every device, or everyone but the owner on this device."""
    if request.POST.get("user", "").isdigit():
        person = get_object_or_404(get_user_model(), pk=request.POST["user"])
        ended = end_sessions(request, user=person, keep=request.session.session_key)
        messages.success(request, _("%(name)s was logged out (%(n)s devices).") % {
            "name": person.get_full_name() or person.username, "n": ended})
    else:
        ended = end_sessions(request, keep=request.session.session_key)
        messages.success(request, _("Everyone else was logged out (%(n)s devices).") % {"n": ended})
    return redirect("settings:security")


@role_required(OWNER)
def deleted_list(request):
    rows = DeletedRecord.objects.select_related("deleted_by")
    model = request.GET.get("model", "")
    if model:
        rows = rows.filter(model=model)
    q = request.GET.get("q", "").strip()
    if q:
        rows = rows.filter(Q(label__icontains=q) | Q(object_id=q))
    models = sorted(((label, DeletedRecord(model=label).kind_name) for label in DeletedRecord.objects.values_list(
        "model", flat=True).distinct().order_by()), key=lambda pair: str(pair[1]))
    return render(request, "settings/deleted.html", {
        "page_obj": Paginator(rows, 50).get_page(request.GET.get("page")), "models": models, "model": model, "q": q})


@role_required(OWNER)
def deleted_detail(request, pk):
    record = get_object_or_404(DeletedRecord.objects.select_related("deleted_by"), pk=pk)
    return render(request, "settings/deleted_detail.html", {"record": record, "fields": readable_fields(record)})


def readable_fields(record):
    """What a deleted record held, in plain words: the field's name, choices by their label, dates as dd/mm/yyyy, and
    the records it pointed to by their name (when they are still there)."""
    from django.apps import apps
    from django.utils.dateparse import parse_date, parse_datetime

    data = record.data if isinstance(record.data, dict) else {}
    try:
        model = apps.get_model(record.model)
    except (LookupError, ValueError):
        return sorted((name, value) for name, value in data.items())
    rows = []
    for field in model._meta.concrete_fields:
        if field.name not in data:
            continue
        value = data[field.name]
        if value in (None, ""):
            shown = None
        elif field.choices:
            shown = dict(field.flatchoices).get(value, value)
        elif field.is_relation:
            target = field.related_model._base_manager.filter(pk=value).first()
            shown = str(target) if target is not None else f"#{value}"
        elif field.get_internal_type() == "DateTimeField" and parse_datetime(str(value)):
            shown = timezone.localtime(parse_datetime(str(value))).strftime("%d/%m/%Y %H:%M")
        elif field.get_internal_type() == "DateField" and parse_date(str(value)):
            shown = parse_date(str(value)).strftime("%d/%m/%Y")
        elif field.get_internal_type() == "BooleanField":
            shown = _("Yes") if value else _("No")
        else:
            shown = value
        rows.append((str(field.verbose_name).capitalize(), shown))
    return rows
