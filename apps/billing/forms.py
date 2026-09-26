from django import forms
from django.utils.translation import gettext_lazy as _

from apps.academy.models import PaymentMethod
from apps.core.forms import BootstrapFormMixin, StyledForm, StyledModelForm
from apps.dentists.forms import DentistChoiceField
from apps.patients.forms import PatientLookupField, lookup_value

from .models import Charge, FawryMove, PatientPayment, Service

NEEDS_REFERENCE = (PaymentMethod.INSTAPAY, PaymentMethod.WALLET, PaymentMethod.BANK, PaymentMethod.BANK_DEPOSIT,
                   PaymentMethod.CHEQUE)


class ServiceChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj} — {obj.price:,.0f}"


class ChargeForm(StyledModelForm):
    service = ServiceChoiceField(label=_("service"), queryset=Service.objects.filter(is_active=True))

    class Meta:
        model = Charge
        fields = ["service", "charged_on", "price", "discount_percent", "discount_reason", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["price"].required = False
        self.fields["price"].help_text = _("Leave empty to use the price of the service.")
        self.fields["discount_percent"].required = False
        for field in self.fields.values():
            field.col = "col-md-4"
        self.fields["discount_reason"].col = self.fields["notes"].col = "col-md-6"

    def clean(self):
        data = super().clean()
        if data.get("price") is None and data.get("service"):
            data["price"] = data["service"].price
            self.instance.price = data["price"]
        if data.get("discount_percent") is None:
            data["discount_percent"] = 0
            self.instance.discount_percent = 0
        if data.get("discount_percent") and not data.get("discount_reason"):
            self.add_error("discount_reason", _("Write why there is a discount."))
        return data


class PatientPaymentForm(StyledModelForm):
    class Meta:
        model = PatientPayment
        fields = ["charge", "amount", "paid_on", "method", "reference", "notes"]

    def __init__(self, *args, account=None, **kwargs):
        self.account = account
        super().__init__(*args, **kwargs)
        unpaid = [row["charge"].pk for row in (account or {}).get("rows", []) if row["left"] > 0]
        self.fields["charge"].queryset = Charge.objects.filter(pk__in=unpaid).select_related("service")
        self.fields["charge"].empty_label = _("the oldest unpaid services")
        for field in self.fields.values():
            field.col = "col-md-4"

    def clean(self):
        data = super().clean()
        amount = data.get("amount")
        if amount and self.account is not None and amount > self.account["balance"]:
            self.add_error("amount", _("The amount is more than what the patient owes (%(balance)s).")
                           % {"balance": f"{self.account['balance']:,.2f}"})
        if data.get("method") in NEEDS_REFERENCE and not data.get("reference"):
            self.add_error("reference", _("Write the transaction / transfer reference number."))
        return data


class PaymentFilterForm(StyledForm):
    date_from = forms.DateField(label=_("From"), required=False)
    date_to = forms.DateField(label=_("To"), required=False)
    method = forms.ChoiceField(label=_("payment method"), required=False,
                               choices=[("", _("All"))] + list(PaymentMethod.choices))


class BillForm(StyledForm):
    patient_lookup = PatientLookupField(label=_("patient"))
    billed_on = forms.DateField(label=_("date"))
    dentist = DentistChoiceField(label=_("dentist who did the work"), required=False)
    notes = forms.CharField(label=_("notes"), required=False, max_length=255)

    def __init__(self, *args, patient=None, **kwargs):
        super().__init__(*args, **kwargs)
        if patient is not None:
            self.fields["patient_lookup"].initial = lookup_value(patient)
            self.fields["patient_lookup"].help_text = str(patient)
        for name in ("patient_lookup", "billed_on", "dentist"):
            self.fields[name].col = "col-md-4"


class ServiceSelect(forms.Select):
    """Each service carries its price, so the page can show it."""

    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        instance = getattr(value, "instance", None)
        if instance is not None:
            option["attrs"]["data-price"] = f"{instance.price:.2f}"
        return option


class BillLineForm(BootstrapFormMixin, forms.Form):
    service = ServiceChoiceField(label=_("service"), queryset=Service.objects.filter(is_active=True),
                                 widget=ServiceSelect)
    teeth = forms.CharField(label=_("teeth"), required=False, max_length=100,
                            widget=forms.TextInput(attrs={"data-teeth-picker": "multi", "data-digits": "1"}))
    price = forms.DecimalField(label=_("price"), required=False, min_value=0, max_digits=10, decimal_places=2)
    discount_percent = forms.DecimalField(label=_("discount %"), required=False, min_value=0, max_value=100,
                                          max_digits=5, decimal_places=2)
    discount_reason = forms.CharField(label=_("why the discount"), required=False, max_length=200)

    def clean_teeth(self):
        from apps.charting.teeth import format_teeth, parse_teeth

        return format_teeth(parse_teeth(self.cleaned_data.get("teeth")))

    def clean(self):
        data = super().clean()
        if data.get("discount_percent") and not data.get("discount_reason"):
            self.add_error("discount_reason", _("Write why there is a discount."))
        return data


BillLineFormSet = forms.formset_factory(BillLineForm, extra=3, min_num=1, validate_min=True)


class PayNowForm(StyledForm):
    amount = forms.DecimalField(label=_("paid now"), required=False, min_value=0, max_digits=10, decimal_places=2,
                                help_text=_("Leave empty if the patient pays later."))
    method = forms.ChoiceField(label=_("payment method"), choices=PaymentMethod.choices, initial=PaymentMethod.CASH)
    reference = forms.CharField(label=_("transaction reference"), required=False, max_length=100)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.col = "col-md-4"

    def clean(self):
        data = super().clean()
        if data.get("amount") and data.get("method") in NEEDS_REFERENCE and not data.get("reference"):
            self.add_error("reference", _("Write the transaction / transfer reference number."))
        return data


class BillFilterForm(StyledForm):
    date_from = forms.DateField(label=_("From"), required=False)
    date_to = forms.DateField(label=_("To"), required=False)
    unpaid = forms.BooleanField(label=_("not fully paid"), required=False)


class FawryMoveForm(StyledModelForm):
    fieldsets = [
        ("", ["kind", "branch", "moved_on", "amount", "fee", "service", "cash_received", "reference", "description"]),
    ]

    class Meta:
        model = FawryMove
        fields = ["kind", "branch", "moved_on", "amount", "fee", "service", "cash_received", "reference", "description"]

    def __init__(self, *args, **kwargs):
        from apps.core.models import Branch

        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = Branch.objects.exclude(kind=Branch.Kind.LAB).order_by("sort_order", "pk")
        self.fields["fee"].required = False
        self.fields["cash_received"].required = False
        for name in ("kind", "branch", "moved_on"):
            self.fields[name].col = "col-md-4"
        for name in ("amount", "fee", "cash_received"):
            self.fields[name].col = "col-md-4"
        if self.instance.pk and self.instance.is_automatic:
            # Made from a payment or a purchase: only Fawry's fee can be corrected here.
            for name in list(self.fields):
                if name != "fee":
                    del self.fields[name]
            self.fieldsets = [("", ["fee"])]

    def clean(self):
        data = super().clean()
        kind = data.get("kind", self.instance.kind)
        if kind == FawryMove.Kind.SERVICE and "service" in self.fields and not data.get("service"):
            self.add_error("service", _("Choose the bill that was paid."))
        if data.get("fee") is None:
            from .fawry import fee_for

            amount = data.get("amount") or self.instance.amount
            data["fee"] = fee_for(amount) if kind == FawryMove.Kind.COLLECTION and amount else 0
        if "cash_received" in self.fields and data.get("cash_received") is None:
            data["cash_received"] = 0
        return data


class FawryFilterForm(StyledForm):
    date_from = forms.DateField(label=_("From"), required=False)
    date_to = forms.DateField(label=_("To"), required=False)
    branch = forms.ModelChoiceField(label=_("for"), required=False, queryset=None, empty_label=_("All"))
    kind = forms.ChoiceField(label=_("move"), required=False, choices=[("", _("All"))] + list(FawryMove.Kind.choices))

    def __init__(self, *args, **kwargs):
        from apps.core.models import Branch

        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = Branch.objects.exclude(kind=Branch.Kind.LAB).order_by("sort_order", "pk")
