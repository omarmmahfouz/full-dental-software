"""Keeps the dental chart equal to the real mouth.

Each procedure type has a chart effect (e.g. "filling", "extraction", "implant
failed"). When a dentist records it on tooth numbers, ``plan_changes`` works out
what every tooth becomes; the dentist sees that list and confirms, then
``apply_changes`` saves the new state and a history line for each tooth.
"""

from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.clinical.models import ChartEffect

from .models import ToothChange, ToothState
from .teeth import merge_surfaces, remove_surfaces

S = ToothState.Status
NATURAL = (S.PRESENT, S.ROOT_REMNANT, S.IMPACTED)
DEFAULT = ToothState().snapshot()
DEFAULT.update({"status": S.PRESENT})


@dataclass
class Change:
    tooth: int
    before: dict
    after: dict
    summary: str = ""
    site: object = None          # SurgerySite whose implant stage changes
    site_status: str = ""        # new implant stage for that site
    notes: list = field(default_factory=list)


def current_states(patient):
    """Tooth number -> saved ToothState (only teeth that are not plain sound teeth)."""
    return {s.tooth: s for s in patient.tooth_states.select_related("implant_site__implant_system")}


def _snapshot(state):
    return state.snapshot() if state is not None else dict(DEFAULT)


def _natural_reset(snap):
    snap.update({
        "caries": False, "caries_surfaces": "", "filled": False, "filling_surfaces": "", "filling_material": "",
        "rct": False, "crown": False, "crown_material": "", "hopeless": False, "fractured": False,
        "not_sure": False, "mobility": 0,
    })
    return snap


def state_label(snap, site=None):
    """Short description of one tooth, e.g. "caries MO", "filled composite (DO) + RCT", "implant (loaded)"."""
    status = snap.get("status", S.PRESENT)
    if status == S.MISSING:
        return _("missing")
    if status == S.PONTIC:
        return _("bridge pontic")
    if status == S.IMPLANT:
        stage = site.get_implant_status_display() if site is not None and site.implant_status else ""
        return _("implant (%(stage)s)") % {"stage": stage} if stage else _("implant")
    parts = []
    if status == S.ROOT_REMNANT:
        parts.append(_("root remnant"))
    if status == S.IMPACTED:
        parts.append(_("impacted"))
    if snap.get("caries"):
        parts.append((_("caries") + " " + snap.get("caries_surfaces", "")).strip())
    if snap.get("filled"):
        label = _("filled")
        if snap.get("filling_material"):
            label += f" {snap['filling_material']}"
        if snap.get("filling_surfaces"):
            label += f" ({snap['filling_surfaces']})"
        parts.append(label)
    if snap.get("rct"):
        parts.append(_("RCT"))
    if snap.get("crown"):
        parts.append((_("crown") + " " + snap.get("crown_material", "")).strip())
    if snap.get("hopeless"):
        parts.append(_("hopeless"))
    if snap.get("fractured"):
        parts.append(_("fractured"))
    if snap.get("not_sure"):
        parts.append(_("not sure"))
    if snap.get("mobility"):
        parts.append(_("mobility %(grade)s") % {"grade": snap["mobility"]})
    return " + ".join(str(p) for p in parts) if parts else _("sound")


def _new_snapshot(effect, snap, surfaces, material, site):
    """Return the tooth's snapshot after the effect (or None when nothing changes)."""
    status = snap["status"]
    new = dict(snap)
    if effect == ChartEffect.CARIES:
        if status not in NATURAL:
            return None
        new["caries"] = True
        new["caries_surfaces"] = merge_surfaces(snap["caries_surfaces"], surfaces)
    elif effect == ChartEffect.FILLING:
        if status not in NATURAL:
            return None
        if surfaces:
            new["caries_surfaces"] = remove_surfaces(snap["caries_surfaces"], surfaces)
            new["caries"] = bool(new["caries_surfaces"]) if snap["caries_surfaces"] else False
        else:
            new["caries"], new["caries_surfaces"] = False, ""
        new["filled"] = True
        new["filling_surfaces"] = merge_surfaces(snap["filling_surfaces"], surfaces)
        new["filling_material"] = material or snap["filling_material"]
    elif effect == ChartEffect.RCT:
        if status not in NATURAL:
            return None
        new.update({"rct": True, "caries": False, "caries_surfaces": "", "hopeless": False})
    elif effect == ChartEffect.CROWN:
        if status not in NATURAL:
            return None
        new.update({"crown": True, "crown_material": material or snap["crown_material"], "caries": False,
                    "caries_surfaces": ""})
    elif effect == ChartEffect.EXTRACTION:
        if status in (S.MISSING, S.PONTIC):
            return None
        _natural_reset(new)
        new.update({"status": S.MISSING, "implant_site_id": None})
    elif effect == ChartEffect.IMPLANT:
        _natural_reset(new)
        new.update({"status": S.IMPLANT, "implant_site_id": site.pk if site is not None else snap["implant_site_id"]})
    elif effect == ChartEffect.IMPLANT_FAILED:
        if status != S.IMPLANT:
            return None
        new.update({"status": S.MISSING, "implant_site_id": None})
    elif effect == ChartEffect.DELIVERY:
        if status in NATURAL:
            new.update({"crown": True, "crown_material": material or snap["crown_material"], "caries": False,
                        "caries_surfaces": ""})
        else:
            return None
    elif effect == ChartEffect.HOPELESS:
        if status not in NATURAL:
            return None
        new["hopeless"] = True
    elif effect == ChartEffect.SOUND:
        _natural_reset(new)
        new.update({"status": S.PRESENT, "implant_site_id": None})
    else:
        return None
    return new if new != snap else None


def _implant_stage(effect):
    from apps.surgery.models import SurgerySite

    return {
        ChartEffect.UNCOVER: SurgerySite.ImplantStatus.UNCOVERED,
        ChartEffect.IMPRESSION: SurgerySite.ImplantStatus.IMPRESSION,
        ChartEffect.DELIVERY: SurgerySite.ImplantStatus.LOADED,
        ChartEffect.IMPLANT_FAILED: SurgerySite.ImplantStatus.FAILED,
    }.get(effect)


def _site_for(patient, tooth, state):
    """The implant currently at this tooth (from the chart, or the latest surgery)."""
    from apps.surgery.models import SurgerySite

    if state is not None and state.implant_site_id:
        return state.implant_site
    return (
        SurgerySite.objects.filter(surgery__patient=patient, tooth=tooth)
        .exclude(implant_status__in=["", SurgerySite.ImplantStatus.FAILED])
        .order_by("-surgery__date", "-pk")
        .first()
    )


def plan_changes(patient, effect, teeth, surfaces="", material="", sites=None):
    """What the chart would become. ``sites`` maps tooth -> SurgerySite for new implants."""
    if not effect or effect == ChartEffect.NONE:
        return []
    states = current_states(patient)
    sites = sites or {}
    changes = []
    for tooth in teeth:
        state = states.get(tooth)
        before = _snapshot(state)
        site = sites.get(tooth)
        after = _new_snapshot(effect, before, surfaces, material, site)
        change = Change(tooth=tooth, before=before, after=after or dict(before))

        stage = _implant_stage(effect)
        if stage and (before["status"] == S.IMPLANT or effect == ChartEffect.IMPLANT_FAILED):
            current_site = _site_for(patient, tooth, state)
            if current_site is not None:
                from apps.surgery.models import SurgerySite

                probe = SurgerySite(implant_status=current_site.implant_status)
                if probe.advance(stage):
                    change.site, change.site_status = current_site, stage
                    old = current_site.get_implant_status_display()
                    new = SurgerySite.ImplantStatus(stage).label
                    change.notes.append(_("implant: %(old)s → %(new)s") % {"old": old, "new": new})
            if effect == ChartEffect.IMPLANT_FAILED and change.after["status"] == S.IMPLANT:
                change.after = dict(before, status=S.MISSING, implant_site_id=None)
        if change.after == before and not change.site:
            continue
        before_site = state.implant_site if state is not None else None
        after_site = site or (before_site if change.after.get("implant_site_id") else None)
        if change.after != before:
            change.summary = f"{state_label(before, before_site)} → {state_label(change.after, after_site)}"
        change.summary = "; ".join(p for p in [change.summary, *change.notes] if p)
        changes.append(change)
    return changes


@transaction.atomic
def apply_changes(patient, changes, user, source, treatment=None, surgery=None, examination=None, when=None):
    when = when or timezone.now()
    for change in changes:
        if change.after != change.before:
            state, _created = ToothState.objects.get_or_create(patient=patient, tooth=change.tooth)
            for name, value in change.after.items():
                setattr(state, name, value)
            state.updated_by = user
            state.save()
        if change.site is not None and change.site_status:
            change.site.advance(change.site_status, on=timezone.localdate(when))
            change.site.save()
        ToothChange.objects.create(
            patient=patient, tooth=change.tooth, changed_at=when, changed_by=user, source=source,
            treatment=treatment, surgery=surgery, examination=examination, summary=change.summary[:255],
            before=change.before, after=change.after,
        )
    return len(changes)


def exam_changes(patient, exam):
    """Chart changes from the tooth lists written on the examination (page 1 of the paper chart)."""
    from .teeth import parse_teeth

    effects = [
        ("teeth_missing", ChartEffect.EXTRACTION),
        ("teeth_implant_failed", ChartEffect.EXTRACTION),
        ("teeth_implant_placed", ChartEffect.IMPLANT),
        ("teeth_carious", ChartEffect.CARIES),
        ("teeth_filled", ChartEffect.FILLING),
        ("teeth_hopeless", ChartEffect.HOPELESS),
    ]
    merged = {}
    states = {t: _snapshot(s) for t, s in current_states(patient).items()}
    for field_name, effect in effects:
        for tooth in parse_teeth(getattr(exam, field_name)):
            before = merged.get(tooth, states.get(tooth, dict(DEFAULT)))
            after = _new_snapshot(effect, before, "", "", None)
            if after is not None:
                merged[tooth] = after
    for tooth in parse_teeth(exam.teeth_not_sure):
        snap = dict(merged.get(tooth, states.get(tooth, dict(DEFAULT))))
        snap["not_sure"] = True
        merged[tooth] = snap
    for tooth in parse_teeth(exam.teeth_mobility):
        snap = dict(merged.get(tooth, states.get(tooth, dict(DEFAULT))))
        snap["mobility"] = snap.get("mobility") or 1
        merged[tooth] = snap
    changes = []
    for tooth, after in sorted(merged.items()):
        before = states.get(tooth, dict(DEFAULT))
        if after != before:
            changes.append(Change(tooth, before, after, f"{state_label(before)} → {state_label(after)}"))
    return changes
