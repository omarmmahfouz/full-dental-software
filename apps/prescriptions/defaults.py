"""Starting lists for prescriptions and post-operative instructions.

They are only a starting point: the head of CIA reviews and edits them in
Settings → Prescriptions and instructions. Re-running setup never overwrites edits.
"""

from .models import Drug, DrugGroup, InstructionSheet, PrescriptionTemplate, PrescriptionTemplateLine

# (Arabic name, English name, kind, dose printed for the patient, [brands])
DRUG_GROUPS = [
    ("أموكسيسيلين + كلافيولانيك ١ جم", "Amoxicillin + clavulanic acid 1 g", "antibiotic",
     "قرص كل ١٢ ساعة بعد الأكل لمدة ٥ أيام", ["Augmentin 1 g", "Megamox 1 g", "Hibiotic 1 g", "Curam 1 g"]),
    ("أموكسيسيلين ٥٠٠ مجم", "Amoxicillin 500 mg", "antibiotic",
     "كبسولة كل ٨ ساعات لمدة ٥ أيام", ["Amoxil 500 mg", "E-Mox 500 mg"]),
    ("كليندامايسين ٣٠٠ مجم (حساسية البنسلين)", "Clindamycin 300 mg (penicillin allergy)", "antibiotic",
     "كبسولة كل ٨ ساعات لمدة ٥ أيام", ["Dalacin C 300 mg", "Clindam 300 mg"]),
    ("مترونيدازول ٥٠٠ مجم", "Metronidazole 500 mg", "antibiotic",
     "قرص كل ٨ ساعات بعد الأكل لمدة ٥ أيام", ["Flagyl 500 mg", "Amrizole 500 mg"]),
    ("أيبوبروفين ٤٠٠ مجم", "Ibuprofen 400 mg", "painkiller",
     "قرص كل ٨ ساعات بعد الأكل عند اللزوم لمدة ٣ أيام بحد أقصى", ["Brufen 400 mg", "Ibuprofen 400 mg"]),
    ("ديكلوفيناك بوتاسيوم ٥٠ مجم", "Diclofenac potassium 50 mg", "painkiller",
     "قرص كل ١٢ ساعة بعد الأكل عند اللزوم لمدة ٣ أيام", ["Cataflam 50 mg", "Rapidus 50 mg"]),
    ("باراسيتامول ٥٠٠ مجم", "Paracetamol 500 mg", "painkiller",
     "قرص أو قرصين كل ٦ إلى ٨ ساعات عند اللزوم", ["Panadol 500 mg", "Abimol 500 mg"]),
    ("غسول كلورهيكسيدين ٠٫١٢٪", "Chlorhexidine 0.12% mouthwash", "mouthwash",
     "مضمضة بـ ١٥ مل لمدة دقيقة مرتين يوميًا لمدة أسبوع، تبدأ بعد ٢٤ ساعة من العملية",
     ["Hexitol mouthwash", "Chlorhexidine 0.12% mouthwash"]),
    ("نقط أنف زيلوميتازولين ٠٫١٪", "Xylometazoline 0.1% nasal drops", "other",
     "نقطتين في كل فتحة أنف ٣ مرات يوميًا لمدة ٥ أيام", ["Otrivin 0.1%"]),
]

# (Arabic name, English name, procedures it fits, for penicillin allergy, [English names of drug groups])
TEMPLATES = [
    ("بعد زراعة الأسنان", "After implant surgery", "simple_implant,immediate_implant,guided,gbr,expansion,splitting",
     False, ["Amoxicillin + clavulanic acid 1 g", "Ibuprofen 400 mg", "Chlorhexidine 0.12% mouthwash"]),
    ("بعد زراعة الأسنان — حساسية البنسلين", "After implant surgery — penicillin allergy",
     "simple_implant,immediate_implant,guided,gbr,expansion,splitting", True,
     ["Clindamycin 300 mg (penicillin allergy)", "Ibuprofen 400 mg", "Chlorhexidine 0.12% mouthwash"]),
    ("بعد رفع الجيب الأنفي", "After sinus lift",
     "open_sinus,closed_sinus,simple_implant,immediate_implant,guided,gbr,expansion,splitting", False,
     ["Amoxicillin + clavulanic acid 1 g", "Ibuprofen 400 mg", "Chlorhexidine 0.12% mouthwash",
      "Xylometazoline 0.1% nasal drops"]),
    ("بعد رفع الجيب الأنفي — حساسية البنسلين", "After sinus lift — penicillin allergy",
     "open_sinus,closed_sinus,simple_implant,immediate_implant,guided,gbr,expansion,splitting", True,
     ["Clindamycin 300 mg (penicillin allergy)", "Ibuprofen 400 mg", "Chlorhexidine 0.12% mouthwash",
      "Xylometazoline 0.1% nasal drops"]),
    ("بعد الخلع", "After extraction", "extraction", False, ["Ibuprofen 400 mg", "Chlorhexidine 0.12% mouthwash"]),
]

# (Arabic name, English name, procedures, Arabic lines, English lines)
SHEETS = [
    ("تعليمات عامة بعد الجراحة", "General instructions after surgery", "",
     """اضغط على الشاش المكان لمدة نصف ساعة إلى ساعة، ثم ارمِه.
لا تبصق ولا تتمضمض بقوة ولا تشرب بالشفاطة في أول ٢٤ ساعة.
ضع كمادات ثلج على الخد من الخارج ١٠ دقائق كل نصف ساعة في اليوم الأول.
كُل أكلًا لينًا باردًا أو فاترًا في أول يومين، وامضغ في الناحية الأخرى.
لا تدخن لمدة أسبوعين على الأقل؛ التدخين من أهم أسباب فشل الزرعة.
نظف أسنانك بالفرشاة بلطف مع تجنب مكان العملية، وابدأ الغسول بعد ٢٤ ساعة.
خذ الأدوية في مواعيدها كما في الروشتة، وأكمل المضاد الحيوي حتى آخره.
نم على وسادة مرتفعة في الليلة الأولى.
تورم بسيط وألم خفيف ونقط دم قليلة أمر طبيعي في أول ٣ أيام.
اتصل بنا فورًا إذا استمر النزيف، أو ارتفعت الحرارة، أو زاد التورم بعد اليوم الثالث.
موعد المتابعة وفك الغرز بعد ١٠ إلى ١٤ يومًا.""",
     """Bite on the gauze for 30 to 60 minutes, then throw it away.
Do not spit, rinse hard or drink through a straw for the first 24 hours.
Put an ice pack on the cheek, 10 minutes every half hour, on the first day.
Eat soft, cold or lukewarm food for two days and chew on the other side.
Do not smoke for at least two weeks: smoking is a main cause of implant failure.
Brush gently, avoiding the surgery area, and start the mouthwash after 24 hours.
Take the medicines on time as prescribed and finish the antibiotic.
Sleep with your head raised on the first night.
Mild swelling, mild pain and a little bleeding are normal for the first 3 days.
Call us at once if bleeding does not stop, you have a fever, or swelling increases after day 3.
Follow-up and suture removal after 10 to 14 days."""),
    ("تعليمات إضافية بعد رفع الجيب الأنفي", "Extra instructions after sinus lift", "open_sinus,closed_sinus",
     """لا تنفّ أنفك بقوة لمدة أسبوعين.
إذا عطست فاعطس وفمك مفتوح.
تجنب الطيران والغطس والسباحة ورفع الأثقال لمدة أسبوعين.
استخدم نقط الأنف كما في الروشتة.
نزول نقط دم بسيطة من الأنف في أول يومين أمر طبيعي.""",
     """Do not blow your nose hard for two weeks.
If you sneeze, sneeze with your mouth open.
Avoid flying, diving, swimming and heavy lifting for two weeks.
Use the nose drops as prescribed.
A few drops of blood from the nose in the first two days are normal."""),
    ("تعليمات إضافية بعد ترقيع العظم", "Extra instructions after bone graft", "gbr,expansion,splitting",
     """لا تضغط على مكان الترقيع بلسانك أو بأصابعك.
لا تلبس الطقم المتحرك فوق مكان العملية إلا بعد أن يعدله الطبيب.
قد تلاحظ حبيبات صغيرة مثل الرمل في فمك في الأيام الأولى، وهذا طبيعي.""",
     """Do not press on the graft with your tongue or fingers.
Do not wear a removable denture over the area until the dentist adjusts it.
You may notice small sand-like granules in the first days; this is normal."""),
    ("تعليمات بعد ترقيع اللثة", "Instructions after soft tissue graft", "soft_tissue",
     """لا تشد الشفة لترى مكان العملية.
لا تستخدم الفرشاة على مكان الترقيع حتى يسمح الطبيب.
إذا أُخذ الترقيع من سقف الحلق فالتزم بلبس الغطاء (stent) كما قال الطبيب.""",
     """Do not pull your lip to look at the area.
Do not brush the graft until the dentist allows it.
If the graft was taken from the palate, wear the palatal stent as instructed."""),
]


def load_defaults():
    """Create the starting lists when they are missing. Returns the number of rows added."""
    added = 0
    groups = {}
    for order, (name_ar, name_en, kind, dose, brands) in enumerate(DRUG_GROUPS, start=1):
        group, created = DrugGroup.objects.get_or_create(
            name_en=name_en, defaults={"name_ar": name_ar, "kind": kind, "dose": dose, "sort_order": order}
        )
        added += created
        groups[name_en] = group
        if created:
            for index, brand in enumerate(brands):
                Drug.objects.create(group=group, name=brand, preferred=index == 0)
    for order, (name_ar, name_en, procedures, allergy, lines) in enumerate(TEMPLATES, start=1):
        template, created = PrescriptionTemplate.objects.get_or_create(
            name_en=name_en,
            defaults={"name_ar": name_ar, "procedures": procedures, "for_penicillin_allergy": allergy, "sort_order": order},
        )
        added += created
        if created:
            for index, group_name in enumerate(lines):
                PrescriptionTemplateLine.objects.create(template=template, group=groups[group_name], sort_order=index)
    for order, (name_ar, name_en, procedures, body_ar, body_en) in enumerate(SHEETS, start=1):
        _sheet, created = InstructionSheet.objects.get_or_create(
            name_en=name_en,
            defaults={"name_ar": name_ar, "procedures": procedures, "body_ar": body_ar, "body_en": body_en,
                      "sort_order": order},
        )
        added += created
    return added
