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
