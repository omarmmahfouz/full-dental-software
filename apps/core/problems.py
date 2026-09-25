"""Problems with the software: anyone can report one from the user menu, and a page that
fails is recorded by itself. The owner (and the head of CIA) read them here, answer, and
download them for whoever maintains the software."""

import csv
import hashlib
import traceback

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from .forms import StyledForm, validate_upload
from .mixins import role_required
from .models import Notification, ProblemReport
from .notify import notify_roles, notify_users
from .roles import HEAD_CIA, OWNER

READERS = (OWNER, HEAD_CIA)


class ProblemForm(StyledForm):
    description = forms.CharField(
        label=gettext_lazy("What happened?"), max_length=4000, widget=forms.Textarea(attrs={"rows": 4}),
        help_text=gettext_lazy("What you were doing, what you expected and what you saw instead."),
    )
    screenshot = forms.FileField(label=gettext_lazy("Screenshot or photo (optional)"), required=False,
                                 validators=[validate_upload])
    page = forms.CharField(required=False, max_length=500, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["screenshot"].widget.attrs["accept"] = "image/*"


def _safe_page(request, page):
    return page if page and url_has_allowed_host_and_scheme(page, {request.get_host()}) else ""


def problem_report(request):
    """The form of the user menu's "Report a problem" (also answers the pop-up with JSON)."""
    page = _safe_page(request, request.POST.get("page") or request.GET.get("page") or request.META.get("HTTP_REFERER"))
    form = ProblemForm(request.POST or None, request.FILES or None, initial={"page": page})
    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if request.method == "POST":
        if form.is_valid():
            report = ProblemReport.objects.create(
                page=page, description=form.cleaned_data["description"],
                screenshot=form.cleaned_data.get("screenshot"), reported_by=request.user,
                error=f"Browser: {request.META.get('HTTP_USER_AGENT', '')[:300]}",
            )
            notify_roles((OWNER,), gettext_lazy("Problem reported by %(user)s"), report.description[:300],
                         "/problems/", Notification.Level.WARNING, exclude=request.user,
                         params={"user": request.user})
            thanks = _("Thank you. The problem was sent to the owner of the system.")
            if wants_json:
                return JsonResponse({"ok": True, "message": thanks})
            messages.success(request, thanks)
            return redirect(page or "core:dashboard")
        if wants_json:
            return JsonResponse({"ok": False, "errors": [e for errors in form.errors.values() for e in errors]},
                                status=400)
    mine = ProblemReport.objects.filter(reported_by=request.user, kind=ProblemReport.Kind.REPORTED)[:10]
    return render(request, "core/problem_report.html", {"form": form, "mine": mine})


@role_required(*READERS)
def problem_list(request):
    reports = ProblemReport.objects.select_related("reported_by", "handled_by")
    status = request.GET.get("status", "open")
    if status == "open":
        reports = reports.exclude(status=ProblemReport.Status.SOLVED)
    elif status in ProblemReport.Status.values:
        reports = reports.filter(status=status)
    return render(request, "core/problems.html", {
        "reports": reports[:200], "status": status, "statuses": ProblemReport.Status.choices,
    })


@role_required(*READERS)
@require_POST
def problem_update(request, pk):
    report = get_object_or_404(ProblemReport, pk=pk)
    status = request.POST.get("status")
    if status in ProblemReport.Status.values:
        report.status = status
    report.answer = request.POST.get("answer", report.answer).strip()[:4000]
    report.handled_by = request.user
    report.save(update_fields=["status", "answer", "handled_by"])
    if report.reported_by_id and report.status == ProblemReport.Status.SOLVED:
        notify_users([report.reported_by], gettext_lazy("The problem you reported was looked at"),
                     report.answer.replace("%", "%%"), "/problems/report/", Notification.Level.SUCCESS)
    messages.success(request, _("Saved."))
    return redirect(f"/problems/?status={request.POST.get('back', 'open')}")


@role_required(*READERS)
def problem_export(request):
    """All the reports as a spreadsheet file (CSV) to send to whoever maintains the software."""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="problems-{timezone.localdate():%Y-%m-%d}.csv"'
    response.write("﻿")  # Excel opens the Arabic text correctly
    writer = csv.writer(response)
    writer.writerow(["id", "kind", "status", "first time", "last time", "times", "reported by", "page",
                     "what happened", "answer", "technical details"])
    for report in ProblemReport.objects.select_related("reported_by"):
        writer.writerow([
            report.pk, report.get_kind_display(), report.get_status_display(),
            timezone.localtime(report.created_at).strftime("%d/%m/%Y %H:%M"),
            timezone.localtime(report.last_seen_at).strftime("%d/%m/%Y %H:%M"), report.times,
            report.reported_by or "", report.page, report.description, report.answer, report.error,
        ])
    return response


# Not software problems: a missing page, no permission, a bad address typed by hand.
IGNORED_ERRORS = (Http404, PermissionDenied, SuspiciousOperation)


def record_error(request, exception):
    """Keep a page error for the owner. The same error on the same page is counted, not repeated."""
    if isinstance(exception, IGNORED_ERRORS):
        return None
    try:
        details = "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))
        where = request.resolver_match.view_name if getattr(request, "resolver_match", None) else request.path
        signature = hashlib.sha1(f"{where}|{type(exception).__name__}|{exception}".encode()).hexdigest()
        user = request.user if getattr(request, "user", None) is not None and request.user.is_authenticated else None
        report = ProblemReport.objects.filter(signature=signature).exclude(status=ProblemReport.Status.SOLVED).first()
        if report is not None:
            report.times += 1
            report.last_seen_at = timezone.now()
            report.save(update_fields=["times", "last_seen_at"])
            return report
        report = ProblemReport.objects.create(
            kind=ProblemReport.Kind.AUTOMATIC, page=request.get_full_path()[:500], signature=signature,
            description=f"{request.method} {type(exception).__name__}: {exception}"[:4000], error=details,
            reported_by=user,
        )
        notify_roles((OWNER,), gettext_lazy("A page stopped with an error"), gettext_lazy("Page: %(page)s"),
                     "/problems/", Notification.Level.DANGER, params={"page": report.page})
        return report
    except Exception:  # recording must never hide the real error
        return None
