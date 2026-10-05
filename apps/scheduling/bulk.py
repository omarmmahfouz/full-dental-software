"""WhatsApp to many patients (round 15). WhatsApp opens one message per press (no automatic sending without
Meta's WhatsApp Business platform), so the list is sent one after another: "Send the next one" opens WhatsApp in a
new tab with the next person's number and the text ready, and this page counts what is sent."""

import csv

from django import forms
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.core.forms import StyledForm
from apps.core.mixins import role_required
from apps.core.models import branch_for_user
from apps.core.roles import FRONT_DESK
from apps.core.utils import GOVERNORATE_CHOICES
from apps.dentists.forms import DentistChoiceField
from apps.patients.models import Gender, Lead, Patient

from .models import Appointment, BulkMessage, BulkRecipient
from .whatsapp import _Keep, whatsapp_number, whatsapp_url

LIMIT = 1000  # people in one message to many


class BulkForm(StyledForm):
    WHO = [("patients", gettext_lazy("Our patients")), ("leads", gettext_lazy("Expected patients (the call list)"))]

    title = forms.CharField(label=gettext_lazy("title"), max_length=120,
                            help_text=gettext_lazy("For you, e.g. Eid greetings, the new implant offer."))
    text = forms.CharField(label=gettext_lazy("message"), widget=forms.Textarea(attrs={"rows": 5, "dir": "rtl"}),
                           help_text=gettext_lazy("{patient} is replaced by each one's name; {clinic}, {phone} and "
                                                  "{address} by the place's."))
    who = forms.ChoiceField(label=gettext_lazy("send to"), choices=WHO, initial="patients",
                            widget=forms.RadioSelect)
    status = forms.MultipleChoiceField(label=gettext_lazy("patients who are"), required=False,
                                       choices=[c for c in Patient.Status.choices if c[0] != Patient.Status.OUT],
                                       widget=forms.CheckboxSelectMultiple,
                                       help_text=gettext_lazy("Empty = all but the patients who are out."))
    dentist = DentistChoiceField(label=gettext_lazy("responsible dentist"), required=False,
                                 empty_label=gettext_lazy("All"))
    gender = forms.ChoiceField(label=gettext_lazy("gender"), required=False,
                               choices=[("", gettext_lazy("All"))] + list(Gender.choices))
    governorate = forms.ChoiceField(label=gettext_lazy("governorate"), required=False,
                                    choices=[("", gettext_lazy("All"))] + list(GOVERNORATE_CHOICES))
    age_from = forms.IntegerField(label=gettext_lazy("age from"), required=False, min_value=0, max_value=120)
    age_to = forms.IntegerField(label=gettext_lazy("age to"), required=False, min_value=0, max_value=120)
    registered_from = forms.DateField(label=gettext_lazy("file opened from"), required=False)
    registered_to = forms.DateField(label=gettext_lazy("file opened to"), required=False)
    not_seen_since = forms.DateField(label=gettext_lazy("no visit since"), required=False,
                                     help_text=gettext_lazy("e.g. patients who have not come for 6 months."))

    fieldsets = [
        (gettext_lazy("The message"), ["title", "text"]),
        (gettext_lazy("Who gets it"), ["who", "status", "dentist", "gender", "governorate", "age_from", "age_to",
                                       "registered_from", "registered_to", "not_seen_since"]),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("dentist", "gender", "governorate", "age_from", "age_to", "registered_from", "registered_to",
                     "not_seen_since"):
            self.fields[name].col = "col-md-6 col-lg-3"
        self.fields["title"].col = "col-12"

    def people(self, place):
        """[(patient, lead, name, phone)] once per mobile number (the first one found)."""
        data = self.cleaned_data
        rows, seen = [], set()
        if data.get("who") == "leads":
            leads = Lead.objects.filter(branch=place, status__in=Lead.OPEN_STATUSES).order_by("first_call_on")
            candidates = ((None, lead, lead.full_name, lead.preferred_number) for lead in leads)
        else:
            patients = Patient.objects.filter(branch=place).exclude(status=Patient.Status.OUT)
            if data.get("status"):
                patients = patients.filter(status__in=data["status"])
            if data.get("dentist"):
                patients = patients.filter(assigned_dentist=data["dentist"])
            if data.get("gender"):
                patients = patients.filter(gender=data["gender"])
            if data.get("governorate"):
                patients = patients.filter(governorate=data["governorate"])
            today = timezone.localdate()
            if data.get("age_from") is not None:
                patients = patients.filter(birth_date__lte=_years_ago(today, data["age_from"]))
            if data.get("age_to") is not None:
                patients = patients.filter(birth_date__gt=_years_ago(today, data["age_to"] + 1))
            if data.get("registered_from"):
                patients = patients.filter(registered_on__gte=data["registered_from"])
            if data.get("registered_to"):
                patients = patients.filter(registered_on__lte=data["registered_to"])
            if data.get("not_seen_since"):
                since = data["not_seen_since"]
                seen_after = Appointment.objects.filter(
                    status=Appointment.Status.COMPLETED, scheduled_at__date__gte=since).values("patient_id")
                patients = patients.exclude(pk__in=seen_after)
            candidates = ((p, None, p.full_name, p.preferred_number) for p in patients.order_by("full_name"))
        for patient, lead, name, phone in candidates:
            number = whatsapp_number(phone)
            if not number or number in seen:
                continue
            seen.add(number)
            rows.append((patient, lead, name, phone))
            if len(rows) >= LIMIT:
                break
        return rows

    def describe(self):
        """The choices in words, kept on the message ("Under treatment · Dr. Ahmed · Cairo")."""
        data, parts = self.cleaned_data, []
        if data.get("who") == "leads":
            return str(_("Expected patients (the call list)"))
        labels = dict(Patient.Status.choices)
        parts += [str(labels[code]) for code in data.get("status") or []]
        for name in ("dentist",):
            if data.get(name):
                parts.append(str(data[name]))
        if data.get("gender"):
            parts.append(str(dict(Gender.choices)[data["gender"]]))
        if data.get("governorate"):
            parts.append(str(dict(GOVERNORATE_CHOICES).get(data["governorate"], "")))
        if data.get("age_from") is not None or data.get("age_to") is not None:
            parts.append(_("age %(a)s–%(b)s") % {"a": data.get("age_from") or 0, "b": data.get("age_to") or "…"})
        if data.get("not_seen_since"):
            parts.append(_("no visit since %(date)s") % {"date": data["not_seen_since"].strftime("%d/%m/%Y")})
        return " · ".join(parts) or str(_("All our patients"))


def _years_ago(today, years):
    try:
        return today.replace(year=today.year - years)
    except ValueError:  # 29 February
        return today.replace(year=today.year - years, day=28)


def text_for(bulk, recipient):
    place = bulk.branch
    return bulk.text.format_map(_Keep({
        "patient": recipient.name, "clinic": place.name_ar if place else "", "phone": place.phone if place else "",
        "address": place.address if place else ""}))


@role_required(*FRONT_DESK)
def bulk_list(request):
    here = branch_for_user(request.user)
    bulks = list(BulkMessage.objects.filter(branch=here).select_related("created_by")[:50])
    for bulk in bulks:
        bulk.done, bulk.total = bulk.progress()
    return render(request, "scheduling/bulk_list.html", {"bulks": bulks})


@role_required(*FRONT_DESK)
def bulk_create(request):
    here = branch_for_user(request.user)
    form = BulkForm(request.POST or None)
    preview = None
    if request.method == "POST" and form.is_valid():
        people = form.people(here)
        if not people:
            messages.warning(request, _("Nobody with a mobile number matches these choices."))
        elif request.POST.get("do") == "count":
            preview = {"count": len(people), "names": [name for _p, _l, name, _phone in people[:12]],
                       "limit": len(people) >= LIMIT}
        else:
            with transaction.atomic():
                bulk = BulkMessage.objects.create(branch=here, title=form.cleaned_data["title"],
                                                  text=form.cleaned_data["text"], audience=form.describe()[:300],
                                                  created_by=request.user)
                BulkRecipient.objects.bulk_create([
                    BulkRecipient(bulk=bulk, patient=patient, lead=lead, name=name[:150], phone=phone)
                    for patient, lead, name, phone in people])
            messages.success(request, _("%(n)s people are ready: press “Send the next one”.") % {"n": len(people)})
            return redirect(bulk)
    return render(request, "scheduling/bulk_form.html", {"form": form, "preview": preview, "limit": LIMIT})


@role_required(*FRONT_DESK)
def bulk_detail(request, pk):
    bulk = get_object_or_404(BulkMessage, pk=pk, branch=branch_for_user(request.user))
    recipients = list(bulk.recipients.select_related("sent_by"))
    left = [r for r in recipients if not r.sent_at and not r.skipped]
    done = len(recipients) - len(left)
    sent_today = BulkRecipient.objects.filter(bulk__branch=bulk.branch, sent_at__date=timezone.localdate()).count()
    return render(request, "scheduling/bulk_detail.html", {
        "bulk": bulk, "recipients": recipients, "next": left[0] if left else None, "done": done,
        "total": len(recipients), "percent": round(100 * done / len(recipients)) if recipients else 100,
        "sample": text_for(bulk, left[0] if left else recipients[0]) if recipients else bulk.text,
        "sent_today": sent_today,
    })


@role_required(*FRONT_DESK)
@require_POST
def bulk_send(request, pk):
    """Mark the next person (or the one pressed) as sent and open WhatsApp with the text ready."""
    bulk = get_object_or_404(BulkMessage, pk=pk, branch=branch_for_user(request.user))
    rows = bulk.recipients.filter(sent_at__isnull=True, skipped=False)
    if request.POST.get("recipient", "").isdigit():
        rows = bulk.recipients.filter(pk=request.POST["recipient"])
    recipient = rows.first()
    if recipient is None:
        messages.success(request, _("Everyone on the list has it."))
        return redirect(bulk)
    if request.POST.get("skip"):
        recipient.skipped = True
        recipient.save(update_fields=["skipped"])
        return redirect(bulk)
    recipient.sent_at, recipient.sent_by, recipient.skipped = timezone.now(), request.user, False
    recipient.save(update_fields=["sent_at", "sent_by", "skipped"])
    return redirect(whatsapp_url(recipient.phone, text_for(bulk, recipient)))


@role_required(*FRONT_DESK)
def bulk_numbers(request, pk):
    """The names and numbers as a CSV (Excel opens it): for a broadcast list of WhatsApp Business."""
    bulk = get_object_or_404(BulkMessage, pk=pk, branch=branch_for_user(request.user))
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="whatsapp-{bulk.pk}.csv"'
    response.write("﻿")  # Excel reads the Arabic names
    writer = csv.writer(response)
    writer.writerow([_("name"), _("mobile"), "WhatsApp"])
    for recipient in bulk.recipients.all():
        writer.writerow([recipient.name, recipient.phone, "+" + whatsapp_number(recipient.phone)])
    return response
