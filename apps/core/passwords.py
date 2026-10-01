"""Forgotten passwords. The clinic works on its own network without e-mail, so a person who forgot the password asks
from the login page; the owner is told, gives a temporary password (Settings → People and logins) and tells it to
the person (or sends it on WhatsApp). At the next login the person must choose a new password of their own."""

import secrets
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from .mixins import role_required
from .models import Notification, PasswordHelp, UserProfile
from .notify import notify_roles
from .roles import OWNER

# Letters and digits that cannot be mistaken for one another when read out or written down.
READABLE = "abcdefghjkmnpqrstuvwxyz23456789"
MAX_A_DAY = 3


def temporary_password(length=8):
    return "".join(secrets.choice(READABLE) for _i in range(length))


@login_not_required
def forgot_password(request):
    if request.user.is_authenticated:
        return redirect("password_change")
    if request.method == "POST":
        username = request.POST.get("username", "").strip()[:150]
        note = request.POST.get("note", "").strip()[:200]
        if not username:
            messages.error(request, _("Write your username."))
            return render(request, "registration/password_forgot.html", {"note": note})
        user = get_user_model().objects.filter(username__iexact=username, is_active=True).first()
        recent = PasswordHelp.objects.filter(username__iexact=username, asked_at__gte=timezone.now() - timedelta(days=1))
        if recent.count() < MAX_A_DAY:
            PasswordHelp.objects.create(username=username, user=user, note=note)
            if user is not None:
                notify_roles((OWNER,), gettext_lazy("Forgotten password: %(name)s"),
                             gettext_lazy("%(name)s asks for a new password. %(note)s"),
                             reverse("settings:users") + "#password-requests", Notification.Level.WARNING,
                             params={"name": user.get_full_name() or user.username, "note": note})
        # The same answer whether the username exists or not.
        return render(request, "registration/password_forgot.html", {"sent": True})
    return render(request, "registration/password_forgot.html", {})


def pending():
    return PasswordHelp.objects.filter(status=PasswordHelp.Status.NEW, user__isnull=False).select_related(
        "user", "user__profile")


@role_required(OWNER)
@require_POST
def give_password(request, pk):
    asked = get_object_or_404(PasswordHelp.objects.select_related("user"), pk=pk, user__isnull=False)
    password = temporary_password()
    asked.user.set_password(password)
    asked.user.save(update_fields=["password"])
    profile = UserProfile.objects.get_or_create(user=asked.user)[0]
    profile.must_change_password = True
    profile.save(update_fields=["must_change_password"])
    PasswordHelp.objects.filter(user=asked.user, status=PasswordHelp.Status.NEW).update(
        status=PasswordHelp.Status.DONE, done_by=request.user, done_at=timezone.now())
    from .models import SecurityEvent
    from .security import log_event

    log_event(SecurityEvent.Kind.PASSWORD_GIVEN, request, user=asked.user, details=_("temporary password"))
    request.session["given_password"] = {"user": asked.user.pk, "name": asked.user.get_full_name() or
                                         asked.user.username, "password": password, "phone": profile.phone}
    return redirect(reverse("settings:users") + "#password-requests")


@role_required(OWNER)
@require_POST
def refuse_password(request, pk):
    asked = get_object_or_404(PasswordHelp, pk=pk)
    PasswordHelp.objects.filter(pk=asked.pk).update(status=PasswordHelp.Status.REFUSED, done_by=request.user,
                                                    done_at=timezone.now())
    messages.info(request, _("The request was closed without a new password."))
    return redirect(reverse("settings:users") + "#password-requests")


class PasswordChange(auth_views.PasswordChangeView):
    """The usual page to change one's password; it also ends the "must choose a new password" of a temporary one."""

    success_url = reverse_lazy("password_change_done")

    def form_valid(self, form):
        from .models import SecurityEvent
        from .security import is_easy, log_event

        response = super().form_valid(form)
        UserProfile.objects.filter(user=self.request.user).update(
            must_change_password=False, weak_password=is_easy(form.cleaned_data.get("new_password1"),
                                                              self.request.user))
        log_event(SecurityEvent.Kind.PASSWORD_CHANGED, self.request)
        return response


def must_change(user):
    profile = getattr(user, "profile", None)
    return bool(profile is not None and profile.must_change_password)
