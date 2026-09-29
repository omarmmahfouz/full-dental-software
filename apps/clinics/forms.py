from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.billing.forms import NEEDS_REFERENCE, ServiceChoiceField
from apps.billing.models import Service
from apps.core.forms import StyledForm, StyledModelForm
from apps.dentists.forms import DentistChoiceField

from .models import DoctorPayout, DoctorPrice, FeeRule


class PlacePeriodForm(StyledForm):
    place = forms.ChoiceField(label=_("place"), required=False)
    date_from = forms.DateField(label=_("From"), required=False)
    date_to = forms.DateField(label=_("To"), required=False)

    def __init__(self, *args, places=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["place"].choices = [(p.code, f"{p.badge} — {p.name}") for p in places]
        self.fields["place"].widget.attrs["class"] = "form-select"


class FeeRuleForm(StyledModelForm):
    dentist = DentistChoiceField(label=_("doctor"))
    service = ServiceChoiceField(label=_("for the service"), required=False, queryset=Service.objects.none(),
                                 empty_label=_("every service"))

    fieldsets = [("", ["branch", "dentist", "service", "patient_source", "method", "value", "deduct_costs", "starts_on",
                       "ends_on", "is_active", "notes"])]

    class Meta:
        model = FeeRule
        fields = ["branch", "dentist", "service", "patient_source", "method", "value", "deduct_costs", "starts_on",
                  "ends_on", "is_active", "notes"]

    def __init__(self, *args, places=(), place=None, **kwargs):
        super().__init__(*args, **kwargs)
        place = self.instance.branch if self.instance.pk else place
        # The place is the one chosen on the page: its doctors and its services are offered.
        self.fields["branch"].queryset = self.fields["branch"].queryset.filter(pk__in=[p.pk for p in places])
        if not self.instance.pk:
            self.initial["branch"] = place.pk if place else None
        self.fields["branch"].disabled = True
        self.fields["dentist"].queryset = self.fields["dentist"].queryset.working_at(place)
        self.fields["service"].queryset = Service.for_place(place)
        for name in ("branch", "dentist", "service", "patient_source", "method", "value", "starts_on", "ends_on"):
            self.fields[name].col = "col-md-6"
        self.fields["notes"].col = self.fields["deduct_costs"].col = "col-12"


class DoctorPriceForm(StyledModelForm):
    dentist = DentistChoiceField(label=_("doctor"))
    service = ServiceChoiceField(label=_("service"), queryset=Service.objects.none())

    class Meta:
        model = DoctorPrice
        fields = ["dentist", "service", "price", "cost", "notes", "is_active"]

    def __init__(self, *args, place=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.place = self.instance.branch if self.instance.pk else place
        self.fields["dentist"].queryset = self.fields["dentist"].queryset.working_at(self.place)
        self.fields["service"].queryset = Service.for_place(self.place)
        for field in self.fields.values():
            field.col = "col-md-6 col-lg-4"
        self.fields["notes"].col = "col-md-8"

    def clean(self):
        data = super().clean()
        taken = DoctorPrice.objects.filter(dentist=data.get("dentist"), service=data.get("service"),
                                           branch=self.place).exclude(pk=self.instance.pk)
        if data.get("dentist") and data.get("service") and taken.exists():
            self.add_error("service", _("This doctor already has a price for this service here: change that one."))
        return data


class PayoutForm(StyledModelForm):
    class Meta:
        model = DoctorPayout
        fields = ["amount", "paid_on", "method", "reference", "period_from", "period_to", "notes"]

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("initial", {}).setdefault("paid_on", timezone.localdate())
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.col = "col-md-4"
        self.fields["notes"].col = "col-md-8"

    def clean(self):
        data = super().clean()
        if data.get("method") in NEEDS_REFERENCE and not data.get("reference"):
            self.add_error("reference", _("Write the transaction / transfer reference number."))
        return data
