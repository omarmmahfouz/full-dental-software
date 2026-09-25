"""Changes by the reception that wait for the head of CIA: a patient's data and a visit's
times (arrived, entered the room, left). The owner and the head of CIA change directly."""

from datetime import date, datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from .mixins import role_required
from .models import ChangeRequest, Notification
from .notify import notify_roles, notify_users
from .roles import HEAD_CIA, OWNER, has_role

APPROVERS = (OWNER, HEAD_CIA)


def needs_approval(user):
    return not has_role(user, *APPROVERS)


def _display(field, value):
    if value is None or value == "" or (field.many_to_many and not value):
        return "—"
    if field.many_to_many:
        return "، ".join(str(item) for item in value)
    if field.choices:
        return str(dict(field.flatchoices).get(value, value))
    if isinstance(value, bool):
        return _("Yes") if value else _("No")
    if isinstance(value, datetime):
        return timezone.localtime(value).strftime("%d/%m/%Y %I:%M %p")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    return str(value)


def _raw(field, value):
    """The new value in a form that can be kept (JSON) and put back later."""
    if field.many_to_many:
        return [item.pk for item in value]
    if isinstance(value, models.Model):
        return value.pk
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def request_change(kind, obj, values, user, reason=""):
    """Keep ``values`` ({field: new value}) for approval and tell the head of CIA."""
    changes = []
    for name, new in values.items():
        field = obj._meta.get_field(name)
        old = list(getattr(obj, name).all()) if field.many_to_many else getattr(obj, name)
        if field.many_to_many:
            new = list(new)
            if {o.pk for o in old} == {n.pk for n in new}:
                continue
        elif old == new:
            continue
        changes.append({"field": name, "label": str(field.verbose_name), "old": _display(field, old),
                        "new": _display(field, new), "value": _raw(field, new)})
    if not changes:
        return None
    change = ChangeRequest.objects.create(
        kind=kind, content_type=ContentType.objects.get_for_model(obj), object_id=obj.pk, title=str(obj)[:200],
        changes=changes, reason=reason, requested_by=user,
    )
    notify_roles(
        (HEAD_CIA,), gettext_lazy("Change to approve: %(title)s"), gettext_lazy("%(kind)s, asked by %(user)s."),
        "/approvals/", Notification.Level.WARNING, exclude=user,
        params={"title": change.title, "kind": change.get_kind_display(), "user": user},
    )
    return change


def apply_change(change):
    obj = change.target
    for item in change.changes:
        field = obj._meta.get_field(item["field"])
        if field.many_to_many:
            continue
        if field.is_relation:
            setattr(obj, field.attname, item["value"])
        else:
            setattr(obj, field.name, field.to_python(item["value"]))
    if change.kind == ChangeRequest.Kind.VISIT_TIMES:
        obj.set_status_from_times()
    obj.validate_unique()
    obj.save()
    for item in change.changes:
        field = obj._meta.get_field(item["field"])
        if field.many_to_many:
            getattr(obj, field.name).set(item["value"])
    return obj


def pending_for(obj):
    return ChangeRequest.objects.filter(content_type=ContentType.objects.get_for_model(obj), object_id=obj.pk,
                                        status=ChangeRequest.Status.PENDING)


@role_required(*APPROVERS)
def approval_list(request):
    return render(request, "core/approvals.html", {
        "pending": ChangeRequest.objects.filter(status=ChangeRequest.Status.PENDING).select_related("requested_by"),
        "decided": ChangeRequest.objects.exclude(status=ChangeRequest.Status.PENDING)
        .select_related("requested_by", "decided_by")[:30],
    })


@role_required(*APPROVERS)
@require_POST
def approval_decide(request, pk):
    change = get_object_or_404(ChangeRequest, pk=pk, status=ChangeRequest.Status.PENDING)
    approve = request.POST.get("action") == "approve"
    change.decision_note = request.POST.get("note", "").strip()[:255]
    if approve:
        try:
            with transaction.atomic():
                obj = apply_change(change)
        except ValidationError as error:
            messages.error(request, _("Could not apply the change: %(error)s") % {"error": " ".join(error.messages)})
            return redirect("core:approvals")
    change.status = ChangeRequest.Status.APPROVED if approve else ChangeRequest.Status.REJECTED
    change.decided_by, change.decided_at = request.user, timezone.now()
    change.save()
    if change.requested_by_id:
        notify_users(
            [change.requested_by],
            gettext_lazy("Change approved: %(title)s") if approve else gettext_lazy("Change rejected: %(title)s"),
            change.decision_note.replace("%", "%%"), obj.get_absolute_url() if approve else "",
            Notification.Level.SUCCESS if approve else Notification.Level.WARNING,
            params={"title": change.title},
        )
    messages.success(request, _("Approved and applied.") if approve else _("Rejected."))
    return redirect("core:approvals")
