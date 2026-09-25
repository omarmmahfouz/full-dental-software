"""Create roles, branches, rooms and the default lists. Safe to run many times."""

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.clinical.models import Lab, LabWorkType, TreatmentStepType
from apps.core.models import Branch
from apps.core.roles import ALL_ROLES
from apps.patients.models import MedicalCondition, ReferralSource
from apps.purchasing.models import PurchaseCategory
from apps.scheduling.models import Room

BRANCHES = [
    # code, kind, Arabic name, English name
    ("CIA", Branch.Kind.ACADEMY, "أكاديمية القاهرة لزراعة الأسنان", "Cairo Implant Academy"),
    ("PVT", Branch.Kind.CLINIC, "العيادة الخاصة", "Private Clinic"),
    ("LAB", Branch.Kind.LAB, "معمل الأسنان", "Dental Lab"),
]

ROOM_COUNT = 5

REFERRAL_SOURCES = [
    # Arabic, English, asks_for_patient
    ("مريض عندنا (قريب أو صديق)", "Existing patient (relative / friend)", True),
    ("فيسبوك", "Facebook", False),
    ("إنستجرام", "Instagram", False),
    ("تيك توك", "TikTok", False),
    ("جوجل / خرائط جوجل", "Google / Google Maps", False),
    ("واتساب", "WhatsApp", False),
    ("طبيب حوّله", "Referred by a dentist", False),
    ("لافتة / مرّ على المكان", "Sign board / passed by", False),
    ("أخرى", "Other", False),
]

MEDICAL_CONDITIONS = [
    ("سكر", "Diabetes"),
    ("ضغط مرتفع", "High blood pressure"),
    ("أمراض القلب", "Heart disease"),
    ("سيولة في الدم / يأخذ مسيّل", "Bleeding problem / blood thinners"),
    ("حساسية من أدوية", "Drug allergy"),
    ("أمراض الكبد (فيروس سي / ب)", "Liver disease (HCV / HBV)"),
    ("أمراض الكلى", "Kidney disease"),
    ("الغدة الدرقية", "Thyroid disease"),
    ("هشاشة عظام / يأخذ علاج لها", "Osteoporosis / its medication"),
    ("علاج كيماوي أو إشعاعي", "Chemo- or radiotherapy"),
    ("حمل", "Pregnancy"),
    ("مدخّن", "Smoker"),
    ("ربو / حساسية صدر", "Asthma"),
]

TREATMENT_STEPS = [
    ("كشف وتشخيص", "Examination & diagnosis"),
    ("أشعة (بانوراما / CBCT)", "X-ray (panoramic / CBCT)"),
    ("خطة علاج", "Treatment plan"),
    ("تنظيف جير", "Scaling"),
    ("خلع", "Extraction"),
    ("زرع فوري بعد الخلع", "Immediate implant"),
    ("زرع دعامة (Implant placement)", "Implant placement"),
    ("ترقيع عظم", "Bone graft"),
    ("رفع جيب أنفي", "Sinus lift"),
    ("فك الغرز", "Suture removal"),
    ("كشف اللثة وتركيب Healing abutment", "Second stage / healing abutment"),
    ("طبعة", "Impression"),
    ("تسجيل العضة", "Bite registration"),
    ("تجربة (Try-in)", "Try-in"),
    ("تركيب التركيبة النهائية", "Final prosthesis delivery"),
    ("تركيبة مؤقتة", "Temporary prosthesis"),
    ("متابعة", "Follow-up"),
    ("أخرى", "Other"),
]

LAB_WORK_TYPES = [
    ("طربوش زيركون", "Zirconia crown"),
    ("طربوش بورسلين على معدن", "PFM crown"),
    ("طربوش إي ماكس", "E.max crown"),
    ("كوبري", "Bridge"),
    ("تركيبة على زرعة (مثبتة بمسمار)", "Screw-retained implant crown"),
    ("تركيبة على زرعة (مثبتة بلاصق)", "Cement-retained implant crown"),
    ("تركيبة كاملة ثابتة على زرعات (Hybrid / All-on-X)", "Full-arch hybrid (All-on-X)"),
    ("طقم متحرك على زرعات (Overdenture)", "Implant overdenture"),
    ("طقم كامل", "Complete denture"),
    ("طقم جزئي", "Partial denture"),
    ("دليل جراحي (Surgical guide)", "Surgical guide"),
    ("دعامة مخصصة (Custom abutment)", "Custom abutment"),
    ("تركيبة مؤقتة", "Temporary (PMMA)"),
    ("نموذج دراسة", "Study model"),
    ("أخرى", "Other"),
]

PURCHASE_CATEGORIES = [
    # Arabic, English, kind
    ("زرعات ومكوناتها", "Implants & components", PurchaseCategory.Kind.DENTAL),
    ("ترقيع عظم وأغشية", "Bone grafts & membranes", PurchaseCategory.Kind.DENTAL),
    ("مستهلكات (جوانتي، ماسكات، شاش...)", "Consumables (gloves, masks, gauze...)", PurchaseCategory.Kind.DENTAL),
    ("مواد طبعات", "Impression materials", PurchaseCategory.Kind.DENTAL),
    ("بنج", "Anaesthesia", PurchaseCategory.Kind.DENTAL),
    ("تعقيم", "Sterilisation", PurchaseCategory.Kind.DENTAL),
    ("أدوات وآلات", "Instruments", PurchaseCategory.Kind.DENTAL),
    ("أدوية", "Medications", PurchaseCategory.Kind.DENTAL),
    ("شاي وقهوة وسكر", "Tea, coffee & sugar", PurchaseCategory.Kind.NON_DENTAL),
    ("أدوات مكتبية", "Stationery", PurchaseCategory.Kind.NON_DENTAL),
    ("أطعمة وحلويات", "Food & candies", PurchaseCategory.Kind.NON_DENTAL),
    ("مياه", "Water", PurchaseCategory.Kind.NON_DENTAL),
    ("أدوات نظافة", "Cleaning supplies", PurchaseCategory.Kind.NON_DENTAL),
    ("صيانة", "Maintenance", PurchaseCategory.Kind.NON_DENTAL),
    ("أخرى", "Other", PurchaseCategory.Kind.NON_DENTAL),
]


def _lookup(model, rows, extra_fields):
    created = 0
    for order, row in enumerate(rows, start=1):
        name_ar, name_en = row[0], row[1]
        _obj, was_created = model.objects.get_or_create(
            name_ar=name_ar, defaults={"name_en": name_en, "sort_order": order, **extra_fields(row)}
        )
        created += was_created
    return created


class Command(BaseCommand):
    help = "Create roles, branches, the 5 rooms and default lists (safe to re-run)."

    @transaction.atomic
    def handle(self, *args, **options):
        for role in ALL_ROLES:
            Group.objects.get_or_create(name=role)

        for order, (code, kind, name_ar, name_en) in enumerate(BRANCHES, start=1):
            Branch.objects.get_or_create(
                code=code, defaults={"kind": kind, "name_ar": name_ar, "name_en": name_en, "sort_order": order}
            )
        academy = Branch.objects.get(code="CIA")
        for number in range(1, ROOM_COUNT + 1):
            Room.objects.get_or_create(branch=academy, name=f"غرفة {number}", defaults={"sort_order": number})

        counts = {
            "referral sources": _lookup(ReferralSource, REFERRAL_SOURCES, extra_fields=lambda r: {"asks_for_patient": r[2]}),
            "medical conditions": _lookup(MedicalCondition, MEDICAL_CONDITIONS, extra_fields=lambda r: {}),
            "treatment steps": _lookup(TreatmentStepType, TREATMENT_STEPS, extra_fields=lambda r: {}),
            "lab work types": _lookup(LabWorkType, LAB_WORK_TYPES, extra_fields=lambda r: {}),
            "purchase categories": _lookup(PurchaseCategory, PURCHASE_CATEGORIES, extra_fields=lambda r: {"kind": r[2]}),
        }
        Lab.objects.get_or_create(name="معمل الأسنان (معملنا)", defaults={"branch": Branch.objects.get(code="LAB")})

        for label, count in counts.items():
            self.stdout.write(f"  {label}: {count} added")
        self.stdout.write(self.style.SUCCESS("Clinic setup complete."))
