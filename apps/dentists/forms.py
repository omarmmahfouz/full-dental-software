from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledForm, StyledModelForm, clean_phone_value

from apps.core.models import Branch

from .models import Dentist

CLINICIANS = (
    Dentist.Kind.CANDIDATE, Dentist.Kind.TRAINING, Dentist.Kind.FULLTIME,
    Dentist.Kind.SPECIALIST, Dentist.Kind.FREELANCER, Dentist.Kind.SUPERVISOR,
)


# Round 15: the drop lists show the people in groups (the juniors, the candidates of each batch, the supervisors...)
# and leave out the candidates whose course has ended and the people taken off the lists in Settings.
GROUP_ORDER = (Dentist.Kind.FULLTIME, Dentist.Kind.CANDIDATE, Dentist.Kind.TRAINING, Dentist.Kind.SPECIALIST,
               Dentist.Kind.FREELANCER, Dentist.Kind.SUPERVISOR)
GROUP_NAMES = {
    Dentist.Kind.FULLTIME: _("CIA junior dentists"), Dentist.Kind.CANDIDATE: _("Candidates"),
    Dentist.Kind.TRAINING: _("Training dentists"), Dentist.Kind.SPECIALIST: _("Specialists"),
    Dentist.Kind.FREELANCER: _("Freelance dentists"), Dentist.Kind.SUPERVISOR: _("Supervisors"),
}


def list_facts():
    """{"hidden": dentists left out of the drop lists, "batch": {candidate's dentist: (label, number)}}, read once
    for the page."""
    from apps.academy.models import Enrollment
    from apps.core.models import _page_cache

    cache = _page_cache.get()
    if cache is not None and "dentist_lists" in cache:
        return cache["dentist_lists"]
    hidden = set(Dentist.objects.filter(show_in_lists=False).values_list("pk", flat=True))
    batches, studying = {}, set()
    for row in Enrollment.objects.filter(candidate__dentist__isnull=False).order_by("enrolled_on", "pk").values(
            "candidate__dentist__id", "status", "course__code", "course__batch_number", "course__kind"):
        pk = row["candidate__dentist__id"]
        if row["status"] == Enrollment.Status.ACTIVE:
            studying.add(pk)
        elif pk in studying:
            continue  # the course he studies now names his batch
        if row["course__kind"] == "private":
            label = _("Private · %(code)s") % {"code": row["course__code"]}
        elif row["course__batch_number"]:
            label = _("Batch %(n)s") % {"n": row["course__batch_number"]}
        else:
            label = row["course__code"]
        batches[pk] = (str(label), row["course__batch_number"] or 0)
    hidden |= set(Dentist.objects.filter(kind=Dentist.Kind.CANDIDATE).exclude(pk__in=studying)
                  .values_list("pk", flat=True))
    facts = {"hidden": hidden, "batch": batches}
    if cache is not None:
        cache["dentist_lists"] = facts
    return facts


class DentistSelect(forms.Select):
    """The options in groups by kind (the candidates by batch), without the people left out of the lists unless
    one of them is the value already chosen."""

    everyone = False

    def optgroups(self, name, value, attrs=None):
        facts = list_facts()
        buckets, loose, index = {}, [], 0
        for option_value, option_label in self.choices:
            instance = getattr(option_value, "instance", None)
            option_value = "" if option_value is None else option_value
            selected = str(option_value) in value
            if instance is not None and not selected and not self.everyone and instance.pk in facts["hidden"]:
                continue
            option = self.create_option(name, option_value, option_label, selected, index, attrs=attrs)
            index += 1
            if instance is None:
                loose.append(option)
                continue
            if instance.kind == Dentist.Kind.CANDIDATE and instance.pk in facts["batch"]:
                label, number = facts["batch"][instance.pk]
                key = (GROUP_ORDER.index(instance.kind), -number, label)
                title = f"{GROUP_NAMES[instance.kind]} · {label}"
            else:
                key = (GROUP_ORDER.index(instance.kind) if instance.kind in GROUP_ORDER else 99, 0, "")
                title = str(GROUP_NAMES.get(instance.kind, instance.get_kind_display()))
            buckets.setdefault(key, (title, []))[1].append(option)
        groups = [(None, [option], i) for i, option in enumerate(loose)]
        if len(buckets) == 1:
            groups += [(None, [option], len(groups) + i) for i, option in enumerate(next(iter(buckets.values()))[1])]
        else:
            groups += [(title, options, len(groups) + i) for i, (_key, (title, options)) in
                       enumerate(sorted(buckets.items()))]
        return groups


class DentistChoiceField(forms.ModelChoiceField):
    """Drop-down of active dentists, labelled with their type or batch, in groups (round 15). ``everyone=True`` for
    the filters of the finders and lists: the people left out of the forms are still offered there."""

    widget = DentistSelect

    def __init__(self, kinds=CLINICIANS, everyone=False, **kwargs):
        queryset = Dentist.objects.active().of_kind(*kinds) if not everyone else \
            Dentist.objects.of_kind(*kinds)
        super().__init__(queryset=queryset, **kwargs)
        self.widget.everyone = everyone

    def label_from_instance(self, obj):
        if obj.kind == Dentist.Kind.CANDIDATE:
            batch = list_facts()["batch"].get(obj.pk)
            return f"{obj} — {batch[0]}" if batch else str(obj)
        if obj.specialty and obj.specialty != Dentist.Specialty.GENERAL:
            return f"{obj} — {obj.get_specialty_display()}"
        if obj.kind == Dentist.Kind.FULLTIME and obj.work_time:
            return f"{obj} — {obj.get_work_time_display()}"
        return str(obj)


class DentistForm(StyledModelForm):
    class Meta:
        model = Dentist
        fields = ["full_name", "name_ar", "kind", "work_time", "specialty", "title", "phone", "places", "user",
                  "is_active", "show_in_lists", "notes"]
        widgets = {"places": forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["places"].queryset = Branch.objects.filter(is_active=True).exclude(
            kind=Branch.Kind.LAB).order_by("sort_order", "pk")
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
