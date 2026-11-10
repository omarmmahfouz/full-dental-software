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


# A service or a visit read lightly (no model objects): only what the sums need.
CHARGE_FIELDS = ("pk", "patient_id", "service_id", "charged_on", "teeth", "price", "discount_percent", "cost",
                 "patient__brought_by_id")
VISIT_FIELDS = ("patient_id", "scheduled_at", "entered_room_at", "left_at", "patient__brought_by_id")


def _sum_services(dentist_pk, charges, rules, accounts):
    """The sums of a doctor's services (rows of ``CHARGE_FIELDS``) and the patients they were for."""
    billed = collected = share = costs = ZERO
    patients = set()
    for pk, patient_id, service_id, day, teeth, price, percent, cost, brought_by in charges:
        paid = accounts[patient_id].get(pk, ZERO)
        billed += price - (price * percent / 100).quantize(CENT)
        collected += paid
        rule = pick_rule(rules, service_id, day, source_of(dentist_pk, brought_by))
        share += line_share(rule, paid, teeth, cost)
        if rule is not None and rule.deduct_costs:
            costs += cost
        patients.add(patient_id)
    return {"billed": billed, "collected": collected, "costs": costs, "services_share": share}, patients


def _sum_visits(dentist_pk, visits, rules):
    """The number, the chair time and the share of a doctor's finished visits (rows of ``VISIT_FIELDS``)."""
    count = minutes = 0
    share = ZERO
    patients = set()
    per_visit = _paid_by_visit(rules)
    for patient_id, scheduled_at, entered, left, brought_by in visits:
        count += 1
        minutes += minutes_between(entered, left) or 0
        patients.add(patient_id)
        if per_visit:
            share += visit_share(rules, timezone.localtime(scheduled_at).date(), source_of(dentist_pk, brought_by))
    return {"visit_count": count, "chair_minutes": minutes, "visits_share": share}, patients


def _paid_by_visit(rules):
    return any(rule.method == M.PER_VISIT for rule in rules)


def _finished_visits(branch, date_from, date_to):
    visits = Appointment.objects.filter(branch=branch, status=Appointment.Status.COMPLETED,
                                        scheduled_at__lt=_bounds(date_to, date_to)[1])
    if date_from is not None:
        visits = visits.filter(scheduled_at__gte=_bounds(date_from, date_from)[0])
    return visits.order_by()


def totals(dentist, branch, date_from, date_to, accounts=None, rules=None):
    """The numbers of ``statement`` without its lines, read lightly so that years of work stay quick.
    ``date_from`` None counts from the first day."""
    rules = _rules(dentist, branch) if rules is None else rules
    accounts = {} if accounts is None else accounts
    charges = doctor_charges(dentist, branch).filter(charged_on__lte=date_to)
    if date_from is not None:
        charges = charges.filter(charged_on__gte=date_from)
    charges = list(charges.order_by().values_list(*CHARGE_FIELDS))
    missing = {row[1] for row in charges} - set(accounts)
    if missing:
        accounts.update(paid_by_charge(missing))
    services, patients = _sum_services(dentist.pk, charges, rules, accounts)
    visits, seen = _sum_visits(dentist.pk, _finished_visits(branch, date_from, date_to).filter(dentist=dentist)
                               .values_list(*VISIT_FIELDS), rules)
    return {"dentist": dentist, "branch": branch, "rules": rules, **services, **visits,
            "share": services["services_share"] + visits["visits_share"], "patient_count": len(patients | seen)}


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
    """One row per doctor at the place, with the place's totals. Everything is read once for all the doctors (the
    services, the visits, the rules, the payouts) and shared out here: it was eight look-ups for each doctor, each
    reading his services from the first day (4 seconds at a clinic with two years of work)."""
    dentists = list(doctors_at(branch, date_from, date_to))
    ids = [dentist.pk for dentist in dentists]
    rules = defaultdict(list)
    for rule in FeeRule.objects.filter(branch=branch, dentist__in=ids).select_related("service"):
        rules[rule.dentist_id].append(rule)
    # Every service given at the place up to the last day: what is owed counts from the first day.
    services = defaultdict(list)
    for row in (Charge.objects.filter(branch=branch, charged_on__lte=date_to)
                .filter(Q(dentist__in=ids) | Q(dentist__isnull=True, bill__dentist__in=ids)).order_by()
                .values_list(*CHARGE_FIELDS, "dentist_id", "bill__dentist_id")):
        services[row[-2] or row[-1]].append(row[:-2])
    accounts = paid_by_charge(Charge.objects.filter(branch=branch, charged_on__lte=date_to).values("patient_id"))
    visits = defaultdict(list)
    for row in _finished_visits(branch, date_from, date_to).filter(dentist__in=ids).values_list(
            *VISIT_FIELDS, "dentist_id"):
        visits[row[-1]].append(row[:-1])
    # The visits before the period count only for a doctor paid by the visit.
    by_visit = [pk for pk in ids if _paid_by_visit(rules[pk])]
    earlier = defaultdict(list)
    if by_visit:
        before = date_from - timedelta(days=1)
        for row in _finished_visits(branch, None, before).filter(dentist__in=by_visit).values_list(
                *VISIT_FIELDS, "dentist_id"):
            earlier[row[-1]].append(row[:-1])
    paid_out, paid_ever = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    for dentist_id, paid_on, amount in DoctorPayout.objects.filter(
            branch=branch, dentist__in=ids, paid_on__lte=date_to).values_list("dentist_id", "paid_on", "amount"):
        paid_ever[dentist_id] += amount
        if paid_on >= date_from:
            paid_out[dentist_id] += amount
    rows = []
    for dentist in dentists:
        mine, ever = rules[dentist.pk], services[dentist.pk]
        period, patients = _sum_services(dentist.pk, [row for row in ever if row[3] >= date_from], mine, accounts)
        seen, visited = _sum_visits(dentist.pk, visits[dentist.pk], mine)
        earned = _sum_services(dentist.pk, ever, mine, accounts)[0]["services_share"] + seen["visits_share"] \
            + _sum_visits(dentist.pk, earlier[dentist.pk], mine)[0]["visits_share"]
        rows.append({"dentist": dentist, "branch": branch, "rules": mine, **period, **seen,
                     "share": period["services_share"] + seen["visits_share"],
                     "patient_count": len(patients | visited), "paid_out": paid_out[dentist.pk],
                     "owed": earned - paid_ever[dentist.pk]})
    sums = defaultdict(lambda: ZERO)
    sums.update(visit_count=0, chair_minutes=0)
    for row in rows:
        for key in ("billed", "collected", "share", "paid_out", "owed", "visit_count", "chair_minutes"):
            sums[key] += row[key]
    return rows, dict(sums)
