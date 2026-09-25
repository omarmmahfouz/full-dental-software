from datetime import timedelta

from django import forms
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledForm, StyledModelForm, UserChoiceField
from apps.core.roles import INTERN, SUPERVISOR
from apps.patients.forms import PatientLookupField

from .models import Appointment, Room, RoomShift


class RoomShiftForm(StyledModelForm):
    intern = UserChoiceField(roles=(INTERN,), label=_("intern doctor"))
    supervisor = UserChoiceField(roles=(SUPERVISOR,), label=_("supervisor"), required=False)

    class Meta:
        model = RoomShift
        fields = ["room", "date", "start_time", "end_time", "intern", "supervisor", "notes"]

    def __init__(self, *args, branch=None, **kwargs):
        super().__init__(*args, **kwargs)
        rooms = Room.objects.filter(is_active=True)
        if branch is not None:
            rooms = rooms.filter(branch=branch)
        self.fields["room"].queryset = rooms
        for field in self.fields.values():
            field.col = "col-md-6"
        self.fields["notes"].col = "col-12"


class AppointmentForm(StyledModelForm):
    patient_lookup = PatientLookupField(label=_("patient"))
    intern = UserChoiceField(
        roles=(INTERN,), label=_("intern doctor"), required=False,
        help_text=_("Leave empty to use the patient's responsible intern."),
    )

    fieldsets = [
        ("", ["patient_lookup", "scheduled_at", "duration_minutes", "intern", "room", "purpose", "status", "notes"]),
    ]

    class Meta:
        model = Appointment
        fields = ["scheduled_at", "duration_minutes", "intern", "room", "purpose", "status", "notes"]

    def __init__(self, *args, branch=None, patient=None, **kwargs):
        super().__init__(*args, **kwargs)
        rooms = Room.objects.filter(is_active=True)
        if branch is not None:
            rooms = rooms.filter(branch=branch)
        self.fields["room"].queryset = rooms
        self.fields["room"].help_text = _("Leave empty to use the room of the intern's shift.")
        self.fields["duration_minutes"].initial = settings.CLINIC["DEFAULT_APPOINTMENT_MINUTES"]
        self.fields["notes"].widget.attrs["rows"] = 2
        patient = patient or (self.instance.patient if self.instance.pk else None)
        if patient is not None:
            self.fields["patient_lookup"].initial = patient.file_number
            self.fields["patient_lookup"].help_text = str(patient)
        if not self.instance.pk:
            del self.fields["status"]
        else:
            self.fields["status"].choices = [
                c for c in Appointment.Status.choices
                if c[0] in (Appointment.Status.SCHEDULED, Appointment.Status.CONFIRMED) or c[0] == self.instance.status
            ]

    def clean(self):
        data = super().clean()
        patient = data.get("patient_lookup")
        start = data.get("scheduled_at")
        if patient and start:
            if not data.get("intern") and patient.assigned_intern_id:
                data["intern"] = patient.assigned_intern
            end = start + timedelta(minutes=data.get("duration_minutes") or 60)
            clash = (
                Appointment.objects.filter(patient=patient, scheduled_at__lt=end, scheduled_at__gt=start - timedelta(hours=4))
                .exclude(status__in=(Appointment.Status.CANCELLED, Appointment.Status.NO_SHOW))
                .exclude(pk=self.instance.pk)
            )
            clash = [a for a in clash if a.scheduled_end > start]
            if clash:
                raise forms.ValidationError(
                    _("This patient already has an appointment at %(time)s.")
                    % {"time": timezone.localtime(clash[0].scheduled_at).strftime("%H:%M")}
                )
        return data

    def save(self, commit=True):
        appointment = super().save(commit=False)
        appointment.patient = self.cleaned_data["patient_lookup"]
        appointment.intern = self.cleaned_data.get("intern")
        if appointment.room_id is None:
            shift = appointment.find_shift()
            if shift:
                appointment.room = shift.room
        if commit:
            appointment.save()
        return appointment


class WalkInForm(StyledForm):
    patient_lookup = PatientLookupField(label=_("patient"))
    purpose = forms.CharField(label=_("reason for visit"), required=False, max_length=200)
    intern = UserChoiceField(roles=(INTERN,), label=_("intern doctor"), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.col = "col-md-4"
            field.help_text = ""


class CancelForm(StyledForm):
    reason = forms.CharField(label=_("reason"), max_length=255, required=False)


class AppointmentFilterForm(StyledForm):
    date_from = forms.DateField(label=_("From"), required=False)
    date_to = forms.DateField(label=_("To"), required=False)
    intern = UserChoiceField(roles=(INTERN,), label=_("intern"), required=False, empty_label=_("All"))
    room = forms.ModelChoiceField(
        label=_("room"), queryset=Room.objects.filter(is_active=True), required=False, empty_label=_("All")
    )
    status = forms.ChoiceField(
        label=_("status"), required=False, choices=[("", _("All"))] + list(Appointment.Status.choices)
    )
