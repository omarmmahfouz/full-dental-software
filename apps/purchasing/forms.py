from django import forms
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.forms import inlineformset_factory
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.forms import BootstrapFormMixin, StyledForm, StyledModelForm, validate_upload
from apps.core.widgets import ChoiceButtons
from apps.stock.models import StockItem

from .models import Purchase, PurchaseCategory, PurchaseItem, PurchaseReturn, Supplier


class SupplierForm(StyledModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "phone", "contact_person", "address", "is_active", "notes"]


def purchase_places(user):
    """The places a person buys for (round 15: each place has its own purchases): every place for the owner, the
    head of CIA and the stock manager, else the places this person can open."""
    from apps.core.models import Branch, switch_places
    from apps.core.roles import HEAD_CIA, OWNER, STOCK, has_role

    if has_role(user, OWNER, HEAD_CIA, STOCK):
        return list(Branch.objects.filter(is_active=True).order_by("sort_order", "pk"))
    return switch_places(user)


class PurchaseForm(StyledModelForm):
    class Meta:
        model = Purchase
        fields = [
            "branch", "supplier", "purchase_date", "invoice_number", "payment_method",
            "payment_status", "amount_paid", "invoice_image", "notes",
        ]

    def __init__(self, *args, user=None, place=None, **kwargs):
        super().__init__(*args, **kwargs)
        places = purchase_places(user) if user is not None else []
        if self.instance.pk and self.instance.branch not in places:
            places.append(self.instance.branch)
        if len(places) > 1:
            self.fields["branch"].label = _("bought for (place)")
            self.fields["branch"].queryset = self.fields["branch"].queryset.filter(pk__in=[p.pk for p in places])
            self.fields["branch"].empty_label = None
            if not self.instance.pk and place is not None:
                self.fields["branch"].initial = place.pk
        else:
            del self.fields["branch"]
        self.fields["supplier"].queryset = Supplier.objects.filter(is_active=True)
        self.fields["invoice_image"].validators.append(validate_upload)
        self.fields["invoice_image"].widget.attrs["accept"] = "image/*,application/pdf"
        self.fields["notes"].widget.attrs["rows"] = 2
        # The only hint with a link: marked safe here (the other hints are always escaped, see field.html).
        self.fields["supplier"].help_text = mark_safe(_(
            'Not in the list? <a href="%(url)s" target="_blank">Add a supplier</a>.') % {
            "url": escape(reverse("purchasing:supplier_create"))})

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
        self.fields["category"].choices = [("", "---------")] + PurchaseCategory.grouped_choices()
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
    group = forms.ChoiceField(label=_("group"), required=False,
                              choices=[("", _("All"))] + list(PurchaseCategory.Group.choices))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].choices = [("", _("All"))] + PurchaseCategory.grouped_choices(
            PurchaseCategory.objects.all())


class ReturnForm(StyledModelForm):
    """Step 1: what goes back and why. The quantities are typed per line of the purchase (see the view)."""

    class Meta:
        model = PurchaseReturn
        fields = ["returned_on", "reason", "notes"]

    def __init__(self, *args, purchase=None, **kwargs):
        self.purchase = purchase
        super().__init__(*args, **kwargs)
        self.lines = []
        for line in purchase.items.select_related("stock_item"):
            left = line.quantity - line.returned_quantity()
            name = f"line_{line.pk}"
            self.fields[name] = forms.DecimalField(
                label=line.description, required=False, min_value=0, max_value=left, decimal_places=2,
                help_text=_("bought %(qty)s, can give back %(left)s") % {"qty": f"{line.quantity:g}",
                                                                         "left": f"{left:g}"})
            self.fields[name].widget.attrs.update({"step": "any", "inputmode": "decimal", "class": "form-control"})
            self.fields[name].col = "col-md-6 col-lg-4"
            self.lines.append((line, name))
        self.fields["notes"].col = "col-12"

    def clean(self):
        data = super().clean()
        self.chosen = [(line, data[name]) for line, name in self.lines if data.get(name)]
        if not self.chosen:
            raise forms.ValidationError(_("Write how many of each item go back to the supplier."))
        for line, quantity in self.chosen:
            if line.stock_item_id and quantity > line.stock_item.quantity:
                self.add_error(f"line_{line.pk}", _("Only %(n)s left in the stock.") % {"n": f"{line.stock_item.quantity:g}"})
        return data


class ReturnTakenForm(StyledModelForm):
    """Step 2: the supplier took the items."""

    class Meta:
        model = PurchaseReturn
        fields = ["taken_on", "taken_by"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["taken_on"].required = True
        self.fields["taken_on"].initial = timezone.localdate()
        for field in self.fields.values():
            field.col = "col-md-6"


class ReturnSettleForm(StyledModelForm):
    """Step 3: the money (or a credit) came back, or new items came instead."""

    class Meta:
        model = PurchaseReturn
        fields = ["settlement", "amount", "method", "settled_on"]
        widgets = {"settlement": ChoiceButtons(icons={"money": "bi-cash-coin", "credit": "bi-journal-check",
                                                      "replaced": "bi-arrow-repeat"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["settlement"].required = True
        self.fields["settlement"].choices = PurchaseReturn.Settlement.choices
        self.fields["settled_on"].required = True
        self.fields["settled_on"].initial = timezone.localdate()
        self.fields["amount"].initial = self.instance.value
        for name in ("amount", "method", "settled_on"):
            self.fields[name].col = "col-md-4"

    def clean(self):
        data = super().clean()
        if data.get("settlement") == PurchaseReturn.Settlement.MONEY and not data.get("method"):
            self.add_error("method", _("Choose how the money came back."))
        if data.get("settlement") == PurchaseReturn.Settlement.REPLACED:
            data["amount"], data["method"] = None, ""
        return data
