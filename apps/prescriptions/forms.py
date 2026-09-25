from django import forms
from django.forms import formset_factory
from django.utils.translation import gettext_lazy as _

from apps.core.forms import BootstrapFormMixin, StyledForm
from apps.dentists.forms import DentistChoiceField

from .models import Drug, DrugGroup


class DrugSelect(forms.Select):
    """Drugs grouped by interchangeable group; each option carries its group's usual dose."""

    doses = {}

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        dose = self.doses.get(str(value))
        if dose:
            option["attrs"]["data-dose"] = dose
        return option


def drug_choices():
    choices = [("", "---------")]
    doses = {}
    for group in DrugGroup.objects.filter(is_active=True).prefetch_related("drugs"):
        drugs = [d for d in group.drugs.all() if d.is_active]
        if drugs:
            choices.append((str(group), [(d.pk, d.name) for d in drugs]))
            doses.update({str(d.pk): group.dose for d in drugs})
    return choices, doses


class PrescriptionForm(StyledForm):
    prescribed_on = forms.DateField(label=_("date"))
    dentist = DentistChoiceField(label=_("dentist"), required=False)
    notes = forms.CharField(label=_("notes for the patient"), required=False, max_length=255)


class LineForm(BootstrapFormMixin, forms.Form):
    drug = forms.TypedChoiceField(label=_("drug"), coerce=int, required=False, empty_value=None)
    dose = forms.CharField(label=_("how to take it"), required=False, max_length=255)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices, doses = drug_choices()
        widget = DrugSelect(attrs={"class": "form-select drug-select"})
        widget.doses = doses
        self.fields["drug"].widget = widget
        self.fields["drug"].choices = choices

    def clean(self):
        data = super().clean()
        if data.get("drug"):
            data["drug"] = Drug.objects.filter(pk=data["drug"]).first()
            if data["drug"] is None:
                self.add_error("drug", _("Choose the drug."))
            elif not data.get("dose"):
                data["dose"] = data["drug"].group.dose
        return data


LineFormSet = formset_factory(LineForm, extra=2)


class InstructionChoiceForm(StyledForm):
    language = forms.ChoiceField(label=_("language"), choices=[("ar", "العربية"), ("en", "English")], required=False)
