"""What each candidate did of his course's content (round 16): the course asks for a number of each procedure
(40 implants, 2 sinus lifts, 1 GBR...), a candidate may add extra cases, and the teeth he operated on the surgery
charts are counted (his own teeth, or the teeth of his surgeries with no other operator)."""

from django.db.models import Count, Q

from .models import Target

# The procedure of each target on the surgery chart (a tooth with an implant counts as an implant).
SITE_FIELDS = {
    Target.IMMEDIATE: "immediate_implant", Target.GUIDED: "guided", Target.OPEN_SINUS: "open_sinus",
    Target.CLOSED_SINUS: "closed_sinus", Target.GBR: "gbr", Target.SPLITTING: "splitting",
    Target.EXPANSION: "expansion", Target.EXTRACTION: "extraction",
}


def done_counts(dentist):
    """{target: how many} for the teeth this dentist operated (one look-up)."""
    from apps.surgery.models import SurgerySite

    if dentist is None:
        return {}
    counts = {Target.IMPLANTS: Count("pk", filter=~Q(implant_status=""))}
    for target, field in SITE_FIELDS.items():
        counts[target] = Count("pk", filter=Q(**{field: True}))
    return SurgerySite.objects.done_by(dentist).aggregate(**counts)


def progress(enrollment, done=None):
    """The rows of what he must do and what he did: [{kind, label, course, extra, target, done, left, percent}]."""
    if done is None:
        dentist = getattr(enrollment.candidate, "dentist", None)
        done = done_counts(dentist)
    targets = {t.kind: t.count for t in enrollment.course.targets.all()}
    if Target.IMPLANTS not in targets and enrollment.course.implants_required:
        targets[Target.IMPLANTS] = enrollment.course.implants_required
    if enrollment.implants_required_override is not None:
        targets[Target.IMPLANTS] = enrollment.implants_required_override
    extras = {}
    for extra in enrollment.extras.all():
        extras[extra.kind] = extras.get(extra.kind, 0) + extra.count
    rows = []
    for kind, label in Target.choices:
        course, extra, did = targets.get(kind, 0), extras.get(kind, 0), done.get(kind, 0) or 0
        if not (course or extra or did):
            continue
        target = course + extra
        rows.append({"kind": kind, "label": label, "course": course, "extra": extra, "target": target, "done": did,
                     "left": max(target - did, 0), "percent": min(100, round(100 * did / target)) if target else None})
    return rows


def content_text(course):
    """"40 implants, 2 sinus lifting (open), 1 GBR" for a course."""
    rows = [f"{t.count} {t.get_kind_display()}" for t in course.targets.all()]
    if not rows and course.implants_required:
        rows = [f"{course.implants_required} {Target.IMPLANTS.label}"]
    return "، ".join(rows)
