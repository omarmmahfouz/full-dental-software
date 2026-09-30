"""What a prosthesis does to its implants and the chart when it moves on: an impression moves the
implants to "impression taken"; a delivered final prosthesis loads them and its pontics show on the chart."""

from datetime import datetime, time

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.charting.models import ToothChange, ToothState
from apps.charting.rules import Change, _snapshot, apply_changes, current_states, state_label

from .models import Prosthesis, SurgerySite

S = ToothState.Status


def apply_stage(prosthesis, user):
    """Move the implants forward (never back) and mark the pontics on the chart. Returns the changes made."""
    patient = prosthesis.patient
    stage = None
    on = timezone.localdate()
    if prosthesis.status in (Prosthesis.Status.IMPRESSION, Prosthesis.Status.TRY_IN):
        stage = SurgerySite.ImplantStatus.IMPRESSION
    elif prosthesis.status == Prosthesis.Status.DELIVERED and not prosthesis.is_temporary:
        stage, on = SurgerySite.ImplantStatus.LOADED, prosthesis.delivered_on or on
    if stage is None:
        return 0
    states = current_states(patient)
    changes = []
    for site in prosthesis.implants.all():
        probe = SurgerySite(implant_status=site.implant_status)
        if probe.advance(stage):
            before = _snapshot(states.get(site.tooth))
            old, new = site.get_implant_status_display(), SurgerySite.ImplantStatus(stage).label
            change = Change(tooth=site.tooth, before=before, after=dict(before), site=site, site_status=stage)
            change.summary = _("implant: %(old)s → %(new)s (%(what)s)") % {"old": old, "new": new, "what": prosthesis.get_kind_display()}
            changes.append(change)
    if stage == SurgerySite.ImplantStatus.LOADED:
        for tooth in prosthesis.pontics:
            before = _snapshot(states.get(tooth))
            if before["status"] == S.MISSING:
                after = dict(before, status=S.PONTIC)
                changes.append(Change(tooth=tooth, before=before, after=after,
                                      summary=f"{state_label(before)} → {state_label(after)}"))
    when = timezone.now() if on == timezone.localdate() else timezone.make_aware(datetime.combine(on, time(12)))
    return apply_changes(patient, changes, user, ToothChange.Source.TREATMENT, when=when)


def plan_from_surgery(surgery, user):
    """The prostheses the surgery's design shows, written as planned: in each jaw, implants and pontics next to
    each other make one prosthesis (ten units or more: a full arch; with pontics: a bridge); implants side by side
    without a pontic get a crown each. Only implants not yet on a prosthesis; returns the prostheses made."""
    from apps.charting.teeth import LOWER, UPPER, format_teeth

    sites = [site for site in surgery.sites.all() if site.has_implant
             and site.implant_status != SurgerySite.ImplantStatus.FAILED]
    taken = set(Prosthesis.implants.through.objects.filter(surgerysite__in=sites).values_list("surgerysite_id",
                                                                                              flat=True))
    free = {site.tooth: site for site in sites if site.pk not in taken}
    if not free:
        return []
    pontics = set(surgery.pontic_teeth) - set(free)
    made = []
    for jaw, arch in ((Prosthesis.Jaw.UPPER, UPPER), (Prosthesis.Jaw.LOWER, LOWER)):
        groups, current = [], []
        for tooth in arch:
            if tooth in free or tooth in pontics:
                current.append(tooth)
            elif current:
                groups.append(current)
                current = []
        if current:
            groups.append(current)
        for group in groups:
            implants = [free[tooth] for tooth in group if tooth in free]
            if not implants:
                continue
            has_pontics = any(tooth in pontics for tooth in group)
            if len(group) >= 10:
                parts = [(Prosthesis.Kind.FULL_FIXED, group, implants)]
            elif has_pontics:
                parts = [(Prosthesis.Kind.BRIDGE, group, implants)]
            else:
                parts = [(Prosthesis.Kind.SINGLE, [site.tooth], [site]) for site in implants]
            for kind, teeth, on in parts:
                prosthesis = Prosthesis.objects.create(
                    patient=surgery.patient, kind=kind, jaw=jaw if kind == Prosthesis.Kind.FULL_FIXED else "",
                    teeth=format_teeth(teeth), status=Prosthesis.Status.PLANNED, dentist=surgery.operator_1,
                    created_by=user)
                prosthesis.implants.set(on)
                made.append(prosthesis)
    return made
