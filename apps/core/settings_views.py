"""Settings the owner changes without touching the code: clinic options, the lists
used everywhere (implant companies, treatments, rooms, drugs...), people and their access."""

import secrets

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Q
from django.forms import inlineformset_factory, modelform_factory
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.charting.models import PhotoType
from apps.clinical.models import Lab, LabWorkType, TreatmentStepType
from apps.dentists.models import Dentist
from apps.billing.models import FawryMachine, Service
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
from .roles import HEAD_CIA, LAB_DESIGNER, LAB_HEAD, LAB_MANAGER, LAB_SECRETARY, OWNER, ROLE_CHOICES

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
    "places": (gettext_lazy("Places (CIA, CIC, El Khadem...): name, look, hours and rooms"), Branch,
               ["name_ar", "name_en", "file_prefix", "tagline", "phone", "address", "email", "theme", "color", "logo",
                "opens_at", "closes_at", "closed_days", "rooms_shared", "has_cbct", "sort_order", "is_active"],
               ["name_ar", "name_en", "file_prefix", "phone", "theme", "rooms_shared"],
               None, gettext_lazy("Reception")),
    "rooms": (gettext_lazy("Rooms"), Room, ["name", "name_en", "branch", "sort_order", "is_active", "notes"],
              ["name", "name_en"], None, gettext_lazy("Reception")),
    "referral_sources": (gettext_lazy("How patients heard about us"), ReferralSource,
                         ["name_ar", "name_en", "asks_for_patient", "sort_order", "is_active"], ["name_ar", "name_en"],
                         None, gettext_lazy("Reception")),
    "medical_conditions": (gettext_lazy("Medical conditions"), MedicalCondition,
                           ["name_ar", "name_en", "is_alert", "sort_order", "is_active"], ["name_ar", "name_en"], None,
                           gettext_lazy("Reception")),
    "services": (gettext_lazy("Paid services and prices"), Service, ["name_ar", "name_en", "price", "cost", "branch",
                                                                   "quick_button", "sort_order", "is_active"],
                 ["name_ar", "name_en", "price", "cost", "branch", "quick_button"], None,
                 gettext_lazy("Reception")),
    "fawry_machines": (gettext_lazy("Fawry machines"), FawryMachine, ["name", "terminal_id", "notes", "sort_order",
                                                                      "is_active"], ["name", "terminal_id"], None,
                       gettext_lazy("Reception")),
    "out_reasons": (gettext_lazy("Reasons for a patient being out"), OutReason, LOOKUP, ["name_ar", "name_en"], None,
                    gettext_lazy("Reception")),
    "labs": (gettext_lazy("Labs"), Lab, ["name", "name_en", "branch", "phone", "contact_person", "is_active"],
             ["name", "name_en", "phone"], None, gettext_lazy("Lab")),
    "lab_work_types": (gettext_lazy("Lab work types"), LabWorkType,
                       ["name_ar", "name_en", "category", "unit", "default_days", "sort_order", "is_active"],
                       ["name_ar", "name_en", "category", "unit", "default_days"], None,
                       gettext_lazy("Lab")),
    "purchase_categories": (gettext_lazy("Purchase categories"), PurchaseCategory,
                            ["name_ar", "name_en", "kind", "sort_order", "is_active"], ["name_ar", "name_en", "kind"],
                            None, gettext_lazy("Stock and purchases")),
    "stock_categories": (gettext_lazy("Stock categories"), StockCategory, ["group", "lab_blocks"] + LOOKUP,
                         ["group", "name_ar", "name_en"], None, gettext_lazy("Stock and purchases")),
    "whatsapp": (gettext_lazy("WhatsApp messages"), MessageTemplate, ["kind", "text", "is_active"], ["kind", "text"],
                 None, gettext_lazy("Reception")),
}


LAB_ROLES = (LAB_HEAD, LAB_MANAGER, LAB_DESIGNER, LAB_SECRETARY)
CLINIC_ROLES = tuple(code for code, _label in ROLE_CHOICES if code not in LAB_ROLES)
LIST_ICONS = {"Clinical": "bi-clipboard2-pulse", "Prescriptions": "bi-capsule", "Reception": "bi-display",
              "Lab": "bi-dental-lab", "Stock and purchases": "bi-boxes"}


def setting_places():
    """The places in the order used everywhere: the clinics, then the lab."""
    places = Branch.objects.filter(is_active=True).order_by("sort_order", "pk")
    return sorted(places, key=lambda place: place.kind == Branch.Kind.LAB)


def people_at(place, users=None):
    """The logins of the people who work at ``place`` (round 14): at a clinic, those who have it as their place or
    ticked; at the lab, everyone with a lab role or on the lab's staff, e.g. a CIA dentist who designs for the lab
    (before, such a dentist could not be found under the lab)."""
    users = users if users is not None else get_user_model().objects.all()
    if place.kind == Branch.Kind.LAB:
        return users.filter(Q(groups__name__in=LAB_ROLES) | Q(lab_worker__isnull=False)).distinct()
    here = Q(profile__branch=place) | Q(profile__places=place) | Q(groups__name=OWNER)
    if place == Branch.default():
        here |= Q(profile__isnull=True) | Q(profile__branch__isnull=True)
    return users.filter(here, groups__name__in=CLINIC_ROLES).distinct()


def place_cards():
    """Settings by place (round 14): for each place its people, doctors, rooms and services, its look and hours; for
    the lab its staff, prices and work types."""
    from apps.lab.models import LabWorker

    users_url = reverse("settings:users")
    cards = []
    for place in setting_places():
        items = [("bi-people", _("People and logins"), people_at(place).count(), f"{users_url}?place={place.code}")]
        if place.kind == Branch.Kind.LAB:
            items += [
                ("bi-person-gear", _("Lab staff and their steps"), LabWorker.objects.filter(is_active=True).count(),
                 reverse("lab:staff")),
                ("bi-list-check", _("Lab work types"), LabWorkType.objects.count(),
                 reverse("settings:list", args=["lab_work_types"])),
                ("bi-tags", _("Lab prices"), None, reverse("lab:prices")),
                ("bi-sliders", _("Lab options"), None, reverse("lab:settings")),
            ]
        else:
            items += [
                ("bi-person-badge", _("Doctors"), Dentist.objects.working_at(place).filter(is_active=True).count(),
                 reverse("dentists:list")),
                ("bi-door-open", _("Rooms"), Room.objects.filter(branch=place).count(),
                 f"{reverse('settings:list', args=['rooms'])}?place={place.code}"),
                ("bi-tags", _("Services only here"), Service.objects.filter(branch=place).count(),
                 f"{reverse('settings:list', args=['services'])}?place={place.code}"),
            ]
        items.append(("bi-palette", _("Name, look and opening hours"), None,
                      reverse("settings:list_update", args=["places", place.pk])))
        cards.append({"place": place, "items": items})
    return cards


@role_required(OWNER, HEAD_CIA)
def settings_home(request):
    """Round 14: the main settings, then each place on its own card, then the lists in groups that can be searched
    (it was one long column of lists)."""
    from .roles import has_role

    groups = {}
    for key, (title, model, _fields, _cols, _inline, group) in LISTS.items():
        groups.setdefault(group, []).append((key, title, model.objects.count()))
    from django.utils import translation

    def icon(group):
        with translation.override("en"):
            return LIST_ICONS.get(str(group), "bi-list-ul")

    list_groups = [(group, icon(group), items) for group, items in groups.items()]
    return render(request, "settings/home.html", {
        "list_groups": list_groups, "place_cards": place_cards() if has_role(request.user, OWNER) else [],
    })


# ------------------------------------------------------------ lists
def _entry(key):
    entry = LISTS.get(key)
    if entry is None:
        raise Http404
    return entry


# Lists whose rows are fixed: they can be changed but not added from here (a new place needs its code).
NO_ADD = {"places"}


@role_required(OWNER, HEAD_CIA)
def list_rows(request, key):
    title, model, _fields, columns, _inline, _group = _entry(key)
    rows = model.objects.all()
    # Lists that belong to a place (rooms, services, labs) can be shown for one place (round 14).
    by_place = any(field.name == "branch" for field in model._meta.fields)
    places = [p for p in setting_places() if p.kind != Branch.Kind.LAB] if by_place else []
    place = next((p for p in places if p.code == request.GET.get("place")), None)
    if place is not None:
        rows = rows.filter(branch=place)
    headers = [model._meta.get_field(name).verbose_name for name in columns]
    cells = []
    for obj in rows:
        values = []
        for name in columns:
            display = getattr(obj, f"get_{name}_display", None)
            values.append(display() if display else getattr(obj, name))
        cells.append((obj, values, getattr(obj, "is_active", True)))
    return render(request, "settings/list.html", {"key": key, "title": title, "headers": headers, "rows": cells,
                                                  "can_add": key not in NO_ADD, "places": places, "place": place})


@role_required(OWNER, HEAD_CIA)
def list_edit(request, key, pk=None):
    title, model, fields, _columns, inline, _group = _entry(key)
    if pk is None and key in NO_ADD:
        raise Http404
    obj = get_object_or_404(model, pk=pk) if pk else None
    form_class = modelform_factory(model, form=StyledModelForm, fields=fields,
                                   widgets={"closed_days": WeekdaysWidget} if "closed_days" in fields else None)
    form = form_class(request.POST or None, request.FILES or None, instance=obj)
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
        fields = ["name_ar", "name_en", "phone", "address", "has_cbct"]


class OptionsForm(StyledModelForm):
    class Meta:
        model = ClinicSettings
        fields = ["day_start", "day_end", "default_appointment_minutes", "surgery_days", "late_threshold_minutes",
                  "complaint_follow_up_days", "stock_expiry_days", "reminder_days_before", "whatsapp_country_code",
                  "dicom_email", "fawry_fee_percent", "hba1c_limit", "glucose_limit", "systolic_limit",
                  "diastolic_limit", "follow_up_sinus_days", "follow_up_graft_days", "follow_up_days",
                  "idle_logout_minutes", "force_strong_passwords", "one_device_per_login"]
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
    places = forms.ModelMultipleChoiceField(
        label=gettext_lazy("works at"), required=False, widget=forms.CheckboxSelectMultiple,
        queryset=Branch.objects.filter(is_active=True).order_by("sort_order", "pk"),
        help_text=gettext_lazy("E.g. the secretary at CIA and CIC; the lab's staff at the lab. With more than one place, "
                               "a switch in the top bar chooses where they work now. The owner works everywhere."))
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
        (gettext_lazy("Person"), ["username", "first_name", "roles", "places", "is_active", "new_password", "dentist"]),
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

    def clean_new_password(self):
        from .models import ClinicSettings
        from .security import is_easy

        password = self.cleaned_data.get("new_password", "")
        if password and ClinicSettings.get().force_strong_passwords and is_easy(password, self.user):
            raise forms.ValidationError(_("This password is too easy to guess: use at least 8 letters and numbers, "
                                          "not like the username."))
        return password

    def clean(self):
        data = super().clean()
        if bool(data.get("access_start")) != bool(data.get("access_end")):
            self.add_error("access_end", _("Write both hours, or neither."))
        lab_roles = {LAB_HEAD, LAB_MANAGER, LAB_DESIGNER, LAB_SECRETARY}
        if any(place.kind == Branch.Kind.LAB for place in data.get("places") or []) and \
                not lab_roles & set(data.get("roles") or []):
            self.add_error("places", _("The lab is for the lab's roles (head, manager, designer, secretary)."))
        dentist = data.get("dentist")
        if dentist and dentist.user_id and (self.user is None or dentist.user_id != self.user.pk):
            self.add_error("dentist", _("This dentist already has a login."))
        return data


@role_required(OWNER)
def user_list(request):
    everyone = get_user_model().objects.all()
    places = setting_places()
    place = next((p for p in places if p.code == request.GET.get("place")), None)
    users = people_at(place, everyone) if place is not None else everyone
    users = (users.prefetch_related("groups", "area_access", "profile__places").select_related("profile", "profile__branch")
             .order_by("-is_active", "first_name"))
    labels = dict(ROLE_CHOICES)
    lab = next((p for p in places if p.kind == Branch.Kind.LAB), None)
    with_lab = set(people_at(lab, everyone).values_list("pk", flat=True)) if lab else set()
    rows = []
    for u in users:
        profile = getattr(u, "profile", None)
        works_at = []  # the places the person works at, shown as badges (round 14)
        if profile is not None:
            works_at = list(profile.places.all()) or ([profile.branch] if profile.branch else [])
        if u.pk in with_lab and lab is not None:
            works_at = [p for p in works_at if p.kind != Branch.Kind.LAB] + [lab]
            if not any(g.name in CLINIC_ROLES for g in u.groups.all()):
                works_at = [lab]
        rows.append((u, [labels.get(g.name, g.name) for g in u.groups.all()], profile,
                     [(AREA_LABELS.get(rule.area, rule.area), rule.get_level_display()) for rule in u.area_access.all()],
                     works_at))
    from .passwords import pending

    tabs = [(p, people_at(p, everyone).count()) for p in places]
    return render(request, "settings/users.html", {"rows": rows, "password_requests": pending(),
                                                   "given_password": request.session.pop("given_password", None),
                                                   "place_tabs": tabs, "place": place, "everyone": everyone.count()})


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
            "places": list(profile.places.all()) or [p for p in [profile.branch or Branch.default()] if p],
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
            if data["new_password"]:
                from .models import SecurityEvent
                from .security import is_easy, log_event

                profile.weak_password = is_easy(data["new_password"], target)
                log_event(SecurityEvent.Kind.PASSWORD_GIVEN, request, user=target,
                          details=_("set in People and logins by %(owner)s") % {"owner": request.user.get_username()})
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
            places = list(data["places"])
            if places and (profile.branch is None or profile.branch not in places):
                profile.branch = places[0]  # their main place: the one they start in
            profile.branch = profile.branch or Branch.default()
            profile.save()
            profile.places.set(places)
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


ACCESS_SECTIONS = [
    (gettext_lazy("Patients and treatment"), ["patients", "calls", "schedule", "charts", "treatments", "lab",
                                               "surgery", "prescriptions", "complaints", "specialists"]),
    (gettext_lazy("Money, stock and people"), ["billing", "purchases", "stock", "dentists", "academy", "clinics"]),
    (gettext_lazy("Reports and statistics"), ["reports", "finder"]),
    (gettext_lazy("Dental lab"), ["dental_lab"]),
]


@role_required(OWNER)
def role_access(request):
    from apps.patients.access import ALL_PARTS, FILE_PARTS

    roles = [(code, label) for code, label in ROLE_CHOICES if code != OWNER]
    current = {(a.role, a.area): a.level for a in AreaAccess.objects.all()}
    options = ClinicSettings.get()
    if request.method == "POST" and request.POST.get("what") == "file_parts":
        options.reception_sees = [code for code in request.POST.getlist("parts") if code in ALL_PARTS]
        options.save(update_fields=["reception_sees"])
        messages.success(request, _("Saved: the reception now sees these parts of a patient's file."))
        return redirect(reverse("settings:access") + "#reception-file")
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
    # Round 14: one role at a time, the parts of the system in groups, three choices for each (it was one wide table
    # of drop-down lists that did not fit on the screen).
    labels = {code: label for code, label, _prefixes in AREAS}
    lab_roles = {LAB_HEAD, LAB_MANAGER, LAB_DESIGNER, LAB_SECRETARY}
    panels = []
    for role, role_label in roles:
        sections = [(title, [(area, labels[area], current.get((role, area), AreaAccess.Level.FULL))
                             for area in areas if area in labels]) for title, areas in ACCESS_SECTIONS]
        panels.append({
            "code": role, "label": role_label, "lab": role in lab_roles, "sections": sections,
            "limits": sum(1 for _title, rows in sections for _a, _l, level in rows if level != AreaAccess.Level.FULL),
        })
    return render(request, "settings/access.html", {
        "panels": panels, "levels": AreaAccess.Level.choices,
        "file_parts": FILE_PARTS, "reception_sees": set(options.reception_sees or ()),
    })


# ------------------------------------------------------------ backup and export
@role_required(OWNER)
def backup_home(request):
    from datetime import timedelta

    from .backup import backup_dir, backup_now, backup_status, files_backup_dir, list_backups
    from .models import BackupRun

    from . import photo_folder

    checked, findings = "", None
    if request.method == "POST" and "check_folder" in request.POST:
        # Where the photos are kept: another folder is checked here, the photos move with move_photos (round 15).
        checked = request.POST.get("check_folder", "").strip()
        findings = photo_folder.check(checked)
    elif request.method == "POST":
        running = BackupRun.objects.filter(kind=BackupRun.Kind.DATABASE, finished_at=None,
                                           started_at__gte=timezone.now() - timedelta(minutes=30)).exists()
        if running:
            messages.info(request, _("A backup is being made now. It will appear below when it is ready."))
            return redirect("settings:backup")
        try:
            path = backup_now()
        except Exception as error:  # disk full, folder not writable…: say it, the data is untouched
            messages.error(request, _("The backup could not be made: %(error)s") % {"error": error})
        else:
            if path is None:
                messages.info(request, _("The backup is being made (there is a lot of data). It will appear below "
                                         "in a few minutes: open this page again then."))
            else:
                messages.success(request, _("Backup made: %(name)s. Download it and keep a copy outside this PC.")
                                 % {"name": path.name})
        return redirect("settings:backup")
    return render(request, "settings/backup.html", {
        "backups": list_backups(), "folder": backup_dir(), "files_folder": files_backup_dir(),
        "status": backup_status(), "runs": BackupRun.objects.all()[:12],
        "photos": photo_folder.current(), "checked": checked, "findings": findings,
        "folder_ok": findings is not None and all(ok for ok, _text in findings),
    })


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
