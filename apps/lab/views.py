import json
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Prefetch, Q, Sum
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.clinical.models import LabRequest, LabWorkType
from apps.core.mixins import role_required
from apps.core.roles import (
    LAB_DESK, LAB_MANAGERS, LAB_MONEY, LAB_SECRETARY, LAB_STAFF, has_role,
)
from apps.stock.models import StockMovement
from apps.stock.services import record_movement

from . import services, stats
from . import whatsapp as wa
from .forms import (
    AssignForm, BlockOpenForm, BlockUseForm, CancelForm, CaseFilterForm, CaseForm, ClientForm, FileForm,
    ItemFormSet, MoveForm, OutsourceForm, PaymentForm, PriceListForm, ReceiveForm, RemakeForm, SettingsForm,
    StockMoveForm, WorkerForm, lab_stock_items,
)
from .models import (
    AWAY_STEPS, CLOSED_STEPS, STEP_ICONS, WORK_STEPS, LabBlock, LabCase, LabCaseItem, LabCaseStep, LabClient,
    LabMessage, LabOutsource, LabPayment, LabPrice, LabPriceList, LabSettings, LabWorker, Step, lab_branch,
)

# The columns of the board: each groups a few steps.
BOARD = [
    ("incoming", "bi-truck", [Step.INCOMING]),
    ("received", "bi-inbox", [Step.RECEIVED]),
    ("design", "bi-vector-pen", [Step.MODELS, Step.DESIGN, Step.DESIGN_CHECK]),
    ("production", "bi-gear-wide-connected", [Step.MILLING, Step.PRINTING, Step.METAL_PRINTING, Step.CASTING,
                                             Step.SINTERING]),
    ("finishing", "bi-brush", [Step.CERAMIC, Step.STAIN_GLAZE, Step.SETUP, Step.PROCESSING, Step.FINISHING]),
    ("qc", "bi-patch-check", [Step.QC]),
    ("ready", "bi-bag-check", [Step.READY]),
    ("away", "bi-arrow-left-right", list(AWAY_STEPS)),
]


def board_titles():
    return {"incoming": _("On the way"), "received": _("To give out"), "design": _("Design"),
            "production": _("Milling, printing, casting"), "finishing": _("Finishing"), "qc": _("Quality check"),
            "ready": _("Ready"), "away": _("At the clinic, another lab, on hold")}


def my_worker(user):
    """The lab staff record of this person (kept on the person for the page: the board asks it for each case)."""
    if not user.is_authenticated:
        return None
    if not hasattr(user, "_lab_worker"):
        user._lab_worker = LabWorker.objects.filter(user=user, is_active=True).first()
    return user._lab_worker


def open_cases():
    return (LabCase.objects.exclude(step__in=CLOSED_STEPS)
            .select_related("client__branch", "worker", "remake_of")
            .prefetch_related(Prefetch("items", queryset=LabCaseItem.objects.select_related("work_type"))))


def can_move(user, case, to_step):
    """Managers move any case; the person who has the case finishes their step (or puts it on hold); the secretary
    delivers, sends for a try-in and takes back from the clinic or another lab."""
    if has_role(user, *LAB_MANAGERS):
        return True
    to_step = str(to_step)
    if case.step in CLOSED_STEPS:
        return False
    worker = my_worker(user)
    if worker is not None and case.worker_id == worker.pk and to_step in (services.next_step(case), Step.ON_HOLD):
        return True
    if has_role(user, LAB_SECRETARY):
        if to_step == Step.DELIVERED and case.step == Step.READY:
            return True
        if to_step == Step.TRY_IN and case.step in (Step.READY, Step.QC):
            return True
        if case.step in AWAY_STEPS and to_step == services.next_step(case):  # back from the clinic or another lab
            return True
    return False


# ------------------------------------------------------------ board and lists
@role_required(*LAB_STAFF)
def board(request):
    cases = open_cases()
    worker_id = request.GET.get("worker", "")
    client_id = request.GET.get("client", "")
    if worker_id.isdigit():
        cases = cases.filter(worker_id=worker_id)
    if client_id.isdigit():
        cases = cases.filter(client_id=client_id)
    if request.GET.get("late"):
        cases = cases.filter(due_date__lt=timezone.localdate())
    cases = sorted(cases, key=lambda c: (not c.urgent, c.due_date or timezone.localdate() + timedelta(days=365), c.pk))
    titles = board_titles()
    columns = []
    for key, icon, steps in BOARD:
        items = [case for case in cases if case.step in steps]
        columns.append({"key": key, "icon": icon, "title": titles[key], "cases": items})
    me = my_worker(request.user)
    for case in cases:
        case.next = services.next_step(case)
        case.next_label = dict(Step.choices).get(case.next, "")
        case.can_next = case.next is not None and can_move(request.user, case, case.next)
        case.late = case.due_date is not None and case.due_date < timezone.localdate()
    return render(request, "lab/board.html", {
        "columns": columns, "work_steps": [str(code) for code in WORK_STEPS], "numbers": stats.home_numbers(me), "workers": LabWorker.objects.filter(is_active=True),
        "clients": LabClient.objects.filter(is_active=True).select_related("branch"), "me": me,
        "filters": {"worker": worker_id, "client": client_id, "late": request.GET.get("late", "")},
    })


@role_required(*LAB_STAFF)
def case_list(request):
    form = CaseFilterForm(request.GET or None)
    cases = (LabCase.objects.select_related("client__branch", "worker")
             .prefetch_related(Prefetch("items", queryset=LabCaseItem.objects.select_related("work_type"))))
    if form.is_valid():
        data = form.cleaned_data
        q = (data.get("q") or "").strip()
        if q:
            digits = "".join(ch for ch in q if ch.isdigit())
            match = Q(patient_name__icontains=q) | Q(doctor__icontains=q) | Q(number__icontains=q)
            if digits and len(digits) <= 6:
                match |= Q(pk=int(digits))
            cases = cases.filter(match)
        if data.get("step") == "open":
            cases = cases.exclude(step__in=CLOSED_STEPS)
        elif data.get("step"):
            cases = cases.filter(step=data["step"])
        if data.get("client"):
            cases = cases.filter(client=data["client"])
        if data.get("date_from"):
            cases = cases.filter(received_at__gte=stats.bounds(data["date_from"], data["date_from"])[0])
        if data.get("date_to"):
            cases = cases.filter(received_at__lt=stats.bounds(data["date_to"], data["date_to"])[1])
        if data.get("late"):
            cases = cases.exclude(step__in=CLOSED_STEPS).filter(due_date__lt=timezone.localdate())
        if data.get("remakes"):
            cases = cases.filter(remake_of__isnull=False)
    totals = cases.aggregate(n=Count("id"), total=Sum("total"))
    page = Paginator(cases, 50).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "lab/case_list.html", {"form": form, "page_obj": page, "totals": totals,
                                                  "query_string": params.urlencode(),
                                                  "money": has_role(request.user, *LAB_DESK)})


@role_required(*LAB_STAFF)
def my_work(request):
    worker = my_worker(request.user)
    if worker is None:
        messages.info(request, _("You are not on the lab's staff list yet: the head of the lab adds you in Lab staff."))
        return redirect("lab:board")
    cases = list(open_cases().filter(worker=worker).order_by("due_date", "pk"))
    for case in cases:
        case.next = services.next_step(case)
        case.next_label = dict(Step.choices).get(case.next, "")
        case.can_next = case.next is not None and can_move(request.user, case, case.next)
        case.late = case.due_date is not None and case.due_date < timezone.localdate()
    done = (LabCaseStep.objects.filter(worker=worker, done_at__isnull=False, step__in=WORK_STEPS)
            .select_related("case__client__branch").order_by("-done_at")[:20])
    month = timezone.localdate().replace(day=1)
    designed_cases = LabCaseStep.objects.filter(worker=worker, step=Step.DESIGN, completed=True,
                                                done_at__gte=stats.bounds(month, month)[0]).values("case_id")
    designed = LabCaseItem.objects.filter(case_id__in=designed_cases).aggregate(n=Sum("units"))["n"] or 0
    return render(request, "lab/my_work.html", {"worker": worker, "cases": cases, "done": done,
                                                "work_steps": [str(code) for code in WORK_STEPS],
                                                "designed": designed,
                                                "fee": (worker.fee_per_unit or 0) * designed})


@role_required(*LAB_DESK)
def incoming(request):
    cases = open_cases().filter(step=Step.INCOMING).order_by("pk")
    return render(request, "lab/incoming.html", {"cases": cases, "form": ReceiveForm()})


# ------------------------------------------------------------ a case
@role_required(*LAB_DESK)
def case_create(request):
    form = CaseForm(request.POST or None, initial={"client": request.GET.get("client")},
                    money=has_role(request.user, *LAB_MONEY))
    formset = ItemFormSet(request.POST or None, instance=LabCase(), prefix="items")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            case = form.save(commit=False)
            case.created_by = request.user
            case.save()
            formset.instance = case
            formset.save()
            services.start_case(case, request.user, received=True)
        messages.success(request, _("Case %(number)s received. Print its label and tell the doctor on WhatsApp.")
                         % {"number": case.number})
        return redirect(f"{case.get_absolute_url()}?new=1")
    return render(request, "lab/case_form.html", {"form": form, "formset": formset, "title": _("Receive a case")})


@role_required(*LAB_DESK)
def case_edit(request, pk):
    case = get_object_or_404(LabCase, pk=pk)
    form = CaseForm(request.POST or None, instance=case, money=has_role(request.user, *LAB_MONEY))
    formset = ItemFormSet(request.POST or None, instance=case, prefix="items")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            form.save()
            formset.save()
            services.fill_prices(case)
        messages.success(request, _("Case %(number)s saved.") % {"number": case.number})
        return redirect(case)
    return render(request, "lab/case_form.html", {"form": form, "formset": formset, "case": case,
                                                  "title": _("Edit case %(number)s") % {"number": case.number}})


@role_required(*LAB_STAFF)
def case_detail(request, pk):
    case = get_object_or_404(LabCase.objects.select_related(
        "client__branch", "client__price_list", "worker", "remake_of", "request__branch", "received_by",
        "delivered_by"), pk=pk)
    items = list(case.items.select_related("work_type"))
    steps = list(case.steps.select_related("worker", "done_by"))
    longest = max((step.hours for step in steps if step.step not in CLOSED_STEPS), default=0) or 1
    for step in steps:
        step.width = max(4, round(100 * step.hours / longest)) if step.step not in CLOSED_STEPS else 0
    nxt = services.next_step(case)
    route = case.route or services.route_for(case)
    passed = {step.step for step in steps if step.done_at and step.completed}
    road = [{"code": code, "label": dict(Step.choices)[code], "icon": STEP_ICONS.get(code, "bi-circle"),
             "done": code in passed and code != case.step, "now": code == case.step} for code in route]
    user = request.user
    context = {
        "case": case, "items": items, "steps": steps, "road": road,
        "next": nxt, "next_label": dict(Step.choices).get(nxt, "") if nxt else "",
        "can_next": nxt is not None and can_move(user, case, nxt),
        "can_hold": case.step in WORK_STEPS and can_move(user, case, Step.ON_HOLD),
        "can_deliver": case.step == Step.READY and can_move(user, case, Step.DELIVERED),
        "is_manager": has_role(user, *LAB_MANAGERS), "is_desk": has_role(user, *LAB_DESK),
        "money": has_role(user, *LAB_DESK),
        "move_form": MoveForm(case=case, initial={"to_step": nxt}), "assign_form": AssignForm(
            initial={"worker": case.worker_id}),
        "outsource_form": OutsourceForm(), "file_form": FileForm(), "block_form": BlockUseForm(
            initial={"units": sum(item.units for item in items) or 1}),
        "receive_form": ReceiveForm(initial={"enclosures": case.enclosures}),
        "files": case.files.all(), "blocks": case.block_uses.select_related("block__item", "by"),
        "outsourced": case.outsourced.select_related("lab"), "remakes": case.remakes.all(),
        "sent": case.messages.select_related("by")[:10], "new": request.GET.get("new") == "1",
        "can_whatsapp": has_role(user, *LAB_DESK) and bool(wa.link(case.whatsapp_phone, "x")),
        "enclosure_choices": LabRequest.ENCLOSURES, "wa_buttons": _wa_buttons(case),
    }
    return render(request, "lab/case_detail.html", context)


def _wa_buttons(case):
    buttons = [(LabMessage.Kind.RECEIVED, _("Case received"))] if case.step != Step.INCOMING else []
    if case.step == Step.READY:
        buttons.append((LabMessage.Kind.READY, _("Case ready")))
    if case.step == Step.DELIVERED:
        buttons.append((LabMessage.Kind.DELIVERED, _("Case sent back")))
    buttons.append((LabMessage.Kind.STATUS, _("Where the case is now")))
    return buttons


@role_required(*LAB_STAFF)
@require_POST
def case_move(request, pk):
    case = get_object_or_404(LabCase, pk=pk)
    to_step = request.POST.get("to_step") or services.next_step(case)
    if not to_step or not can_move(request.user, case, to_step):
        raise PermissionDenied
    worker = None
    worker_id = request.POST.get("worker", "")
    if worker_id.isdigit():
        worker = LabWorker.objects.filter(pk=worker_id, is_active=True).first()
    try:
        services.move(case, to_step, request.user, worker=worker, notes=request.POST.get("notes", ""))
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, _("Case %(number)s: %(step)s.") % {"number": case.number,
                                                                     "step": case.get_step_display()})
    target = request.POST.get("next", "")
    return redirect(target if target.startswith("/lab/") else case.get_absolute_url())


@role_required(*LAB_MANAGERS)
@require_POST
def case_assign(request, pk):
    case = get_object_or_404(LabCase, pk=pk)
    form = AssignForm(request.POST)
    if form.is_valid():
        try:
            services.assign(case, form.cleaned_data["worker"], request.user)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, _("Given to %(worker)s.") % {"worker": form.cleaned_data["worker"] or "—"})
    return redirect(case)


@role_required(*LAB_DESK)
@require_POST
def case_receive(request, pk):
    case = get_object_or_404(LabCase, pk=pk)
    form = ReceiveForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Tick that you checked the work against the request."))
        return redirect(request.POST.get("next") if request.POST.get("next", "").startswith("/lab/") else case)
    try:
        services.receive(case, request.user, form.cleaned_data["enclosures"], form.cleaned_data["notes"])
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, _("Case %(number)s received. Print its label.") % {"number": case.number})
    return redirect(case)


@role_required(*LAB_DESK)
def case_remake(request, pk):
    case = get_object_or_404(LabCase, pk=pk)
    form = RemakeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        remake = services.make_remake(case, request.user, data["reason"], data["fault"], data["notes"],
                                      in_hand=data["in_hand"])
        messages.success(request, _("Remake %(number)s opened.") % {"number": remake.number})
        return redirect(remake)
    return render(request, "includes/form_page.html", {
        "form": form, "title": _("Remake of %(number)s") % {"number": case.number}, "title_icon": "bi-arrow-repeat",
        "cancel_url": case.get_absolute_url(), "submit_label": _("Open the remake"),
        "intro": _("A new case linked to this one, on the same steps. Say what is wrong and whose fault it is: the "
                   "lab report counts the remakes by reason, by client and by designer.")})


@role_required(*LAB_MANAGERS)
@require_POST
def case_outsource(request, pk):
    case = get_object_or_404(LabCase, pk=pk)
    form = OutsourceForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        services.outsource(case, data["lab"], data["work"], request.user, cost=data["cost"],
                           due_date=data["due_date"], notes=data["notes"])
        messages.success(request, _("Sent to %(lab)s.") % {"lab": data["lab"]})
    else:
        messages.error(request, _("Choose the lab and write what is sent."))
    return redirect(case)


@role_required(*LAB_DESK)
@require_POST
def outsource_back(request, pk):
    sent = get_object_or_404(LabOutsource.objects.select_related("case"), pk=pk, back_at__isnull=True)
    cost = request.POST.get("cost", "").strip()
    try:
        cost = Decimal(cost) if cost else None
    except ArithmeticError:
        cost = None
    services.outsource_back(sent, request.user, cost=cost)
    messages.success(request, _("Back from %(lab)s.") % {"lab": sent.lab})
    return redirect(sent.case)


@role_required(*LAB_STAFF)
@require_POST
def case_file(request, pk):
    case = get_object_or_404(LabCase, pk=pk)
    form = FileForm(request.POST, request.FILES)
    if form.is_valid():
        added = form.save(commit=False)
        added.case, added.uploaded_by = case, request.user
        added.save()
        messages.success(request, _("File added."))
    else:
        messages.error(request, " ".join(e for errors in form.errors.values() for e in errors))
    return redirect(case)


@role_required(*LAB_STAFF)
@require_POST
def case_block(request, pk):
    case = get_object_or_404(LabCase, pk=pk)
    form = BlockUseForm(request.POST)
    if form.is_valid():
        try:
            services.use_block(form.cleaned_data["block"], case, form.cleaned_data["units"], request.user)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, _("%(units)s unit(s) from block %(block)s.") % {
                "units": form.cleaned_data["units"], "block": form.cleaned_data["block"].code})
    return redirect(case)


@role_required(*LAB_STAFF)
def case_print(request, pk):
    case = get_object_or_404(LabCase.objects.select_related("client__branch", "remake_of", "worker"), pk=pk)
    route = case.route or services.route_for(case)
    return render(request, "lab/case_print.html", {
        "case": case, "items": case.items.select_related("work_type"), "place": lab_branch(),
        "route": [(code, dict(Step.choices)[code]) for code in route if code not in (Step.RECEIVED, Step.READY)],
        "money": has_role(request.user, *LAB_DESK) and request.GET.get("prices") != "0",
        "steps": {s.step: s for s in case.steps.select_related("worker") if s.done_at},
    })


@role_required(*LAB_STAFF)
def case_label(request, pk):
    case = get_object_or_404(LabCase.objects.select_related("client__branch"), pk=pk)
    return render(request, "lab/case_label.html", {"case": case, "place": lab_branch()})


@role_required(*LAB_DESK)
@require_POST
def case_whatsapp(request, pk, kind):
    case = get_object_or_404(LabCase.objects.select_related("client__branch"), pk=pk)
    if kind not in LabMessage.Kind.values or kind in (LabMessage.Kind.AUTO, LabMessage.Kind.STATEMENT):
        raise Http404
    url = wa.link(case.whatsapp_phone, wa.message_text(case, kind))
    if not url:
        messages.error(request, _("There is no mobile for WhatsApp on this case or its client."))
        return redirect(case)
    wa.record(case, kind, request.user)
    return redirect(url)


# ------------------------------------------------------------ blocks and the lab's stock
@role_required(*LAB_STAFF)
def blocks(request):
    units = services.block_units()
    in_use = list(LabBlock.objects.filter(status=LabBlock.Status.IN_USE).select_related("item"))
    finished = list(LabBlock.objects.exclude(status=LabBlock.Status.IN_USE).select_related("item")[:40])
    for block in in_use + finished:
        block.units = units.get(block.pk, 0)
    items = list(lab_stock_items())
    return render(request, "lab/blocks.html", {
        "in_use": in_use, "finished": finished, "items": items, "open_form": BlockOpenForm(),
        "move_form": StockMoveForm(), "can_desk": has_role(request.user, *LAB_DESK),
        "place": lab_branch(),
    })


@role_required(*LAB_DESK)
@require_POST
def block_open(request):
    form = BlockOpenForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        if data["item"].quantity < 1:
            messages.error(request, _("There is no %(item)s left in the lab's stock: receive it first.")
                           % {"item": data["item"].name})
            return redirect("lab:blocks")
        block = services.open_block(data["item"], request.user, data["code"], data["lot"], data["shade"],
                                    data["notes"])
        messages.success(request, _("Block %(code)s opened.") % {"code": block.code})
    else:
        messages.error(request, _("Choose the block to open."))
    return redirect("lab:blocks")


@role_required(*LAB_STAFF)
def block_detail(request, pk):
    block = get_object_or_404(LabBlock.objects.select_related("item", "opened_by"), pk=pk)
    uses = block.uses.select_related("case__client__branch", "by")
    total = uses.aggregate(n=Sum("units"))["n"] or 0
    return render(request, "lab/block_detail.html", {
        "lab_block": block, "uses": uses, "total": total, "can_desk": has_role(request.user, *LAB_DESK),
        "cost_per_unit": (block.unit_cost / total) if block.unit_cost and total else None})


@role_required(*LAB_DESK)
@require_POST
def block_finish(request, pk):
    block = get_object_or_404(LabBlock, pk=pk, status=LabBlock.Status.IN_USE)
    status = request.POST.get("status")
    services.finish_block(block, status if status in LabBlock.Status.values else LabBlock.Status.FINISHED)
    messages.success(request, _("Block %(code)s closed.") % {"code": block.code})
    return redirect(block)


@role_required(*LAB_DESK)
@require_POST
def stock_move(request):
    form = StockMoveForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        if data["kind"] == StockMovement.Kind.OUT and data["quantity"] > data["item"].quantity:
            messages.error(request, _("Only %(qty)s left of %(item)s.") % {"qty": f"{data['item'].quantity:g}",
                                                                           "item": data["item"].name})
            return redirect("lab:blocks")
        record_movement(data["item"], data["kind"], data["quantity"], request.user, branch=lab_branch(),
                        unit_cost=data["unit_cost"] if data["kind"] == StockMovement.Kind.IN else None,
                        destination=data["notes"])
        messages.success(request, _("Saved: %(item)s.") % {"item": data["item"].name})
    else:
        messages.error(request, _("Choose the item and the quantity."))
    return redirect("lab:blocks")


# ------------------------------------------------------------ clients, prices, receipts
@role_required(*LAB_DESK)
def client_list(request):
    clients = list(LabClient.objects.select_related("branch", "price_list").annotate(
        open_cases=Count("cases", filter=~Q(cases__step__in=CLOSED_STEPS))))
    money = services.balances(clients)
    for client in clients:
        client.money = money.get(client.pk, {})
    totals = {key: sum((c.money.get(key, 0) for c in clients), Decimal("0"))
              for key in ("billed", "paid", "balance", "in_work")}
    return render(request, "lab/client_list.html", {"clients": clients, "totals": totals})


@role_required(*LAB_DESK)
def client_edit(request, pk=None):
    client = get_object_or_404(LabClient, pk=pk) if pk else None
    form = ClientForm(request.POST or None, instance=client)
    if not has_role(request.user, *LAB_MONEY):
        form.fields["price_list"].disabled = True
    if request.method == "POST" and form.is_valid():
        client = form.save()
        messages.success(request, _("Saved."))
        return redirect(client)
    return render(request, "includes/form_page.html", {
        "form": form, "title": str(client) if client else _("New client of the lab"), "title_icon": "bi-building",
        "cancel_url": client.get_absolute_url() if client else reverse("lab:clients")})


@role_required(*LAB_DESK)
def client_detail(request, pk):
    client = get_object_or_404(LabClient.objects.select_related("branch", "price_list"), pk=pk)
    money = services.balances([client])[client.pk]
    cases = Paginator(client.cases.select_related("worker").prefetch_related(
        Prefetch("items", queryset=LabCaseItem.objects.select_related("work_type"))), 40).get_page(
        request.GET.get("page"))
    return render(request, "lab/client_detail.html", {
        "client": client, "money": money, "page_obj": cases, "payments": client.payments.select_related(
            "received_by")[:30],
        "is_money": has_role(request.user, *LAB_MONEY)})


@role_required(*LAB_DESK)
def client_statement(request, pk):
    client = get_object_or_404(LabClient.objects.select_related("branch"), pk=pk)
    today = timezone.localdate()
    from apps.core.forms import DateRangeForm

    form = DateRangeForm(request.GET or None, initial={"date_from": today.replace(day=1), "date_to": today})
    date_from, date_to = today.replace(day=1), today
    if form.is_valid():
        date_from = form.cleaned_data.get("date_from") or date_from
        date_to = form.cleaned_data.get("date_to") or date_to
    start, end = stats.bounds(date_from, date_to)
    delivered = LabCase.objects.filter(client=client, step=Step.DELIVERED)
    before_cases = delivered.filter(delivered_at__lt=start).aggregate(t=Sum("total"))["t"] or 0
    payments = client.payments.filter(cancelled_at__isnull=True)
    before_paid = payments.filter(paid_on__lt=date_from).aggregate(t=Sum("amount"))["t"] or 0
    cases = (delivered.filter(delivered_at__gte=start, delivered_at__lt=end).order_by("delivered_at")
             .prefetch_related(Prefetch("items", queryset=LabCaseItem.objects.select_related("work_type"))))
    paid = payments.filter(paid_on__range=(date_from, date_to)).order_by("paid_on")
    opening = before_cases - before_paid
    cases_total = sum((c.total for c in cases), Decimal("0"))
    paid_total = sum((p.amount for p in paid), Decimal("0"))
    closing = opening + cases_total - paid_total
    if request.method == "POST":  # send the statement's total on WhatsApp
        text = _("Account of %(client)s at %(lab)s from %(start)s to %(end)s: work %(work)s, paid %(paid)s, "
                 "balance %(balance)s.") % {
            "client": client, "lab": lab_branch().name if lab_branch() else "", "start": date_from.strftime("%d/%m/%Y"),
            "end": date_to.strftime("%d/%m/%Y"), "work": f"{cases_total:,.2f}", "paid": f"{paid_total:,.2f}",
            "balance": f"{closing:,.2f}"}
        url = wa.link(client.whatsapp_phone, text)
        if not url:
            messages.error(request, _("This client has no mobile for WhatsApp."))
            return redirect(client)
        wa.record(None, LabMessage.Kind.STATEMENT, request.user, phone=client.whatsapp_phone, text=text,
                  client=client)
        return redirect(url)
    return render(request, "lab/statement.html", {
        "client": client, "form": form, "cases": cases, "payments": paid, "opening": opening,
        "cases_total": cases_total, "paid_total": paid_total, "closing": closing, "date_from": date_from,
        "date_to": date_to, "place": lab_branch()})


@role_required(*LAB_MONEY)
def prices(request):
    lists = list(LabPriceList.objects.filter(is_active=True))
    work_types = list(LabWorkType.objects.filter(is_active=True))
    current = {(p.price_list_id, p.work_type_id): p for p in LabPrice.objects.filter(price_list__in=lists)}
    list_form = PriceListForm(request.POST or None, prefix="list") if request.POST.get("add_list") else \
        PriceListForm(prefix="list")
    if request.method == "POST":
        if request.POST.get("add_list"):
            if list_form.is_valid():
                list_form.save()
                messages.success(request, _("Price list added."))
                return redirect("lab:prices")
        else:
            changed = 0
            with transaction.atomic():
                for price_list in lists:
                    for work_type in work_types:
                        raw = request.POST.get(f"p-{price_list.pk}-{work_type.pk}", "").strip().replace(",", "")
                        existing = current.get((price_list.pk, work_type.pk))
                        if not raw:
                            if existing is not None:
                                existing.delete()
                                changed += 1
                            continue
                        try:
                            value = Decimal(raw)
                        except ArithmeticError:
                            continue
                        if value < 0:
                            continue
                        if existing is None:
                            LabPrice.objects.create(price_list=price_list, work_type=work_type, price=value)
                            changed += 1
                        elif existing.price != value:
                            existing.price = value
                            existing.save(update_fields=["price"])
                            changed += 1
            messages.success(request, _("%(n)s prices saved.") % {"n": changed})
            return redirect("lab:prices")
    rows = [{"work_type": wt, "cells": [(pl, current.get((pl.pk, wt.pk))) for pl in lists]} for wt in work_types]
    clients = LabClient.objects.select_related("branch").order_by("price_list__name")
    return render(request, "lab/prices.html", {"lists": lists, "rows": rows, "list_form": list_form,
                                               "clients": clients})


@role_required(*LAB_DESK)
def payment_list(request):
    from apps.core.forms import DateRangeForm

    today = timezone.localdate()
    form = DateRangeForm(request.GET or None)
    payments = LabPayment.objects.select_related("client__branch", "received_by")
    date_from = date_to = None
    if form.is_valid():
        date_from, date_to = form.cleaned_data.get("date_from"), form.cleaned_data.get("date_to")
    if not request.GET:
        date_from, date_to = today.replace(day=1), today
    if date_from:
        payments = payments.filter(paid_on__gte=date_from)
    if date_to:
        payments = payments.filter(paid_on__lte=date_to)
    client_id = request.GET.get("client", "")
    if client_id.isdigit():
        payments = payments.filter(client_id=client_id)
    total = payments.filter(cancelled_at__isnull=True).aggregate(t=Sum("amount"))["t"] or 0
    by_method = dict(payments.filter(cancelled_at__isnull=True).values("method").annotate(t=Sum("amount"))
                     .values_list("method", "t"))
    from apps.academy.models import PaymentMethod

    methods = [(label, by_method[code]) for code, label in PaymentMethod.choices if code in by_method]
    page = Paginator(payments, 100).get_page(request.GET.get("page"))
    return render(request, "lab/payment_list.html", {
        "form": form, "page_obj": page, "total": total, "methods": methods, "date_from": date_from,
        "date_to": date_to})


@role_required(*LAB_DESK)
def payment_create(request):
    client = LabClient.objects.filter(pk=request.GET.get("client")).first() if str(
        request.GET.get("client", "")).isdigit() else None
    initial = {"client": client}
    if client is not None:
        balance = services.balances([client])[client.pk]["balance"]
        if balance > 0:
            initial["amount"] = balance
    form = PaymentForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        payment = form.save(commit=False)
        payment.received_by = request.user
        payment.save()
        messages.success(request, _("Receipt %(number)s saved.") % {"number": payment.number})
        return redirect(payment)
    return render(request, "includes/form_page.html", {
        "form": form, "title": _("New receipt of the lab"), "title_icon": "bi-cash-coin",
        "cancel_url": client.get_absolute_url() if client else reverse("lab:payments")})


@role_required(*LAB_DESK)
def payment_detail(request, pk):
    payment = get_object_or_404(LabPayment.objects.select_related("client__branch", "received_by", "cancelled_by"),
                                pk=pk)
    return render(request, "lab/receipt.html", {
        "payment": payment, "place": lab_branch(), "cancel_form": CancelForm(),
        "can_cancel": has_role(request.user, *LAB_MONEY) and not payment.is_cancelled,
        "balance": services.balances([payment.client])[payment.client_id]["balance"]})


@role_required(*LAB_MONEY)
@require_POST
def payment_cancel(request, pk):
    payment = get_object_or_404(LabPayment, pk=pk, cancelled_at__isnull=True)
    form = CancelForm(request.POST)
    if form.is_valid():
        payment.cancelled_at, payment.cancelled_by = timezone.now(), request.user
        payment.cancel_reason = form.cleaned_data["reason"]
        payment.save(update_fields=["cancelled_at", "cancelled_by", "cancel_reason"])
        messages.success(request, _("Receipt %(number)s cancelled. It stays in the list, crossed out.")
                         % {"number": payment.number})
    else:
        messages.error(request, _("Write why the receipt is cancelled."))
    return redirect(payment)


# ------------------------------------------------------------ report
@role_required(*LAB_MANAGERS)
def report(request):
    from apps.core.forms import DateRangeForm

    today = timezone.localdate()
    form = DateRangeForm(request.GET or None, initial={"date_from": today.replace(day=1), "date_to": today})
    date_from, date_to = today.replace(day=1), today
    if form.is_valid():
        date_from = form.cleaned_data.get("date_from") or date_from
        date_to = form.cleaned_data.get("date_to") or date_to
    with_money = has_role(request.user, *LAB_MONEY)
    data = stats.report(date_from, date_to, with_money=with_money)
    longest = max((row["average"] for row in data["steps"]), default=0) or 1
    for row in data["steps"]:
        row["width"] = max(3, round(100 * row["average"] / longest))
    return render(request, "lab/report.html", {"form": form, "data": data, "date_from": date_from,
                                               "date_to": date_to, "with_money": with_money})


# ------------------------------------------------------------ WhatsApp
@role_required(*LAB_DESK)
def whatsapp_page(request):
    query = request.GET.get("q", "").strip()
    found = []
    if query:
        for case in wa.cases_for(query):
            found.append({"case": case, "text": wa.status_text(case), "phone": case.whatsapp_phone})
    since = timezone.now() - timedelta(days=3)
    told = {(case_id, kind) for case_id, kind in LabMessage.objects.filter(sent_at__gte=since - timedelta(days=30))
            .values_list("case_id", "kind")}
    recent = open_cases().filter(received_at__gte=since)
    to_send = []
    for case in recent:
        if (case.pk, LabMessage.Kind.RECEIVED) not in told:
            to_send.append((case, LabMessage.Kind.RECEIVED, _("Case received")))
    for case in open_cases().filter(step=Step.READY):
        if (case.pk, LabMessage.Kind.READY) not in told:
            to_send.append((case, LabMessage.Kind.READY, _("Case ready")))
    for case in (LabCase.objects.filter(step=Step.DELIVERED, delivered_at__gte=since)
                 .select_related("client__branch")):
        if (case.pk, LabMessage.Kind.DELIVERED) not in told:
            to_send.append((case, LabMessage.Kind.DELIVERED, _("Case sent back")))
    options = LabSettings.get()
    return render(request, "lab/whatsapp.html", {
        "query": query, "found": found, "to_send": to_send, "options": options,
        "sent": LabMessage.objects.select_related("case", "by")[:30],
        "hook_url": request.build_absolute_uri(reverse("lab:whatsapp_hook"))})


@role_required(*LAB_DESK)
@require_POST
def whatsapp_answer(request, pk):
    case = get_object_or_404(LabCase.objects.select_related("client__branch"), pk=pk)
    phone = request.POST.get("phone", "").strip() or case.whatsapp_phone
    text = wa.status_text(case)
    url = wa.link(phone, text)
    if not url:
        messages.error(request, _("Write the mobile to answer."))
        return redirect(f"{reverse('lab:whatsapp')}?q={case.number}")
    wa.record(case, LabMessage.Kind.STATUS, request.user, phone=phone, text=text)
    return redirect(url)


@login_not_required
@csrf_exempt
def whatsapp_hook(request):
    """The WhatsApp Business platform calls this address: once to check it (GET), then with each message (POST)."""
    options = LabSettings.get()
    if request.method == "GET":
        if (options.wa_verify_token and request.GET.get("hub.mode") == "subscribe"
                and request.GET.get("hub.verify_token") == options.wa_verify_token):
            return HttpResponse(request.GET.get("hub.challenge", ""), content_type="text/plain")
        return HttpResponseForbidden()
    if request.method != "POST" or not options.auto_reply:
        return HttpResponseForbidden()
    if not wa.signature_ok(request.body, request.headers.get("X-Hub-Signature-256"), options.wa_app_secret):
        return HttpResponseForbidden()
    try:
        payload = json.loads(request.body.decode() or "{}")
    except ValueError:
        return HttpResponse(status=400)
    wa.handle_webhook(payload)
    return HttpResponse("ok")


# ------------------------------------------------------------ staff, options, the universal form
@role_required(*LAB_MANAGERS)
def staff(request):
    workers = LabWorker.objects.select_related("user").annotate(
        open_cases=Count("current_cases", filter=~Q(current_cases__step__in=CLOSED_STEPS)))
    return render(request, "lab/staff.html", {"workers": workers})


@role_required(*LAB_MANAGERS)
def worker_edit(request, pk=None):
    worker = get_object_or_404(LabWorker, pk=pk) if pk else None
    form = WorkerForm(request.POST or None, instance=worker)
    if not has_role(request.user, *LAB_MONEY):
        form.fields.pop("fee_per_unit")
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Saved."))
        return redirect("lab:staff")
    return render(request, "includes/form_page.html", {
        "form": form, "title": str(worker) if worker else _("Add to the lab staff"), "title_icon": "bi-person-gear",
        "cancel_url": reverse("lab:staff"),
        "intro": _("Tick the steps this person does: a case goes by itself to the only person who does a step.")})


@role_required(*LAB_MONEY)
def lab_settings(request):
    options = LabSettings.get()
    form = SettingsForm(request.POST or None, instance=options)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Saved."))
        return redirect("lab:settings")
    return render(request, "lab/settings.html", {
        "form": form, "hook_url": request.build_absolute_uri(reverse("lab:whatsapp_hook"))})


@role_required(*LAB_STAFF)
def universal_form(request):
    from apps.clinical.models import LabCategory

    groups = []
    for code, label in LabCategory.choices:
        types = [wt for wt in LabWorkType.objects.filter(is_active=True, category=code)]
        if types:
            groups.append((label, types))
    return render(request, "lab/universal_form.html", {
        "place": lab_branch(), "groups": groups, "enclosures": LabRequest.ENCLOSURES,
        "stages": LabRequest.Stage.choices, "impressions": LabCase.Impression.choices,
        "upper": [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28],
        "lower": [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38],
        "margins": LabRequest.Margin.choices, "pontics": LabRequest.Pontic.choices})


def lab_home_context(user):
    """The lab's part of the home page (for the lab staff, and the owner working at the lab)."""
    me = my_worker(user)
    context = {"lab_numbers": stats.home_numbers(me), "lab_me": me}
    if me is not None:
        context["lab_mine"] = list(open_cases().filter(worker=me).order_by("due_date", "pk")[:8])
    context["lab_late"] = list(open_cases().filter(due_date__lt=timezone.localdate()).order_by("due_date")[:8])
    if has_role(user, *LAB_MONEY):
        month = timezone.localdate().replace(day=1)
        start = stats.bounds(month, month)[0]
        context["lab_month"] = {
            "billed": LabCase.objects.filter(step=Step.DELIVERED, delivered_at__gte=start).aggregate(
                t=Sum("total"))["t"] or 0,
            "paid": LabPayment.objects.filter(cancelled_at__isnull=True, paid_on__gte=month).aggregate(
                t=Sum("amount"))["t"] or 0,
            "owed": sum((row["balance"] for row in services.balances().values() if row["balance"] > 0),
                        Decimal("0")),
        }
    return context

