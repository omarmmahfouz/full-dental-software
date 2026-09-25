"""Choose the instruction sheets and the prescription that fit a surgery."""

from apps.surgery.models import SurgerySite

from .models import InstructionSheet, PrescriptionTemplate


def surgery_procedures(surgery):
    """Procedure codes done in a surgery (as used by the templates' "fits" lists)."""
    if surgery is None:
        return set()
    codes = set()
    for site in surgery.sites.all():
        codes |= {name for name, _label in SurgerySite.PROCEDURES if getattr(site, name)}
    if surgery.block_graft:
        codes.add("gbr")
    if surgery.soft_tissue_graft:
        codes.add("soft_tissue")
    return codes


def penicillin_allergy(patient):
    exam = patient.examinations.first()
    return bool(exam and exam.allergy_penicillin)


def matching_sheets(procedures):
    sheets = InstructionSheet.objects.filter(is_active=True)
    return [s for s in sheets if not s.procedure_set() or s.procedure_set() & procedures]


def best_template(procedures, allergic=False):
    """The template sharing most procedures with the surgery (allergy-safe when needed)."""
    templates = PrescriptionTemplate.objects.filter(is_active=True, for_penicillin_allergy=allergic)
    scored = [(len(t.procedure_set() & procedures), -t.sort_order, t) for t in templates if t.procedure_set() & procedures]
    if not scored:
        return None
    return max(scored, key=lambda row: (row[0], row[1]))[2]
