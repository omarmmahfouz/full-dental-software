from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledForm, StyledModelForm, UserChoiceField
from apps.core.roles import MANAGEMENT
from apps.dentists.forms import DentistChoiceField
from apps.patients.forms import PatientLookupField, lookup_value

from .models import Complaint, ComplaintFollowUp


class ComplaintForm(StyledModelForm):
    patient_lookup = PatientLookupField(label=_("patient"))
    assigned_to = UserChoiceField(roles=MANAGEMENT, label=_("followed up by"), required=False,
                                  help_text=_("The supervisor responsible for solving it."))
    concerned_dentist = DentistChoiceField(label=_("concerned dentist"), required=False)

    fieldsets = [
        ("", ["patient_lookup", "category", "severity", "concerned_dentist", "concerned_staff", "assigned_to",
              "follow_up_due", "description"]),
    ]

    class Meta:
        model = Complaint
        fields = ["category", "severity", "concerned_dentist", "concerned_staff", "assigned_to", "follow_up_due",
                  "description"]

    def __init__(self, *args, patient=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["concerned_staff"].queryset = get_user_model().objects.filter(is_active=True).order_by("first_name")
        self.fields["follow_up_due"].help_text = _("Leave empty for the default follow-up period.")
        if patient is not None:
            self.fields["patient_lookup"].initial = lookup_value(patient)
            self.fields["patient_lookup"].help_text = str(patient)
        elif self.instance.pk:
            self.fields["patient_lookup"].initial = lookup_value(self.instance.patient)


class FollowUpForm(StyledModelForm):
    current_situation = forms.CharField(
        label=_("current situation of the case"), required=False, widget=forms.Textarea(attrs={"rows": 2}),
        help_text=_("Where the case stands now. Shown at the top of the complaint and in the list."),
    )

    class Meta:
        model = ComplaintFollowUp
        fields = ["action", "new_status", "next_follow_up", "note"]
        labels = {"note": _("what I did")}

    def __init__(self, *args, complaint=None, **kwargs):
        super().__init__(*args, **kwargs)
        if complaint is not None:
            self.fields["new_status"].initial = (
                Complaint.Status.IN_PROGRESS if complaint.status == Complaint.Status.OPEN else complaint.status
            )
            self.fields["current_situation"].initial = complaint.current_situation
        self.fields["note"].widget.attrs["rows"] = 3
        for name in ("action", "new_status", "next_follow_up"):
            self.fields[name].col = "col-md-4"

    def clean(self):
        data = super().clean()
        if data.get("new_status") in Complaint.OPEN_STATUSES and not data.get("next_follow_up"):
            self.add_error("next_follow_up", _("Set the next follow-up date while the complaint is still open."))
        return data


class FollowUpEditForm(StyledModelForm):
    """Correct a follow-up already written (what was done, the next date)."""

    class Meta:
        model = ComplaintFollowUp
        fields = ["action", "next_follow_up", "note"]
        labels = {"note": _("what I did")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["note"].widget.attrs["rows"] = 4
        for name in ("action", "next_follow_up"):
            self.fields[name].col = "col-md-6"


class SituationForm(StyledModelForm):
    class Meta:
        model = Complaint
        fields = ["current_situation"]
        widgets = {"current_situation": forms.Textarea(attrs={"rows": 3})}


class ComplaintFilterForm(StyledForm):
    status = forms.ChoiceField(
        label=_("status"), required=False,
        choices=[("open", _("Open")), ("", _("All"))] + list(Complaint.Status.choices),
    )
    category = forms.ChoiceField(label=_("category"), required=False, choices=[("", _("All"))] + list(Complaint.Category.choices))
    overdue = forms.BooleanField(label=_("follow-up overdue"), required=False)


class DentistAnswerForm(StyledForm):
    note = forms.CharField(label=_("your answer and what will be done to solve it"), widget=forms.Textarea(attrs={"rows": 3}))
    next_follow_up = forms.DateField(label=_("follow up again on"), required=False)
