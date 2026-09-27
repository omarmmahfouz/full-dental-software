from django import forms
from django.utils.translation import gettext_lazy as _

from apps.academy.models import PaymentMethod
from apps.core.forms import BootstrapFormMixin, StyledForm, StyledModelForm
from apps.dentists.forms import DentistChoiceField
from apps.patients.forms import PatientLookupField, lookup_value

from .models import Charge, FawryMachine, FawryMove, PatientPayment, Service

NEEDS_REFERENCE = (PaymentMethod.INSTAPAY, PaymentMethod.WALLET, PaymentMethod.BANK, PaymentMethod.BANK_DEPOSIT,
                   PaymentMethod.CHEQUE)


def fawry_machine_field():
    return forms.ModelChoiceField(
        label=_("Fawry machine"), required=False, queryset=FawryMachine.objects.filter(is_active=True),
        help_text=_("For card payments: the machine that took it."))


def check_fawry_machine(form, data):
    """A card payment on Fawry says which machine took it (chosen for you when there is only one)."""
    if data.get("method") != PaymentMethod.FAWRY or data.get("fawry_machine") or "fawry_machine" not in form.fields:
        return
    machines = list(FawryMachine.objects.filter(is_active=True)[:2])
    if len(machines) > 1:
        form.add_error("fawry_machine", _("Choose the Fawry machine that took the payment."))
    elif machines:
        data["fawry_machine"] = machines[0]


def add_place_filter(form, places, current):
    """Lists of payments and bills: the place worked in, or another one, or all of them.
    Only for people who work in more than one place."""
    if len(places) < 2:
        return
    form.fields["place"] = forms.ChoiceField(
        label=_("place"), required=False, initial=current.code if current else "",
        choices=[(p.code, p.name) for p in places] + [("all", _("All places"))])
    form.fields["place"].widget.attrs["class"] = "form-select"


def chosen_places(form, places, current):
    """The places a filtered list shows: the chosen one, all of the person's places, or the place worked in."""
    code = form.cleaned_data.get("place") if form.is_bound and form.is_valid() else None
    if code == "all":
        return list(places)
    chosen = [p for p in places if p.code == code]
    return chosen or [current]


class ServiceChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj} — {obj.price:,.0f}"


class ChargeForm(StyledModelForm):
    service = ServiceChoiceField(label=_("service"), queryset=Service.objects.filter(is_active=True))
    dentist = DentistChoiceField(label=_("dentist who did the work"), required=False)

    class Meta:
        model = Charge
        fields = ["service", "dentist", "charged_on", "price", "discount_percent", "discount_reason", "notes"]

    def __init__(self, *args, branch=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["service"].queryset = Service.for_place(branch)
        self.fields["dentist"].queryset = self.fields["dentist"].queryset.working_at(branch)
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
    fawry_machine = fawry_machine_field()

    class Meta:
        model = PatientPayment
        fields = ["charge", "amount", "paid_on", "method", "fawry_machine", "reference", "notes"]

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
        check_fawry_machine(self, data)
        if data.get("fawry_machine"):
            self.instance.fawry_machine = data["fawry_machine"]
        return data


class PaymentFilterForm(StyledForm):
    date_from = forms.DateField(label=_("From"), required=False)
    date_to = forms.DateField(label=_("To"), required=False)
    method = forms.ChoiceField(label=_("payment method"), required=False,
                               choices=[("", _("All"))] + list(PaymentMethod.choices))

    def __init__(self, *args, places=(), current=None, **kwargs):
        super().__init__(*args, **kwargs)
        add_place_filter(self, places, current)


class BillForm(StyledForm):
    patient_lookup = PatientLookupField(label=_("patient"))
    billed_on = forms.DateField(label=_("date"))
    dentist = DentistChoiceField(label=_("dentist who did the work"), required=False)
    notes = forms.CharField(label=_("notes"), required=False, max_length=255)

    def __init__(self, *args, patient=None, branch=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["dentist"].queryset = self.fields["dentist"].queryset.working_at(branch)
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

    def __init__(self, *args, branch=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["service"].queryset = Service.for_place(branch)

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
    fawry_machine = fawry_machine_field()
    reference = forms.CharField(label=_("transaction reference"), required=False, max_length=100)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.col = "col-md-3"

    def clean(self):
        data = super().clean()
        if data.get("amount") and data.get("method") in NEEDS_REFERENCE and not data.get("reference"):
            self.add_error("reference", _("Write the transaction / transfer reference number."))
        if data.get("amount"):
            check_fawry_machine(self, data)
        return data


class BillFilterForm(StyledForm):
    date_from = forms.DateField(label=_("From"), required=False)
    date_to = forms.DateField(label=_("To"), required=False)
    unpaid = forms.BooleanField(label=_("not fully paid"), required=False)

    def __init__(self, *args, places=(), current=None, **kwargs):
        super().__init__(*args, **kwargs)
        add_place_filter(self, places, current)


class FawryMoveForm(StyledModelForm):
    fieldsets = [
        ("", ["machine", "kind", "branch", "moved_on", "amount", "fee", "service", "cash_received", "reference",
              "description"]),
    ]

    class Meta:
        model = FawryMove
        fields = ["machine", "kind", "branch", "moved_on", "amount", "fee", "service", "cash_received", "reference",
                  "description"]

    def __init__(self, *args, **kwargs):
        from apps.core.models import Branch

        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = Branch.objects.exclude(kind=Branch.Kind.LAB).order_by("sort_order", "pk")
        self.fields["fee"].required = False
        self.fields["cash_received"].required = False
        self.fields["machine"].queryset = FawryMachine.objects.filter(is_active=True)
        self.fields["machine"].required = True
        self.fields["machine"].initial = self.fields["machine"].initial or FawryMachine.default()
        for name in ("kind", "branch", "moved_on"):
            self.fields[name].col = "col-md-4"
        for name in ("amount", "fee", "cash_received"):
            self.fields[name].col = "col-md-4"
        if self.instance.pk and self.instance.is_automatic:
            # Made from a payment or a purchase: only Fawry's fee and the machine can be corrected here.
            for name in list(self.fields):
                if name not in ("fee", "machine"):
                    del self.fields[name]
            self.fields["machine"].required = False
            self.fieldsets = [("", ["machine", "fee"])]

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
        if "machine" in self.fields and not data.get("machine") and self.instance.machine_id:
            data["machine"] = self.instance.machine  # left empty: keep the machine it was on
        return data


class FawryFilterForm(StyledForm):
    date_from = forms.DateField(label=_("From"), required=False)
    date_to = forms.DateField(label=_("To"), required=False)
    machine = forms.ModelChoiceField(label=_("Fawry machine"), required=False, empty_label=_("All"),
                                     queryset=FawryMachine.objects.all())
    branch = forms.ModelChoiceField(label=_("for"), required=False, queryset=None, empty_label=_("All"))
    kind = forms.ChoiceField(label=_("move"), required=False, choices=[("", _("All"))] + list(FawryMove.Kind.choices))

    def __init__(self, *args, **kwargs):
        from apps.core.models import Branch

        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = Branch.objects.exclude(kind=Branch.Kind.LAB).order_by("sort_order", "pk")
