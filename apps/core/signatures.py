"""Signatures drawn on the screen (round 13): each person draws theirs once (user menu → My signature) and it is
printed on the receipts and prescriptions; a doctor without a login gets his on his page. A signature is kept as a
small PNG picture in the database (a data: address), so it goes with the data backup."""

import base64
import binascii
import re

from django import forms
from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

PNG = re.compile(r"^data:image/png;base64,([A-Za-z0-9+/]+={0,2})$")
LIMIT = 300 * 1024


def clean_signature(value):
    """A drawn signature as sent by the pad, or a ValidationError."""
    value = (value or "").strip()
    match = PNG.match(value)
    if not match or len(value) > LIMIT:
        raise forms.ValidationError(gettext_lazy("Draw the signature in the box, then save."))
    try:
        data = base64.b64decode(match.group(1), validate=True)
    except (binascii.Error, ValueError):
        raise forms.ValidationError(gettext_lazy("Draw the signature in the box, then save."))
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise forms.ValidationError(gettext_lazy("Draw the signature in the box, then save."))
    return value


def person_signature(user):
    """(name, drawn signature) of a login, for the foot of a printed paper."""
    if user is None:
        return "", ""
    profile = getattr(user, "profile", None)
    dentist = getattr(user, "dentist", None)
    name = str(dentist) if dentist is not None else (user.get_full_name() or user.get_username())
    return name, (profile.signature if profile is not None else "") or (dentist.signature if dentist else "")


def signature_page(request, owner, title, back):
    """The pad to draw (or clear) the signature kept on ``owner`` (a UserProfile or a Dentist)."""
    error = None
    if request.method == "POST":
        if request.POST.get("clear"):
            owner.signature = ""
            owner.save(update_fields=["signature"])
            messages.info(request, _("The signature was removed."))
            return redirect(back)
        try:
            owner.signature = clean_signature(request.POST.get("signature"))
        except forms.ValidationError as problem:
            error = problem.messages[0]
        else:
            owner.save(update_fields=["signature"])
            messages.success(request, _("The signature was saved: it is printed on the receipts and prescriptions."))
            return redirect(back)
    return render(request, "core/signature.html", {"title": title, "current": owner.signature, "error": error,
                                                   "back": back})


def my_signature(request):
    from .models import UserProfile

    from django.utils.http import url_has_allowed_host_and_scheme

    profile, _created = UserProfile.objects.get_or_create(user=request.user)
    back = request.GET.get("next") or "/"
    if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
        back = "/"
    return signature_page(request, profile, _("My signature"), back)
