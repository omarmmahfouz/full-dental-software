"""Create roles, branches, rooms and the default lists. Safe to run many times."""

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.charting.models import PhotoType
from apps.clinical.models import Lab, LabWorkType, TreatmentStepType
from apps.surgery.models import ImplantSystem
from apps.core.models import Branch, ClinicSettings
from apps.core.roles import ALL_ROLES
from apps.billing.models import Service
from apps.patients.models import MedicalCondition, OutReason, ReferralSource
from apps.prescriptions.defaults import load_defaults as load_prescription_defaults
from apps.purchasing.models import PurchaseCategory
from apps.scheduling.models import Room
from apps.scheduling.whatsapp import load_default_templates as load_whatsapp_templates
from apps.stock.models import StockCategory

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

# Paid services (prices are set by the owner in Settings → Paid services and prices).
SERVICES = [
    ("كشف", "Consultation"),
    ("أشعة مقطعية CBCT", "CBCT"),
    ("أشعة بانوراما", "Panoramic X-ray"),
    ("أشعة صغيرة", "Periapical X-ray"),
    ("تنظيف جير", "Scaling"),
    ("حشو", "Filling"),
    ("علاج عصب", "Root canal treatment"),
    ("خلع", "Extraction"),
    ("زرعة", "Implant"),
    ("ترقيع عظم", "Bone graft"),
    ("دليل جراحي", "Surgical guide"),
    ("طربوش على زرعة", "Crown on implant"),
    ("أخرى", "Other"),
]

OUT_REASONS = [
    ("انقطع عن الحضور", "Stopped coming"),
    ("انتقل لعيادة أخرى", "Moved to another clinic"),
    ("رفض خطة العلاج أو التكلفة", "Refused the plan or the cost"),
    ("سبب طبي", "Medical reason"),
    ("عدم الالتزام بالمواعيد أو التعليمات", "Did not follow appointments or instructions"),
    ("أنهى العلاج في مكان آخر", "Finished the treatment elsewhere"),
    ("أخرى", "Other"),
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
    ("أمراض نفسية", "Psychological"),
    ("حمى روماتيزمية", "Rheumatic fever"),
    ("أنيميا", "Anemia"),
    ("صرع", "Epilepsy"),
    ("أمراض تناسلية", "Venereal disease"),
]

# Arabic, English, chart effect, matching surgery-chart procedure, default material
TREATMENT_STEPS = [
    ("كشف وتشخيص", "Examination & diagnosis", "none", "", ""),
    ("أشعة (بانوراما / CBCT)", "X-ray (panoramic / CBCT)", "none", "", ""),
    ("خطة علاج", "Treatment plan", "none", "", ""),
    ("تنظيف جير", "Scaling", "none", "", ""),
    ("حشو كومبوزيت", "Composite restoration", "filling", "", "composite"),
    ("حشو أملجم", "Amalgam restoration", "filling", "", "amalgam"),
    ("حشو جلاس أيونومر", "Glass ionomer restoration", "filling", "", "GIC"),
    ("حشو مؤقت", "Temporary filling", "filling", "", "temporary"),
    ("علاج عصب", "Root canal treatment", "rct", "", ""),
    ("تحضير طربوش", "Crown preparation", "none", "", ""),
    ("تركيب طربوش على سن", "Crown cementation (natural tooth)", "crown", "", ""),
    ("خلع", "Extraction", "extraction", "extraction", ""),
    ("زرع فوري بعد الخلع", "Immediate implant", "implant", "immediate_implant", ""),
    ("زرع دعامة (Implant placement)", "Implant placement", "implant", "simple_implant", ""),
    ("زرع بدليل جراحي", "Guided implant surgery", "implant", "guided", ""),
    ("ترقيع عظم", "Bone graft", "none", "gbr", ""),
    ("رفع جيب أنفي", "Sinus lift", "none", "open_sinus", ""),
    ("رفع جيب أنفي مغلق", "Closed sinus lift", "none", "closed_sinus", ""),
    ("توسيع / شق العظم", "Ridge expansion / splitting", "none", "expansion", ""),
    ("فك الغرز", "Suture removal", "none", "", ""),
    ("كشف اللثة وتركيب Healing abutment", "Second stage / healing abutment", "uncover", "", ""),
    ("طبعة", "Impression", "impression", "", ""),
    ("مسح رقمي (Scan)", "Digital scan", "impression", "", ""),
    ("تسجيل العضة", "Bite registration", "none", "", ""),
    ("تجربة (Try-in)", "Try-in", "none", "", ""),
    ("تركيب التركيبة النهائية", "Final prosthesis delivery", "delivery", "", ""),
    ("تركيبة مؤقتة", "Temporary prosthesis", "none", "", ""),
    ("فشل الزرعة / إزالتها", "Implant failure / removal", "implant_failed", "", ""),
    ("متابعة", "Follow-up", "none", "", ""),
    ("أخرى", "Other", "none", "", ""),
]



def _step_category(effect, procedure):
    """Implants, surgeries and their stages go to the implant section of the plans."""
    implant = procedure or effect in TreatmentStepType.IMPLANT_EFFECTS
    return TreatmentStepType.Category.IMPLANT if implant else TreatmentStepType.Category.RESTORATIVE


# Plain Arabic explanations of the treatments, for the reception (by English name).
TREATMENT_EXPLANATIONS = {
    "Treatment plan": "الطبيب كشف على المريض وكتب خطة العلاج المطلوبة.",
    "Scaling": "تنظيف الأسنان من الجير والرواسب.",
    "Composite restoration": "حشو أبيض بلون السن لسد التسوس.",
    "Amalgam restoration": "حشو فضي (معدني) لسد التسوس.",
    "Glass ionomer restoration": "حشو أبيض بسيط، غالبًا للأسنان الصغيرة أو كحشو مبدئي.",
    "Temporary filling": "حشو مؤقت لحين استكمال العلاج في زيارة قادمة.",
    "Root canal treatment": "علاج عصب السن وتنظيف القنوات من الداخل ثم حشوها.",
    "Crown preparation": "برد السن لتجهيزه لتركيب طربوش (تلبيسة).",
    "Crown cementation (natural tooth)": "تركيب الطربوش (التلبيسة) النهائي على السن.",
    "Extraction": "خلع السن.",
    "Immediate implant": "خلع السن وتركيب الزرعة في نفس الجلسة.",
    "Implant placement": "تركيب زرعة (مسمار من التيتانيوم) في العظم مكان السن المفقود.",
    "Guided implant surgery": "تركيب الزرعة بدليل جراحي مصمم بالكمبيوتر من الأشعة المقطعية: أدق وأسرع.",
    "Bone graft": "تعويض نقص العظم بمادة عظمية حتى يكفي لتركيب الزرعة.",
    "Sinus lift": "رفع أرضية الجيب الأنفي من فتحة جانبية وإضافة عظم، لزرع الأضراس العلوية الخلفية.",
    "Closed sinus lift": "رفع بسيط للجيب الأنفي من مكان الزرعة نفسه وإضافة عظم.",
    "Ridge expansion / splitting": "توسيع العظم الرفيع أو شقه حتى يتسع للزرعة.",
    "Suture removal": "فك الغرز بعد العملية (عادة بعد 7 إلى 10 أيام).",
    "Second stage / healing abutment": "فتح اللثة فوق الزرعة وتركيب قطعة تشكيل اللثة، تمهيدًا للتركيبة.",
    "Impression": "أخذ مقاس الأسنان أو الزرعات بالمعجون لعمل التركيبة في المعمل.",
    "Digital scan": "أخذ مقاس الأسنان بالماسح الرقمي بدل المعجون.",
    "Bite registration": "تسجيل طريقة إطباق الفكين لضبط التركيبة.",
    "Try-in": "تجربة التركيبة في الفم قبل تجهيزها النهائي.",
    "Final prosthesis delivery": "تركيب التركيبة النهائية (طربوش أو كوبري أو طقم).",
    "Temporary prosthesis": "تركيبة مؤقتة لحين تجهيز التركيبة النهائية.",
    "Implant failure / removal": "الزرعة لم تلتحم بالعظم فتمت إزالتها.",
    "Follow-up": "زيارة متابعة للاطمئنان على الحالة.",
}

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

IMPLANT_SYSTEMS = [
    ("Osstem", "TS III"), ("Dentium", "SuperLine"), ("MIS", "C1"), ("Neodent", "Grand Morse"),
    ("Straumann", "BLT"), ("Nobel Biocare", "NobelActive"), ("Megagen", "AnyRidge"), ("Dio", "UF II"),
    ("Bredent", "blueSKY"), ("Alpha-Bio", "SPI"),
]

# CIA photo checklist: stage -> [(English, Arabic, optional)]
PHOTO_CHECKLIST = {
    "diagnostic": [
        ("Upper primary impression", "طبعة أولية علوية", False),
        ("Lower primary impression", "طبعة أولية سفلية", False),
        ("Extra oral facial full-face at rest", "صورة الوجه كامل - راحة", False),
        ("Extra oral facial full-face smiling", "صورة الوجه كامل - ابتسامة", False),
        ("Extra oral full-face retracted (teeth apart)", "صورة الوجه مع مبعد الشفاه (الأسنان منفصلة)", False),
        ("Extra oral profile right side smiling", "جانبية يمين - ابتسامة", False),
        ("Extra oral profile right side rest", "جانبية يمين - راحة", False),
        ("Extra oral profile left side smiling", "جانبية يسار - ابتسامة", False),
        ("Extra oral profile left side rest", "جانبية يسار - راحة", False),
        ("Intra oral upper occlusal", "إطباقية علوية", False),
        ("Intra oral lower occlusal", "إطباقية سفلية", False),
        ("Bite right side", "العضة - يمين", False),
        ("Bite left side", "العضة - يسار", False),
        ("Intra oral retracting and biting", "داخل الفم مع مبعد وعض", False),
        ("Extra oral 45° right side", "خارج الفم 45 يمين", True),
        ("Extra oral 45° left side", "خارج الفم 45 يسار", True),
        ("12 o'clock photo", "صورة الساعة 12", True),
    ],
    "surgery": [
        ("Flap", "الشريحة", False), ("Extraction socket", "مكان الخلع", False), ("Extracted teeth", "الأسنان المخلوعة", False),
        ("Surgical guide extra oral", "الدليل الجراحي خارج الفم", False),
        ("Surgical guide in place", "الدليل الجراحي في مكانه", False),
        ("Paralleling pin occlusal", "دبوس التوازي - إطباقي", False), ("Paralleling pin lateral", "دبوس التوازي - جانبي", False),
        ("Expander / osteotome", "الموسع / الأوستيوتوم", False), ("Split occlusal view", "الشق - إطباقي", False),
        ("Split lateral view", "الشق - جانبي", False), ("After splitting and expansion", "بعد الشق والتوسيع", False),
        ("Bone", "العظم", False), ("Membrane", "الغشاء", False),
        ("Implant placed with cover screw", "الزرعة مع مسمار الغطاء", False),
        ("Temporization occlusal", "المؤقت - إطباقي", False), ("Temporization lateral", "المؤقت - جانبي", False),
        ("Temporization occluding", "المؤقت - في العضة", False),
        ("Temporary restoration extra oral", "التركيبة المؤقتة خارج الفم", False), ("Suture", "الغرز", False),
    ],
    "sinus_gbr": [
        ("Flap", "الشريحة", False), ("Extraction socket", "مكان الخلع", False), ("Extracted teeth", "الأسنان المخلوعة", False),
        ("Window", "النافذة", False), ("Sinus intact (video)", "الجيب سليم (فيديو)", False),
        ("Paralleling pin occlusal", "دبوس التوازي - إطباقي", False), ("Paralleling pin lateral", "دبوس التوازي - جانبي", False),
        ("Expander / osteotome", "الموسع / الأوستيوتوم", False), ("Split occlusal view", "الشق - إطباقي", False),
        ("Split lateral view", "الشق - جانبي", False), ("After splitting and expansion", "بعد الشق والتوسيع", False),
        ("Bone extra oral", "العظم خارج الفم", False), ("Bone intra oral", "العظم داخل الفم", False),
        ("Membrane", "الغشاء", False), ("Tacks", "المسامير (Tacks)", False), ("Flap of donor site", "شريحة مكان الأخذ", False),
        ("Cuts in donor site", "القطع في مكان الأخذ", False), ("Bone block", "البلوك العظمي", False),
        ("Implant placed with cover screw", "الزرعة مع مسمار الغطاء", False), ("Temporization", "المؤقت", False),
        ("Suture", "الغرز", False),
    ],
    "follow_up": [
        ("Healing occlusal after removing suture", "الالتئام بعد فك الغرز - إطباقي", False),
        ("Extra oral facial view in case of swelling", "الوجه في حالة التورم", True),
        ("Extra oral profile view in case of swelling", "الجانب في حالة التورم", True),
        ("Temporization after healing or the new one", "المؤقت بعد الالتئام أو الجديد", False),
        ("Any complication (video + multiple photos)", "أي مضاعفات (فيديو وعدة صور)", True),
        ("Healing of donor site", "التئام مكان الأخذ", True),
    ],
    "soft_tissue": [
        ("Flap", "الشريحة", False), ("Donor flap", "شريحة مكان الأخذ", False), ("Soft tissue graft", "رقعة الأنسجة", False),
        ("Suture soft tissue graft", "غرز رقعة الأنسجة", False), ("Suture donor site", "غرز مكان الأخذ", False),
    ],
    "second_stage": [
        ("Flap", "الشريحة", False), ("Healing customized occlusal view", "الهيلنج المخصص - إطباقي", False),
        ("Healing customized lateral view", "الهيلنج المخصص - جانبي", False), ("Healing extra oral", "الهيلنج خارج الفم", False),
        ("Suture", "الغرز", False),
    ],
    "impression": [
        ("Transfer in place", "الترانسفير في مكانه", False),
        ("Impression before putting analogue", "الطبعة قبل وضع الأنالوج", False),
        ("Impression after putting analogue", "الطبعة بعد وضع الأنالوج", False),
        ("Shade guide with teeth", "دليل اللون مع الأسنان", False),
    ],
    "delivery": [
        ("Cast with restoration", "الموديل مع التركيبة", False), ("Cast without restoration", "الموديل بدون التركيبة", False),
        ("Restoration in patient mouth occlusal", "التركيبة في الفم - إطباقي", False),
        ("Restoration in patient mouth lateral in occlusion", "التركيبة في الفم - جانبي في العضة", False),
        ("Restoration after filling the screw channel", "التركيبة بعد حشو فتحة المسمار", False),
        ("Any error (multiple shots)", "أي خطأ (عدة صور)", True),
    ],
}

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


STOCK_CATEGORIES = [
    ("مواد أسنان", "Dental materials"),
    ("أدوات وآلات", "Instruments"),
    ("زرعات ومكوناتها", "Implants & components"),
    ("بنج وأدوية", "Anaesthesia & drugs"),
    ("مستهلكات (جوانتي، ماسكات، شاش...)", "Consumables (gloves, masks, gauze...)"),
    ("أجهزة", "Equipment"),
    ("طعام ومشروبات", "Food & beverage"),
    ("منظفات", "Cleaning"),
    ("أدوات مكتبية", "Stationery"),
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
            room, _created = Room.objects.get_or_create(branch=academy, name=f"غرفة {number}", defaults={"sort_order": number})
            if not room.name_en:
                Room.objects.filter(pk=room.pk).update(name_en=f"Room {number}")

        counts = {
            "referral sources": _lookup(ReferralSource, REFERRAL_SOURCES, extra_fields=lambda r: {"asks_for_patient": r[2]}),
            "medical conditions": _lookup(MedicalCondition, MEDICAL_CONDITIONS, extra_fields=lambda r: {}),
            "reasons for being out": _lookup(OutReason, OUT_REASONS, extra_fields=lambda r: {}),
            "paid services": _lookup(Service, SERVICES, extra_fields=lambda r: {}),
            "treatment steps": _lookup(
                TreatmentStepType, TREATMENT_STEPS,
                extra_fields=lambda r: {"chart_effect": r[2], "surgery_procedure": r[3], "default_material": r[4],
                                        "category": _step_category(r[2], r[3])},
            ),
            "lab work types": _lookup(LabWorkType, LAB_WORK_TYPES, extra_fields=lambda r: {}),
            "purchase categories": _lookup(PurchaseCategory, PURCHASE_CATEGORIES, extra_fields=lambda r: {"kind": r[2]}),
            "stock categories": _lookup(StockCategory, STOCK_CATEGORIES, extra_fields=lambda r: {}),
        }
        Lab.objects.get_or_create(name="معمل الأسنان (معملنا)", defaults={"branch": Branch.objects.get(code="LAB")})
        Lab.objects.filter(name="معمل الأسنان (معملنا)", name_en="").update(name_en="Our dental lab")
        # Older installations: give existing treatment types their chart effect once.
        for name_ar, name_en, effect, procedure, material in TREATMENT_STEPS:
            TreatmentStepType.objects.filter(name_ar=name_ar, chart_effect="none").exclude(chart_effect=effect).update(
                chart_effect=effect)
            if procedure:
                TreatmentStepType.objects.filter(name_ar=name_ar, surgery_procedure="").update(surgery_procedure=procedure)
        for name_en, explanation in TREATMENT_EXPLANATIONS.items():
            TreatmentStepType.objects.filter(name_en=name_en, description_ar="").update(description_ar=explanation)
        for company, line in IMPLANT_SYSTEMS:
            ImplantSystem.objects.get_or_create(company=company, line=line)
        added_photos = 0
        for stage, items in PHOTO_CHECKLIST.items():
            for order, (name_en, name_ar, optional) in enumerate(items, start=1):
                _obj, created = PhotoType.objects.get_or_create(
                    stage=stage, name_en=name_en,
                    defaults={"name_ar": name_ar, "optional": optional, "sort_order": order},
                )
                added_photos += created
        counts["photo checklist items"] = added_photos
        counts["drugs, ready prescriptions and instruction sheets"] = load_prescription_defaults()
        counts["WhatsApp messages"] = load_whatsapp_templates()
        ClinicSettings.get()

        for label, count in counts.items():
            self.stdout.write(f"  {label}: {count} added")
        self.stdout.write(self.style.SUCCESS("Clinic setup complete."))
