"""Starting lists for prescriptions and post-operative instructions.

They are only a starting point: the head of CIA reviews and edits them in
Settings → Prescriptions and instructions. Re-running setup never overwrites edits.
"""

from .models import (
    ConsentTemplate, Drug, DrugGroup, InstructionSheet, PrescriptionTemplate, PrescriptionTemplateLine,
)

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
    # Injections: the route (IM = عضل, IV = وريد) is written in the dose; the doctor reviews them in Settings.
    ("سيفترياكسون ١ جم حقن (عضل / وريد)", "Ceftriaxone 1 g injection (IM / IV)", "injection",
     "حقنة عضل أو وريد مرة واحدة يوميًا لمدة ٣ أيام، بعد اختبار الحساسية", ["Ceftriaxone 1 g vial", "Cefaxone 1 g vial"]),
    ("كليندامايسين ٦٠٠ مجم حقن (عضل / وريد) — حساسية البنسلين",
     "Clindamycin 600 mg injection (IM / IV) — penicillin allergy", "injection",
     "حقنة عضل أو وريد كل ١٢ ساعة حسب تعليمات الطبيب", ["Dalacin C 600 mg ampoule"]),
    ("ديكساميثازون ٨ مجم حقن (عضل / وريد)", "Dexamethasone 8 mg injection (IM / IV)", "injection",
     "حقنة واحدة عضل أو وريد يوم العملية حسب تعليمات الطبيب", ["Dexamethasone 8 mg ampoule", "Epidron 8 mg ampoule"]),
    ("ديكلوفيناك صوديوم ٧٥ مجم حقن عضل", "Diclofenac sodium 75 mg injection (IM)", "injection",
     "حقنة عضل عميق عند اللزوم، بحد أقصى حقنتين في اليوم", ["Voltaren 75 mg ampoule", "Declophen 75 mg ampoule"]),
    ("كيتورولاك ٣٠ مجم حقن (عضل / وريد)", "Ketorolac 30 mg injection (IM / IV)", "injection",
     "حقنة عضل أو وريد عند اللزوم كل ٨ ساعات، لمدة لا تزيد عن يومين", ["Ketolac 30 mg ampoule"]),
    # Round 16: the specialties of El Khadem (TMJ muscles, orthodontics). The doctor reviews them in Settings.
    ("أورفينادرين ٣٥ مجم + باراسيتامول ٤٥٠ مجم (مرخي عضلات)", "Orphenadrine 35 mg + paracetamol 450 mg (muscle relaxant)",
     "painkiller", "قرص كل ٨ ساعات بعد الأكل لمدة ٥ أيام", ["Norgesic", "Myofen"]),
    ("تيزانيدين ٢ مجم (مرخي عضلات)", "Tizanidine 2 mg (muscle relaxant)", "other",
     "قرص قبل النوم لمدة ١٠ أيام", ["Sirdalud 2 mg"]),
    ("شمع التقويم", "Orthodontic wax", "other",
     "قطعة صغيرة على السلك أو الحلقة اللي بتجرح الخد أو الشفايف", ["Orthodontic relief wax"]),
]

# (Arabic name, English name, procedures it fits, for penicillin allergy, [English names of drug groups], specialty)
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
    ("بعد الخلع", "After extraction", "extraction", False, ["Ibuprofen 400 mg", "Chlorhexidine 0.12% mouthwash"],
     "oral_surgeon"),
    # Round 16: a ready prescription for each specialty of El Khadem.
    ("بعد علاج العصب", "After root canal treatment", "", False, ["Ibuprofen 400 mg", "Paracetamol 500 mg"],
     "endodontist"),
    ("بعد علاج العصب مع تورم", "After root canal treatment, with swelling", "", False,
     ["Amoxicillin + clavulanic acid 1 g", "Ibuprofen 400 mg"], "endodontist"),
    ("ألم المفصل والعضلات (TMJ)", "TMJ and muscle pain", "", False,
     ["Diclofenac potassium 50 mg", "Orphenadrine 35 mg + paracetamol 450 mg (muscle relaxant)"], "tmj"),
    ("بعد تركيب أو شد التقويم", "After placing or adjusting braces", "", False,
     ["Paracetamol 500 mg", "Orthodontic wax", "Chlorhexidine 0.12% mouthwash"], "orthodontist"),
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
    ("تعليمات بعد تركيب الأسنان على الزرعات", "Instructions after the teeth on your implants", "delivery",
     """امضغ بلطف في الأسبوع الأول، وتجنب الأكل الصلب جدًا (مثل العظم والمكسرات الصلبة) على الأسنان الجديدة.
نظف حول الزرعات مرتين يوميًا: بالفرشاة، والخيط الخاص (سوبر فلوس) أو فرشاة ما بين الأسنان أو الدش المائي.
إذا كانت التركيبة متحركة: اخلعها ونظفها بعد كل وجبة، ولا تنم بها إلا إذا طلب الطبيب ذلك.
إذا شعرت أن الأسنان تتحرك، أو سمعت صوتًا، أو شعرت بألم، أو انكسر شيء: اتصل بنا فورًا.
إذا كنت تضغط على أسنانك أو تجز عليها ليلًا: البس الواقي الليلي.
موعد الكشف بعد أسبوع، ثم كل ٦ أشهر لتنظيف الزرعات ومتابعتها.""",
     """Chew gently for the first week and avoid very hard food (bones, hard nuts) with the new teeth.
Clean around the implants twice a day: brush, superfloss or an interdental brush, or a water flosser.
A removable prosthesis: take it out and clean it after every meal; do not sleep in it unless told to.
If the teeth feel loose, click, hurt, or something breaks: call us at once.
If you clench or grind at night: wear the night guard.
Your check is after one week, then every 6 months for cleaning and checking the implants."""),
    ("تعليمات بعد ترقيع اللثة", "Instructions after soft tissue graft", "soft_tissue",
     """لا تشد الشفة لترى مكان العملية.
لا تستخدم الفرشاة على مكان الترقيع حتى يسمح الطبيب.
إذا أُخذ الترقيع من سقف الحلق فالتزم بلبس الغطاء (stent) كما قال الطبيب.""",
     """Do not pull your lip to look at the area.
Do not brush the graft until the dentist allows it.
If the graft was taken from the palate, wear the palatal stent as instructed."""),
]


# Round 16: the consent forms (Arabic name, English name, words of the treatments they fit, Arabic, English). A
# starting point only: the owner has them checked (by a lawyer too) and edits them in Settings → Consent forms.
CONSENTS = [
    ("موافقة على العلاج والتخدير الموضعي", "Consent to dental treatment and local anaesthesia", "",
     """شرح لي الطبيب حالتي والعلاج المقترح والبدائل الممكنة، ومنها عدم العلاج وما قد يترتب عليه.
أعلم أن التخدير الموضعي قد يسبب تنميلًا مؤقتًا أو تورمًا أو كدمة بسيطة مكان الحقن، ونادرًا تنميلًا أطول.
أخبرت الطبيب بكل أمراضي والأدوية التي أتناولها والحساسية التي عندي، وسأخبره بأي تغيير.
أعلم أن نتيجة العلاج تعتمد أيضًا على التزامي بالتعليمات والمواعيد والنظافة.
أوافق على أخذ الصور والأشعة اللازمة لعلاجي، وتبقى سرية في ملفي.
قرأت هذه الموافقة (أو قُرئت لي) وفهمتها، وسألت ما أردت، وأوافق على بدء العلاج.""",
     """The dentist explained my condition, the treatment proposed and the other options, including no treatment and its results.
I know local anaesthesia may cause temporary numbness, swelling or a small bruise, and rarely a longer numbness.
I told the dentist all my diseases, medicines and allergies, and I will tell any change.
I know the result also depends on my following the instructions, the appointments and my oral hygiene.
I agree to the photos and X-rays needed for my treatment; they stay confidential in my file.
I read this consent (or it was read to me), understood it, asked my questions, and I agree to start."""),
    ("موافقة على زراعة الأسنان", "Consent to dental implant surgery", "implant,sinus,graft,gbr,bone",
     """شرح لي الطبيب خطة الزراعة وعدد الزرعات وأماكنها، وإن كان هناك ترقيع عظم أو رفع للجيب الأنفي.
أعلم أن بعد العملية قد يحدث ألم وتورم وكدمات ونزيف بسيط لأيام، وأن هذا طبيعي.
أعلم أن من المخاطر القليلة: العدوى، أو عدم التحام الزرعة وفشلها، أو تنميل الشفة أو اللسان مؤقتًا أو نادرًا لمدة أطول، أو مشكلة في الجيب الأنفي.
أعلم أن التدخين والسكر غير المنضبط يزيدان خطر فشل الزرعة، وألتزم بالتوقف عن التدخين وضبط السكر.
أعلم أن الزرعة قد تحتاج وقتًا للالتحام قبل تركيب الأسنان، وقد يتغير جزء من الخطة أثناء العملية لمصلحتي.
ألتزم بتعليمات ما بعد العملية والأدوية ومواعيد المتابعة والتنظيف كل ٦ أشهر.""",
     """The dentist explained the implant plan: how many implants, where, and any bone graft or sinus lift.
I know that after surgery there may be pain, swelling, bruising and some bleeding for a few days; this is normal.
I know the less common risks: infection, the implant not integrating (failure), numbness of the lip or tongue (usually temporary, rarely longer), or a sinus problem.
I know smoking and uncontrolled diabetes raise the risk of failure; I will stop smoking and keep my sugar controlled.
I know the implant may need time to heal before the teeth are fitted, and part of the plan may change during surgery for my benefit.
I will follow the after-surgery instructions, the medicines, the follow-up visits and a cleaning every 6 months."""),
    ("موافقة على خلع الأسنان", "Consent to tooth extraction", "extraction,surgical,wisdom",
     """شرح لي الطبيب سبب خلع السن والبدائل الممكنة.
أعلم أن الخلع قد يحتاج جراحة بسيطة (فتح لثة أو تقسيم السن)، وقد يتبقى جزء صغير من الجذر إذا كان إخراجه أخطر من تركه.
أعلم أن من المخاطر: النزيف، الالتهاب أو التجويف الجاف، تورم، تنميل الشفة أو اللسان (خاصة في ضرس العقل السفلي)، أو اتصال بالجيب الأنفي في الأسنان العلوية.
ألتزم بتعليمات ما بعد الخلع والأدوية، وأتصل بالعيادة إذا استمر النزيف أو زاد الألم بعد اليوم الثالث.""",
     """The dentist explained why the tooth is removed and the other options.
I know the extraction may need minor surgery (opening the gum or dividing the tooth), and a small root piece may be left when removing it is riskier.
I know the risks: bleeding, infection or dry socket, swelling, numbness of the lip or tongue (mainly lower wisdom teeth), or an opening to the sinus for upper teeth.
I will follow the instructions and the medicines, and call the clinic if bleeding continues or pain increases after the third day."""),
    ("موافقة على علاج العصب", "Consent to root canal treatment", "root canal,endodontic,endo,pulp",
     """شرح لي الطبيب أن السن يحتاج علاج عصب لإنقاذه، والبديل هو الخلع.
أعلم أن العلاج قد يحتاج أكثر من زيارة، وأن ألمًا بسيطًا بعده لأيام أمر طبيعي.
أعلم أن من المخاطر: كسر آلة داخل القناة، أو ثقب في الجذر، أو قناة لا يمكن تنظيفها كاملًا، أو كسر السن، وقد يحتاج الأمر إعادة العلاج أو جراحة أو خلع.
أعلم أن السن بعد علاج العصب يحتاج حشوًا نهائيًا وغالبًا تاجًا (طربوش) لحمايته من الكسر في أقرب وقت.""",
     """The dentist explained the tooth needs a root canal treatment to be saved; the other option is extraction.
I know the treatment may need more than one visit, and mild pain for a few days after it is normal.
I know the risks: an instrument breaking in the canal, a perforation, a canal that cannot be fully cleaned, or a fractured tooth; it may then need retreatment, surgery or extraction.
I know the tooth needs a final filling and usually a crown soon, to protect it from fracture."""),
    ("موافقة على علاج التقويم", "Consent to orthodontic treatment", "orthodontic,braces,aligner,ortho",
     """شرح لي الطبيب خطة التقويم ومدتها المتوقعة ونوع الجهاز.
أعلم أن المدة قد تطول عن المتوقع حسب استجابة الأسنان والتزامي بالمواعيد والأستك.
أعلم أن من المخاطر: تسوس أو بقع بيضاء حول الأقواس إذا ضعفت النظافة، التهاب اللثة، قِصر بسيط في الجذور، أو ألم في المفصل.
أعلم أن الأسنان قد ترجع بعد التقويم إذا لم ألبس المثبت كما قال الطبيب.""",
     """The dentist explained the orthodontic plan, its expected time and the appliance.
I know the time may be longer than expected, depending on how the teeth respond and on my keeping the appointments and elastics.
I know the risks: decay or white spots around the brackets with poor cleaning, gum inflammation, slight root shortening, or joint pain.
I know the teeth may move back after treatment if I do not wear the retainer as instructed."""),
    ("موافقة على التيجان والجسور والقشور", "Consent to crowns, bridges and veneers", "crown,bridge,veneer,fixed",
     """شرح لي الطبيب أن تحضير السن يزيل جزءًا منه بشكل دائم.
أعلم أن السن قد يصبح حساسًا لفترة، ونادرًا يحتاج علاج عصب بعد التحضير.
اتفقت مع الطبيب على اللون والشكل، وأعلم أن اللون النهائي قد يختلف قليلًا تحت الإضاءات المختلفة.
أعلم أن التاج أو الجسر قد ينكسر أو يحتاج تغييرًا بعد سنوات، وألتزم بالنظافة والمتابعة.""",
     """The dentist explained that preparing the tooth removes part of it for good.
I know the tooth may be sensitive for a while, and rarely needs a root canal after preparation.
I agreed with the dentist on the shade and shape; the final shade may look slightly different under different lights.
I know a crown or bridge may break or need replacing after years; I will keep it clean and come for checks."""),
    ("موافقة على العلاج في الأكاديمية والتصوير للتعليم", "Consent to treatment at the academy and photos for teaching",
     "academy,teaching,photo",
     """أعلم أن علاجي في أكاديمية تعليمية، وقد يقوم به طبيب أسنان متدرب في دورة تحت إشراف ومتابعة طبيب مدرب.
أوافق على تصوير حالتي (صور وأشعة وفيديو) لملف العلاج وسجل التدريب والتعليم.
أعلم أن الصور المستخدمة في التعليم أو النشر العلمي لا تُظهر اسمي ولا وجهي إلا بموافقة أخرى مني.
أعلم أن من حقي أن أسأل عن الطبيب المعالج والمشرف في أي وقت.""",
     """I know I am treated at a teaching academy, possibly by a dentist on a course, under the supervision of an instructor.
I agree to photos, X-rays and videos of my case for my file, the training log book and teaching.
I know the photos used for teaching or scientific publication do not show my name or face unless I agree again.
I know I may ask at any time who treats me and who supervises."""),
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
    for order, (name_ar, name_en, procedures, allergy, lines, *rest) in enumerate(TEMPLATES, start=1):
        template, created = PrescriptionTemplate.objects.get_or_create(
            name_en=name_en,
            defaults={"name_ar": name_ar, "procedures": procedures, "for_penicillin_allergy": allergy, "sort_order": order,
                      "specialty": rest[0] if rest else ""},
        )
        added += created
        if created:
            for index, group_name in enumerate(lines):
                PrescriptionTemplateLine.objects.create(template=template, group=groups[group_name], sort_order=index)
    for order, (name_ar, name_en, procedures, body_ar, body_en) in enumerate(CONSENTS, start=1):
        _consent, created = ConsentTemplate.objects.get_or_create(
            name_en=name_en, defaults={"name_ar": name_ar, "procedures": procedures, "body_ar": body_ar,
                                       "body_en": body_en, "sort_order": order})
        added += created
    for order, (name_ar, name_en, procedures, body_ar, body_en) in enumerate(SHEETS, start=1):
        _sheet, created = InstructionSheet.objects.get_or_create(
            name_en=name_en,
            defaults={"name_ar": name_ar, "procedures": procedures, "body_ar": body_ar, "body_en": body_en,
                      "sort_order": order},
        )
        added += created
    return added
