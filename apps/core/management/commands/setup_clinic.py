"""Create roles, branches, rooms and the default lists. Safe to run many times."""

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.charting.models import PhotoType
from apps.clinical.models import Lab, LabWorkType, TreatmentStepType
from apps.surgery.models import ImplantSystem
from apps.core.models import Branch, ClinicSettings
from apps.core.roles import ALL_ROLES
from apps.billing.models import FawryMachine, Service
from apps.patients.models import MedicalCondition, OutReason, ReferralSource
from apps.prescriptions.defaults import load_defaults as load_prescription_defaults
from apps.purchasing.models import PurchaseCategory
from apps.scheduling.models import Room
from apps.scheduling.whatsapp import load_default_templates as load_whatsapp_templates
from apps.stock.models import StockCategory

BRANCHES = [
    # code, kind, Arabic name, English name
    ("CIA", Branch.Kind.ACADEMY, "أكاديمية القاهرة لزراعة الأسنان", "Cairo Implant Academy"),
    ("PVT", Branch.Kind.CLINIC, "عيادة الخادم لطب الأسنان", "El Khadem Dental Clinic"),
    ("LAB", Branch.Kind.LAB, "معمل GDIL للأسنان", "GDIL Dental Lab"),
    ("CIC", Branch.Kind.CLINIC, "مركز القاهرة لزراعة الأسنان", "Cairo Implant Center"),
]

ROOM_COUNT = 5
EXTRA_ROOM_COUNT = 4
CIC_ROOM_COUNT = 3  # a start: the owner renames, adds or stops rooms in Settings → Rooms
KHADEM_ROOM_COUNT = 4  # shared: any doctor in any free room
# El Khadem's own look: the first time only (the owner changes it in Settings → Places).
KHADEM = {"file_prefix": "EK", "theme": Branch.Theme.ELITE, "rooms_shared": True,
          "tagline": "Specialist dental care · Dr. Amr El Khadem"}

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
    ("انتقل لمكان آخر من أماكننا (ملف جديد)", "Moved to another of our places (new file)"),
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
    ("كوبري على زرعات", "Bridge on implants", "delivery", "", ""),
    ("تركيبة كاملة ثابتة على زرعات (All-on-X)", "Full arch fixed on implants (All-on-X)", "delivery", "", ""),
    ("طقم متحرك على زرعات (Overdenture)", "Overdenture on implants", "delivery", "", ""),
    ("فشل الزرعة / إزالتها", "Implant failure / removal", "implant_failed", "", ""),
    ("متابعة", "Follow-up", "none", "", ""),
    # The specialists of El Khadem
    ("إعادة علاج عصب", "Root canal retreatment", "rct", "", ""),
    ("كشف مفصل الفك", "TMJ examination", "none", "", ""),
    ("جبيرة إطباق (Splint)", "Occlusal splint", "none", "", ""),
    ("تركيب تقويم", "Orthodontic bonding", "none", "", ""),
    ("متابعة تقويم", "Orthodontic adjustment", "none", "", ""),
    ("تحديد لون التركيبة", "Shade taking", "none", "", ""),
    ("أخرى", "Other", "none", "", ""),
    # Round 10: the records of a new patient and the steps of a root canal treatment
    ("طبعة أولية (موديل دراسة)", "Primary impression (study models)", "none", "", ""),
    ("مسح رقمي تشخيصي", "Diagnostic intraoral scan", "none", "", ""),
    ("أشعة مقطعية (CBCT) في العيادة", "CBCT taken here", "none", "", ""),
    ("فتح العصب", "Endo: access opening", "none", "", ""),
    ("فتح وتنظيف وتشكيل القنوات", "Endo: access, cleaning and shaping", "none", "", ""),
    ("حشو القنوات (Obturation)", "Endo: obturation", "rct", "", ""),
    ("علاج عصب كامل في جلسة واحدة", "Endo: all in a single visit", "rct", "", ""),
    ("بتر العصب / تغطية العصب", "Endo: pulpotomy / pulp capping", "none", "", ""),
    ("وتد وقلب", "Post and core", "none", "", ""),
    ("تنظيف عميق وكحت اللثة", "Deep scaling and root planing", "none", "", ""),
]

# Round 10: the kind of work of each step (by English name), the file's step it ticks, and the photos and periapical
# X-rays it should have. Older installations get them once (a step the owner changed keeps his choice).
STEP_GROUPS = {
    "records": ["Examination & diagnosis", "X-ray (panoramic / CBCT)", "Treatment plan", "Primary impression (study models)",
                "Diagnostic intraoral scan", "CBCT taken here"],
    "surgery": ["Extraction", "Immediate implant", "Implant placement", "Guided implant surgery", "Bone graft",
                "Sinus lift", "Closed sinus lift", "Ridge expansion / splitting", "Suture removal",
                "Second stage / healing abutment", "Implant failure / removal"],
    "implant_teeth": ["Impression", "Digital scan", "Bite registration", "Try-in", "Final prosthesis delivery",
                      "Temporary prosthesis", "Bridge on implants", "Full arch fixed on implants (All-on-X)",
                      "Overdenture on implants"],
    "endo": ["Root canal treatment", "Root canal retreatment", "Endo: access opening", "Endo: access, cleaning and shaping",
             "Endo: obturation", "Endo: all in a single visit", "Endo: pulpotomy / pulp capping"],
    "fillings": ["Composite restoration", "Amalgam restoration", "Glass ionomer restoration", "Temporary filling"],
    "fixed": ["Crown preparation", "Crown cementation (natural tooth)", "Shade taking", "Post and core"],
    "gums": ["Scaling", "Deep scaling and root planing"],
    "ortho": ["TMJ examination", "Occlusal splint", "Orthodontic bonding", "Orthodontic adjustment"],
}
STEP_JOURNEY = {"Primary impression (study models)": "impression", "Diagnostic intraoral scan": "impression",
                "CBCT taken here": "cbct"}
STEP_SHOTS = {
    "Root canal treatment": "pa_before,pa_after", "Root canal retreatment": "pa_before,pa_after",
    "Endo: access opening": "pa_before", "Endo: access, cleaning and shaping": "pa_before,pa_working",
    "Endo: obturation": "pa_cone,pa_after", "Endo: all in a single visit": "pa_before,pa_working,pa_cone,pa_after",
    "Endo: pulpotomy / pulp capping": "pa_before,pa_after",
    "Composite restoration": "photo_before,photo_after", "Amalgam restoration": "photo_before,photo_after",
    "Glass ionomer restoration": "photo_before,photo_after",
    "Crown preparation": "photo_before,photo_after", "Crown cementation (natural tooth)": "photo_after,pa_after",
    "Shade taking": "photo_shade", "Post and core": "pa_after",
    "Final prosthesis delivery": "photo_after,pa_after", "Bridge on implants": "photo_after,pa_after",
    "Full arch fixed on implants (All-on-X)": "photo_after,pa_after", "Scaling": "photo_before,photo_after",
    "Deep scaling and root planing": "photo_before,photo_after",
}



def _step_category(effect, procedure):
    """Implants, surgeries and their stages go to the implant section of the plans."""
    implant = procedure or effect in TreatmentStepType.IMPLANT_EFFECTS
    return TreatmentStepType.Category.IMPLANT if implant else TreatmentStepType.Category.RESTORATIVE


# Plain Arabic explanations of the treatments, for the reception (by English name).
TREATMENT_EXPLANATIONS = {
    "Root canal retreatment": "إعادة علاج عصب سن سبق علاجه: فك الحشو القديم وتنظيف القنوات وحشوها من جديد.",
    "TMJ examination": "كشف على مفصل الفك وعضلات المضغ: الفتح والطقطقة والألم.",
    "Occlusal splint": "جبيرة شفافة تُلبس على الأسنان (غالبًا بالليل) لراحة المفصل والعضلات ومنع الضغط على الأسنان.",
    "Orthodontic bonding": "تركيب التقويم (الأقواس والسلك) على الأسنان.",
    "Orthodontic adjustment": "زيارة متابعة التقويم: تغيير السلك أو الأستك وضبط التقويم.",
    "Shade taking": "اختيار لون التركيبة ليطابق لون الأسنان الطبيعية.",
    "Treatment plan": "الطبيب كشف على المريض وكتب خطة العلاج المطلوبة.",
    "Scaling": "تنظيف الأسنان من الجير والرواسب.",
    "Primary impression (study models)": "طبعة أولى للأسنان لعمل موديل لدراسة الحالة قبل التخطيط.",
    "Diagnostic intraoral scan": "تصوير الأسنان بالماسح الرقمي لدراسة الحالة قبل التخطيط.",
    "CBCT taken here": "أشعة مقطعية على الفك في العيادة لتخطيط الزرع.",
    "Endo: access opening": "أول جلسة علاج عصب: فتح السن للوصول للعصب.",
    "Endo: access, cleaning and shaping": "جلسة علاج عصب: فتح السن وتنظيف القنوات وتشكيلها.",
    "Endo: obturation": "آخر جلسة علاج عصب: حشو القنوات.",
    "Endo: all in a single visit": "علاج العصب كله في جلسة واحدة.",
    "Endo: pulpotomy / pulp capping": "علاج جزء من العصب أو تغطيته للحفاظ عليه.",
    "Post and core": "وتد داخل السن المعالج عصبه لتقوية السن قبل الطربوش.",
    "Deep scaling and root planing": "تنظيف عميق للجير تحت اللثة.",
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
    "Bridge on implants": "كوبري ثابت محمول على زرعتين أو أكثر يعوّض أكثر من سن.",
    "Full arch fixed on implants (All-on-X)": "تركيبة ثابتة لفك كامل محمولة على عدة زرعات.",
    "Overdenture on implants": "طقم متحرك لفك كامل يثبت على الزرعات بأزرار أو بار.",
    "Implant failure / removal": "الزرعة لم تلتحم بالعظم فتمت إزالتها.",
    "Follow-up": "زيارة متابعة للاطمئنان على الحالة.",
}

# Usual working days at the lab for each work type (sets the date the work is needed back).
LAB_DAYS = {
    "Zirconia crown": 7, "PFM crown": 7, "E.max crown": 7, "Bridge": 10, "Screw-retained implant crown": 10,
    "Cement-retained implant crown": 10, "Full-arch hybrid (All-on-X)": 21, "Implant overdenture": 21,
    "Complete denture": 14, "Partial denture": 14, "Surgical guide": 5, "Custom abutment": 7,
    "Temporary (PMMA)": 3, "Study model": 2, "E.max veneer": 7, "Inlay / onlay": 5, "Milled titanium bar": 14,
    "Printed CoCr framework": 7, "Printed titanium framework, milled finish": 14, "Printed model": 2,
    "Night guard / splint": 4, "Diagnostic wax-up": 4, "Custom tray": 2,
}

LAB_WORK_TYPES = [
    # Arabic, English, kind of work (gives the steps at our lab), priced per
    ("طربوش زيركون", "Zirconia crown", "zirconia", "tooth"),
    ("طربوش بورسلين على معدن", "PFM crown", "pfm", "tooth"),
    ("طربوش إي ماكس", "E.max crown", "emax", "tooth"),
    ("كوبري", "Bridge", "zirconia", "tooth"),
    ("تركيبة على زرعة (مثبتة بمسمار)", "Screw-retained implant crown", "zirconia", "tooth"),
    ("تركيبة على زرعة (مثبتة بلاصق)", "Cement-retained implant crown", "zirconia", "tooth"),
    ("تركيبة كاملة ثابتة على زرعات (Hybrid / All-on-X)", "Full-arch hybrid (All-on-X)", "print_mill", "arch"),
    ("طقم متحرك على زرعات (Overdenture)", "Implant overdenture", "removable", "arch"),
    ("طقم كامل", "Complete denture", "removable", "arch"),
    ("طقم جزئي", "Partial denture", "removable", "arch"),
    ("دليل جراحي (Surgical guide)", "Surgical guide", "resin_print", "case"),
    ("دعامة مخصصة (Custom abutment)", "Custom abutment", "ti_mill", "tooth"),
    ("تركيبة مؤقتة", "Temporary (PMMA)", "pmma", "tooth"),
    ("نموذج دراسة", "Study model", "resin_print", "case"),
    ("فينير إي ماكس", "E.max veneer", "emax", "tooth"),
    ("إنلاي / أونلاي", "Inlay / onlay", "emax", "tooth"),
    ("بار تيتانيوم (تفريز)", "Milled titanium bar", "ti_mill", "arch"),
    ("هيكل معدن مطبوع (كوبالت كروم)", "Printed CoCr framework", "metal_print", "arch"),
    ("هيكل تيتانيوم مطبوع ثم مفرّز", "Printed titanium framework, milled finish", "print_mill", "arch"),
    ("نموذج مطبوع", "Printed model", "resin_print", "arch"),
    ("جبيرة ليلية (Night guard)", "Night guard / splint", "splint", "arch"),
    ("شمع تشخيصي (Wax-up)", "Diagnostic wax-up", "other", "tooth"),
    ("طابع خاص (Custom tray)", "Custom tray", "resin_print", "arch"),
    ("أخرى", "Other", "other", "case"),
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
    # Arabic, English, group (apps/stock/models.py StockGroup)
    ("مواد أسنان", "Dental materials", "dental"),
    ("مواد حشو وترميم", "Restorative materials (composite, bonding, GIC)", "dental"),
    ("مواد علاج العصب", "Endodontics (files, gutta-percha, sealers)", "dental"),
    ("مواد الطبعات", "Impression materials", "dental"),
    ("مواد التركيبات واللصق", "Prosthodontics & cements", "dental"),
    ("فرز وأدوات دوّارة", "Burs & rotary", "dental"),
    ("زرعات ومكوناتها", "Implants & components", "implants"),
    ("دعامات وأجزاء تركيبات الزرعات", "Abutments & prosthetic parts", "implants"),
    ("عظم صناعي وأغشية", "Bone grafts & membranes", "implants"),
    ("خيوط جراحية", "Sutures", "implants"),
    ("أدوات ودريلات الجراحة", "Surgical kits & drills", "implants"),
    ("مستهلكات (جوانتي، ماسكات، شاش...)", "Consumables (gloves, masks, gauze...)", "infection"),
    ("تعقيم (أكياس ومؤشرات)", "Sterilisation (pouches, indicators)", "infection"),
    ("مستهلكات للاستخدام مرة واحدة", "Disposables (suction tips, cups, bibs)", "infection"),
    ("بنج وأدوية", "Anaesthesia & drugs", "medicines"),
    ("أدوات وآلات", "Instruments", "equipment"),
    ("أجهزة", "Equipment", "equipment"),
    ("قطع غيار", "Spare parts", "equipment"),
    ("طعام ومشروبات", "Food & beverage", "beverage"),
    ("ضيافة (شاي، قهوة، سكر، أكواب)", "Hospitality (tea, coffee, sugar, cups)", "beverage"),
    ("منظفات", "Cleaning", "cleaning"),
    ("أدوات مكتبية", "Stationery", "stationery"),
    ("مطبوعات وورق إيصالات", "Printing & receipt rolls", "stationery"),
    ("أحبار وطابعات", "Printer ink & toner", "stationery"),
    # The dental lab
    ("بلوكات وأقراص (زيركون، إي ماكس، PMMA، شمع، تيتانيوم)", "Lab blocks and discs", "lab"),
    ("سوائل وألوان وجليز", "Liquids, stains and glaze", "lab"),
    ("بورسلين وبوند", "Porcelain and bond", "lab"),
    ("راتنج الطباعة", "Printing resins", "lab"),
    ("مساحيق وسبائك المعادن", "Metal powders and alloys", "lab"),
    ("جبس وأكريليك وأسنان صناعية", "Plaster, acrylic and denture teeth", "lab"),
    ("أدوات وفريزات المعمل", "Lab tools and milling burs", "lab"),
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
                code=code, defaults={"kind": kind, "name_ar": name_ar, "name_en": name_en, "sort_order": order,
                                     **(KHADEM if code == "PVT" else {})}
            )
        # The private clinic opened as El Khadem Dental Clinic (an older system still has the first name).
        khadem = Branch.objects.get(code="PVT")
        if khadem.name_en in ("", "Private Clinic"):
            Branch.objects.filter(pk=khadem.pk).update(name_ar=BRANCHES[1][2], name_en=BRANCHES[1][3], **KHADEM)
        if not Room.objects.filter(branch=khadem).exists():
            for number in range(1, KHADEM_ROOM_COUNT + 1):
                Room.objects.create(branch=khadem, name=f"غرفة {number}", name_en=f"Room {number}", sort_order=number)
        # The lab opened as GDIL (its logo is in static/img): an older system still has the first name.
        Branch.objects.filter(code="LAB", name_en__in=("", "Dental Lab")).update(
            name_ar=BRANCHES[2][2], name_en=BRANCHES[2][3])
        Branch.objects.filter(code="LAB", tagline="").update(tagline="The art of dentistry")
        academy = Branch.objects.get(code="CIA")
        for number in range(1, ROOM_COUNT + 1):
            room, _created = Room.objects.get_or_create(branch=academy, name=f"غرفة {number}", defaults={"sort_order": number})
            if not room.name_en:
                Room.objects.filter(pk=room.pk).update(name_en=f"Room {number}")
        cic = Branch.objects.get(code="CIC")
        if not Room.objects.filter(branch=cic).exists():
            for number in range(1, CIC_ROOM_COUNT + 1):
                Room.objects.create(branch=cic, name=f"CIC غرفة {number}", name_en=f"CIC room {number}", sort_order=number)
        # Up to four numbered extra rooms at each place: shown on the schedules only on a day an appointment or a
        # shift is put in them.
        for place, prefix_ar, prefix_en in ((academy, "", ""), (cic, "CIC ", "CIC ")):
            for number in range(1, EXTRA_ROOM_COUNT + 1):
                Room.objects.get_or_create(
                    branch=place, name=f"{prefix_ar}غرفة إضافية {number}",
                    defaults={"name_en": f"{prefix_en}Extra room {number}", "sort_order": 100 + number, "is_extra": True,
                              "notes": "Opened on busy days"})

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
            "lab work types": _lookup(LabWorkType, LAB_WORK_TYPES, extra_fields=lambda r: {"category": r[2],
                                                                                          "unit": r[3]}),
            "purchase categories": _lookup(PurchaseCategory, PURCHASE_CATEGORIES, extra_fields=lambda r: {"kind": r[2]}),
            "stock categories": _lookup(StockCategory, STOCK_CATEGORIES, extra_fields=lambda r: {"group": r[2]}),
        }
        StockCategory.objects.filter(name_en="Lab blocks and discs", lab_blocks=False).update(lab_blocks=True)
        Lab.objects.get_or_create(name="معمل الأسنان (معملنا)", defaults={"branch": Branch.objects.get(code="LAB")})
        Lab.objects.filter(name="معمل الأسنان (معملنا)", name_en="").update(name_en="Our dental lab")
        # Older installations: give existing treatment types their chart effect once.
        for name_ar, name_en, effect, procedure, material in TREATMENT_STEPS:
            TreatmentStepType.objects.filter(name_ar=name_ar, chart_effect="none").exclude(chart_effect=effect).update(
                chart_effect=effect)
            if procedure:
                TreatmentStepType.objects.filter(name_ar=name_ar, surgery_procedure="").update(surgery_procedure=procedure)
        for name_ar, name_en, category, unit in LAB_WORK_TYPES:  # older installations: the kind of each lab work
            LabWorkType.objects.filter(name_ar=name_ar, category="other").exclude(category=category).update(
                category=category, unit=unit)
        for name_en, days in LAB_DAYS.items():  # a starting point: the owner changes them in Settings
            LabWorkType.objects.filter(name_en=name_en, default_days__isnull=True).update(default_days=days)
        if not Service.objects.filter(quick_button=True).exists():  # one-click buttons on a new bill
            Service.objects.filter(name_en__in=("Consultation", "CBCT")).update(quick_button=True)
        for group, names in STEP_GROUPS.items():
            TreatmentStepType.objects.filter(name_en__in=names, group="other").update(group=group)
        for name_en, step in STEP_JOURNEY.items():
            TreatmentStepType.objects.filter(name_en=name_en, journey_step="").update(journey_step=step)
        for name_en, shots in STEP_SHOTS.items():
            TreatmentStepType.objects.filter(name_en=name_en, shots="").update(shots=shots)
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
        # The owner's two Fawry POS machines (renamed, e.g. with their terminal numbers, in Settings).
        for number in (1, 2):
            if FawryMachine.objects.count() < 2 and not FawryMachine.objects.filter(name=f"Fawry {number}").exists():
                FawryMachine.objects.create(name=f"Fawry {number}", sort_order=number)
        ClinicSettings.get()

        for label, count in counts.items():
            self.stdout.write(f"  {label}: {count} added")
        self.stdout.write(self.style.SUCCESS("Clinic setup complete."))
