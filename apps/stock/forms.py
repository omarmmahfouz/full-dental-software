from django import forms
from django.forms import formset_factory
from django.utils.translation import gettext_lazy as _

from apps.core.forms import BootstrapFormMixin, StyledForm, StyledModelForm

from apps.core.models import Branch

from .models import StockCategory, StockGroup, StockItem, StockMovement


def places():
    return Branch.objects.filter(is_active=True).exclude(kind=Branch.Kind.LAB).order_by("sort_order", "pk")


def place_filter_field(label, shared_label=None):
    """All / (shared) / each place, by code."""
    choices = [("", _("All"))] + ([("shared", shared_label)] if shared_label else [])
    choices += [(p.code, f"{p.code} — {p.name}") for p in places()]
    field = forms.ChoiceField(label=label, required=False, choices=choices)
    field.widget.attrs["class"] = "form-select"
    return field


def grouped_categories(categories, empty="---------"):
    """The categories as choices under their group (dental, implants, beverage...), easy to find in the list."""
    by_group = {}
    for category in categories:
        by_group.setdefault(category.group, []).append((category.pk, str(category)))
    return [("", empty)] + [(label, by_group[code]) for code, label in StockGroup.choices if code in by_group]


class StockItemForm(StyledModelForm):
    opening_quantity = forms.DecimalField(
        label=_("quantity in stock now"), required=False, min_value=0, max_digits=10, decimal_places=2,
    )

    class Meta:
        model = StockItem
        fields = ["name", "category", "unit", "min_quantity", "location", "branch", "code", "unit_cost", "is_active",
                  "notes", "implant_system", "implant_diameter", "implant_length"]

    def __init__(self, *args, **kwargs):
        from apps.surgery.models import ImplantSystem

        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = StockCategory.objects.filter(is_active=True)
        self.fields["category"].choices = grouped_categories(self.fields["category"].queryset)
        self.fields["branch"].queryset = places()
        self.fields["branch"].empty_label = _("shared by all the places")
        self.fields["implant_system"].queryset = ImplantSystem.objects.filter(is_active=True)
        for name in ("implant_system", "implant_diameter", "implant_length"):
            self.fields[name].col = "col-md-4"
        for name in ("implant_diameter", "implant_length"):
            self.fields[name].widget.attrs.update({"step": "0.1", "min": "2", "max": "20"})
        if self.instance.pk:
            del self.fields["opening_quantity"]

    def clean(self):
        data = super().clean()
        implant = [data.get(n) for n in ("implant_system", "implant_diameter", "implant_length")]
        if any(implant) and not all(implant):
            self.add_error("implant_system", _("For an implant, choose the company and write the diameter and the length."))
        return data


class StockFilterForm(StyledForm):
    q = forms.CharField(label=_("Search"), required=False)
    category = forms.ModelChoiceField(label=_("category"), queryset=StockCategory.objects.all(), required=False,
                                      empty_label=_("All"))
    low = forms.BooleanField(label=_("low stock only"), required=False)
    expiring = forms.BooleanField(label=_("expiring soon"), required=False)
    inactive = forms.BooleanField(label=_("show items no longer used"), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["place"] = place_filter_field(_("belongs to"), _("shared by all the places"))
        self.fields["category"].choices = grouped_categories(StockCategory.objects.all(), _("All"))


class MovementForm(StyledModelForm):
    class Meta:
        model = StockMovement
        fields = ["kind", "quantity", "moved_at", "branch", "destination", "lot", "expiry_date", "unit_cost", "notes"]

    def __init__(self, *args, item=None, **kwargs):
        self.item = item
        super().__init__(*args, **kwargs)
        self.fields["quantity"].min_value = 0
        self.fields["branch"].queryset = places()
        self.fields["branch"].help_text = _("Empty = the place you work in.")
        self.fields["branch"].col = "col-md-4"
        if item is not None and item.branch_id:  # material of one place is used there only
            self.fields["branch"].queryset = places().filter(pk=item.branch_id)
        for name in ("kind", "quantity", "moved_at"):
            self.fields[name].col = "col-md-4"
        for name in ("destination", "lot", "expiry_date", "unit_cost"):
            self.fields[name].col = "col-md-3"

    def clean(self):
        data = super().clean()
        kind, quantity = data.get("kind"), data.get("quantity")
        if quantity is not None and quantity <= 0 and kind != StockMovement.Kind.COUNT:
            self.add_error("quantity", _("Write a quantity above zero."))
        if (self.item is not None and kind in (StockMovement.Kind.OUT, StockMovement.Kind.WASTE)
                and quantity and quantity > self.item.quantity):
            self.add_error("quantity", _("Only %(qty)s in stock.") % {"qty": f"{self.item.quantity:g}"})
        return data


class UseLineForm(BootstrapFormMixin, forms.Form):
    item = forms.ModelChoiceField(label=_("item"), queryset=StockItem.objects.filter(is_active=True), required=False)
    quantity = forms.DecimalField(label=_("quantity"), required=False, min_value=0, max_digits=10, decimal_places=2)

    def clean(self):
        data = super().clean()
        item, quantity = data.get("item"), data.get("quantity")
        if item and not quantity:
            self.add_error("quantity", _("Write the quantity."))
        if quantity and not item:
            self.add_error("item", _("Choose the item."))
        if item and quantity and quantity > item.quantity:
            self.add_error("quantity", _("Only %(qty)s in stock.") % {"qty": f"{item.quantity:g}"})
        return data


UseFormSet = formset_factory(UseLineForm, extra=8)


class UseHeaderForm(StyledForm):
    branch = forms.ModelChoiceField(label=_("for the place"), queryset=Branch.objects.none(), required=False,
                                    empty_label=None,
                                    help_text=_("The place that uses these items, so each place's use can be followed."))
    destination = forms.CharField(label=_("for / taken by"), max_length=150,
                                  help_text=_("e.g. room 3, Dr. Mona, sterilisation, kitchen"))
    kind = forms.ChoiceField(label=_("movement"), choices=[
        (StockMovement.Kind.OUT, StockMovement.Kind.OUT.label), (StockMovement.Kind.WASTE, StockMovement.Kind.WASTE.label),
    ])
    notes = forms.CharField(label=_("notes"), required=False, max_length=255)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = places()


class MovementFilterForm(StyledForm):
    date_from = forms.DateField(label=_("From"), required=False)
    date_to = forms.DateField(label=_("To"), required=False)
    kind = forms.ChoiceField(label=_("movement"), required=False, choices=[("", _("All"))] + list(StockMovement.Kind.choices))
    group = forms.ChoiceField(label=_("group"), required=False, choices=[("", _("All"))] + list(StockGroup.choices))
    category = forms.ModelChoiceField(label=_("category"), queryset=StockCategory.objects.all(), required=False,
                                      empty_label=_("All"))
    q = forms.CharField(label=_("item or destination"), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["place"] = place_filter_field(_("place"))


class ImportForm(StyledForm):
    file = forms.FileField(label=_("Excel or CSV file"),
                           help_text=_("One item per row: the quantity and the item name. Extra columns 'category', "
                                       "'unit' and 'min' are read when the first row has these titles."))
    category = forms.ModelChoiceField(label=_("category for items without one"),
                                      queryset=StockCategory.objects.filter(is_active=True))
    as_count = forms.BooleanField(
        label=_("The quantities are a stock count"), required=False, initial=True,
        help_text=_("Ticked: items already in stock are set to the quantity in the file. "
                    "Unticked: the quantities are added (a delivery)."),
    )

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if not upload.name.lower().endswith((".xlsx", ".csv")):
            raise forms.ValidationError(_("Upload an .xlsx or .csv file."))
        return upload


class StockCategoryForm(StyledModelForm):
    class Meta:
        model = StockCategory
        fields = ["group", "name_ar", "name_en", "sort_order", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("group", "name_ar", "name_en"):
            self.fields[name].col = "col-md-4"
        for name in ("sort_order", "is_active"):
            self.fields[name].col = "col-6 col-md-2"
