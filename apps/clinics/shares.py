"""What each doctor earned at a place, from the services they gave and their visits.

- The services counted are those given at the place with the doctor named on them (on the bill line, else
  on the bill), by the date the service was given.
- A percentage is taken of what the patient has paid for that service so far (not of what is still owed),
  so the share grows as the patient pays.
- A fixed amount is for each service, times the number of teeth written on it (1 when none are written).
- A fixed amount for each visit counts the doctor's finished visits at the place (patient left).
- A rule for one service comes before the rule for every service; a rule for the doctor's own patients (the
  patient's file says he brought him) or for the clinic's patients comes before a rule for every patient; among
  rules of the same kind, the newest one that applies on the day counts.
- A percentage can be taken after the lab and implant cost of the service (the cost on the bill line)."""

from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from apps.billing.models import Charge, paid_by_charge
from apps.core.utils import minutes_between
from apps.scheduling.models import Appointment

from .models import DoctorPayout, FeeRule

CENT = Decimal("0.01")
ZERO = Decimal("0")
M = FeeRule.Method


def source_of(dentist_id, brought_by_id):
    """Whose patient it is for this doctor: his own (he brought him) or the clinic's."""
    return FeeRule.OWN if brought_by_id is not None and brought_by_id == dentist_id else FeeRule.CLINIC


def pick_rule(rules, service_id, day, source=""):
    """The rule that pays for ``service_id`` on ``day`` for a patient of ``source`` (None when no rule applies)."""
    live = [rule for rule in rules if rule.applies_on(day)]
    pools = ([[rule for rule in live if rule.service_id == service_id]] if service_id is not None else []) + \
        [[rule for rule in live if rule.service_id is None]]
    for pool in pools:
        for wanted in ((source, "") if source else ("",)):
            found = [rule for rule in pool if rule.patient_source == wanted]
            if found:
                return max(found, key=lambda rule: (rule.starts_on, rule.pk))
    return None


def teeth_count(teeth):
    from apps.charting.teeth import parse_teeth

    return max(len(parse_teeth(teeth)), 1)


def units(charge):
    return teeth_count(charge.teeth)


def line_share(rule, paid, teeth, cost=ZERO):
    """The doctor's share of one service under ``rule`` (after its lab / implant ``cost`` when the rule says so)."""
    if rule is not None and rule.method == M.PERCENT:
        base = max(paid - (cost or ZERO), ZERO) if rule.deduct_costs else paid
        return (base * rule.value / 100).quantize(CENT)
    if rule is not None and rule.method == M.PER_UNIT:
        return rule.value * teeth_count(teeth)
    return ZERO


def visit_share(rules, day, source=""):
    rule = pick_rule([r for r in rules if r.service_id is None], None, day, source)
    return rule.value if rule is not None and rule.method == M.PER_VISIT else ZERO


def _bounds(date_from, date_to):
    start = timezone.make_aware(datetime.combine(date_from, time.min))
    end = timezone.make_aware(datetime.combine(date_to + timedelta(days=1), time.min))
    return start, end


def doctor_charges(dentist, branch):
    return Charge.objects.filter(branch=branch).filter(
        Q(dentist=dentist) | Q(dentist__isnull=True, bill__dentist=dentist))


def _rules(dentist, branch):
    return list(FeeRule.objects.filter(dentist=dentist, branch=branch).select_related("service"))


def statement(dentist, branch, date_from, date_to, accounts=None):
    """The doctor's services, visits, share and payments at ``branch`` between the two dates, line by line."""
    rules = _rules(dentist, branch)
    accounts = {} if accounts is None else accounts
    lines = []
    charges = list(doctor_charges(dentist, branch).filter(charged_on__range=(date_from, date_to))
                   .select_related("service", "patient", "bill").order_by("charged_on", "pk"))
    accounts.update(paid_by_charge({charge.patient_id for charge in charges} - set(accounts)))
    for charge in charges:
        paid = accounts[charge.patient_id].get(charge.pk, ZERO)
        source = source_of(dentist.pk, charge.patient.brought_by_id)
        rule = pick_rule(rules, charge.service_id, charge.charged_on, source)
        lines.append({"charge": charge, "net": charge.net, "paid": paid, "rule": rule, "source": source,
                      "cost": charge.cost if rule is not None and rule.deduct_costs else ZERO,
                      "share": line_share(rule, paid, charge.teeth, charge.cost), "units": units(charge)})

    start, end = _bounds(date_from, date_to)
    visits = []
    appointments = (Appointment.objects.filter(branch=branch, dentist=dentist, status=Appointment.Status.COMPLETED,
                                               scheduled_at__gte=start, scheduled_at__lt=end)
                    .select_related("patient").order_by("scheduled_at"))
    for visit in appointments:
        day = timezone.localtime(visit.scheduled_at).date()
        source = source_of(dentist.pk, visit.patient.brought_by_id)
        visits.append({"visit": visit, "minutes": visit.chair_minutes or 0, "share": visit_share(rules, day, source)})

    payouts = list(DoctorPayout.objects.filter(dentist=dentist, branch=branch, paid_on__range=(date_from, date_to)))
    services_share = sum((line["share"] for line in lines), ZERO)
    visits_share = sum((row["share"] for row in visits), ZERO)
    patients = {line["charge"].patient_id for line in lines} | {row["visit"].patient_id for row in visits}
    return {
        "dentist": dentist, "branch": branch, "date_from": date_from, "date_to": date_to, "rules": rules,
        "lines": lines, "visits": visits, "payouts": payouts,
        "billed": sum((line["net"] for line in lines), ZERO),
        "collected": sum((line["paid"] for line in lines), ZERO),
        "costs": sum((line["cost"] for line in lines), ZERO),
        "services_share": services_share, "visits_share": visits_share, "share": services_share + visits_share,
        "paid_out": sum((p.amount for p in payouts), ZERO),
        "visit_count": len(visits), "chair_minutes": sum(row["minutes"] for row in visits),
        "patient_count": len(patients),
    }


def totals(dentist, branch, date_from, date_to, accounts=None, rules=None):
    """The numbers of ``statement`` without its lines, read lightly so that years of work stay quick.
    ``date_from`` None counts from the first day."""
    rules = _rules(dentist, branch) if rules is None else rules
    accounts = {} if accounts is None else accounts
    charges = doctor_charges(dentist, branch).filter(charged_on__lte=date_to)
    appointments = Appointment.objects.filter(branch=branch, dentist=dentist, status=Appointment.Status.COMPLETED,
                                              scheduled_at__lt=_bounds(date_to, date_to)[1])
    if date_from is not None:
        charges = charges.filter(charged_on__gte=date_from)
        appointments = appointments.filter(scheduled_at__gte=_bounds(date_from, date_from)[0])
    charges = list(charges.order_by().values_list("pk", "patient_id", "service_id", "charged_on", "teeth", "price",
                                                  "discount_percent", "cost", "patient__brought_by_id"))
    accounts.update(paid_by_charge({row[1] for row in charges} - set(accounts)))
    billed = collected = services_share = visits_share = costs = ZERO
    patients = set()
    for pk, patient_id, service_id, day, teeth, price, percent, cost, brought_by in charges:
        paid = accounts[patient_id].get(pk, ZERO)
        billed += price - (price * percent / 100).quantize(CENT)
        collected += paid
        rule = pick_rule(rules, service_id, day, source_of(dentist.pk, brought_by))
        services_share += line_share(rule, paid, teeth, cost)
        if rule is not None and rule.deduct_costs:
            costs += cost
        patients.add(patient_id)
    visit_count = chair_minutes = 0
    per_visit = any(rule.method == M.PER_VISIT for rule in rules)
    for patient_id, scheduled_at, entered, left, brought_by in appointments.order_by().values_list(
            "patient_id", "scheduled_at", "entered_room_at", "left_at", "patient__brought_by_id"):
        visit_count += 1
        chair_minutes += minutes_between(entered, left) or 0
        patients.add(patient_id)
        if per_visit:
            visits_share += visit_share(rules, timezone.localtime(scheduled_at).date(), source_of(dentist.pk, brought_by))
    return {"dentist": dentist, "branch": branch, "rules": rules, "billed": billed, "collected": collected,
            "costs": costs, "services_share": services_share, "visits_share": visits_share, "share": services_share + visits_share,
            "visit_count": visit_count, "chair_minutes": chair_minutes, "patient_count": len(patients)}


def owed(dentist, branch, until, accounts=None, rules=None):
    """What the doctor earned at the place up to ``until``, less what they were paid up to then."""
    earned = totals(dentist, branch, None, until, accounts, rules)["share"]
    paid = DoctorPayout.objects.filter(dentist=dentist, branch=branch, paid_on__lte=until).aggregate(
        total=Sum("amount"))["total"] or ZERO
    return earned - paid


def doctors_at(branch, date_from, date_to):
    """Every doctor with a rule, a service or a visit at the place in the period."""
    from apps.dentists.models import Dentist

    start, end = _bounds(date_from, date_to)
    ids = set(FeeRule.objects.filter(branch=branch, is_active=True).values_list("dentist_id", flat=True))
    charges = Charge.objects.filter(branch=branch, charged_on__range=(date_from, date_to))
    ids |= set(charges.exclude(dentist=None).values_list("dentist_id", flat=True))
    ids |= set(charges.filter(dentist=None).exclude(bill__dentist=None).values_list("bill__dentist_id", flat=True))
    ids |= set(Appointment.objects.filter(branch=branch, scheduled_at__gte=start, scheduled_at__lt=end)
               .exclude(dentist=None).values_list("dentist_id", flat=True))
    return Dentist.objects.filter(pk__in=ids).order_by("full_name")


def summary(branch, date_from, date_to):
    """One row per doctor at the place, with the place's totals."""
    # What is paid on every service ever given at the place, read once for all the doctors.
    accounts = paid_by_charge(Charge.objects.filter(branch=branch, charged_on__lte=date_to).values("patient_id"))
    rows = []
    for dentist in doctors_at(branch, date_from, date_to):
        rules = _rules(dentist, branch)
        data = totals(dentist, branch, date_from, date_to, accounts, rules)
        data["paid_out"] = DoctorPayout.objects.filter(dentist=dentist, branch=branch,
                                                       paid_on__range=(date_from, date_to)).aggregate(
            total=Sum("amount"))["total"] or ZERO
        data["owed"] = owed(dentist, branch, date_to, accounts, rules)
        rows.append(data)
    sums = defaultdict(lambda: ZERO)
    sums.update(visit_count=0, chair_minutes=0)
    for row in rows:
        for key in ("billed", "collected", "share", "paid_out", "owed", "visit_count", "chair_minutes"):
            sums[key] += row[key]
    return rows, dict(sums)
