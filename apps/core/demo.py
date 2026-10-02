"""Round 11 sample data: the security log (logins, wrong passwords, a login closed after wrong passwords, a visit
from outside the clinic's network, files taken out, a page refused) and a record deleted by mistake. Round 13
sample data: ``load_round_thirteen``."""

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
