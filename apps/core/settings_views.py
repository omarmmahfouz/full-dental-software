"""Settings the owner changes without touching the code: clinic options, the lists
used everywhere (implant companies, treatments, rooms, drugs...), people and their access."""

import secrets

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.forms import inlineformset_factory, modelform_factory
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.charting.models import PhotoType
from apps.clinical.models import Lab, LabWorkType, TreatmentStepType
from apps.dentists.models import Dentist
from apps.billing.models import Service
from apps.patients.models import MedicalCondition, OutReason, ReferralSource
from apps.prescriptions.models import (
    Drug,
    DrugGroup,
    InstructionSheet,
    PrescriptionTemplate,
    PrescriptionTemplateLine,
)
from apps.purchasing.models import PurchaseCategory
from apps.scheduling.models import MessageTemplate, Room
from apps.stock.models import StockCategory
from apps.surgery.models import ImplantSystem

from .access import AREA_LABELS, AREAS
from .forms import BootstrapFormMixin, StyledForm, StyledModelForm
from .widgets import TimeSelect, WeekdaysWidget
from .mixins import role_required
from .models import AreaAccess, Branch, ClinicSettings, PersonAreaAccess, UserProfile
from .roles import HEAD_CIA, OWNER, ROLE_CHOICES

LOOKUP = ["name_ar", "name_en", "sort_order", "is_active"]

# key: (title, model, form fields, columns, inline (model, fields) or None, group)
LISTS = {
    "implant_systems": (gettext_lazy("Implant companies and types"), ImplantSystem, ["company", "line", "is_active"],
                        ["company", "line"], None, gettext_lazy("Clinical")),
    "treatment_types": (gettext_lazy("Treatments"), TreatmentStepType,
                        ["name_ar", "name_en", "category", "description_ar", "chart_effect", "surgery_procedure",
                         "default_material", "sort_order", "is_active"], ["name_en", "name_ar", "category",
                                                                          "description_ar"], None,
                        gettext_lazy("Clinical")),
    "photo_types": (gettext_lazy("Photo checklist"), PhotoType, ["stage", "name_ar", "name_en", "optional", "sort_order",
                                                                 "is_active"], ["stage", "name_en"], None,
                    gettext_lazy("Clinical")),
    "drug_groups": (gettext_lazy("Drug groups (interchangeable drugs)"), DrugGroup,
                    ["name_ar", "name_en", "kind", "dose", "sort_order", "is_active"], ["name_en", "dose"],
                    (Drug, ["name", "preferred", "is_active"]), gettext_lazy("Prescriptions")),
    "prescription_templates": (gettext_lazy("Ready prescriptions"), PrescriptionTemplate,
                               ["name_ar", "name_en", "procedures", "for_penicillin_allergy", "sort_order", "is_active"],
                               ["name_en", "procedures"], (PrescriptionTemplateLine, ["group", "dose", "sort_order"]),
                               gettext_lazy("Prescriptions")),
    "instruction_sheets": (gettext_lazy("Post-op instruction sheets"), InstructionSheet,
                           ["name_ar", "name_en", "procedures", "body_ar", "body_en", "sort_order", "is_active"],
                           ["name_en", "procedures"], None, gettext_lazy("Prescriptions")),
    "rooms": (gettext_lazy("Rooms"), Room, ["name", "name_en", "branch", "sort_order", "is_active", "notes"],
              ["name", "name_en"], None, gettext_lazy("Reception")),
    "referral_sources": (gettext_lazy("How patients heard about us"), ReferralSource,
                         ["name_ar", "name_en", "asks_for_patient", "sort_order", "is_active"], ["name_ar", "name_en"],
                         None, gettext_lazy("Reception")),
    "medical_conditions": (gettext_lazy("Medical conditions"), MedicalCondition,
                           ["name_ar", "name_en", "is_alert", "sort_order", "is_active"], ["name_ar", "name_en"], None,
                           gettext_lazy("Reception")),
    "services": (gettext_lazy("Paid services and prices"), Service, ["name_ar", "name_en", "price", "quick_button",
                                                                   "sort_order", "is_active"],
                 ["name_ar", "name_en", "price", "quick_button"], None,
                 gettext_lazy("Reception")),
    "out_reasons": (gettext_lazy("Reasons for a patient being out"), OutReason, LOOKUP, ["name_ar", "name_en"], None,
                    gettext_lazy("Reception")),
    "labs": (gettext_lazy("Labs"), Lab, ["name", "name_en", "branch", "phone", "contact_person", "is_active"],
             ["name", "name_en", "phone"], None, gettext_lazy("Lab")),
    "lab_work_types": (gettext_lazy("Lab work types"), LabWorkType,
                       ["name_ar", "name_en", "default_days", "sort_order", "is_active"],
                       ["name_ar", "name_en", "default_days"], None,
                       gettext_lazy("Lab")),
    "purchase_categories": (gettext_lazy("Purchase categories"), PurchaseCategory,
                            ["name_ar", "name_en", "kind", "sort_order", "is_active"], ["name_ar", "name_en", "kind"],
                            None, gettext_lazy("Stock and purchases")),
    "stock_categories": (gettext_lazy("Stock categories"), StockCategory, LOOKUP, ["name_ar", "name_en"], None,
                         gettext_lazy("Stock and purchases")),
    "whatsapp": (gettext_lazy("WhatsApp messages"), MessageTemplate, ["kind", "text", "is_active"], ["kind", "text"],
                 None, gettext_lazy("Reception")),
}


@role_required(OWNER, HEAD_CIA)
def settings_home(request):
    groups = {}
    for key, (title, model, _fields, _cols, _inline, group) in LISTS.items():
        groups.setdefault(str(group), []).append((key, title, model.objects.count()))
    return render(request, "settings/home.html", {"list_groups": groups.items()})


# ------------------------------------------------------------ lists
def _entry(key):
    entry = LISTS.get(key)
    if entry is None:
        raise Http404
    return entry


@role_required(OWNER, HEAD_CIA)
def list_rows(request, key):
    title, model, _fields, columns, _inline, _group = _entry(key)
    rows = model.objects.all()
    headers = [model._meta.get_field(name).verbose_name for name in columns]
    cells = []
    for obj in rows:
        values = []
        for name in columns:
            display = getattr(obj, f"get_{name}_display", None)
            values.append(display() if display else getattr(obj, name))
        cells.append((obj, values, getattr(obj, "is_active", True)))
    return render(request, "settings/list.html", {"key": key, "title": title, "headers": headers, "rows": cells})


@role_required(OWNER, HEAD_CIA)
def list_edit(request, key, pk=None):
    title, model, fields, _columns, inline, _group = _entry(key)
    obj = get_object_or_404(model, pk=pk) if pk else None
    form_class = modelform_factory(model, form=StyledModelForm, fields=fields)
    form = form_class(request.POST or None, instance=obj)
    formset = None
    if inline:
        inline_model, inline_fields = inline
        formset_class = inlineformset_factory(model, inline_model, form=_InlineForm, fields=inline_fields, extra=3,
                                              can_delete=True)
        formset = formset_class(request.POST or None, instance=obj or model(), prefix="rows")
    if request.method == "POST" and form.is_valid() and (formset is None or formset.is_valid()):
        with transaction.atomic():
            saved = form.save()
            if formset is not None:
                formset.instance = saved
                formset.save()
        messages.success(request, _("Saved."))
        return redirect("settings:list", key=key)
    return render(request, "settings/list_edit.html", {
        "key": key, "title": title, "form": form, "formset": formset, "object": obj,
    })


class _InlineForm(BootstrapFormMixin, forms.ModelForm):
    pass


# ------------------------------------------------------------ clinic options
class BranchForm(StyledModelForm):
    class Meta:
        model = Branch
        fields = ["name_ar", "name_en", "phone", "address"]


class OptionsForm(StyledModelForm):
    class Meta:
        model = ClinicSettings
        fields = ["day_start", "day_end", "default_appointment_minutes", "surgery_days", "late_threshold_minutes",
                  "complaint_follow_up_days", "stock_expiry_days", "reminder_days_before", "whatsapp_country_code",
                  "dicom_email", "fawry_fee_percent"]
        widgets = {"surgery_days": WeekdaysWidget}


@role_required(OWNER)
def options_edit(request):
    branch = Branch.default()
    form = OptionsForm(request.POST or None, instance=ClinicSettings.get(), prefix="o")
    branch_form = BranchForm(request.POST or None, instance=branch, prefix="b")
    if request.method == "POST" and form.is_valid() and branch_form.is_valid():
        form.save()
        branch_form.save()
        messages.success(request, _("Clinic options saved."))
        return redirect("settings:home")
    return render(request, "settings/options.html", {"form": form, "branch_form": branch_form})


# ------------------------------------------------------------ people and access
class UserForm(StyledForm):
    username = forms.CharField(label=gettext_lazy("username"), max_length=150)
    first_name = forms.CharField(label=gettext_lazy("name"), max_length=150)
    roles = forms.MultipleChoiceField(label=gettext_lazy("roles"), choices=ROLE_CHOICES, required=False,
                                      widget=forms.CheckboxSelectMultiple)
    is_active = forms.BooleanField(label=gettext_lazy("can log in"), required=False, initial=True)
    new_password = forms.CharField(label=gettext_lazy("new password"), required=False,
                                   help_text=gettext_lazy("Leave empty to keep the password (a new person gets one made up)."))
    dentist = forms.ModelChoiceField(label=gettext_lazy("dentist record"), required=False,
                                     queryset=Dentist.objects.filter(kind__in=Dentist.LOGIN_KINDS),
                                     help_text=gettext_lazy("For CIA dentists: the dentist this login belongs to."))
    read_only = forms.BooleanField(label=gettext_lazy("read only everywhere"), required=False)
    access_from = forms.DateField(label=gettext_lazy("access starts on"), required=False)
    access_until = forms.DateField(label=gettext_lazy("access ends on"), required=False)
    access_days = forms.MultipleChoiceField(label=gettext_lazy("days allowed"), choices=UserProfile.WEEKDAYS,
                                            required=False, widget=forms.CheckboxSelectMultiple,
                                            help_text=gettext_lazy("None ticked = every day."))
    access_start = forms.TimeField(label=gettext_lazy("from hour"), required=False,
                                   widget=TimeSelect())
    access_end = forms.TimeField(label=gettext_lazy("to hour"), required=False,
                                 widget=TimeSelect())

    fieldsets = [
        (gettext_lazy("Person"), ["username", "first_name", "roles", "is_active", "new_password", "dentist"]),
        (gettext_lazy("Access limits"), ["read_only", "access_from", "access_until", "access_days", "access_start",
                                         "access_end"]),
    ]

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        for name in ("username", "first_name", "new_password", "dentist", "access_from", "access_until",
                     "access_start", "access_end"):
            self.fields[name].col = "col-md-6"
        choices = [("", gettext_lazy("As the role"))] + list(AreaAccess.Level.choices)
        for code, label, _prefixes in AREAS:
            field = forms.ChoiceField(label=label, choices=choices, required=False)
            field.widget.attrs["class"] = "form-select form-select-sm"
            field.col = "col-sm-6 col-lg-4"
            self.fields[f"area__{code}"] = field
        self.fieldsets = [*self.fieldsets, (gettext_lazy("Parts of the system for this person"),
                                            [f"area__{code}" for code, _label, _prefixes in AREAS])]

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        others = get_user_model().objects.filter(username=username)
        if self.user is not None:
            others = others.exclude(pk=self.user.pk)
        if others.exists():
            raise forms.ValidationError(_("This username is taken."))
        return username

    def clean(self):
        data = super().clean()
        if bool(data.get("access_start")) != bool(data.get("access_end")):
            self.add_error("access_end", _("Write both hours, or neither."))
        dentist = data.get("dentist")
        if dentist and dentist.user_id and (self.user is None or dentist.user_id != self.user.pk):
            self.add_error("dentist", _("This dentist already has a login."))
        return data


@role_required(OWNER)
def user_list(request):
    users = (get_user_model().objects.prefetch_related("groups", "area_access").select_related("profile")
             .order_by("-is_active", "first_name"))
    labels = dict(ROLE_CHOICES)
    rows = [(u, [labels.get(g.name, g.name) for g in u.groups.all()], getattr(u, "profile", None),
             [(AREA_LABELS.get(rule.area, rule.area), rule.get_level_display()) for rule in u.area_access.all()])
            for u in users]
    return render(request, "settings/users.html", {"rows": rows})


@role_required(OWNER)
def user_edit(request, pk=None):
    User = get_user_model()
    target = get_object_or_404(User, pk=pk) if pk else None
    profile = UserProfile.objects.get_or_create(user=target)[0] if target else None
    initial = {}
    if target is not None:
        initial = {
            "username": target.username, "first_name": target.first_name, "is_active": target.is_active,
            "roles": list(target.groups.values_list("name", flat=True)), "dentist": getattr(target, "dentist", None),
            "read_only": profile.read_only, "access_from": profile.access_from, "access_until": profile.access_until,
            "access_days": [d for d in profile.access_days.split(",") if d], "access_start": profile.access_start,
            "access_end": profile.access_end,
            **{f"area__{rule.area}": rule.level for rule in PersonAreaAccess.objects.filter(user=target)},
        }
    form = UserForm(request.POST or None, user=target, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        password = data["new_password"]
        with transaction.atomic():
            if target is None:
                password = password or secrets.token_urlsafe(6)
                target = User.objects.create_user(data["username"], password=password)
                profile = UserProfile.objects.get_or_create(user=target)[0]
            elif password:
                target.set_password(password)
            if target.pk == request.user.pk and OWNER not in data["roles"] and not target.is_superuser:
                data["roles"] = [*data["roles"], OWNER]  # the owner cannot remove their own access
            target.username, target.first_name = data["username"], data["first_name"]
            target.is_active = data["is_active"] or target.pk == request.user.pk
            target.save()
            target.groups.set(Group.objects.filter(name__in=data["roles"]))
            profile.read_only = data["read_only"]
            profile.access_from, profile.access_until = data["access_from"], data["access_until"]
            profile.access_days = ",".join(data["access_days"])
            profile.access_start, profile.access_end = data["access_start"], data["access_end"]
            profile.branch = profile.branch or Branch.default()
            profile.save()
            for code, _label, _prefixes in AREAS:
                level = data.get(f"area__{code}")
                if level:
                    PersonAreaAccess.objects.update_or_create(user=target, area=code, defaults={"level": level})
                else:
                    PersonAreaAccess.objects.filter(user=target, area=code).delete()
            Dentist.objects.filter(user=target).exclude(pk=getattr(data["dentist"], "pk", None)).update(user=None)
            if data["dentist"]:
                Dentist.objects.filter(pk=data["dentist"].pk).update(user=target)
        text = _("Saved.")
        if password:
            text += " " + _("Password: %(p)s (write it down now; it will not be shown again).") % {"p": password}
        messages.success(request, text)
        return redirect("settings:users")
    return render(request, "settings/user_form.html", {"form": form, "target": target})


@role_required(OWNER)
def role_access(request):
    roles = [(code, label) for code, label in ROLE_CHOICES if code != OWNER]
    current = {(a.role, a.area): a.level for a in AreaAccess.objects.all()}
    if request.method == "POST":
        with transaction.atomic():
            for role, _label in roles:
                for area, _area_label, _prefixes in AREAS:
                    level = request.POST.get(f"{role}__{area}", AreaAccess.Level.FULL)
                    if level not in AreaAccess.Level.values:
                        continue
                    if level == AreaAccess.Level.FULL:
                        AreaAccess.objects.filter(role=role, area=area).delete()
                    else:
                        AreaAccess.objects.update_or_create(role=role, area=area, defaults={"level": level})
        messages.success(request, _("Access saved."))
        return redirect("settings:access")
    rows = [(area, label, [(role, current.get((role, area), AreaAccess.Level.FULL)) for role, _l in roles])
            for area, label, _prefixes in AREAS]
    return render(request, "settings/access.html", {
        "roles": roles, "rows": rows, "levels": AreaAccess.Level.choices,
    })


# ------------------------------------------------------------ backup and export
@role_required(OWNER)
def backup_home(request):
    from .backup import backup_dir, create_backup, list_backups

    if request.method == "POST":
        try:
            path = create_backup()
        except Exception as error:  # disk full, folder not writable…: say it, the data is untouched
            messages.error(request, _("The backup could not be made: %(error)s") % {"error": error})
        else:
            messages.success(request, _("Backup made: %(name)s. Download it and keep a copy outside this PC.")
                             % {"name": path.name})
        return redirect("settings:backup")
    return render(request, "settings/backup.html", {"backups": list_backups(), "folder": backup_dir()})


@role_required(OWNER)
def backup_download(request, name):
    from .backup import list_backups

    backup = next((b for b in list_backups() if b["name"] == name), None)
    if backup is None:
        raise Http404
    return FileResponse(open(backup["path"], "rb"), as_attachment=True, filename=backup["name"])


@role_required(OWNER)
def export_excel(request):
    """All the data as one Excel workbook (a sheet per table)."""
    import tempfile

    from .backup import excel_workbook

    workbook = tempfile.TemporaryFile()
    excel_workbook(workbook)
    workbook.seek(0)
    return FileResponse(workbook, as_attachment=True,
                        filename=f"cia-all-data-{timezone.localtime():%Y-%m-%d}.xlsx")
