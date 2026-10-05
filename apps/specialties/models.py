"""The specialists of a clinic (El Khadem): referrals between the doctors, and each specialist's own chart:
endodontics (canal by canal), the TMJ examination, orthodontics (records and adjustments) and the shade
taken for the prosthesis. Each record belongs to a patient and a place, and is written by a doctor."""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import Branch, TimeStampedModel
from apps.dentists.models import Dentist

from . import shades

VAS = [MinValueValidator(0), MaxValueValidator(10)]


def labels(choices, codes):
    """The labels of the codes kept in a list field (in the reader's language)."""
    names = dict(choices)
    return [names[code] for code in codes or [] if code in names]


class Referral(TimeStampedModel):
    """A doctor sends a patient to a specialist (inside the clinic or outside): the letter, the booking by the
    reception, and the specialist's answer back."""

    class Urgency(models.TextChoices):
        ROUTINE = "routine", _("Routine")
        SOON = "soon", _("Soon (within a week)")
        URGENT = "urgent", _("Urgent (pain / swelling)")

    class Status(models.TextChoices):
        SENT = "sent", _("Sent: to book")
        BOOKED = "booked", _("Booked")
        DONE = "done", _("Seen: answer sent back")
        DECLINED = "declined", _("The patient did not want it")
        CANCELLED = "cancelled", _("Cancelled")

    OPEN = (Status.SENT, Status.BOOKED)

    number = models.CharField(_("number"), max_length=20, unique=True, blank=True, editable=False)
    branch = models.ForeignKey(Branch, verbose_name=_("place"), on_delete=models.PROTECT, related_name="referrals")
    patient = models.ForeignKey("patients.Patient", verbose_name=_("patient"), on_delete=models.PROTECT,
                                related_name="referrals")
    from_dentist = models.ForeignKey("dentists.Dentist", verbose_name=_("referred by"), null=True,
                                     on_delete=models.PROTECT, related_name="referrals_sent")
    to_dentist = models.ForeignKey("dentists.Dentist", verbose_name=_("to the doctor"), null=True, blank=True,
                                   on_delete=models.PROTECT, related_name="referrals_received",
                                   help_text=_("One of our doctors. Empty when the patient goes outside the clinic."))
    to_outside = models.CharField(_("or outside the clinic"), max_length=150, blank=True,
                                  help_text=_("The doctor or centre outside, e.g. a radiology centre."))
    specialty = models.CharField(_("specialty"), max_length=20, blank=True, choices=Dentist.Specialty.choices)
    teeth = models.CharField(_("teeth"), max_length=100, blank=True)
    reason = models.TextField(_("what to do, and why"))
    urgency = models.CharField(_("urgency"), max_length=10, choices=Urgency.choices, default=Urgency.ROUTINE)
    status = models.CharField(_("status"), max_length=10, choices=Status.choices, default=Status.SENT, db_index=True)
    appointment = models.ForeignKey("scheduling.Appointment", verbose_name=_("appointment"), null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="referrals")
    reply = models.TextField(_("the specialist's answer"), blank=True,
                             help_text=_("What was found, what was done, and what the referring doctor should do next."))
    replied_at = models.DateTimeField(_("answered at"), null=True, blank=True)
    replied_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("answered by"), null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("referral")
        verbose_name_plural = _("referrals")

    def __str__(self):
        return f"{self.number} — {self.patient.full_name}"

    def get_absolute_url(self):
        return reverse("specialties:referral", args=[self.pk])

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.number:
                self.number = f"RF-{self.pk:06d}"
                type(self).objects.filter(pk=self.pk).update(number=self.number)

    @property
    def to_name(self):
        return str(self.to_dentist) if self.to_dentist_id else self.to_outside

    @property
    def is_open(self):
        return self.status in self.OPEN


class SpecialistRecord(TimeStampedModel):
    """What every specialist chart has: the patient, the place, the doctor, the day, and the referral it answers."""

    patient = models.ForeignKey("patients.Patient", verbose_name=_("patient"), on_delete=models.PROTECT,
                                related_name="%(class)ss")
    branch = models.ForeignKey(Branch, verbose_name=_("place"), on_delete=models.PROTECT, related_name="+")
    dentist = models.ForeignKey("dentists.Dentist", verbose_name=_("doctor"), null=True, on_delete=models.PROTECT,
                                related_name="+")
    referral = models.ForeignKey(Referral, verbose_name=_("for the referral"), null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="+")
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        abstract = True


# ------------------------------------------------------------------ endodontics
class EndoCase(SpecialistRecord):
    """A root canal case of one tooth: history and tests, the AAE diagnosis and difficulty, the canals with their
    working lengths, the medication between visits, the obturation and what to do next."""

    class Pain(models.TextChoices):
        NONE = "none", _("No pain")
        MILD = "mild", _("Mild")
        MODERATE = "moderate", _("Moderate")
        SEVERE = "severe", _("Severe")

    PAIN_KINDS = [("spontaneous", _("Spontaneous")), ("provoked", _("Provoked (cold / hot / sweet)")),
                  ("lingering", _("Lingers after the stimulus")), ("night", _("Wakes at night")),
                  ("biting", _("On biting / chewing")), ("radiating", _("Radiating (ear, head)"))]

    class Test(models.TextChoices):
        NORMAL = "normal", _("Normal response")
        NONE = "none", _("No response")
        LINGERING = "lingering", _("Lingering response")
        EXAGGERATED = "exaggerated", _("Exaggerated, short")
        NOT_DONE = "not_done", _("Not done")

    class Tender(models.TextChoices):
        NORMAL = "normal", _("Not tender")
        TENDER = "tender", _("Tender")
        VERY = "very", _("Very tender")

    class Swelling(models.TextChoices):
        NONE = "none", _("None")
        LOCAL = "local", _("Localised")
        DIFFUSE = "diffuse", _("Diffuse (cellulitis)")

    class Pulp(models.TextChoices):  # AAE
        NORMAL = "normal", _("Normal pulp")
        REVERSIBLE = "reversible", _("Reversible pulpitis")
        SYMPTOMATIC_IRREVERSIBLE = "sym_irreversible", _("Symptomatic irreversible pulpitis")
        ASYMPTOMATIC_IRREVERSIBLE = "asym_irreversible", _("Asymptomatic irreversible pulpitis")
        NECROSIS = "necrosis", _("Pulp necrosis")
        TREATED = "treated", _("Previously treated")
        INITIATED = "initiated", _("Previously initiated therapy")

    class Apical(models.TextChoices):  # AAE
        NORMAL = "normal", _("Normal apical tissues")
        SYMPTOMATIC = "symptomatic", _("Symptomatic apical periodontitis")
        ASYMPTOMATIC = "asymptomatic", _("Asymptomatic apical periodontitis")
        CHRONIC_ABSCESS = "chronic_abscess", _("Chronic apical abscess")
        ACUTE_ABSCESS = "acute_abscess", _("Acute apical abscess")
        CONDENSING = "condensing", _("Condensing osteitis")

    class Difficulty(models.TextChoices):  # AAE Endodontic Case Difficulty Assessment
        MINIMAL = "minimal", _("Minimal difficulty")
        MODERATE = "moderate", _("Moderate difficulty")
        HIGH = "high", _("High difficulty")

    DIFFICULTY_FACTORS = [
        ("curvature", _("Severe root curvature (> 30°) or S-shaped canal")),
        ("calcified", _("Calcified / hardly visible canals")),
        ("long", _("Long tooth (> 25 mm) or short root")),
        ("open_apex", _("Open apex (> 1.5 mm)")),
        ("resorption", _("Resorption (internal / external)")),
        ("extra_canals", _("Extra canals (e.g. MB2, C-shaped)")),
        ("retreatment", _("Retreatment: post, silver points, ledge or blockage")),
        ("perforation", _("Perforation or separated instrument")),
        ("access", _("Limited mouth opening or access")),
        ("isolation", _("Hard to isolate (rubber dam)")),
        ("medical", _("Medical condition (ASA III or more)")),
        ("anaesthesia", _("History of failed anaesthesia")),
        ("trauma", _("Trauma: luxation, avulsion, fracture")),
    ]

    class Treatment(models.TextChoices):
        PULPOTOMY = "pulpotomy", _("Pulpotomy (vital pulp therapy)")
        INITIAL = "initial", _("Initial root canal treatment")
        RETREATMENT = "retreatment", _("Non-surgical retreatment")
        APEXIFICATION = "apexification", _("Apexification (MTA plug)")
        REGENERATIVE = "regenerative", _("Regenerative endodontics")
        APICOECTOMY = "apicoectomy", _("Apical surgery (apicoectomy)")
        OTHER = "other", _("Other")

    IRRIGANTS = [("naocl_25", _("NaOCl 2.5%")), ("naocl_525", _("NaOCl 5.25%")), ("edta", _("EDTA 17%")),
                 ("chx", _("Chlorhexidine 2%")), ("saline", _("Saline")), ("citric", _("Citric acid 10%"))]

    class Activation(models.TextChoices):
        NONE = "none", _("Needle only")
        SONIC = "sonic", _("Sonic (EndoActivator)")
        ULTRASONIC = "ultrasonic", _("Ultrasonic (PUI)")
        XP = "xp", _("XP-endo Finisher")
        LASER = "laser", _("Laser")

    class Obturation(models.TextChoices):
        LATERAL = "lateral", _("Cold lateral condensation")
        WARM_VERTICAL = "warm_vertical", _("Warm vertical condensation")
        CONTINUOUS_WAVE = "continuous_wave", _("Continuous wave")
        SINGLE_CONE = "single_cone", _("Single cone with bioceramic sealer")
        CARRIER = "carrier", _("Carrier-based (Thermafil / GuttaCore)")
        MTA = "mta", _("MTA / bioceramic plug")

    class Sealer(models.TextChoices):
        AH_PLUS = "ah_plus", _("AH Plus (epoxy resin)")
        BIOCERAMIC = "bioceramic", _("Bioceramic (BC Sealer / TotalFill)")
        ADSEAL = "adseal", _("Adseal")
        ZOE = "zoe", _("Zinc oxide eugenol")
        OTHER = "other", _("Other")

    class Restoration(models.TextChoices):
        CROWN = "crown", _("Full crown")
        ONLAY = "onlay", _("Onlay / overlay")
        POST_CROWN = "post_crown", _("Fibre post, core and crown")
        COMPOSITE = "composite", _("Direct composite")
        OTHER = "other", _("Other")

    class Prognosis(models.TextChoices):
        FAVOURABLE = "favourable", _("Favourable")
        QUESTIONABLE = "questionable", _("Questionable")
        UNFAVOURABLE = "unfavourable", _("Unfavourable")

    class Status(models.TextChoices):
        OPEN = "open", _("In treatment")
        OBTURATED = "obturated", _("Obturated (finished)")
        STOPPED = "stopped", _("Stopped")

    tooth = models.PositiveSmallIntegerField(_("tooth"))
    started_on = models.DateField(_("first visit"), default=timezone.localdate)
    status = models.CharField(_("status"), max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    # History and tests
    chief_complaint = models.TextField(_("chief complaint"), blank=True)
    pain = models.CharField(_("pain now"), max_length=10, choices=Pain.choices, blank=True)
    pain_kinds = models.JSONField(_("the pain"), default=list, blank=True)
    cold_test = models.CharField(_("cold test"), max_length=12, choices=Test.choices, blank=True)
    heat_test = models.CharField(_("heat test"), max_length=12, choices=Test.choices, blank=True)
    ept = models.CharField(_("electric pulp test (reading)"), max_length=30, blank=True)
    percussion = models.CharField(_("percussion"), max_length=8, choices=Tender.choices, blank=True)
    palpation = models.CharField(_("palpation"), max_length=8, choices=Tender.choices, blank=True)
    mobility = models.PositiveSmallIntegerField(_("mobility (grade)"), null=True, blank=True,
                                                choices=[(0, "0"), (1, "I"), (2, "II"), (3, "III")])
    probing = models.CharField(_("deepest probing (mm)"), max_length=30, blank=True)
    swelling = models.CharField(_("swelling"), max_length=8, choices=Swelling.choices, blank=True)
    sinus_tract = models.BooleanField(_("sinus tract"), default=False)
    radiographic = models.TextField(_("X-ray / CBCT findings"), blank=True,
                                    help_text=_("e.g. PDL widening, periapical radiolucency 4 × 5 mm, calcified canal."))
    # Diagnosis
    pulpal_diagnosis = models.CharField(_("pulpal diagnosis"), max_length=20, choices=Pulp.choices, blank=True)
    apical_diagnosis = models.CharField(_("apical diagnosis"), max_length=20, choices=Apical.choices, blank=True)
    difficulty = models.CharField(_("case difficulty (AAE)"), max_length=10, choices=Difficulty.choices, blank=True)
    difficulty_factors = models.JSONField(_("what makes it difficult"), default=list, blank=True)
    # Treatment
    treatment = models.CharField(_("treatment"), max_length=15, choices=Treatment.choices, default=Treatment.INITIAL)
    anaesthesia = models.CharField(_("anaesthesia"), max_length=120, blank=True,
                                   help_text=_("e.g. Articaine 4% IANB + buccal infiltration"))
    rubber_dam = models.BooleanField(_("rubber dam"), default=True)
    magnification = models.CharField(_("magnification"), max_length=60, blank=True,
                                     help_text=_("e.g. microscope, loupes 3.5×"))
    instruments = models.CharField(_("files / system"), max_length=120, blank=True,
                                   help_text=_("e.g. ProTaper Gold to F2, WaveOne Gold Primary, K-files"))
    irrigants = models.JSONField(_("irrigation"), default=list, blank=True)
    activation = models.CharField(_("irrigant activation"), max_length=12, choices=Activation.choices, blank=True)
    obturation = models.CharField(_("obturation"), max_length=20, choices=Obturation.choices, blank=True)
    sealer = models.CharField(_("sealer"), max_length=12, choices=Sealer.choices, blank=True)
    obturated_on = models.DateField(_("obturated on"), null=True, blank=True)
    restoration = models.CharField(_("final restoration advised"), max_length=12, choices=Restoration.choices,
                                   blank=True)
    prognosis = models.CharField(_("prognosis"), max_length=15, choices=Prognosis.choices, blank=True)
    recall = models.CharField(_("recall"), max_length=100, blank=True, help_text=_("e.g. X-ray after 6 and 12 months"))
    treatment_step = models.ForeignKey("clinical.TreatmentStep", verbose_name=_("in the treatment log"), null=True,
                                       blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-started_on", "-pk"]
        verbose_name = _("endodontic case")
        verbose_name_plural = _("endodontic cases")

    def __str__(self):
        return f"{_('Endodontics')} {self.tooth} — {self.patient.full_name}"

    def get_absolute_url(self):
        return reverse("specialties:endo", args=[self.pk])

    def pain_labels(self):
        return labels(self.PAIN_KINDS, self.pain_kinds)

    def factor_labels(self):
        return labels(self.DIFFICULTY_FACTORS, self.difficulty_factors)

    def irrigant_labels(self):
        return labels(self.IRRIGANTS, self.irrigants)


class EndoCanal(models.Model):
    """One canal: where it is measured from, its working length, the last file and the cone."""

    class Method(models.TextChoices):
        APEX_LOCATOR = "apex_locator", _("Apex locator")
        XRAY = "xray", _("X-ray")
        BOTH = "both", _("Apex locator + X-ray")

    class Curve(models.TextChoices):
        STRAIGHT = "straight", _("Straight")
        MILD = "mild", _("Mild (< 10°)")
        MODERATE = "moderate", _("Moderate (10–25°)")
        SEVERE = "severe", _("Severe (> 25°)")

    NAMES = ["MB", "MB2", "DB", "P", "D", "M", "ML", "DL", "B", "L", "Single"]

    case = models.ForeignKey(EndoCase, on_delete=models.CASCADE, related_name="canals")
    name = models.CharField(_("canal"), max_length=12)
    reference = models.CharField(_("reference point"), max_length=40, blank=True, help_text=_("e.g. MB cusp"))
    working_length = models.DecimalField(_("working length (mm)"), max_digits=4, decimal_places=1, null=True,
                                         blank=True, validators=[MinValueValidator(5), MaxValueValidator(40)])
    method = models.CharField(_("measured by"), max_length=12, choices=Method.choices, blank=True)
    master_file = models.CharField(_("master apical file"), max_length=20, blank=True, help_text=_("e.g. 25/.06"))
    master_cone = models.CharField(_("master cone"), max_length=20, blank=True)
    curvature = models.CharField(_("curvature"), max_length=10, choices=Curve.choices, blank=True)
    notes = models.CharField(_("notes"), max_length=150, blank=True)

    class Meta:
        ordering = ["pk"]
        verbose_name = _("canal")
        verbose_name_plural = _("canals")

    def __str__(self):
        return self.name


class EndoVisit(models.Model):
    """One visit of the case: what was done, the medication left in the canals and the temporary filling."""

    class Medication(models.TextChoices):
        NONE = "none", _("None")
        CAOH = "caoh", _("Calcium hydroxide")
        LEDERMIX = "ledermix", _("Ledermix")
        TAP = "tap", _("Triple antibiotic paste")
        CHX = "chx", _("Chlorhexidine gel")
        CRESOPHENE = "cresophene", _("Cresophene / formocresol pellet")

    class Temporary(models.TextChoices):
        CAVIT = "cavit", _("Cavit")
        GIC = "gic", _("Glass ionomer")
        IRM = "irm", _("IRM")
        COMPOSITE = "composite", _("Composite")
        NONE = "none", _("None")

    WORK = [("access", _("Access and pulp extirpation")), ("wl", _("Working length")),
            ("shaping", _("Cleaning and shaping")), ("medication", _("Medication placed")),
            ("obturation", _("Obturation")), ("retreatment", _("Old filling / post removed")),
            ("drainage", _("Drainage")), ("recall", _("Recall check"))]

    case = models.ForeignKey(EndoCase, on_delete=models.CASCADE, related_name="visits")
    date = models.DateField(_("date"), default=timezone.localdate)
    work = models.JSONField(_("done at this visit"), default=list, blank=True)
    medication = models.CharField(_("intracanal medication"), max_length=12, choices=Medication.choices, blank=True)
    temporary = models.CharField(_("temporary filling"), max_length=10, choices=Temporary.choices, blank=True)
    pain = models.PositiveSmallIntegerField(_("pain before (0–10)"), null=True, blank=True, validators=VAS)
    notes = models.CharField(_("notes"), max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+", editable=False)

    class Meta:
        ordering = ["date", "pk"]
        verbose_name = _("endodontic visit")
        verbose_name_plural = _("endodontic visits")

    def work_labels(self):
        return labels(self.WORK, self.work)


# ------------------------------------------------------------------ TMJ
class TMJExam(SpecialistRecord):
    """The TMJ examination (after DC/TMD): pain, jaw movements in mm, joint sounds, locking, the muscles that are
    tender, the diagnosis and the plan; then each follow-up visit."""

    class Bruxism(models.TextChoices):
        NONE = "none", _("None")
        AWAKE = "awake", _("Awake clenching")
        SLEEP = "sleep", _("Sleep grinding")
        BOTH = "both", _("Awake and sleep")

    class Path(models.TextChoices):
        STRAIGHT = "straight", _("Straight")
        DEVIATION_R = "deviation_r", _("Deviation to the right (comes back)")
        DEVIATION_L = "deviation_l", _("Deviation to the left (comes back)")
        DEFLECTION_R = "deflection_r", _("Deflection to the right")
        DEFLECTION_L = "deflection_l", _("Deflection to the left")

    class Sound(models.TextChoices):
        NONE = "none", _("None")
        OPENING = "opening", _("Click on opening")
        CLOSING = "closing", _("Click on closing")
        RECIPROCAL = "reciprocal", _("Reciprocal click")
        CREPITUS = "crepitus", _("Crepitus")

    class Locking(models.TextChoices):
        NONE = "none", _("None")
        CLOSED_NOW = "closed_now", _("Closed lock now")
        CLOSED_PAST = "closed_past", _("Closed lock in the past")
        INTERMITTENT = "intermittent", _("Catches, then opens")
        OPEN = "open", _("Open lock (cannot close)")

    PAIN_SITES = [("joint_r", _("Right joint")), ("joint_l", _("Left joint")), ("ear", _("Ear")),
                  ("temple", _("Temple")), ("cheek", _("Cheek / masseter")), ("neck", _("Neck / shoulder")),
                  ("teeth", _("Teeth"))]
    MUSCLES = [("masseter_r", _("Masseter right")), ("masseter_l", _("Masseter left")),
               ("temporalis_r", _("Temporalis right")), ("temporalis_l", _("Temporalis left")),
               ("lat_pterygoid_r", _("Lateral pterygoid right")), ("lat_pterygoid_l", _("Lateral pterygoid left")),
               ("med_pterygoid_r", _("Medial pterygoid right")), ("med_pterygoid_l", _("Medial pterygoid left")),
               ("scm_r", _("Sternocleidomastoid right")), ("scm_l", _("Sternocleidomastoid left")),
               ("trapezius", _("Trapezius"))]
    DIAGNOSES = [("myalgia", _("Myalgia")), ("myofascial", _("Myofascial pain with referral")),
                 ("arthralgia", _("Arthralgia")), ("dd_r", _("Disc displacement with reduction")),
                 ("dd_r_lock", _("Disc displacement with reduction, with intermittent locking")),
                 ("dd_nr_limited", _("Disc displacement without reduction, with limited opening")),
                 ("dd_nr", _("Disc displacement without reduction, without limited opening")),
                 ("djd", _("Degenerative joint disease (osteoarthritis)")), ("subluxation", _("Subluxation")),
                 ("headache", _("Headache attributed to TMD")), ("bruxism", _("Bruxism"))]
    PLAN = [("counselling", _("Counselling and self-care")), ("stabilization", _("Stabilization splint")),
            ("repositioning", _("Anterior repositioning splint")), ("physio", _("Physiotherapy and exercises")),
            ("nsaids", _("Anti-inflammatory drugs")), ("relaxant", _("Muscle relaxant")),
            ("botox", _("Botulinum toxin injection")), ("arthrocentesis", _("Arthrocentesis")),
            ("injection", _("Joint injection (PRP / hyaluronic acid)")), ("occlusal", _("Occlusal treatment")),
            ("surgery", _("Joint surgery"))]

    exam_date = models.DateField(_("date"), default=timezone.localdate)
    chief_complaint = models.TextField(_("chief complaint"), blank=True)
    since = models.CharField(_("since when"), max_length=100, blank=True)
    pain_vas = models.PositiveSmallIntegerField(_("pain now (0–10)"), null=True, blank=True, validators=VAS)
    pain_sites = models.JSONField(_("where it hurts"), default=list, blank=True)
    headache = models.BooleanField(_("headaches"), default=False)
    bruxism = models.CharField(_("clenching / grinding"), max_length=8, choices=Bruxism.choices, blank=True)
    habits = models.CharField(_("habits"), max_length=150, blank=True, help_text=_("e.g. gum chewing, nail biting"))
    opening = models.PositiveSmallIntegerField(_("mouth opening without help (mm)"), null=True, blank=True)
    opening_max = models.PositiveSmallIntegerField(_("maximum opening with help (mm)"), null=True, blank=True)
    opening_pain = models.BooleanField(_("pain on opening"), default=False)
    right_lateral = models.PositiveSmallIntegerField(_("to the right (mm)"), null=True, blank=True)
    left_lateral = models.PositiveSmallIntegerField(_("to the left (mm)"), null=True, blank=True)
    protrusion = models.PositiveSmallIntegerField(_("forward (mm)"), null=True, blank=True)
    path = models.CharField(_("opening path"), max_length=15, choices=Path.choices, blank=True)
    sound_right = models.CharField(_("right joint sounds"), max_length=12, choices=Sound.choices, blank=True)
    sound_left = models.CharField(_("left joint sounds"), max_length=12, choices=Sound.choices, blank=True)
    locking = models.CharField(_("locking"), max_length=15, choices=Locking.choices, blank=True)
    joint_tender_right = models.BooleanField(_("right joint tender"), default=False)
    joint_tender_left = models.BooleanField(_("left joint tender"), default=False)
    muscles = models.JSONField(_("tender muscles"), default=list, blank=True)
    occlusion = models.CharField(_("occlusion"), max_length=200, blank=True,
                                 help_text=_("e.g. missing back teeth, Class II, deep bite, interferences"))
    imaging = models.TextField(_("panorama / CBCT / MRI"), blank=True)
    diagnoses = models.JSONField(_("diagnosis (DC/TMD)"), default=list, blank=True)
    plan = models.JSONField(_("treatment plan"), default=list, blank=True)
    splint = models.CharField(_("splint"), max_length=120, blank=True,
                              help_text=_("e.g. hard upper stabilization splint, worn at night"))

    class Meta:
        ordering = ["-exam_date", "-pk"]
        verbose_name = _("TMJ examination")
        verbose_name_plural = _("TMJ examinations")

    def __str__(self):
        return f"{_('TMJ')} — {self.patient.full_name} ({self.exam_date:%d/%m/%Y})"

    def get_absolute_url(self):
        return reverse("specialties:tmj", args=[self.pk])

    def site_labels(self):
        return labels(self.PAIN_SITES, self.pain_sites)

    def muscle_labels(self):
        return labels(self.MUSCLES, self.muscles)

    def diagnosis_labels(self):
        return labels(self.DIAGNOSES, self.diagnoses)

    def plan_labels(self):
        return labels(self.PLAN, self.plan)

    @property
    def opening_limited(self):
        return self.opening is not None and self.opening < 40


class TMJVisit(models.Model):
    exam = models.ForeignKey(TMJExam, on_delete=models.CASCADE, related_name="visits")
    date = models.DateField(_("date"), default=timezone.localdate)
    opening = models.PositiveSmallIntegerField(_("mouth opening (mm)"), null=True, blank=True)
    pain_vas = models.PositiveSmallIntegerField(_("pain (0–10)"), null=True, blank=True, validators=VAS)
    done = models.CharField(_("what was done"), max_length=200, blank=True,
                            help_text=_("e.g. splint delivered and adjusted, botox 25 U each masseter"))
    notes = models.CharField(_("notes"), max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+", editable=False)

    class Meta:
        ordering = ["date", "pk"]
        verbose_name = _("TMJ follow-up")
        verbose_name_plural = _("TMJ follow-ups")


# ------------------------------------------------------------------ orthodontics
class OrthoCase(SpecialistRecord):
    """An orthodontic case: the records (face, occlusion, cephalometric values), the diagnosis and plan, then each
    adjustment visit with the wires, elastics or aligner number."""

    class Status(models.TextChoices):
        RECORDS = "records", _("Records and planning")
        ACTIVE = "active", _("In treatment")
        RETENTION = "retention", _("Retention")
        FINISHED = "finished", _("Finished")
        STOPPED = "stopped", _("Stopped")

    class Profile(models.TextChoices):
        STRAIGHT = "straight", _("Straight")
        CONVEX = "convex", _("Convex")
        CONCAVE = "concave", _("Concave")

    class Lips(models.TextChoices):
        COMPETENT = "competent", _("Competent")
        INCOMPETENT = "incompetent", _("Incompetent")

    class Smile(models.TextChoices):
        LOW = "low", _("Low")
        AVERAGE = "average", _("Average")
        HIGH = "high", _("High (gummy smile)")

    class Relation(models.TextChoices):
        CLASS_I = "I", _("Class I")
        CLASS_II_HALF = "II_half", _("Class II (½ unit)")
        CLASS_II = "II", _("Class II (full unit)")
        CLASS_III_HALF = "III_half", _("Class III (½ unit)")
        CLASS_III = "III", _("Class III (full unit)")

    class Skeletal(models.TextChoices):
        CLASS_I = "I", _("Skeletal Class I")
        CLASS_II = "II", _("Skeletal Class II")
        CLASS_III = "III", _("Skeletal Class III")

    class Vertical(models.TextChoices):
        NORMAL = "normal", _("Normal angle")
        HIGH = "high", _("High angle (long face)")
        LOW = "low", _("Low angle (short face)")

    class Appliance(models.TextChoices):
        METAL = "metal", _("Fixed: metal brackets")
        CERAMIC = "ceramic", _("Fixed: ceramic brackets")
        SELF_LIGATING = "self_ligating", _("Fixed: self-ligating")
        LINGUAL = "lingual", _("Fixed: lingual")
        ALIGNERS = "aligners", _("Clear aligners")
        REMOVABLE = "removable", _("Removable appliance")
        FUNCTIONAL = "functional", _("Functional appliance (e.g. Twin Block)")
        EXPANDER = "expander", _("Expander (RPE)")

    class Prescription(models.TextChoices):
        MBT = "mbt", _("MBT")
        ROTH = "roth", _("Roth")
        DAMON = "damon", _("Damon")
        OTHER = "other", _("Other")

    class Retention(models.TextChoices):
        BONDED = "bonded", _("Bonded (fixed) retainer")
        HAWLEY = "hawley", _("Hawley retainer")
        ESSIX = "essix", _("Clear (Essix) retainer")
        COMBINED = "combined", _("Bonded + clear retainer")

    ANCHORAGE = [("tads", _("Mini-screws (TADs)")), ("tpa", _("Transpalatal arch / Nance")),
                 ("headgear", _("Headgear")), ("elastics", _("Inter-arch elastics"))]

    status = models.CharField(_("status"), max_length=10, choices=Status.choices, default=Status.RECORDS,
                              db_index=True)
    records_on = models.DateField(_("records taken on"), default=timezone.localdate)
    chief_complaint = models.TextField(_("chief complaint"), blank=True)
    # The face
    profile = models.CharField(_("profile"), max_length=10, choices=Profile.choices, blank=True)
    symmetric = models.BooleanField(_("face symmetric"), default=True)
    lips = models.CharField(_("lips"), max_length=12, choices=Lips.choices, blank=True)
    smile_line = models.CharField(_("smile line"), max_length=8, choices=Smile.choices, blank=True)
    # The teeth
    molar_right = models.CharField(_("molars right"), max_length=10, choices=Relation.choices, blank=True)
    molar_left = models.CharField(_("molars left"), max_length=10, choices=Relation.choices, blank=True)
    canine_right = models.CharField(_("canines right"), max_length=10, choices=Relation.choices, blank=True)
    canine_left = models.CharField(_("canines left"), max_length=10, choices=Relation.choices, blank=True)
    overjet = models.DecimalField(_("overjet (mm)"), max_digits=4, decimal_places=1, null=True, blank=True)
    overbite = models.DecimalField(_("overbite (mm)"), max_digits=4, decimal_places=1, null=True, blank=True,
                                   help_text=_("Below 0 = open bite."))
    crossbite = models.CharField(_("crossbite"), max_length=100, blank=True, help_text=_("Which teeth, e.g. 12, 22"))
    midline = models.CharField(_("midlines"), max_length=100, blank=True,
                               help_text=_("e.g. upper centred, lower 2 mm to the left"))
    crowding_upper = models.DecimalField(_("upper crowding (mm)"), max_digits=4, decimal_places=1, null=True,
                                         blank=True, help_text=_("Below 0 = spacing."))
    crowding_lower = models.DecimalField(_("lower crowding (mm)"), max_digits=4, decimal_places=1, null=True,
                                         blank=True)
    habits = models.CharField(_("habits"), max_length=150, blank=True,
                              help_text=_("e.g. thumb sucking, tongue thrust, mouth breathing"))
    # The cephalometric values
    sna = models.DecimalField("SNA (°)", max_digits=4, decimal_places=1, null=True, blank=True)
    snb = models.DecimalField("SNB (°)", max_digits=4, decimal_places=1, null=True, blank=True)
    anb = models.DecimalField("ANB (°)", max_digits=4, decimal_places=1, null=True, blank=True)
    fma = models.DecimalField(_("FMA / SN-MP (°)"), max_digits=4, decimal_places=1, null=True, blank=True)
    u1_sn = models.DecimalField("U1-SN (°)", max_digits=4, decimal_places=1, null=True, blank=True)
    impa = models.DecimalField("IMPA (°)", max_digits=4, decimal_places=1, null=True, blank=True)
    wits = models.DecimalField(_("Wits (mm)"), max_digits=4, decimal_places=1, null=True, blank=True)
    skeletal = models.CharField(_("skeletal class"), max_length=5, choices=Skeletal.choices, blank=True)
    vertical = models.CharField(_("vertical pattern"), max_length=8, choices=Vertical.choices, blank=True)
    diagnosis = models.TextField(_("diagnosis and problem list"), blank=True)
    # The plan
    appliance = models.CharField(_("appliance"), max_length=15, choices=Appliance.choices, blank=True)
    prescription = models.CharField(_("bracket prescription"), max_length=6, choices=Prescription.choices, blank=True)
    extraction = models.CharField(_("extractions"), max_length=100, blank=True,
                                  help_text=_("Empty = no extraction. e.g. 14, 24, 34, 44"))
    anchorage = models.JSONField(_("anchorage"), default=list, blank=True)
    months = models.PositiveSmallIntegerField(_("expected months"), null=True, blank=True)
    retention = models.CharField(_("retention"), max_length=10, choices=Retention.choices, blank=True)
    bonded_on = models.DateField(_("bonded / first aligners on"), null=True, blank=True)
    debonded_on = models.DateField(_("debonded on"), null=True, blank=True)

    class Meta:
        ordering = ["-records_on", "-pk"]
        verbose_name = _("orthodontic case")
        verbose_name_plural = _("orthodontic cases")

    def __str__(self):
        return f"{_('Orthodontics')} — {self.patient.full_name}"

    def get_absolute_url(self):
        return reverse("specialties:ortho", args=[self.pk])

    def anchorage_labels(self):
        return labels(self.ANCHORAGE, self.anchorage)

    @property
    def months_in_treatment(self):
        if not self.bonded_on:
            return None
        end = self.debonded_on or timezone.localdate()
        return max((end.year - self.bonded_on.year) * 12 + end.month - self.bonded_on.month, 0)


class OrthoVisit(models.Model):
    class Hygiene(models.TextChoices):
        GOOD = "good", _("Good")
        FAIR = "fair", _("Fair")
        POOR = "poor", _("Poor")

    WIRES = ["0.012 NiTi", "0.014 NiTi", "0.016 NiTi", "0.018 NiTi", "0.016×0.022 NiTi", "0.017×0.025 NiTi",
             "0.019×0.025 NiTi", "0.016 SS", "0.018 SS", "0.016×0.022 SS", "0.017×0.025 SS", "0.019×0.025 SS",
             "0.017×0.025 TMA", "0.019×0.025 TMA"]

    case = models.ForeignKey(OrthoCase, on_delete=models.CASCADE, related_name="visits")
    date = models.DateField(_("date"), default=timezone.localdate)
    upper_wire = models.CharField(_("upper wire"), max_length=30, blank=True)
    lower_wire = models.CharField(_("lower wire"), max_length=30, blank=True)
    aligner = models.PositiveSmallIntegerField(_("aligner number"), null=True, blank=True)
    elastics = models.CharField(_("elastics"), max_length=80, blank=True, help_text=_("e.g. Class II 3/16\" 6 oz"))
    done = models.CharField(_("what was done"), max_length=200, blank=True,
                            help_text=_("e.g. rebond 25, power chain 13–23, IPR 0.2 mm, TAD placed"))
    hygiene = models.CharField(_("oral hygiene"), max_length=5, choices=Hygiene.choices, blank=True)
    next_weeks = models.PositiveSmallIntegerField(_("next visit in (weeks)"), null=True, blank=True)
    notes = models.CharField(_("notes"), max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+", editable=False)

    class Meta:
        ordering = ["date", "pk"]
        verbose_name = _("orthodontic visit")
        verbose_name_plural = _("orthodontic visits")


# ------------------------------------------------------------------ prosthodontics: the shade
def shade_photo_path(instance, filename):
    import os
    import uuid

    return f"patients/{instance.patient_id}/{uuid.uuid4().hex}{os.path.splitext(filename)[1].lower()[:10]}"


class ShadeRecord(SpecialistRecord):
    """The shade taken for a prosthesis: the guide, the shade of each third of the tooth, the prepared tooth's
    shade, the translucency and the characters, the light it was taken in, and a photo with the tab."""

    class Light(models.TextChoices):
        DAYLIGHT = "daylight", _("Daylight (by the window)")
        LAMP = "lamp", _("Shade lamp (5500 K)")
        POLARIZED = "polarized", _("Cross-polarized photo")
        CLINIC = "clinic", _("Clinic light")

    class Translucency(models.TextChoices):
        LOW = "low", _("Low (opaque)")
        MEDIUM = "medium", _("Medium")
        HIGH = "high", _("High (translucent incisal)")

    class Surface(models.TextChoices):
        SMOOTH = "smooth", _("Smooth, glossy")
        MEDIUM = "medium", _("Some texture")
        TEXTURED = "textured", _("Strong texture (perikymata)")

    CHARACTERS = [("mamelons", _("Mamelons")), ("halo", _("Incisal halo")), ("white_spots", _("White spots")),
                  ("cracks", _("Enamel crack lines")), ("cervical", _("Darker cervical third")),
                  ("stain", _("Stain in the fissures")), ("opalescence", _("Opalescent (blue) incisal"))]

    taken_on = models.DateField(_("date"), default=timezone.localdate)
    teeth = models.CharField(_("teeth"), max_length=100)
    prosthesis = models.CharField(_("for"), max_length=120, blank=True,
                                  help_text=_("e.g. zirconia crowns 11, 21 or e.max veneers 13–23"))
    guide = models.CharField(_("shade guide"), max_length=10, choices=shades.GUIDES, default=shades.CLASSICAL)
    shade = models.CharField(_("shade (middle third)"), max_length=10)
    shade_cervical = models.CharField(_("cervical third"), max_length=10, blank=True)
    shade_incisal = models.CharField(_("incisal third"), max_length=10, blank=True)
    stump = models.CharField(_("prepared tooth (stump) shade"), max_length=5, blank=True,
                             help_text=_("For all-ceramic crowns and veneers (IPS Natural Die ND1–ND9)."))
    translucency = models.CharField(_("translucency"), max_length=8, choices=Translucency.choices, blank=True)
    surface = models.CharField(_("surface"), max_length=10, choices=Surface.choices, blank=True)
    characters = models.JSONField(_("characters to copy"), default=list, blank=True)
    light = models.CharField(_("taken in"), max_length=10, choices=Light.choices, default=Light.DAYLIGHT)
    photo = models.ImageField(_("photo with the shade tab"), upload_to=shade_photo_path, blank=True)

    class Meta:
        ordering = ["-taken_on", "-pk"]
        verbose_name = _("shade taken")
        verbose_name_plural = _("shades taken")

    def __str__(self):
        return f"{_('Shade')} {self.shade} — {self.teeth}"

    def get_absolute_url(self):
        return reverse("specialties:shade", args=[self.pk])

    def character_labels(self):
        return labels(self.CHARACTERS, self.characters)

    def colour(self, name):
        return shades.COLOURS.get(name, "")


# ------------------------------------------------------------------ prosthodontics: the case (round 15)
class ProsthoCase(SpecialistRecord):
    """The prosthodontist's chart (the shade is only one step of it): the missing teeth (Kennedy class, or the
    edentulous jaw), the abutment teeth, the occlusion (vertical dimension, space, scheme, parafunction), the
    esthetics (smile line, lip support, midline), the old prosthesis, then the plan: the prosthesis, its material
    and retention, and how far it has gone."""

    class Status(models.TextChoices):
        EXAMINED = "examined", _("Examined and planned")
        IN_WORK = "in_work", _("In work (preparation to try-in)")
        DELIVERED = "delivered", _("Delivered")
        RECALL = "recall", _("On recall")

    class Kennedy(models.TextChoices):
        I = "I", _("Class I (bilateral free end)")  # noqa: E741
        II = "II", _("Class II (one free end)")
        III = "III", _("Class III (bounded, one side)")
        IV = "IV", _("Class IV (anterior, across the midline)")
        EDENTULOUS = "edentulous", _("Completely edentulous")
        NONE = "none", _("No missing teeth")

    class Ridge(models.TextChoices):
        GOOD = "good", _("Good height and width")
        RESORBED = "resorbed", _("Resorbed")
        KNIFE = "knife", _("Knife edge")
        FLABBY = "flabby", _("Flabby ridge")

    class VerticalDimension(models.TextChoices):
        NORMAL = "normal", _("Normal")
        REDUCED = "reduced", _("Reduced (collapsed bite)")
        INCREASED = "increased", _("Increased")

    class Scheme(models.TextChoices):
        CANINE = "canine", _("Canine guidance")
        GROUP = "group", _("Group function")
        BALANCED = "balanced", _("Bilateral balanced (dentures)")
        MUTUALLY = "mutually", _("Mutually protected")

    class SmileLine(models.TextChoices):
        LOW = "low", _("Low (teeth only)")
        MEDIUM = "medium", _("Medium (papillae show)")
        HIGH = "high", _("High (gummy smile)")

    class Plan(models.TextChoices):
        SINGLE_CROWNS = "crowns", _("Single crowns")
        BRIDGE = "bridge", _("Bridge on teeth")
        IMPLANT_CROWNS = "implant_crowns", _("Crowns / bridge on implants")
        FULL_ARCH_FIXED = "full_arch", _("Full arch fixed on implants")
        OVERDENTURE = "overdenture", _("Overdenture on implants")
        COMPLETE_DENTURE = "complete_denture", _("Complete denture")
        PARTIAL_DENTURE = "partial_denture", _("Removable partial denture")
        VENEERS = "veneers", _("Veneers")
        INLAYS = "inlays", _("Inlays / onlays")
        OTHER = "other", _("Other")

    class Material(models.TextChoices):
        ZIRCONIA = "zirconia", _("Zirconia")
        EMAX = "emax", _("E.max (lithium disilicate)")
        PFM = "pfm", _("Porcelain fused to metal")
        PMMA = "pmma", _("PMMA (temporary)")
        ACRYLIC = "acrylic", _("Acrylic")
        COCR = "cocr", _("Cobalt-chrome framework")
        PEEK = "peek", _("PEEK / BioHPP")
        OTHER = "other", _("Other")

    ABUTMENT_CHECKS = [("mobility", _("Mobility")), ("perio", _("Bone loss / pockets")),
                       ("crown_root", _("Poor crown-root ratio")), ("rct", _("Root canal treated")),
                       ("caries", _("Caries or a big restoration")), ("tilted", _("Tilted / drifted"))]
    PARAFUNCTION = [("bruxism", _("Bruxism (grinding)")), ("clenching", _("Clenching")),
                    ("wear", _("Tooth wear")), ("tmj", _("TMJ signs"))]

    examined_on = models.DateField(_("date"), default=timezone.localdate)
    status = models.CharField(_("status"), max_length=10, choices=Status.choices, default=Status.EXAMINED)
    chief_complaint = models.TextField(_("chief complaint and wishes"), blank=True)
    upper = models.CharField(_("upper jaw"), max_length=12, choices=Kennedy.choices, blank=True)
    lower = models.CharField(_("lower jaw"), max_length=12, choices=Kennedy.choices, blank=True)
    missing_teeth = models.CharField(_("missing teeth"), max_length=150, blank=True)
    ridge = models.CharField(_("the ridge"), max_length=10, choices=Ridge.choices, blank=True)
    abutment_teeth = models.CharField(_("abutment teeth"), max_length=100, blank=True)
    abutment_findings = models.JSONField(_("abutment findings"), default=list, blank=True)
    vertical_dimension = models.CharField(_("vertical dimension"), max_length=10,
                                          choices=VerticalDimension.choices, blank=True)
    interocclusal_space = models.DecimalField(_("space for the prosthesis (mm)"), max_digits=4, decimal_places=1,
                                              null=True, blank=True)
    scheme = models.CharField(_("occlusal scheme"), max_length=10, choices=Scheme.choices, blank=True)
    parafunction = models.JSONField(_("parafunction"), default=list, blank=True)
    smile_line = models.CharField(_("smile line"), max_length=8, choices=SmileLine.choices, blank=True)
    lip_support = models.CharField(_("lip support"), max_length=100, blank=True)
    midline = models.CharField(_("midline"), max_length=100, blank=True)
    old_prosthesis = models.CharField(_("the old prosthesis"), max_length=255, blank=True)
    diagnosis = models.TextField(_("prosthodontic diagnosis"), blank=True)
    plan = models.CharField(_("the prosthesis planned"), max_length=20, choices=Plan.choices, blank=True)
    plan_teeth = models.CharField(_("on the teeth"), max_length=100, blank=True)
    material = models.CharField(_("material"), max_length=10, choices=Material.choices, blank=True)
    retention = models.CharField(_("retention"), max_length=40, blank=True,
                                 help_text=_("e.g. cemented, screw-retained, locators, bar"))
    other_options = models.TextField(_("other options told to the patient"), blank=True)
    delivered_on = models.DateField(_("delivered on"), null=True, blank=True)
    next_recall = models.DateField(_("next recall"), null=True, blank=True)

    class Meta:
        ordering = ["-examined_on", "-pk"]
        verbose_name = _("prosthodontic case")
        verbose_name_plural = _("prosthodontic cases")

    def __str__(self):
        return f"{_('Prosthodontic case')} {self.get_plan_display() or ''} {self.plan_teeth}".strip()

    def get_absolute_url(self):
        return reverse("specialties:prostho", args=[self.pk])

    def abutment_labels(self):
        return labels(self.ABUTMENT_CHECKS, self.abutment_findings)

    def parafunction_labels(self):
        return labels(self.PARAFUNCTION, self.parafunction)
