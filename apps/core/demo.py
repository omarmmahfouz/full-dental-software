"""Round 11 sample data: the security log (logins, wrong passwords, a login closed after wrong passwords, a visit
from outside the clinic's network, files taken out, a page refused) and a record deleted by mistake. Round 13
sample data: ``load_round_thirteen``; round 14: ``load_round_fourteen``."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import DeletedRecord, SecurityEvent
from .security import working_as

DEVICES = {
    "pc": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36",
    "ipad": "Mozilla/5.0 (iPad; CPU OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 "
            "Mobile/15E148 Safari/604.1",
    "phone": "Mozilla/5.0 (Linux; Android 14; SM-A546E) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Mobile "
             "Safari/537.36",
    "bot": "python-requests/2.31",
}


def load_round_eleven(patients, secretary):
    users = get_user_model().objects.in_bulk(field_name="username")
    now = timezone.now()

    def event(kind, minutes_ago, username="", ip="192.168.1.10", device="pc", **extra):
        user = users.get(username)
        SecurityEvent.objects.create(kind=kind, at=now - timedelta(minutes=minutes_ago), user=user,
                                     username=username, ip=ip, device=DEVICES[device], **extra)

    day = 24 * 60
    K = SecurityEvent.Kind
    # An ordinary day: the reception, the doctors on the tablets, the lab.
    for username, ip, device, minutes in [("owner", "192.168.1.10", "pc", 2 * day + 300),
                                          ("secretary", "192.168.1.21", "pc", 2 * day + 200),
                                          ("dentist1", "192.168.1.35", "ipad", 2 * day + 150),
                                          ("labsec", "192.168.1.60", "pc", 2 * day + 120),
                                          ("khadem", "192.168.2.15", "pc", day + 400),
                                          ("dentist2", "192.168.1.36", "ipad", day + 250),
                                          ("owner", "192.168.1.10", "pc", day + 90)]:
        event(K.LOGIN, minutes, username, ip, device, path="/login/")
    # The secretary mistyped her password twice, then got in.
    event(K.LOGIN_FAILED, day + 182, "secretary", "192.168.1.21", path="/login/")
    event(K.LOGIN_FAILED, day + 181, "secretary", "192.168.1.21", path="/login/")
    event(K.LOGIN, day + 180, "secretary", "192.168.1.21", path="/login/")
    event(K.IDLE_LOGOUT, day + 30, "secretary", "192.168.1.21")
    # Someone on the guest Wi-Fi tried "admin" with guessed passwords at night: closed after five.
    for n in range(5):
        event(K.LOGIN_FAILED, 3 * day + 60 - n, "admin", "192.168.1.77", "phone", path="/login/")
    event(K.LOCKED, 3 * day + 55, "admin", "192.168.1.77", "phone", details="5 wrong passwords")
    # A program on the internet knocked on the server: refused, it is not the clinic's network.
    event(K.OUTSIDE, 4 * day + 700, "", "41.33.12.5", "bot", path="/admin/login/")
    # Pages refused and files taken out.
    event(K.DENIED, day + 120, "secretary2", "192.168.1.22", path="/reports/money/")
    first = patients[4]
    event(K.EXPORT, day + 85, "owner", details=f"{first.file_number} {first.full_name}.xlsx",
          path=f"/patients/{first.pk}/excel/")
    event(K.EXPORT, 2 * day + 290, "owner", details="all-data.xlsx", path="/settings/backup/excel/")
    event(K.PASSWORD_CHANGED, 2 * day + 140, "dentist1", "192.168.1.35", "ipad", path="/password/")

    # A paper deleted by mistake at the reception: kept with what it held, who and when. (The rows the earlier
    # sample data replaced while it was being made are not shown.)
    DeletedRecord.objects.filter(deleted_by=None).delete()
    from apps.patients.models import PatientDocument

    patient = patients[2]
    paper = PatientDocument.objects.create(patient=patient, kind=PatientDocument.Kind.OTHER, created_by=secretary,
                                           location="https://lab.example/referral/5512",
                                           notes="Referral letter from Dr. Hesham (implant, lower left)")
    PatientDocument.objects.filter(pk=paper.pk).update(created_at=now - timedelta(days=3))
    paper.refresh_from_db()
    with working_as(secretary, f"/patients/{patient.pk}/documents/{paper.pk}/delete/"):
        paper.delete()
    DeletedRecord.objects.filter(deleted_by=secretary).update(deleted_at=now - timedelta(hours=20))


def signature_png(seed):
    """A made-up handwritten signature (a few loops and a line under them) as a PNG data: address."""
    import base64
    import io
    import math
    import random

    from PIL import Image, ImageDraw

    rng = random.Random(seed)
    image = Image.new("RGBA", (420, 140), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    points, x = [], 18
    loops = rng.randint(4, 7)
    for n in range(loops * 12):
        t = n / 12
        x += 4.2 + rng.random() * 1.5
        y = 70 + 28 * math.sin(t * math.pi * 1.6) * (0.6 + 0.4 * math.cos(t)) + rng.uniform(-3, 3)
        points.append((x, y))
    draw.line(points, fill=(11, 42, 107, 255), width=4, joint="curve")
    draw.line([(30, 112), (x + 10, 104)], fill=(11, 42, 107, 255), width=3)
    output = io.BytesIO()
    image.save(output, "PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()


def load_round_thirteen(today, patients, secretary, stock_user, owner):
    """Round 13 sample data: the patients' visit preferences and the new registration details, drawn signatures,
    stock prices that changed, items given back to a supplier, comments on complaints and a problem reported with a
    picture of the page."""
    import random
    from decimal import Decimal

    from apps.complaints.models import Complaint, ComplaintFollowUp
    from apps.dentists.models import Dentist
    from apps.patients.models import DayPart, Patient
    from apps.purchasing.models import Purchase, PurchaseCategory, PurchaseItem, PurchaseReturn, PurchaseReturnLine
    from apps.purchasing.views import _tell_price_rises
    from apps.stock.models import StockItem, StockMovement
    from apps.stock.services import record_movement, sync_purchase

    from .egypt import CITIES
    from .models import ProblemReport, UserProfile

    rng = random.Random(13)
    jobs = ["مهندس", "مدرسة", "محاسب", "ربة منزل", "موظف", "طالب", "تاجر", "بالمعاش", "طبيب", "سائق"]
    times = [code for code, _label in DayPart.choices]
    for n, patient in enumerate(Patient.objects.filter(pk__in=[p.pk for p in patients]).order_by("pk")):
        governorate = patient.governorate or rng.choice(["01", "21", "14"])
        patient.governorate = governorate
        patient.city = patient.city or rng.choice(CITIES.get(governorate, ["القاهرة"]))
        patient.marital_status = patient.marital_status or rng.choice(["married", "married", "single", "widowed"])
        patient.occupation = patient.occupation or rng.choice(jobs)
        if not patient.phone_secondary:
            patient.phone_secondary = f"0111{5000000 + patient.pk * 37:07d}"
        if n % 3 != 2:  # most patients say how far they live and when they can come
            patient.travel_minutes = rng.choice([15, 20, 30, 45, 60, 90, 120])
            patient.preferred_days = ",".join(sorted(rng.sample(["5", "6", "0", "1", "2", "3"], rng.randint(1, 3))))
            patient.preferred_times = ",".join(sorted(rng.sample(times, rng.randint(1, 2)), key=times.index))
        Patient.objects.filter(pk=patient.pk).update(
            governorate=patient.governorate, city=patient.city, marital_status=patient.marital_status,
            occupation=patient.occupation, phone_secondary=patient.phone_secondary,
            travel_minutes=patient.travel_minutes, preferred_days=patient.preferred_days,
            preferred_times=patient.preferred_times)

    # Signatures: the reception and the doctors drew theirs (user menu → My signature); a doctor without a login
    # had his drawn on his page.
    users = get_user_model().objects.in_bulk(field_name="username")
    for seed, username in enumerate(["secretary", "khadem", "dentist1", "dentist2", "amr", "endo", "cicdoctor"]):
        user = users.get(username)
        if user is not None:
            UserProfile.objects.update_or_create(user=user, defaults={"signature": signature_png(seed)})
    no_login = Dentist.objects.filter(user__isnull=True, kind__in=Dentist.LOGIN_KINDS).first()
    if no_login is not None:
        Dentist.objects.filter(pk=no_login.pk).update(signature=signature_png(99))

    # Prices that changed: the gloves and the articaine bought again, dearer and cheaper.
    articaine = StockItem.objects.filter(name="Carpule articaine (Spain)").first()
    tea = StockItem.objects.filter(name="Tea").first()
    first = Purchase.objects.filter(items__stock_item=articaine).order_by("pk").first()
    if articaine is not None and first is not None:
        categories = {c.name_en: c for c in PurchaseCategory.objects.all()}
        again = Purchase.objects.create(branch=first.branch, supplier=first.supplier, purchase_date=today,
                                        invoice_number="INV-1043", created_by=stock_user)
        PurchaseItem.objects.create(purchase=again, category=categories["Anaesthesia"], description="Articaine carpules",
                                    quantity=40, unit="carpule", unit_price=Decimal("21"), stock_item=articaine)
        if tea is not None:
            PurchaseItem.objects.create(purchase=again, category=categories["Tea, coffee & sugar"], description="Tea",
                                        quantity=1, unit="box", unit_price=Decimal("115"), stock_item=tea)
        sync_purchase(again, stock_user)
        _tell_price_rises(again, stock_user)  # +16.7%: the owner and the stock manager are told

        # Given back to the supplier: 10 carpules near expiry (step 2: taken, waiting for the refund), and 2 more
        # finished with a credit off the next invoice.
        line = first.items.get(stock_item=articaine)
        for quantity, step, reason in [(10, PurchaseReturn.Status.TAKEN, PurchaseReturn.Reason.EXPIRED),
                                       (2, PurchaseReturn.Status.DONE, PurchaseReturn.Reason.DAMAGED)]:
            back = PurchaseReturn.objects.create(purchase=first, returned_on=today - timedelta(days=2), reason=reason,
                                                 notes="", created_by=stock_user, status=step,
                                                 taken_on=today - timedelta(days=1), taken_by="أ. سامح (المندوب)")
            PurchaseReturnLine.objects.create(purchase_return=back, item=line, quantity=quantity)
            record_movement(articaine, StockMovement.Kind.RETURN, quantity, stock_user, branch=first.branch,
                            notes=f"Given back #{back.pk} — {first.supplier}")
            if step == PurchaseReturn.Status.DONE:
                PurchaseReturn.objects.filter(pk=back.pk).update(
                    settlement=PurchaseReturn.Settlement.CREDIT, settled_on=today, amount=Decimal("36"))

    # Comments written on the spot on an open complaint (the list opens it in place).
    complaint = Complaint.objects.filter(status__in=Complaint.OPEN_STATUSES).order_by("pk").first()
    if complaint is not None:
        dentist_user = complaint.concerned_dentist.user if complaint.concerned_dentist_id else None
        for author, text in [(secretary, "كلمت المريض الصبح، قال إن الألم خف شوية وهييجي يوم السبت."),
                             (dentist_user or owner, "Seen. I will check the bite on Saturday and adjust it.")]:
            ComplaintFollowUp.objects.create(complaint=complaint, action=ComplaintFollowUp.Action.NOTE, note=text,
                                             new_status=complaint.status, created_by=author)

    # A problem reported with a picture of the page (Report a problem → Picture of this page).
    from django.core.files.base import ContentFile
    from PIL import Image, ImageDraw
    import io

    picture = Image.new("RGB", (1280, 720), (243, 245, 240))
    ImageDraw.Draw(picture).rectangle((0, 0, 76, 720), fill=(20, 32, 16))
    ImageDraw.Draw(picture).rectangle((110, 120, 1240, 680), fill=(255, 255, 255), outline=(220, 225, 215))
    output = io.BytesIO()
    picture.save(output, "JPEG", quality=80)
    report = ProblemReport(page="/billing/fawry/", reported_by=secretary,
                           description="الصفحة بتاخد وقت عشان تفتح لما أختار شهر كامل.",
                           error="Browser: Chrome on Windows")
    report.screenshot.save("page-demo.jpg", ContentFile(output.getvalue()), save=False)
    report.save()


def load_round_fourteen(today, patients, owner, demo_photo):
    """Round 14 sample data: the time each person spent in the system this week (some are in it now), a closed day at
    the lab, and photos of a surgery case to try the photo editor and 4 or 6 photos on each page."""
    import random
    from datetime import datetime, time as day_time

    from apps.billing.models import DayClosing
    from apps.charting.models import ClinicalPhoto, PhotoStage, PhotoType
    from apps.lab.day import day_summary, lab_place
    from apps.surgery.models import Surgery

    from .models import Branch, WorkSession

    rng = random.Random(14)
    # Photos of one surgery case: 4 of the first visit, 6 of the surgery.
    surgery = Surgery.objects.filter(branch__code="CIA").select_related("patient").order_by("pk").first()
    if surgery is not None:
        for stage, count in ((PhotoStage.DIAGNOSTIC, 4), (PhotoStage.SURGERY, 6)):
            shots = list(PhotoType.objects.filter(stage=stage, is_active=True).order_by("sort_order")[:count])
            for number, shot in enumerate(shots):
                ClinicalPhoto.objects.create(
                    patient=surgery.patient, stage=stage, photo_type=shot, surgery=surgery if stage == "surgery" else None,
                    teeth="36", taken_on=surgery.date if stage == "surgery" else surgery.date - timedelta(days=14),
                    file=demo_photo(shot.name_en, 1400 + number + (10 if stage == "surgery" else 0)))
    # The time in the system: a working day for each person this week.
    users = {u.username: u for u in get_user_model().objects.filter(username__in=[
        "owner", "headcia", "dentist1", "dentist2", "secretary", "secretary2", "stock", "moderator", "amr", "khadem",
        "labsec", "labmanager"]).select_related("profile")}
    now = timezone.now()
    for username, user in users.items():
        place = getattr(getattr(user, "profile", None), "branch", None) or Branch.default()
        for days_ago in range(6, -1, -1):
            day = today - timedelta(days=days_ago)
            if day.weekday() == 4 and username not in ("owner", "labsec"):  # Friday off
                continue
            start = timezone.make_aware(datetime.combine(day, day_time(8, 30))) + timedelta(minutes=rng.randint(0, 90))
            hours = rng.uniform(2.5, 7.5) if username not in ("owner", "headcia") else rng.uniform(0.5, 2)
            finish = start + timedelta(hours=hours)
            still_open = days_ago == 0 and username in ("secretary", "labsec", "khadem")
            if days_ago == 0:
                if start > now:
                    continue
                finish = min(finish, now - timedelta(minutes=2))
            open_seconds = max(60, int((finish - start).total_seconds()))
            end = "" if still_open else rng.choice(["logout", "logout", "logout", "idle", "closed"])
            WorkSession.objects.create(
                user=user, branch=place, started_at=start, last_seen_at=finish, last_active_at=finish,
                active_seconds=int(open_seconds * rng.uniform(0.5, 0.88)), pages=rng.randint(25, 320),
                ended_at=None if still_open else finish, end=end, device=f"192.168.1.{rng.randint(20, 80)}")
    # Yesterday's day closed at the lab, 20 short in the drawer, not reviewed yet.
    lab = lab_place()
    yesterday = today - timedelta(days=1)
    labsec = get_user_model().objects.filter(username="labsec").first()
    if lab is not None and not DayClosing.objects.filter(branch=lab, day=yesterday).exists():
        summary = day_summary(yesterday)
        DayClosing.objects.create(
            branch=lab, day=yesterday, totals={row[2]: str(row[1]) for row in summary["by_method"]},
            total=summary["total"], receipts=summary["count"], cash_expected=summary["cash"],
            cash_counted=max(summary["cash"] - 20, 0), notes="ناقص ٢٠ جنيه", closed_by=labsec,
            closed_at=timezone.make_aware(datetime.combine(yesterday, day_time(19, 5))))


def load_round_fifteen(today, patients, owner, secretary, stock_user, demo_photo):
    """Round 15 sample data: an old paper file typed with its number, travel times, an expected patient booked from
    the call list, a WhatsApp message to many, a refund and the owner's money, complaints called about again, the
    implants' checks and complications, a prosthodontic case, calls for a new HbA1c test, purchases by place and by
    group, the academy by batch (a private course, online candidates, a finished one), a preparation day, the
    supervisor of the surgery day and a patient operated by two candidates (36 and 46)."""
    import random
    from datetime import datetime, time as day_time
    from decimal import Decimal

    from apps.academy.models import Candidate, Course, Enrollment
    from apps.billing.models import OwnerCash, PatientPayment, PaymentMethod
    from apps.billing.receipts import refund_services, service_receipts
    from apps.charting.models import ClinicalPhoto, Examination, PhotoStage, PhotoType
    from apps.complaints.models import Complaint, ComplaintFollowUp
    from apps.dentists.models import Dentist
    from apps.patients.medical import sync_recalls
    from apps.patients.models import Lead, MedicalRecall, Patient
    from apps.purchasing.models import Purchase, PurchaseCategory, PurchaseItem, Supplier
    from apps.scheduling.models import Appointment, BulkMessage, BulkRecipient, Room, RoomShift
    from apps.specialties.models import ProsthoCase
    from apps.surgery.implant_life import mark_failed
    from apps.surgery.models import (
        DaySupervisor, ImplantComplication, ImplantFollowUp, ImplantSystem, Surgery, SurgerySite,
    )

    from .models import Branch

    rng = random.Random(15)
    cia = Branch.default()
    cic = Branch.objects.filter(code="CIC").first()
    khadem = Branch.objects.filter(code="PVT").first()
    now = timezone.now()
    cia_patients = [p for p in patients if p.branch_id == cia.pk]

    # 1. An old paper file typed in with its own number, and the travel time of a few patients (hours and minutes).
    Patient.objects.create(
        branch=cia, file_number="CIA-00777", full_name="سعاد محمود عبد الرحمن", national_id="26505120101775",
        phone_primary="01099007770", gender="F", city="Giza", notes="Typed from the old paper file.",
        created_by=secretary)
    for patient, minutes in zip(cia_patients[:6], (20, 45, 75, 90, 130, 30)):
        Patient.objects.filter(pk=patient.pk).update(travel_minutes=minutes)

    # 2. An expected patient booked from the call list: a short file, waiting to be completed when he comes.
    lead = Lead.objects.filter(branch=cia, status__in=(Lead.Status.NEW, Lead.Status.FOLLOW_UP)).first()
    if lead is not None:
        expected = Patient.objects.create(
            branch=cia, full_name=lead.full_name, national_id="", is_expected=True, phone_primary=lead.phone_primary,
            missing_teeth=lead.missing_teeth, referral_source=lead.referral_source, created_by=secretary)
        lead.converted_patient, lead.status = expected, Lead.Status.BOOKED
        lead.save(update_fields=["converted_patient", "status"])
        day = today + timedelta(days=1)
        Appointment.objects.create(
            branch=cia, patient=expected, created_by=secretary, duration_minutes=45,
            scheduled_at=timezone.make_aware(datetime.combine(day, day_time(12, 15))),
            room=Room.objects.filter(branch=cia).order_by("sort_order").first())

    # 3. A WhatsApp message to many patients, half sent.
    bulk = BulkMessage.objects.create(
        branch=cia, title="Eid greetings", audience="Patients seen in the last 6 months", created_by=secretary,
        text="كل سنة وحضرتك طيب يا {patient} 🌙 — {clinic} {phone}")
    for number, patient in enumerate(cia_patients[10:22]):
        BulkRecipient.objects.create(bulk=bulk, patient=patient, name=patient.full_name,
                                     phone=patient.preferred_number,
                                     sent_at=now - timedelta(minutes=30 - number) if number < 6 else None,
                                     sent_by=secretary if number < 6 else None)

    # 4. A refund of one service (the patient did not do it), and the owner's money in the drawer.
    for payment in PatientPayment.objects.filter(patient__branch=cia, amount__gte=500, refund_of__isnull=True)\
            .select_related("patient").order_by("-paid_on")[:20]:
        paid = [(pk, row["paid"]) for pk, row in service_receipts(payment.patient).items() if row["paid"] >= 300]
        if paid:
            refund_services(payment.patient, secretary, [(paid[0][0], Decimal("300"))], PaymentMethod.CASH,
                            "The patient travelled: this part was not done.")
            break
    for days_ago, direction, amount, reason in ((3, "in", "5000", "The day's costs were more than the income"),
                                                (1, "out", "2000", "Taken back by the owner")):
        OwnerCash.objects.create(branch=cia, moved_on=today - timedelta(days=days_ago), direction=direction,
                                 amount=Decimal(amount), reason=reason, created_by=owner)

    # 5. A complaint the patient called about again, twice.
    complaint = Complaint.objects.filter(branch=cia).order_by("pk").first()
    if complaint is not None:
        for number, note in enumerate(("Still feels pain when chewing.", "Asked again for the doctor's call.")):
            ComplaintFollowUp.objects.create(complaint=complaint, action=ComplaintFollowUp.Action.CALLED_AGAIN,
                                             note=note, new_status=complaint.status, created_by=secretary)
        Complaint.objects.filter(pk=complaint.pk).update(calls=2, last_call_at=now - timedelta(hours=3))

    # 6. The implants' life: checks (healthy, mucositis, peri-implantitis) and complications for the follow-up.
    sites = list(SurgerySite.objects.filter(surgery__branch=cia).exclude(implant_status="").select_related(
        "surgery__patient", "surgery__operator_1").order_by("pk")[:8])
    findings = [dict(probing_depth=Decimal("3"), bleeding=False, suppuration=False, bone_loss=Decimal("0.5")),
                dict(probing_depth=Decimal("4"), bleeding=True, suppuration=False, bone_loss=Decimal("0.5")),
                dict(probing_depth=Decimal("6.5"), bleeding=True, suppuration=True, bone_loss=Decimal("3"))]
    for site, found in zip(sites, findings):
        ImplantFollowUp.objects.create(site=site, patient=site.surgery.patient, dentist=site.done_by,
                                       checked_on=today - timedelta(days=rng.randint(5, 40)), plaque=True,
                                       xray_taken=True, created_by=owner, **found)
    complications = [
        ("paresthesia", dict(nerve="ian", side="right", area="Lower lip and chin", severity="moderate",
                             treatment="medicines", treatment_notes="Vitamin B complex and a short steroid course.",
                             outcome="improving", signs="Tingling of the lower lip since the surgery.")),
        ("peri_implantitis", dict(severity="moderate", treatment="cleaning", outcome="open",
                                  cause="Plaque control is poor; smoker.")),
        ("screw_loosening", dict(severity="mild", treatment="retighten", outcome="resolved", resolved_on=today)),
        ("early_failure", dict(severity="severe", treatment="removed", outcome="implant_lost",
                               signs="Mobile at the uncovering, no osseointegration.")),
    ]
    for site, (kind, extra) in zip(sites[3:], complications):
        row = ImplantComplication.objects.create(site=site, patient=site.surgery.patient, kind=kind,
                                                 found_on=today - timedelta(days=rng.randint(3, 30)),
                                                 dentist=site.done_by, created_by=owner, **extra)
        if kind == "early_failure":
            mark_failed(site, row.found_on, row.get_kind_display(), owner)

    # 7. A prosthodontic case at El Khadem (the shade is one step of it).
    amr = Dentist.objects.filter(user__username="amr").first()
    ek_patient = Patient.objects.filter(branch=khadem).order_by("pk").first() if khadem else None
    if amr is not None and ek_patient is not None:
        ProsthoCase.objects.create(
            patient=ek_patient, branch=khadem, dentist=amr, examined_on=today - timedelta(days=4), status="in_work",
            chief_complaint="Wants fixed teeth on the right side.", upper="III", lower="none",
            missing_teeth="15, 16", ridge="good", abutment_teeth="14, 17", abutment_findings=["rct"],
            vertical_dimension="normal", scheme="canine", parafunction=["clenching"], smile_line="medium",
            diagnosis="Kennedy class III, upper right; 14 root treated.", plan="bridge", plan_teeth="14, 15, 16, 17",
            material="zirconia", retention="cemented", created_by=owner)

    # 8. Calls for a new test: a high HbA1c three months ago, and a high pressure last month.
    recalled = cia_patients[-3:]
    for patient, values in ((recalled[0], dict(hba1c=Decimal("8.6"), hba1c_date=today - timedelta(days=95))),
                            (recalled[1], dict(hba1c=Decimal("7.9"), hba1c_date=today - timedelta(days=88))),
                            (recalled[2], dict(bp_clinic_systolic=172, bp_clinic_diastolic=104))):
        Examination.objects.create(patient=patient, history_only=True, medical_taken=True,
                                   exam_date=today - timedelta(days=95 if "hba1c" in values else 32), **values)
    sync_recalls(Patient.objects.filter(pk__in=[p.pk for p in recalled]))
    called = MedicalRecall.objects.filter(patient=recalled[1]).first()
    if called is not None:
        MedicalRecall.objects.filter(pk=called.pk).update(
            calls=1, last_outcome=MedicalRecall.Outcome.NO_ANSWER, last_call_at=now - timedelta(days=1),
            last_call_by=secretary, due_on=today)

    # 9. Purchases of each place, dental (by group) or not.
    depot = Supplier.objects.get_or_create(name="Dental depot (Cairo)", defaults={"phone": "0225550000"})[0]
    market = Supplier.objects.get_or_create(name="Corner market")[0]
    groups = {c.name_en: c for c in PurchaseCategory.objects.all()}
    for place, rows in ((cic, [("Bone grafts & membranes", "Xenograft 0.5 g", 2, "1800"),
                               ("Sutures & surgical supplies", "PTFE suture 4-0", 6, "260"),
                               ("Tea, coffee & sugar", "Coffee", 2, "180")]),
                        (khadem, [("Fillings & bonding (composite, GIC)", "Composite kit", 1, "3200"),
                                  ("Endodontic materials (files, gutta-percha, sealers)", "Rotary files", 3, "950"),
                                  ("Burs & rotary", "Diamond burs", 10, "45"),
                                  ("Water", "Water bottles", 12, "8")])):
        if place is None:
            continue
        for supplier, lines in ((depot, [r for r in rows if r[0] in groups and groups[r[0]].kind == "dental"]),
                                (market, [r for r in rows if r[0] in groups and groups[r[0]].kind != "dental"])):
            if not lines:
                continue
            purchase = Purchase.objects.create(branch=place, supplier=supplier, purchase_date=today - timedelta(days=2),
                                               created_by=stock_user)
            for name, description, quantity, price in lines:
                PurchaseItem.objects.create(purchase=purchase, category=groups[name], description=description,
                                            quantity=quantity, unit_price=Decimal(price))

    # 10. The academy by batch: the first batch is batch 7; a batch 6 that finished; a private course; online.
    Course.objects.filter(code="IMP-2026-A").update(batch_number=7)
    old_course = Course.objects.create(branch=cia, name="Implant diploma", code="IMP-2025-B", batch_number=6,
                                       start_date=today - timedelta(days=420), end_date=today - timedelta(days=60),
                                       fee=Decimal("40000"), implants_required=10, is_active=False, created_by=owner)
    private = Course.objects.create(branch=cia, name="Private implant course", code="PRV-2026-1",
                                    kind=Course.Kind.PRIVATE, start_date=today - timedelta(days=30),
                                    fee=Decimal("60000"), implants_required=6, created_by=owner)
    for code, name, phone, course, mode, status in (
            ("C-090", "Dr. Hany Saleh", "01230000090", old_course, "offline", "completed"),
            ("C-201", "Dr. Laila Fathy", "01230000201", private, "online", "active")):
        candidate = Candidate.objects.create(code=code, full_name=name, phone_primary=phone, whatsapp=phone,
                                             university="Ain Shams University", created_by=secretary)
        Enrollment.objects.create(candidate=candidate, course=course, enrolled_on=course.start_date,
                                  agreed_fee=course.fee, study_mode=mode, status=status)
    Enrollment.objects.filter(candidate__code="C-102").update(study_mode="online")
    Dentist.objects.filter(kind=Dentist.Kind.TRAINING).update(show_in_lists=False)  # comes rarely
    Dentist.objects.filter(kind=Dentist.Kind.FULLTIME, user__username="dentist2").update(work_time="part")
    Dentist.objects.filter(kind=Dentist.Kind.FULLTIME).exclude(user__username="dentist2").update(work_time="full")

    # 11. A preparation day (a candidate with a CIA junior), the supervisor of the last surgery day, and one patient
    # operated by two candidates: 36 by the first, 46 by the second, each with the photos of his tooth.
    first, second = list(Dentist.objects.filter(kind=Dentist.Kind.CANDIDATE, candidate__code__in=("C-101", "C-103"))
                         .order_by("candidate__code"))[:2] or (None, None)
    junior = Dentist.objects.filter(user__username="dentist1").first()
    supervisor = Dentist.objects.filter(full_name="Dr. Hesham Fawzy").first()
    room = Room.objects.filter(branch=cia, is_extra=False).order_by("-sort_order").first()
    prep_day = today + timedelta(days=(2 - today.weekday()) % 7 or 7)
    if room is not None and junior is not None and first is not None:
        try:
            RoomShift.objects.create(room=room, date=prep_day, start_time=day_time(17, 0), end_time=day_time(20, 0),
                                     day_type=RoomShift.DayType.PREPARATION, dentist=junior, second_dentist=first,
                                     notes="Preparation: scaling and impressions before the surgery day",
                                     created_by=owner)
        except Exception:  # noqa: BLE001 - the room is taken at that time in this sample
            pass
    if supervisor is not None and first is not None and second is not None:
        surgery_day = today - timedelta(days=(today.weekday() - 3) % 7 or 7)  # the last Thursday
        DaySupervisor.objects.create(branch=cia, date=surgery_day, supervisor=supervisor,
                                     written_by=junior.user if junior and junior.user_id else owner)
        patient = cia_patients[-4]
        system = ImplantSystem.objects.filter(is_active=True).first()
        surgery = Surgery.objects.create(branch=cia, patient=patient, date=surgery_day, operator_1=first,
                                         operator_2=second, instructor=supervisor, assistant=junior,
                                         sutured=True, suture_size="4-0", suture_material="vicryl",
                                         suture_technique="Simple interrupted", created_by=owner)
        for tooth, operator in ((36, None), (46, second)):
            SurgerySite.objects.create(surgery=surgery, tooth=tooth, operator=operator, flap=True,
                                       simple_implant=True, implant_system=system,
                                       implant_diameter=Decimal("4.0"), implant_length=Decimal("10"),
                                       implant_status=SurgerySite.ImplantStatus.PLACED)
        shot = PhotoType.objects.filter(stage=PhotoStage.SURGERY, is_active=True).order_by("sort_order").first()
        for number, teeth in enumerate(("36", "46")):
            ClinicalPhoto.objects.create(patient=patient, stage=PhotoStage.SURGERY, photo_type=shot, surgery=surgery,
                                         teeth=teeth, taken_on=surgery_day,
                                         file=demo_photo(f"Implant {teeth}", 1500 + number))
