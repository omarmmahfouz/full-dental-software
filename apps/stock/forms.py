from django import forms
from django.forms import formset_factory
from django.utils.translation import gettext_lazy as _

from apps.core.forms import BootstrapFormMixin, StyledForm, StyledModelForm

from .models import StockCategory, StockItem, StockMovement


class StockItemForm(StyledModelForm):
    opening_quantity = forms.DecimalField(
        label=_("quantity in stock now"), required=False, min_value=0, max_digits=10, decimal_places=2,
    )

    class Meta:
        model = StockItem
        fields = ["name", "category", "unit", "min_quantity", "location", "code", "unit_cost", "is_active", "notes",
                  "implant_system", "implant_diameter", "implant_length"]

    def __init__(self, *args, **kwargs):
        from apps.surgery.models import ImplantSystem

        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = StockCategory.objects.filter(is_active=True)
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


class MovementForm(StyledModelForm):
    class Meta:
        model = StockMovement
        fields = ["kind", "quantity", "moved_at", "destination", "lot", "expiry_date", "unit_cost", "notes"]

    def __init__(self, *args, item=None, **kwargs):
        self.item = item
        super().__init__(*args, **kwargs)
        self.fields["quantity"].min_value = 0
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
    destination = forms.CharField(label=_("for / taken by"), max_length=150,
                                  help_text=_("e.g. room 3, Dr. Mona, sterilisation, kitchen"))
    kind = forms.ChoiceField(label=_("movement"), choices=[
        (StockMovement.Kind.OUT, StockMovement.Kind.OUT.label), (StockMovement.Kind.WASTE, StockMovement.Kind.WASTE.label),
    ])
    notes = forms.CharField(label=_("notes"), required=False, max_length=255)


class MovementFilterForm(StyledForm):
    date_from = forms.DateField(label=_("From"), required=False)
    date_to = forms.DateField(label=_("To"), required=False)
    kind = forms.ChoiceField(label=_("movement"), required=False, choices=[("", _("All"))] + list(StockMovement.Kind.choices))
    category = forms.ModelChoiceField(label=_("category"), queryset=StockCategory.objects.all(), required=False,
                                      empty_label=_("All"))
    q = forms.CharField(label=_("item or destination"), required=False)


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
