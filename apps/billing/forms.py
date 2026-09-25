from django import forms
from django.utils.translation import gettext_lazy as _

from apps.academy.models import PaymentMethod
from apps.core.forms import StyledForm, StyledModelForm

from .models import Charge, PatientPayment, Service

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
