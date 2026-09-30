from django import forms
from django.contrib.auth import get_user_model
from django.forms import inlineformset_factory
from django.utils.translation import gettext_lazy as _

from apps.clinical.models import Lab, LabRequest, LabWorkType
from apps.core.forms import BootstrapFormMixin, StyledForm, StyledModelForm, clean_phone_value
from apps.core.roles import DENTIST, LAB_DESIGNER, LAB_HEAD, LAB_MANAGER, LAB_SECRETARY, OWNER
from apps.stock.models import StockItem, StockMovement

from .models import (
    WORK_STEPS, LabBlock, LabCase, LabCaseItem, LabClient, LabFile, LabPayment, LabPriceList, LabSettings, LabWorker,
    Step, lab_branch,
)


class CaseForm(StyledModelForm):
    enclosures = forms.MultipleChoiceField(label=_("Came with the work"), choices=LabRequest.ENCLOSURES,
                                           required=False, widget=forms.CheckboxSelectMultiple)

    fieldsets = [
        (_("Who sent it"), ["client", "doctor", "doctor_phone", "patient_name"]),
        (_("How it came"), ["impression", "stage", "shade", "enclosures"]),
        (_("When"), ["due_date", "urgent"]),
        (_("Instructions"), ["instructions", "discount", "notes"]),
    ]

    class Meta:
        model = LabCase
        fields = ["client", "doctor", "doctor_phone", "patient_name", "impression", "stage", "shade", "enclosures",
                  "due_date", "urgent", "instructions", "discount", "notes"]
        widgets = {"instructions": forms.Textarea(attrs={"rows": 3}), "notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, money=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = LabClient.objects.filter(is_active=True).select_related("branch")
        self.fields["due_date"].help_text = _("Empty = the usual days of the work.")
        self.fields["shade"].widget.attrs["placeholder"] = "A2 · 3M2 · …"
        if not money:
            del self.fields["discount"]
        for name in ("instructions", "notes"):
            if name in self.fields:
                self.fields[name].col = "col-md-6"

    def clean_doctor_phone(self):
        return clean_phone_value(self.cleaned_data.get("doctor_phone"), mobile_only=False)


class ItemForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = LabCaseItem
        fields = ["work_type", "teeth", "units", "material", "unit_price"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["work_type"].queryset = LabWorkType.objects.filter(is_active=True)
        self.fields["teeth"].widget.attrs.update({"data-digits": "1", "data-teeth-picker": "multi"})
        self.fields["unit_price"].widget.attrs["placeholder"] = str(_("price list"))


ItemFormSet = inlineformset_factory(LabCase, LabCaseItem, form=ItemForm, extra=0, can_delete=True, min_num=1,
                                    validate_min=True)


class MoveForm(StyledForm):
    to_step = forms.ChoiceField(label=_("Move to"), choices=[])
    worker = forms.ModelChoiceField(label=_("Given to"), queryset=LabWorker.objects.none(), required=False,
                                    empty_label=_("— nobody yet —"))
    notes = forms.CharField(label=_("Notes"), max_length=255, required=False)

    def __init__(self, *args, case=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["to_step"].choices = [(code, label) for code, label in Step.choices
                                          if code not in (Step.INCOMING, case.step if case else "")]
        self.fields["worker"].queryset = LabWorker.objects.filter(is_active=True)


class AssignForm(StyledForm):
    worker = forms.ModelChoiceField(label=_("Given to"), queryset=LabWorker.objects.none(), required=False,
                                    empty_label=_("— nobody —"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["worker"].queryset = LabWorker.objects.filter(is_active=True)


class ReceiveForm(StyledForm):
    enclosures = forms.MultipleChoiceField(label=_("Came with the work"), choices=LabRequest.ENCLOSURES,
                                           required=False, widget=forms.CheckboxSelectMultiple)
    checked = forms.BooleanField(label=_("I checked the work against the request"))
    notes = forms.CharField(label=_("Notes"), max_length=255, required=False)


class RemakeForm(StyledForm):
    reason = forms.ChoiceField(label=_("Why the remake"), choices=LabCase.RemakeReason.choices)
    fault = forms.ChoiceField(label=_("Whose fault"), choices=LabCase.Fault.choices, initial=LabCase.Fault.UNKNOWN,
                              help_text=_("The lab's own mistake is remade free."))
    in_hand = forms.BooleanField(label=_("The work is at the lab now"), required=False, initial=True,
                                 help_text=_("Untick when the clinic still has to send it back."))
    notes = forms.CharField(label=_("What is wrong"), widget=forms.Textarea(attrs={"rows": 3}))


class OutsourceForm(StyledForm):
    lab = forms.ModelChoiceField(label=_("Send to the lab"), queryset=Lab.objects.none())
    work = forms.CharField(label=_("What is sent"), max_length=150)
    cost = forms.DecimalField(label=_("Cost"), max_digits=10, decimal_places=2, required=False, min_value=0)
    due_date = forms.DateField(label=_("Back by"), required=False)
    notes = forms.CharField(label=_("Notes"), max_length=255, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lab"].queryset = Lab.objects.filter(is_active=True, branch__isnull=True)


class FileForm(StyledModelForm):
    class Meta:
        model = LabFile
        fields = ["kind", "file", "note"]

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if upload and upload.size > 60 * 1024 * 1024:
            raise forms.ValidationError(_("The file is too large (maximum %(size)s MB).") % {"size": 60})
        return upload


def lab_stock_items():
    place = lab_branch()
    return StockItem.objects.filter(is_active=True, branch=place).select_related("category")


class BlockOpenForm(StyledModelForm):
    class Meta:
        model = LabBlock
        fields = ["item", "code", "lot", "shade", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = lab_stock_items().filter(category__lab_blocks=True)
        self.fields["item"].help_text = _("One piece is taken out of the lab's stock.")


class BlockUseForm(StyledForm):
    block = forms.ModelChoiceField(label=_("Block / disc"), queryset=LabBlock.objects.none(),
                                   empty_label=_("— choose the block —"))
    units = forms.IntegerField(label=_("Units made from it"), min_value=1, max_value=99, initial=1)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["block"].queryset = LabBlock.objects.filter(status=LabBlock.Status.IN_USE).select_related("item")


class StockMoveForm(StyledForm):
    item = forms.ModelChoiceField(label=_("Item"), queryset=StockItem.objects.none())
    kind = forms.ChoiceField(label=_("Movement"), choices=[(StockMovement.Kind.OUT, _("Taken out / used")),
                                                            (StockMovement.Kind.IN, _("Received into stock"))])
    quantity = forms.DecimalField(label=_("Quantity"), max_digits=10, decimal_places=2, min_value=0.01)
    unit_cost = forms.DecimalField(label=_("Unit price"), max_digits=12, decimal_places=2, required=False,
                                   min_value=0)
    notes = forms.CharField(label=_("For / notes"), max_length=150, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = lab_stock_items()


class ClientForm(StyledModelForm):
    class Meta:
        model = LabClient
        fields = ["name", "kind", "price_list", "contact", "phone", "whatsapp", "address", "notes", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["price_list"].queryset = LabPriceList.objects.filter(is_active=True)
        if self.instance.branch_id:
            self.fields["kind"].disabled = True

    def clean_phone(self):
        return clean_phone_value(self.cleaned_data.get("phone"), mobile_only=False)

    def clean_whatsapp(self):
        return clean_phone_value(self.cleaned_data.get("whatsapp"), mobile_only=False)


class PaymentForm(StyledModelForm):
    class Meta:
        model = LabPayment
        fields = ["client", "amount", "method", "paid_on", "reference", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = LabClient.objects.filter(is_active=True).select_related("branch")
        self.fields["amount"].min_value = 0.01
        self.fields["amount"].widget.attrs["min"] = "0.01"

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount is not None and amount <= 0:
            raise forms.ValidationError(_("Write an amount above zero."))
        return amount


class CancelForm(StyledForm):
    reason = forms.CharField(label=_("Why"), max_length=255)


class WorkerForm(StyledModelForm):
    jobs = forms.MultipleChoiceField(label=_("Works on"), required=False, widget=forms.CheckboxSelectMultiple,
                                     choices=[(code, label) for code, label in Step.choices if code in WORK_STEPS])

    class Meta:
        model = LabWorker
        fields = ["name", "user", "jobs", "phone", "fee_per_unit", "is_active", "sort_order"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = (get_user_model().objects.filter(
            is_active=True, groups__name__in=(LAB_HEAD, LAB_MANAGER, LAB_DESIGNER, LAB_SECRETARY, DENTIST, OWNER))
            .distinct().order_by("first_name", "username"))


class PriceListForm(StyledModelForm):
    class Meta:
        model = LabPriceList
        fields = ["name", "notes", "is_active"]


class SettingsForm(StyledModelForm):
    fieldsets = [
        (_("WhatsApp messages"), ["received_text", "ready_text", "delivered_text"]),
        (_("The automatic answer (WhatsApp Business platform)"),
         ["auto_reply", "wa_phone_number_id", "wa_token", "wa_verify_token", "wa_app_secret"]),
    ]

    class Meta:
        model = LabSettings
        fields = ["received_text", "ready_text", "delivered_text", "auto_reply", "wa_phone_number_id", "wa_token",
                  "wa_verify_token", "wa_app_secret"]
        widgets = {"wa_token": forms.PasswordInput(render_value=True),
                   "wa_app_secret": forms.PasswordInput(render_value=True)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("received_text", "ready_text", "delivered_text"):
            self.fields[name].col = "col-12"
            self.fields[name].widget.attrs["rows"] = 3
            self.fields[name].help_text = _("Words in braces are filled in: {doctor} {patient} {work} {number} {due} "
                                            "{lab} {phone}")


class CaseFilterForm(StyledForm):
    q = forms.CharField(label=_("Search"), required=False)
    step = forms.ChoiceField(label=_("Step"), required=False)
    client = forms.ModelChoiceField(label=_("Client"), queryset=LabClient.objects.none(), required=False)
    date_from = forms.DateField(label=_("Received from"), required=False)
    date_to = forms.DateField(label=_("To"), required=False)
    late = forms.BooleanField(label=_("Late only"), required=False)
    remakes = forms.BooleanField(label=_("Remakes only"), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["step"].choices = [("", _("All")), ("open", _("Still at the lab"))] + list(Step.choices)
        self.fields["client"].queryset = LabClient.objects.select_related("branch")
