from datetime import time, timedelta

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledForm, StyledModelForm
from apps.core.models import ClinicSettings
from apps.clinical.models import TreatmentStepType
from apps.core.widgets import DatalistInput, DateTimeSplitWidget, TimeSelect
from apps.dentists.forms import DentistChoiceField
from apps.dentists.models import Dentist
from apps.patients.forms import PatientLookupField

from .models import Appointment, Room, RoomShift


class RoomShiftForm(StyledModelForm):
    dentist = DentistChoiceField(kinds=Dentist.LOGIN_KINDS, label=_("CIA dentist"), required=False)
    other_dentist = DentistChoiceField(
        kinds=(Dentist.Kind.SUPERVISOR, Dentist.Kind.CANDIDATE, Dentist.Kind.TRAINING),
        label=_("or: supervisor, candidate or training dentist"), required=False,
        help_text=_("When a supervisor or a candidate works in the room instead of a CIA dentist."),
    )
    supervisor = DentistChoiceField(kinds=(Dentist.Kind.SUPERVISOR,), label=_("supervisor"), required=False)

    fieldsets = [("", ["room", "date", "start_time", "end_time", "day_type", "supervisor", "dentist",
                       "other_dentist", "notes"])]

    class Meta:
        model = RoomShift
        fields = ["room", "day_type", "date", "start_time", "end_time", "dentist", "supervisor", "notes"]
        widgets = {"start_time": TimeSelect(start=time(7), end=time(23, 45)),
                   "end_time": TimeSelect(start=time(7), end=time(23, 45))}

    def __init__(self, *args, branch=None, **kwargs):
        super().__init__(*args, **kwargs)
        rooms = Room.objects.filter(is_active=True)
        if branch is not None:
            rooms = rooms.filter(branch=branch)
        self.fields["room"].queryset = rooms
        self.fields["room"].label_from_instance = lambda room: (
            f"{room} ({_('extra room')})" if room.is_extra else str(room))
        self.fields["day_type"].help_text = _("For this room only: the other rooms can work as a regular day.")
        dentist = self.instance.dentist if self.instance.pk else None
        if dentist is not None and dentist.kind not in Dentist.LOGIN_KINDS:
            self.initial["other_dentist"] = dentist.pk
            self.initial["dentist"] = None
        surgery_days = ",".join(str(day) for day in sorted(ClinicSettings.get().surgery_weekdays))
        self.fields["date"].widget.attrs["data-surgery-days"] = surgery_days
        for field in self.fields.values():
            field.col = "col-md-6"
        self.fields["notes"].col = "col-12"

    def clean(self):
        data = super().clean()
        main, other = data.get("dentist"), data.get("other_dentist")
        if main and other:
            self.add_error("other_dentist", _("Choose one dentist: a CIA dentist or someone from this list."))
        elif not main and not other:
            self.add_error("dentist", _("Choose the dentist who works in the room."))
        data["dentist"] = main or other
        return data


DURATIONS = [15, 30, 45, 60, 90, 120, 150, 180, 240]


def duration_choices(current=None):
    minutes = sorted(set(DURATIONS) | ({current} if current else set()))
    return [(m, _("%(n)s minutes") % {"n": m}) for m in minutes]


class AppointmentForm(StyledModelForm):
    patient_lookup = PatientLookupField(label=_("patient"))
    dentist = DentistChoiceField(
        label=_("dentist"), required=False,
        help_text=_("Leave empty to use the patient's responsible dentist."),
    )

    fieldsets = [
        ("", ["patient_lookup", "scheduled_at", "duration_minutes", "dentist", "room", "purpose", "status", "notes"]),
    ]

    class Meta:
        model = Appointment
        fields = ["scheduled_at", "duration_minutes", "dentist", "room", "purpose", "status", "notes"]
        widgets = {"scheduled_at": DateTimeSplitWidget(step=15, start=time(7), end=time(23, 45))}

    def __init__(self, *args, branch=None, patient=None, **kwargs):
        super().__init__(*args, **kwargs)
        rooms = Room.objects.filter(is_active=True)
        if branch is not None:
            rooms = rooms.filter(branch=branch)
        self.fields["room"].queryset = rooms
        self.fields["room"].help_text = _("Leave empty to use the room of the dentist's shift.")
        default = ClinicSettings.get().default_appointment_minutes
        self.fields["duration_minutes"].initial = default
        self.fields["duration_minutes"].widget = forms.Select(
            choices=duration_choices(self.instance.duration_minutes if self.instance.pk else default),
            attrs={"class": "form-select"},
        )
        self.fields["notes"].widget.attrs["rows"] = 2
        self.fields["purpose"].widget = DatalistInput(
            options=lambda: [str(t) for t in TreatmentStepType.objects.filter(is_active=True)],
            attrs={"class": "form-control", "maxlength": 200})
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
            if not data.get("dentist") and patient.assigned_dentist_id:
                data["dentist"] = patient.assigned_dentist
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
        appointment.dentist = self.cleaned_data.get("dentist")
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
    dentist = DentistChoiceField(label=_("dentist"), required=False)

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
    dentist = DentistChoiceField(label=_("dentist"), required=False, empty_label=_("All"))
    room = forms.ModelChoiceField(
        label=_("room"), queryset=Room.objects.filter(is_active=True), required=False, empty_label=_("All")
    )
    status = forms.ChoiceField(
        label=_("status"), required=False, choices=[("", _("All"))] + list(Appointment.Status.choices)
    )


class VisitTimesForm(StyledModelForm):
    """Put right the times the reception forgot to press (arrived, entered the room, left)."""

    reason = forms.CharField(label=_("why"), max_length=255, required=False,
                             help_text=_("e.g. forgot to press “Left” when the patient went out"))

    class Meta:
        model = Appointment
        fields = ["arrived_at", "entered_room_at", "left_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.col = "col-md-6 col-xl-3"

    def clean(self):
        data = super().clean()
        times = [data.get(name) for name in ("arrived_at", "entered_room_at", "left_at")]
        filled = [t for t in times if t]
        if filled != sorted(filled):
            raise forms.ValidationError(_("The times must be in order: arrived, then entered the room, then left."))
        if data.get("left_at") and not data.get("entered_room_at") or data.get("entered_room_at") and not data.get("arrived_at"):
            raise forms.ValidationError(_("Fill the earlier times too."))
        return data
