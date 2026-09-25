"""Tick treatment-plan items automatically when the planned work is recorded."""

from django.utils import timezone

from .models import PlanItem, TreatmentPlan
from .teeth import format_teeth, parse_teeth


def complete_plan_items(patient, step_type, teeth, treatment=None, surgery=None, when=None):
    """Mark planned items with the same procedure on these teeth as done.

    When only some of an item's teeth are treated, the item is split: the treated
    teeth are marked done and the rest stay planned as a new item.
    """
    teeth = set(teeth)
    done = []
    items = PlanItem.objects.filter(
        plan__patient=patient, plan__status__in=TreatmentPlan.OPEN_STATUSES,
        status=PlanItem.Status.PLANNED, step_type=step_type,
    )
    for item in items:
        item_teeth = set(parse_teeth(item.teeth)) if item.teeth else set()
        if item_teeth and teeth and not item_teeth & teeth:
            continue
        left = item_teeth - teeth if teeth else set()
        if left:
            PlanItem.objects.create(plan=item.plan, phase=item.phase, step_type=item.step_type,
                                    teeth=format_teeth(left), details=item.details)
            item.teeth = format_teeth(item_teeth & teeth)
        item.status = PlanItem.Status.DONE
        item.done_treatment, item.done_surgery = treatment, surgery
        item.done_at = when or timezone.now()
        item.save(update_fields=["teeth", "status", "done_treatment", "done_surgery", "done_at"])
        done.append(item)
    for plan in {item.plan for item in done}:
        remaining = plan.items.filter(status=PlanItem.Status.PLANNED).exists()
        if not remaining and plan.status in TreatmentPlan.OPEN_STATUSES:
            plan.status = TreatmentPlan.Status.COMPLETED
            plan.save(update_fields=["status", "updated_at"])
    return done


def planned_by_tooth(patient):
    """Tooth -> list of planned procedures (for the chart's blue markers)."""
    result = {}
    items = PlanItem.objects.filter(
        plan__patient=patient, plan__status__in=TreatmentPlan.OPEN_STATUSES, status=PlanItem.Status.PLANNED
    ).select_related("step_type")
    for item in items:
        for tooth in parse_teeth(item.teeth) if item.teeth else []:
            result.setdefault(tooth, []).append(f"{item.step_type} {item.details}".strip())
    return result
