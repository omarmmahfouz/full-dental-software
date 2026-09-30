"""The lab report: cases in and out, the time each step takes, the people, the remakes, the blocks and the money.
A few look-ups for any period, whatever the number of cases."""

from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal
from statistics import median

from django.db.models import Count, Sum
from django.utils import timezone

from apps.stock.models import StockMovement

from .models import (
    WORK_STEPS, LabBlock, LabBlockUse, LabCase, LabCaseItem, LabCaseStep, LabClient, LabOutsource, LabPayment,
    LabWorker, Step, lab_branch,
)
from .services import block_units


def bounds(date_from, date_to):
    tz = timezone.get_current_timezone()
    return (timezone.make_aware(datetime.combine(date_from, time.min), tz),
            timezone.make_aware(datetime.combine(date_to + timedelta(days=1), time.min), tz))


def _hours(start, end):
    return (end - start).total_seconds() / 3600


def step_times(start, end, category=None):
    """For each step finished in the period: how many, the average, the middle (median) and the longest time, in
    hours (waiting for the step included)."""
    rows = LabCaseStep.objects.filter(done_at__gte=start, done_at__lt=end, completed=True).exclude(
        step__in=(Step.DELIVERED, Step.CANCELLED))
    if category:
        rows = rows.filter(case__items__work_type__category=category).distinct()
    times = defaultdict(list)
    for step, started, done in rows.values_list("step", "started_at", "done_at"):
        times[step].append(_hours(started, done))
    order = {code: i for i, code in enumerate(Step.values)}
    labels = dict(Step.choices)
    return [{"step": step, "label": labels.get(step, step), "count": len(values),
             "average": sum(values) / len(values), "median": median(values), "longest": max(values)}
            for step, values in sorted(times.items(), key=lambda kv: order.get(kv[0], 99))]


def report(date_from, date_to, with_money=True):
    start, end = bounds(date_from, date_to)
    today = timezone.localdate()
    received = LabCase.objects.filter(received_at__gte=start, received_at__lt=end)
    delivered = list(LabCase.objects.filter(step=Step.DELIVERED, delivered_at__gte=start, delivered_at__lt=end)
                     .values("pk", "client_id", "received_at", "delivered_at", "due_date", "total"))
    delivered_ids = [row["pk"] for row in delivered]
    units_in = LabCaseItem.objects.filter(case__in=received).aggregate(n=Sum("units"))["n"] or 0

    # The kind of work of each case (its first item) and its units
    kinds, units = {}, Counter()
    for case_id, category, n in (LabCaseItem.objects.filter(case_id__in=delivered_ids).order_by("pk")
                                 .values_list("case_id", "work_type__category", "units")):
        kinds.setdefault(case_id, category)
        units[case_id] += n
    from apps.clinical.models import LabCategory

    category_labels = dict(LabCategory.choices)
    turnaround = defaultdict(lambda: {"cases": 0, "units": 0, "days": [], "on_time": 0})
    on_time = 0
    for row in delivered:
        kind = turnaround[kinds.get(row["pk"], LabCategory.OTHER)]
        kind["cases"] += 1
        kind["units"] += units[row["pk"]]
        if row["received_at"]:
            kind["days"].append(_hours(row["received_at"], row["delivered_at"]) / 24)
        in_time = row["due_date"] is None or timezone.localtime(row["delivered_at"]).date() <= row["due_date"]
        kind["on_time"] += in_time
        on_time += in_time
    by_kind = [{"kind": key, "label": category_labels.get(key, key), "cases": value["cases"], "units": value["units"],
                "days": sum(value["days"]) / len(value["days"]) if value["days"] else None,
                "on_time": round(100 * value["on_time"] / value["cases"]) if value["cases"] else None}
               for key, value in sorted(turnaround.items(), key=lambda kv: -kv[1]["cases"])]

    # Remakes
    remakes = LabCase.objects.filter(remake_of__isnull=False, created_at__gte=start, created_at__lt=end)
    remake_rows = list(remakes.values("pk", "remake_reason", "remake_fault", "client_id", "remake_of_id"))
    reasons = Counter(row["remake_reason"] for row in remake_rows)
    faults = Counter(row["remake_fault"] or LabCase.Fault.UNKNOWN for row in remake_rows)
    reason_labels, fault_labels = dict(LabCase.RemakeReason.choices), dict(LabCase.Fault.choices)

    # People: the steps each one finished, the units designed, the remakes of the cases they designed
    workers = {w.pk: w for w in LabWorker.objects.all()}
    done = (LabCaseStep.objects.filter(done_at__gte=start, done_at__lt=end, completed=True, worker__isnull=False,
                                       step__in=WORK_STEPS)
            .values_list("worker_id", "step", "case_id", "started_at", "done_at"))
    done = list(done)
    case_units = dict(LabCaseItem.objects.filter(case_id__in={row[2] for row in done})
                      .values("case").annotate(n=Sum("units")).values_list("case", "n"))
    people = defaultdict(lambda: {"steps": 0, "hours": [], "designed": 0, "cases": set()})
    for worker_id, step, case_id, started, finished in done:
        person = people[worker_id]
        person["steps"] += 1
        person["hours"].append(_hours(started, finished))
        person["cases"].add(case_id)
        if step == Step.DESIGN:
            person["designed"] += case_units.get(case_id, 0)
    designers = dict(LabCaseStep.objects.filter(case_id__in=[r["remake_of_id"] for r in remake_rows],
                                                step=Step.DESIGN, worker__isnull=False)
                     .values_list("case_id", "worker_id"))
    remakes_of = Counter(designers[r["remake_of_id"]] for r in remake_rows if r["remake_of_id"] in designers)
    staff = []
    for worker_id, person in people.items():
        worker = workers.get(worker_id)
        fee = (worker.fee_per_unit or 0) * person["designed"] if worker else 0
        staff.append({"worker": worker, "steps": person["steps"], "cases": len(person["cases"]),
                      "average": sum(person["hours"]) / len(person["hours"]), "designed": person["designed"],
                      "remakes": remakes_of.get(worker_id, 0), "fee": Decimal(fee)})
    staff.sort(key=lambda row: -row["steps"])

    # Clients
    client_names = {c.pk: c for c in LabClient.objects.select_related("branch")}
    in_by_client = Counter(dict(received.values("client").annotate(n=Count("id")).values_list("client", "n")))
    billed = defaultdict(Decimal)
    for row in delivered:
        billed[row["client_id"]] += row["total"] or 0
    paid = dict(LabPayment.objects.filter(cancelled_at__isnull=True, paid_on__range=(date_from, date_to))
                .values("client").annotate(t=Sum("amount")).values_list("client", "t"))
    remakes_by_client = Counter(row["client_id"] for row in remake_rows)
    clients = sorted(({"client": client_names.get(pk), "received": in_by_client.get(pk, 0),
                       "delivered": sum(1 for row in delivered if row["client_id"] == pk),
                       "billed": billed.get(pk, Decimal("0")), "paid": paid.get(pk) or Decimal("0"),
                       "remakes": remakes_by_client.get(pk, 0)}
                      for pk in set(in_by_client) | set(billed) | set(paid)), key=lambda row: -row["billed"])

    # Blocks
    opened = LabBlock.objects.filter(opened_at__gte=start, opened_at__lt=end).count()
    made = LabBlockUse.objects.filter(used_at__gte=start, used_at__lt=end).aggregate(n=Sum("units"))["n"] or 0
    per_block = block_units()
    finished_blocks = defaultdict(list)
    for block in LabBlock.objects.filter(status=LabBlock.Status.FINISHED).select_related("item"):
        finished_blocks[block.item].append((per_block.get(block.pk, 0), block.unit_cost))
    block_kinds = [{"item": item, "blocks": len(rows), "average": sum(n for n, _c in rows) / len(rows),
                    "cost_per_unit": (sum((c or 0) for _n, c in rows) / sum(n for n, _c in rows))
                    if sum(n for n, _c in rows) else None}
                   for item, rows in finished_blocks.items()]

    outsourced = LabOutsource.objects.filter(sent_at__gte=start, sent_at__lt=end)
    result = {
        "received": received.count(), "units_in": units_in, "delivered": len(delivered),
        "on_time": round(100 * on_time / len(delivered)) if delivered else None,
        "late_now": LabCase.objects.exclude(step__in=(Step.DELIVERED, Step.CANCELLED)).filter(due_date__lt=today).count(),
        "in_lab": LabCase.objects.exclude(step__in=(Step.DELIVERED, Step.CANCELLED, Step.INCOMING)).count(),
        "by_kind": by_kind, "steps": step_times(start, end),
        "remakes": len(remake_rows),
        "remake_rate": round(100 * len(remake_rows) / len(delivered), 1) if delivered else None,
        "reasons": [(reason_labels.get(k, k), n) for k, n in reasons.most_common()],
        "faults": [(fault_labels.get(k, k), n) for k, n in faults.most_common()],
        "staff": staff, "clients": clients,
        "blocks_opened": opened, "units_milled": made, "block_kinds": block_kinds,
        "outsourced": outsourced.count(),
    }
    if with_money:
        materials = Decimal("0")
        place = lab_branch()
        for quantity, cost, item_cost in (StockMovement.objects.filter(
                branch=place, kind__in=(StockMovement.Kind.OUT, StockMovement.Kind.WASTE), moved_at__gte=start,
                moved_at__lt=end).values_list("quantity", "unit_cost", "item__unit_cost")):
            materials += quantity * (cost if cost is not None else (item_cost or 0))
        outsourcing = outsourced.aggregate(t=Sum("cost"))["t"] or Decimal("0")
        fees = sum((row["fee"] for row in staff), Decimal("0"))
        billed_total = sum(billed.values(), Decimal("0"))
        received_money = sum((v or 0 for v in paid.values()), Decimal("0"))
        result.update({
            "billed": billed_total, "paid": received_money, "materials": materials, "outsourcing": outsourcing,
            "fees": fees, "costs": materials + outsourcing + fees, "left": billed_total - materials - outsourcing - fees,
        })
    return result


def board_counts():
    """{step: number of open cases} for the board and the home page."""
    return dict(LabCase.objects.exclude(step__in=(Step.DELIVERED, Step.CANCELLED)).values("step")
                .annotate(n=Count("id")).values_list("step", "n"))


def home_numbers(worker=None):
    """The numbers on the lab's home page."""
    today = timezone.localdate()
    start, end = bounds(today, today)
    open_cases = LabCase.objects.exclude(step__in=(Step.DELIVERED, Step.CANCELLED))
    numbers = {
        "incoming": open_cases.filter(step=Step.INCOMING).count(),
        "received_today": LabCase.objects.filter(received_at__gte=start, received_at__lt=end).count(),
        "to_give_out": open_cases.filter(step=Step.RECEIVED).count(),
        "in_work": open_cases.exclude(step__in=(Step.INCOMING, Step.RECEIVED, Step.READY)).count(),
        "due_today": open_cases.filter(due_date=today).exclude(step=Step.INCOMING).count(),
        "late": open_cases.filter(due_date__lt=today).count(),
        "ready": open_cases.filter(step=Step.READY).count(),
        "delivered_today": LabCase.objects.filter(delivered_at__gte=start, delivered_at__lt=end).count(),
        "remakes_month": LabCase.objects.filter(remake_of__isnull=False,
                                                created_at__gte=bounds(today.replace(day=1), today)[0]).count(),
        "unassigned": open_cases.filter(step__in=WORK_STEPS, worker__isnull=True).count(),
    }
    if worker is not None:
        numbers["mine"] = open_cases.filter(worker=worker).count()
    return numbers

