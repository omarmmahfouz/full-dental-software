from django import forms
from django.forms import inlineformset_factory
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.core.forms import BootstrapFormMixin, StyledForm, StyledModelForm, validate_upload
from apps.stock.models import StockItem

from .models import Purchase, PurchaseCategory, PurchaseItem, Supplier


class SupplierForm(StyledModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "phone", "contact_person", "address", "is_active", "notes"]


class PurchaseForm(StyledModelForm):
    class Meta:
        model = Purchase
        fields = [
            "supplier", "purchase_date", "invoice_number", "payment_method",
            "payment_status", "amount_paid", "invoice_image", "notes",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier"].queryset = Supplier.objects.filter(is_active=True)
        self.fields["invoice_image"].validators.append(validate_upload)
        self.fields["invoice_image"].widget.attrs["accept"] = "image/*,application/pdf"
        self.fields["notes"].widget.attrs["rows"] = 2
        self.fields["supplier"].help_text = _('Not in the list? <a href="%(url)s" target="_blank">Add a supplier</a>.') % {
            "url": reverse("purchasing:supplier_create")
        }

    def clean(self):
        data = super().clean()
        if data.get("payment_status") == Purchase.PaymentStatus.PARTIAL and not data.get("amount_paid"):
            self.add_error("amount_paid", _("Enter how much was paid."))
        return data


class PurchaseItemForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = PurchaseItem
        fields = ["category", "description", "quantity", "unit", "unit_price", "stock_item"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = PurchaseCategory.objects.filter(is_active=True)
        self.fields["stock_item"].queryset = StockItem.objects.filter(is_active=True)
        self.fields["stock_item"].empty_label = _("not a stock item")
        for field in self.fields.values():
            field.widget.attrs["class"] += " form-control-sm" if "form-control" in field.widget.attrs["class"] else " form-select-sm"


class BaseItemFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        filled = [f for f in self.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")]
        if not filled:
            raise forms.ValidationError(_("Add at least one item."))


PurchaseItemFormSet = inlineformset_factory(
    Purchase, PurchaseItem, form=PurchaseItemForm, formset=BaseItemFormSet, extra=3, can_delete=True
)


class PurchaseFilterForm(StyledForm):
    date_from = forms.DateField(label=_("From"), required=False)
    date_to = forms.DateField(label=_("To"), required=False)
    supplier = forms.ModelChoiceField(label=_("supplier"), queryset=Supplier.objects.all(), required=False, empty_label=_("All"))
    category = forms.ModelChoiceField(
        label=_("category"), queryset=PurchaseCategory.objects.all(), required=False, empty_label=_("All")
    )
    kind = forms.ChoiceField(label=_("type"), required=False, choices=[("", _("All"))] + list(PurchaseCategory.Kind.choices))
