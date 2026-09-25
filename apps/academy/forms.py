import calendar
from datetime import date
from decimal import ROUND_DOWN, Decimal

from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.forms import (
    BootstrapFormMixin,
    StyledForm,
    StyledModelForm,
    clean_digits_value,
    clean_phone_value,
    validate_upload,
)

from .models import Candidate, Course, Enrollment, Installment, Payment, PaymentMethod


def add_months(day, months):
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def split_amount(total, parts):
    """Split ``total`` into ``parts`` whole-pound amounts; the last part takes the rest."""
    if parts <= 0:
        return []
    base = (total / parts).quantize(Decimal("1"), rounding=ROUND_DOWN)
    amounts = [base] * (parts - 1)
    amounts.append(total - base * (parts - 1))
    return amounts


class CourseForm(StyledModelForm):
    class Meta:
        model = Course
        fields = ["name", "code", "start_date", "end_date", "fee", "capacity", "implants_required", "is_active",
                  "description"]


class CandidateForm(StyledModelForm):
    fieldsets = [
        (_("Personal data"), ["code", "full_name", "certificate_name", "national_id", "birth_date", "nationality"]),
        (_("Contact"), ["phone_primary", "whatsapp", "phone_secondary", "email", "facebook", "instagram", "linkedin"]),
        (_("Professional data"), ["university", "graduation_year", "syndicate_number"]),
        ("", ["referral_source", "id_scan", "notes"]),
    ]

    class Meta:
        model = Candidate
        fields = [
            "code", "full_name", "certificate_name", "national_id", "birth_date", "nationality",
            "phone_primary", "whatsapp", "phone_secondary", "email", "facebook", "instagram", "linkedin",
            "university", "graduation_year", "syndicate_number", "referral_source", "id_scan", "notes",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("phone_primary", "phone_secondary", "whatsapp"):
            self.fields[name].widget.input_type = "tel"
        self.fields["id_scan"].validators.append(validate_upload)
        self.fields["id_scan"].widget.attrs["accept"] = "image/*,application/pdf"

    def clean_national_id(self):
        value = clean_digits_value(self.cleaned_data.get("national_id")).replace(" ", "")
        return value or None

    def clean_phone_primary(self):
        return clean_phone_value(self.cleaned_data.get("phone_primary"))

    def clean_phone_secondary(self):
        return clean_phone_value(self.cleaned_data.get("phone_secondary"), mobile_only=False)

    def clean_whatsapp(self):
        return clean_phone_value(self.cleaned_data.get("whatsapp"), mobile_only=False)

    def clean_code(self):
        return (self.cleaned_data.get("code") or "").strip().upper() or None


class EnrollmentForm(StyledModelForm):
    down_payment = forms.DecimalField(
        label=_("down payment paid now"), required=False, min_value=0, max_digits=10, decimal_places=2
    )
    down_payment_method = forms.ChoiceField(
        label=_("down payment method"), choices=PaymentMethod.choices, initial=PaymentMethod.CASH
    )
    installments_count = forms.IntegerField(
        label=_("number of installments (after down payment)"), min_value=0, max_value=36, initial=3
    )
    first_due_date = forms.DateField(label=_("first installment date"), required=False)

    fieldsets = [
        ("", ["course", "enrolled_on", "agreed_fee", "discount", "implants_required_override"]),
        (_("Installment plan"), ["down_payment", "down_payment_method", "installments_count", "first_due_date"]),
        ("", ["notes"]),
    ]

    class Meta:
        model = Enrollment
        fields = ["course", "enrolled_on", "agreed_fee", "discount", "implants_required_override", "notes"]

    def __init__(self, *args, candidate=None, **kwargs):
        self.candidate = candidate
        super().__init__(*args, **kwargs)
        self.fields["course"].queryset = Course.objects.filter(is_active=True)
        self.fields["agreed_fee"].required = False
        self.fields["agreed_fee"].help_text = _("Leave empty to use the course fee.")
        self.fields["first_due_date"].help_text = _("Following installments are monthly.")
        self.fields["notes"].widget.attrs["rows"] = 2

    def clean(self):
        data = super().clean()
        course = data.get("course")
        if not course:
            return data
        if data.get("agreed_fee") is None:
            data["agreed_fee"] = course.fee
            self.instance.agreed_fee = course.fee
        if self.candidate and Enrollment.objects.filter(candidate=self.candidate, course=course).exists():
            raise forms.ValidationError(_("This candidate is already enrolled in this course."))
        net = data["agreed_fee"] - (data.get("discount") or 0)
        if net < 0:
            self.add_error("discount", _("The discount is larger than the fee."))
            return data
        down = data.get("down_payment") or Decimal("0")
        if down > net:
            self.add_error("down_payment", _("The down payment is larger than the fee."))
        if net - down > 0:
            if not data.get("installments_count"):
                self.add_error("installments_count", _("Enter the number of installments for the remaining amount."))
            if not data.get("first_due_date"):
                self.add_error("first_due_date", _("Enter the date of the first installment."))
        return data

    def build_plan(self):
        """Return [(due_date, amount)] and the down payment amount."""
        data = self.cleaned_data
        net = data["agreed_fee"] - (data.get("discount") or 0)
        down = data.get("down_payment") or Decimal("0")
        plan = []
        if down > 0:
            plan.append((data.get("enrolled_on") or timezone.localdate(), down))
        remaining = net - down
        count = data.get("installments_count") or 0
        if remaining > 0 and count:
            for index, amount in enumerate(split_amount(remaining, count)):
                plan.append((add_months(data["first_due_date"], index), amount))
        return plan, down


class InstallmentForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Installment
        fields = ["due_date", "amount"]


InstallmentFormSet = inlineformset_factory(
    Enrollment, Installment, form=InstallmentForm, extra=1, can_delete=True
)


class PaymentForm(StyledModelForm):
    class Meta:
        model = Payment
        fields = ["amount", "paid_on", "method", "reference", "proof", "notes"]

    def __init__(self, *args, enrollment=None, **kwargs):
        self.enrollment = enrollment
        super().__init__(*args, **kwargs)
        self.fields["proof"].validators.append(validate_upload)
        self.fields["proof"].widget.attrs["accept"] = "image/*,application/pdf"
        for name in self.fields:
            self.fields[name].col = "col-md-4"

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if self.enrollment is not None and amount > self.enrollment.balance:
            raise forms.ValidationError(
                _("The amount is more than the remaining balance (%(balance)s).") % {"balance": self.enrollment.balance}
            )
        return amount

    def clean(self):
        data = super().clean()
        needs_reference = (PaymentMethod.INSTAPAY, PaymentMethod.WALLET, PaymentMethod.BANK,
                           PaymentMethod.BANK_DEPOSIT, PaymentMethod.CHEQUE)
        if data.get("method") in needs_reference and not data.get("reference"):
            self.add_error("reference", _("Write the transaction / transfer reference number."))
        return data


class PaymentFilterForm(StyledForm):
    date_from = forms.DateField(label=_("From"), required=False)
    date_to = forms.DateField(label=_("To"), required=False)
    method = forms.ChoiceField(label=_("payment method"), required=False, choices=[("", _("All"))] + list(PaymentMethod.choices))
    course = forms.ModelChoiceField(label=_("course"), queryset=Course.objects.all(), required=False, empty_label=_("All"))


class CandidateFilterForm(StyledForm):
    q = forms.CharField(label=_("Search"), required=False)
    course = forms.ModelChoiceField(label=_("batch / course"), queryset=Course.objects.all(), required=False, empty_label=_("All"))
