from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledForm, StyledModelForm, clean_phone_value

from .models import Dentist

CLINICIANS = (
    Dentist.Kind.CANDIDATE, Dentist.Kind.TRAINING, Dentist.Kind.FULLTIME,
    Dentist.Kind.SPECIALIST, Dentist.Kind.FREELANCER, Dentist.Kind.SUPERVISOR,
)


class DentistChoiceField(forms.ModelChoiceField):
    """Drop-down of active dentists, labelled with their type or batch."""

    def __init__(self, kinds=CLINICIANS, **kwargs):
        queryset = Dentist.objects.active().of_kind(*kinds).select_related("candidate")
        super().__init__(queryset=queryset, **kwargs)

    def label_from_instance(self, obj):
        return obj.label


class DentistForm(StyledModelForm):
    class Meta:
        model = Dentist
        fields = ["full_name", "name_ar", "kind", "phone", "branch", "user", "is_active", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        taken = Dentist.objects.exclude(pk=self.instance.pk).exclude(user=None).values_list("user_id", flat=True)
        self.fields["user"].queryset = get_user_model().objects.filter(is_active=True).exclude(pk__in=taken)
        self.fields["user"].help_text = _("The login this dentist uses, so the system knows which work is theirs.")
        if self.instance.pk and self.instance.kind == Dentist.Kind.CANDIDATE:
            # Candidates are managed from the academy file and do not log in.
            self.fields["kind"].disabled = True
            self.fields["full_name"].disabled = True
            del self.fields["user"]
        else:
            self.fields["kind"].choices = [c for c in Dentist.Kind.choices if c[0] != Dentist.Kind.CANDIDATE]

    def clean_phone(self):
        return clean_phone_value(self.cleaned_data.get("phone"), mobile_only=False)

    def clean(self):
        data = super().clean()
        if data.get("user") and data.get("kind") not in Dentist.LOGIN_KINDS:
            self.add_error("user", _("Only CIA dentists log in. Candidates, training dentists and supervisors are "
                                     "chosen by name on the forms."))
        return data


class DentistFilterForm(StyledForm):
    q = forms.CharField(label=_("Search"), required=False)
    kind = forms.ChoiceField(label=_("type"), required=False, choices=[("", _("All"))] + list(Dentist.Kind.choices))
    active = forms.ChoiceField(
        label=_("status"), required=False,
        choices=[("1", _("Working now")), ("", _("All")), ("0", _("Left"))],
    )
