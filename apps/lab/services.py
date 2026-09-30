"""Every change of a lab case goes through here, so its steps, times, people and notifications always agree."""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.clinical.models import LabCategory, LabRequest
from apps.core.models import Notification, staff_at
from apps.core.notify import notify_roles, notify_users
from apps.core.roles import LAB_HEAD, LAB_MANAGER, LAB_SECRETARY, SECRETARY

from .models import (
    CLOSED_STEPS, ROUTES, WORK_STEPS, LabBlock, LabBlockUse, LabCase, LabCaseItem, LabCaseStep,
    LabClient, LabOutsource, LabPayment, LabPrice, LabWorker, Step,
)


# ------------------------------------------------------------ prices
def price_for(client, work_type):
    """The client's price for this work (its price list), or None when the list has no price for it."""
    if client is None or not client.price_list_id:
        return None
    return (LabPrice.objects.filter(price_list_id=client.price_list_id, work_type=work_type)
            .values_list("price", flat=True).first())


def fill_prices(case):
    """Items without a price take the client's price list; then the total of the case is kept."""
    for item in case.items.select_related("work_type"):
        if item.unit_price is None:
            price = price_for(case.client, item.work_type)
            if case.is_remake and case.remake_fault == LabCase.Fault.LAB:
                price = Decimal("0")  # the lab's own mistake is remade free
            if price is not None:
                LabCaseItem.objects.filter(pk=item.pk).update(unit_price=price)
    total = case.recalc()
    if case.request_id and case.request.lab_cost is None and total:
        # Our place's lab cost (taken off the doctor's share where the clinic's rule says so).
        LabRequest.objects.filter(pk=case.request_id).update(lab_cost=total)
    return total


# ------------------------------------------------------------ the road of a case
def route_for(case):
    """The usual steps of the case's work: the kind of its first item; a conventional impression adds models first."""
    item = case.items.select_related("work_type").first()
    category = item.work_type.category if item else LabCategory.OTHER
    route = list(ROUTES.get(category, ROUTES[LabCategory.OTHER]))
    if case.impression == LabCase.Impression.CONVENTIONAL and Step.MODELS not in route and Step.DESIGN in route:
        route.insert(route.index(Step.DESIGN), Step.MODELS)  # pour and scan the impression before the design
    return [str(code) for code in route]


def next_step(case):
    """The step that comes next on the case's road. After a hold the paused step goes on; after a try-in or another
    lab, the step after the last one finished."""
    route = case.route or route_for(case)
    if case.step in CLOSED_STEPS:
        return None
    if case.step in route:
        return _after(route, case.step)
    last = case.steps.filter(step__in=route).order_by("-started_at", "-pk").first()
    if last is None:
        return route[0]
    if not last.completed:
        return last.step
    return _after(route, last.step)


def _after(route, step):
    index = route.index(step)
    return route[index + 1] if index + 1 < len(route) else Step.DELIVERED


def default_worker(step):
    """The one person who does this step, when there is only one: the case goes to them by itself."""
    if step not in WORK_STEPS:
        return None
    people = [worker for worker in LabWorker.objects.filter(is_active=True) if worker.does(step)]
    return people[0] if len(people) == 1 else None


@transaction.atomic
def move(case, to_step, user, worker=None, notes="", now=None, tell_clinic=True):
    """Close the step the case is in and open ``to_step`` (with the person who will do it)."""
    now = now or timezone.now()
    to_step = str(to_step)
    if to_step not in Step.values:
        raise ValidationError(_("Unknown step."))
    if to_step == case.step:
        raise ValidationError(_("The case is already in this step."))
    if to_step == Step.INCOMING:
        raise ValidationError(_("A case cannot go back on the way to the lab."))
    current = case.steps.filter(done_at__isnull=True).order_by("-pk").first()
    if current is not None:
        current.done_at = now
        current.done_by = user
        current.completed = to_step != Step.ON_HOLD
        if notes and not current.notes:
            current.notes = notes[:255]
        current.save(update_fields=["done_at", "done_by", "completed", "notes"])
    if worker is None and to_step in WORK_STEPS:
        worker = default_worker(to_step)
    if to_step not in WORK_STEPS:
        worker = None
    LabCaseStep.objects.create(case=case, step=to_step, worker=worker, started_at=now,
                               done_at=now if to_step in CLOSED_STEPS else None,
                               done_by=user if to_step in CLOSED_STEPS else None,
                               notes=notes[:255] if to_step in CLOSED_STEPS else "")
    case.step, case.step_since, case.worker = to_step, now, worker
    fields = ["step", "step_since", "worker", "updated_at"]
    if to_step == Step.DELIVERED:
        case.delivered_at, case.delivered_by = now, user
        fields += ["delivered_at", "delivered_by"]
    elif case.delivered_at and to_step not in CLOSED_STEPS:
        case.delivered_at = case.delivered_by = None  # opened again (a mistake)
        fields += ["delivered_at", "delivered_by"]
    case.save(update_fields=fields)
    if worker is not None and worker.user_id and worker.user != user:
        notify_users([worker.user], _("Lab case %(number)s is yours: %(step)s"), _("%(work)s · due %(due)s"),
                     case.get_absolute_url(), Notification.Level.INFO,
                     params={"number": case.number, "step": case.get_step_display(), "work": case.work_summary(),
                             "due": case.due_date.strftime("%d/%m/%Y") if case.due_date else "—"})
    if to_step == Step.READY:
        notify_roles((LAB_SECRETARY,), _("Lab case %(number)s is ready to deliver"), _("%(client)s · %(patient)s"),
                     case.get_absolute_url(), Notification.Level.SUCCESS, exclude=user,
                     params={"number": case.number, "client": str(case.client), "patient": case.patient_name})
    if to_step == Step.DELIVERED and tell_clinic and clinic_request(case) is not None:
        _tell_the_clinic(case, user)
    return case


def assign(case, worker, user):
    """Give the step the case is in now to someone (or to nobody)."""
    if case.step not in WORK_STEPS:
        raise ValidationError(_("Nobody works on a case in this step."))
    current = case.steps.filter(done_at__isnull=True).order_by("-pk").first()
    if current is not None:
        current.worker = worker
        current.save(update_fields=["worker"])
    case.worker = worker
    case.save(update_fields=["worker", "updated_at"])
    if worker is not None and worker.user_id and worker.user != user:
        notify_users([worker.user], _("Lab case %(number)s is yours: %(step)s"), _("%(work)s · due %(due)s"),
                     case.get_absolute_url(), Notification.Level.INFO,
                     params={"number": case.number, "step": case.get_step_display(), "work": case.work_summary(),
                             "due": case.due_date.strftime("%d/%m/%Y") if case.due_date else "—"})


def clinic_request(case):
    """The lab request of our place behind a case (a remake's is the first case's)."""
    seen = 0
    while case is not None and seen < 20:
        if case.request_id:
            return case.request
        case, seen = case.remake_of, seen + 1
    return None


def _tell_the_clinic(case, user):
    """The work goes back to one of our places: its reception is told to expect it (and checks it on arrival)."""
    lab_request = clinic_request(case)
    users = list(staff_at(lab_request.branch, SECRETARY)) + [
        lab_request.dentist.user if lab_request.dentist_id else None]
    notify_users(users, _("Lab work %(number)s left the lab: it is on its way back"), _("Patient: %(patient)s"),
                 lab_request.get_absolute_url(), Notification.Level.INFO, exclude=user,
                 params={"number": lab_request.number, "patient": lab_request.patient.full_name})


# ------------------------------------------------------------ a case comes in
@transaction.atomic
def start_case(case, user, received=True, now=None):
    """A new case saved with its items: its road, its prices, and its first step (received, or on the way)."""
    now = now or timezone.now()
    if not case.route:
        case.route = route_for(case)
    if received:
        case.received_at = case.received_at or now
        case.received_by = case.received_by or user
        case.step = str(case.route[0]) if case.route else Step.RECEIVED
    else:
        case.step = Step.INCOMING
    if not case.due_date:
        days = max((item.work_type.default_days or 0 for item in case.items.select_related("work_type")), default=0)
        if days:
            case.due_date = timezone.localdate(now) + timedelta(days=days)
    case.step_since = now
    case.save()
    LabCaseStep.objects.create(case=case, step=case.step, started_at=now)
    fill_prices(case)
    if received:
        notify_roles((LAB_MANAGER, LAB_HEAD), _("New lab case %(number)s to give out"), _("%(client)s · %(work)s"),
                     case.get_absolute_url(), Notification.Level.INFO, exclude=user,
                     params={"number": case.number, "client": str(case.client), "work": case.work_summary()})
    return case


@transaction.atomic
def receive(case, user, enclosures=None, notes="", now=None):
    """A case on the way (from one of our places) arrives: checked against the request, then it waits to start."""
    if case.step != Step.INCOMING:
        raise ValidationError(_("This case is already at the lab."))
    now = now or timezone.now()
    if enclosures is not None:
        case.enclosures = list(enclosures)
    case.received_at, case.received_by = now, user
    case.save(update_fields=["enclosures", "received_at", "received_by", "updated_at"])
    first = case.route[0] if case.route else Step.RECEIVED
    move(case, first, user, notes=notes, now=now)
    notify_roles((LAB_MANAGER, LAB_HEAD), _("New lab case %(number)s to give out"), _("%(client)s · %(work)s"),
                 case.get_absolute_url(), Notification.Level.INFO, exclude=user,
                 params={"number": case.number, "client": str(case.client), "work": case.work_summary()})
    return case


def client_for_place(branch):
    """The lab's client for one of our places (made the first time, with the place's price list)."""
    from .models import LabPriceList

    client = LabClient.objects.filter(branch=branch).first()
    if client is None:
        price_list, _created = LabPriceList.objects.get_or_create(name=f"{branch.badge} prices")
        client = LabClient.objects.create(name=branch.name_ar, kind=LabClient.Kind.PLACE, branch=branch,
                                          price_list=price_list, phone=branch.phone)
    return client


SHADE_PARTS = (("shade_cervical", _("cervical")), ("shade_incisal", _("incisal")), ("stump_shade", _("stump")))


def shade_text(lab_request):
    parts = [lab_request.shade] if lab_request.shade else []
    extra = [f"{label} {getattr(lab_request, name)}" for name, label in SHADE_PARTS if getattr(lab_request, name)]
    text = " ".join(parts)
    if extra:
        text += f" ({', '.join(str(e) for e in extra)})"
    return text.strip()


@transaction.atomic
def case_from_request(lab_request, user, remake_of=None, reason="", notes=""):
    """A lab request of our place sent to our own lab: the case waits at the lab as "on the way"."""
    existing = getattr(lab_request, "lab_case", None) if remake_of is None else None
    if existing is not None:
        return existing
    dentist = lab_request.dentist
    case = LabCase(
        client=client_for_place(lab_request.branch), request=None if remake_of else lab_request,
        doctor=dentist.full_name if dentist else "", doctor_phone=dentist.phone if dentist else "",
        patient_name=lab_request.patient.full_name,
        impression=(LabCase.Impression.DIGITAL if lab_request.work_form == LabRequest.WorkForm.DIGITAL
                    else LabCase.Impression.CONVENTIONAL),
        enclosures=list(lab_request.enclosures or []), stage=lab_request.stage, shade=shade_text(lab_request),
        instructions="\n".join(filter(None, [lab_request.instructions, notes])), due_date=lab_request.due_date,
        remake_of=remake_of, remake_reason=reason if remake_of else "",
        remake_fault=LabCase.Fault.UNKNOWN if remake_of else "", created_by=user,
    )
    case.save()
    LabCaseItem.objects.create(case=case, work_type=lab_request.work_type, teeth=lab_request.teeth,
                               units=lab_request.units or 1, material=lab_request.material)
    start_case(case, user, received=False)
    return case


def clinic_received(lab_request, user):
    """The clinic checked the work back in: the lab's case is closed as delivered if the lab had not done it."""
    for case in LabCase.objects.filter(request=lab_request).exclude(step__in=CLOSED_STEPS):
        move(case, Step.DELIVERED, user, notes=str(_("Received back by the clinic")), tell_clinic=False)
    for case in LabCase.objects.filter(remake_of__request=lab_request).exclude(step__in=CLOSED_STEPS):
        move(case, Step.DELIVERED, user, notes=str(_("Received back by the clinic")), tell_clinic=False)


def request_remade(lab_request, user, notes=""):
    """The clinic returned the work for a remake: a remake case on its way to our lab, linked to the first one."""
    first = getattr(lab_request, "lab_case", None)
    if first is None:
        return case_from_request(lab_request, user)
    return case_from_request(lab_request, user, remake_of=first, reason=LabCase.RemakeReason.OTHER, notes=notes)


@transaction.atomic
def make_remake(case, user, reason, fault, notes="", in_hand=True):
    """The work came back (or failed the check): a new case, linked to the first, on the same road. The lab's own
    mistake is remade free."""
    remake = LabCase.objects.create(
        client=case.client, remake_of=case, remake_reason=reason, remake_fault=fault, doctor=case.doctor,
        doctor_phone=case.doctor_phone, patient_name=case.patient_name, impression=case.impression,
        enclosures=case.enclosures, stage=case.stage, shade=case.shade,
        instructions="\n".join(filter(None, [notes, case.instructions])), urgent=True, created_by=user,
        route=case.route,
    )
    for item in case.items.all():
        LabCaseItem.objects.create(case=remake, work_type=item.work_type, teeth=item.teeth, units=item.units,
                                   material=item.material,
                                   unit_price=Decimal("0") if fault == LabCase.Fault.LAB else item.unit_price)
    start_case(remake, user, received=in_hand)
    notify_roles((LAB_HEAD,), _("Remake of lab case %(number)s"), "%(reason)s", remake.get_absolute_url(),
                 Notification.Level.WARNING, exclude=user,
                 params={"number": case.number, "reason": remake.get_remake_reason_display()})
    return remake


# ------------------------------------------------------------ another lab, blocks
@transaction.atomic
def outsource(case, lab, work, user, cost=None, due_date=None, notes=""):
    sent = LabOutsource.objects.create(case=case, lab=lab, work=work, cost=cost, due_date=due_date, notes=notes,
                                       sent_by=user)
    move(case, Step.OUTSOURCED, user, notes=str(lab))
    return sent


@transaction.atomic
def outsource_back(sent, user, cost=None):
    sent.back_at = timezone.now()
    if cost is not None:
        sent.cost = cost
    sent.save(update_fields=["back_at", "cost"])
    case = sent.case
    if case.step == Step.OUTSOURCED:
        move(case, next_step(case), user)
    return sent


@transaction.atomic
def open_block(item, user, code="", lot="", shade="", notes=""):
    """A new block or disc is taken out of the lab's stock and opened for milling."""
    from apps.stock.models import StockMovement
    from apps.stock.services import record_movement

    from .models import lab_branch

    block = LabBlock.objects.create(item=item, code=code, lot=lot, shade=shade, notes=notes, opened_by=user,
                                    unit_cost=item.unit_cost)
    record_movement(item, StockMovement.Kind.OUT, 1, user, branch=lab_branch(), lot=lot,
                    destination=str(_("Block %(code)s opened") % {"code": block.code}))
    return block


def use_block(block, case, units, user):
    if block.status != LabBlock.Status.IN_USE:
        raise ValidationError(_("This block is finished."))
    return LabBlockUse.objects.create(block=block, case=case, units=units, by=user)


def finish_block(block, status=LabBlock.Status.FINISHED):
    block.status = status
    block.finished_at = timezone.now()
    block.save(update_fields=["status", "finished_at"])
    return block


def block_units():
    """{block id: units made from it}."""
    return dict(LabBlockUse.objects.values("block").annotate(n=Sum("units")).values_list("block", "n"))


# ------------------------------------------------------------ money
def balances(clients=None):
    """{client id: {"billed", "paid", "balance", "in_work"}}: what was delivered, paid, owed, and the work still in the
    lab. A few look-ups, whatever the number of cases."""
    cases = LabCase.objects.exclude(step=Step.CANCELLED)
    payments = LabPayment.objects.filter(cancelled_at__isnull=True)
    if clients is not None:
        ids = [c.pk for c in clients]
        cases, payments = cases.filter(client_id__in=ids), payments.filter(client_id__in=ids)
    billed = dict(cases.filter(step=Step.DELIVERED).values("client").annotate(t=Sum("total"))
                  .values_list("client", "t"))
    in_work = dict(cases.exclude(step=Step.DELIVERED).values("client").annotate(t=Sum("total"))
                   .values_list("client", "t"))
    paid = dict(payments.values("client").annotate(t=Sum("amount")).values_list("client", "t"))
    result = {}
    for pk in set(billed) | set(paid) | set(in_work) | {c.pk for c in clients or []}:
        b, p = billed.get(pk) or Decimal("0"), paid.get(pk) or Decimal("0")
        result[pk] = {"billed": b, "paid": p, "balance": b - p, "in_work": in_work.get(pk) or Decimal("0")}
    return result
