"""Sample data of the dental lab for the practice copy (called by ``load_demo_data``): its head, manager, secretary and
designers (Dr. Sherif of CIA designs too), technicians without a login, a price list for CIA, CIC, El Khadem and the
outside clinics, the lab's stock and blocks, six weeks of cases in every step with the time of each step, remakes, work
sent to another lab, receipts and WhatsApp messages."""

import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group
from django.db.models import F
from django.utils import timezone

from apps.academy.models import PaymentMethod
from apps.clinical.models import Lab, LabRequest, LabWorkType
from apps.core.models import Branch, Notification
from apps.stock.models import StockCategory, StockItem, StockMovement
from apps.stock.services import record_movement

from . import services
from .models import (
    CLOSED_STEPS, LabBlock, LabCase, LabCaseItem, LabCaseStep, LabClient, LabMessage, LabPayment, LabPrice,
    LabPriceList, LabWorker, Step,
)

# Base price of each work at the lab (per unit); each price list is a share of it.
BASE_PRICES = {
    "Zirconia crown": 1200, "E.max crown": 1500, "PFM crown": 800, "Bridge": 1200,
    "Screw-retained implant crown": 1800, "Cement-retained implant crown": 1600,
    "Full-arch hybrid (All-on-X)": 25000, "Implant overdenture": 9000, "Complete denture": 3000,
    "Partial denture": 2500, "Surgical guide": 1500, "Custom abutment": 1200, "Temporary (PMMA)": 300,
    "Study model": 150, "E.max veneer": 1600, "Inlay / onlay": 1200, "Milled titanium bar": 15000,
    "Printed CoCr framework": 3000, "Printed titanium framework, milled finish": 20000, "Printed model": 200,
    "Night guard / splint": 800, "Diagnostic wax-up": 150, "Custom tray": 150,
}
LISTS = [("CIA prices", Decimal("1")), ("CIC prices", Decimal("1.15")), ("EK prices", Decimal("1.4")),
         ("Outside clinics", Decimal("1.5"))]

# Hours a step usually takes here (waiting included): (shortest, longest)
HOURS = {
    Step.RECEIVED: (0.3, 3), Step.MODELS: (1, 5), Step.DESIGN: (2, 18), Step.DESIGN_CHECK: (0.5, 4),
    Step.MILLING: (1, 6), Step.PRINTING: (2, 6), Step.METAL_PRINTING: (10, 24), Step.CASTING: (4, 12),
    Step.SINTERING: (8, 12), Step.CERAMIC: (6, 24), Step.STAIN_GLAZE: (2, 8), Step.SETUP: (4, 20),
    Step.PROCESSING: (6, 24), Step.FINISHING: (2, 10), Step.QC: (0.5, 3), Step.READY: (1, 20),
}

LAB_STOCK = [  # category (English), name, unit, unit cost, quantity
    ("Lab blocks and discs", "Zirconia disc multilayer 98×14 mm A2", "disc", 4200, 6),
    ("Lab blocks and discs", "Zirconia disc HT 98×18 mm A1", "disc", 4800, 3),
    ("Lab blocks and discs", "E.max CAD block LT A2 C14", "block", 650, 20),
    ("Lab blocks and discs", "PMMA disc 98×20 mm A2", "disc", 1500, 4),
    ("Lab blocks and discs", "Titanium grade 5 disc 98×14 mm", "disc", 9000, 2),
    ("Lab blocks and discs", "Wax disc 98×16 mm", "disc", 350, 5),
    ("Liquids, stains and glaze", "Zirconia colouring liquids (A–D set)", "set", 3800, 2),
    ("Liquids, stains and glaze", "Stain and glaze kit", "kit", 2600, 3),
    ("Liquids, stains and glaze", "Glaze paste", "jar", 900, 4),
    ("Porcelain and bond", "Porcelain powder set (dentine / enamel)", "set", 7500, 1),
    ("Porcelain and bond", "Bond / opaquer", "bottle", 1100, 3),
    ("Printing resins", "Model resin", "litre", 2200, 3),
    ("Printing resins", "Surgical guide resin", "litre", 3500, 2),
    ("Metal powders and alloys", "CoCr powder", "kg", 6000, 2),
    ("Plaster, acrylic and denture teeth", "Plaster type IV", "bag", 1200, 4),
    ("Plaster, acrylic and denture teeth", "Heat-cure acrylic", "kit", 800, 6),
    ("Plaster, acrylic and denture teeth", "Denture teeth (set of 28)", "set", 450, 15),
    ("Lab tools and milling burs", "Milling burs set", "set", 5200, 2),
]


def _round50(value):
    return (value / 50).quantize(Decimal("1")) * 50


def load_lab(today, at, make_user, owner):
    rng = random.Random(53)
    now = timezone.now()
    lab_place = Branch.objects.get(kind=Branch.Kind.LAB)
    Branch.objects.filter(pk=lab_place.pk).update(phone="01099998888", address="Nasr City, Cairo",
                                                  tagline="The art of dentistry")
    lab_place.refresh_from_db()

    # People: the head, the manager and the secretary of the lab; Dr. Sherif (CIA) designs too.
    head = make_user("labhead", "Dr. Hossam", "(Head of the lab)", "lab_head")
    manager = make_user("labmanager", "Eng. Karim", "(Lab manager)", "lab_manager")
    secretary = make_user("labsec", "نورا", "(سكرتيرة المعمل)", "lab_secretary")
    for person in (head, manager, secretary):
        person.profile.branch = lab_place
        person.profile.save()
    from django.contrib.auth import get_user_model

    sherif = get_user_model().objects.get(username="dentist2")
    sherif.groups.add(Group.objects.get(name="lab_designer"))
    workers = {
        "sherif": LabWorker.objects.create(name="Dr. Sherif Nabil", user=sherif, jobs=[Step.DESIGN],
                                           fee_per_unit=Decimal("150"), sort_order=1),
        "nada": LabWorker.objects.create(name="Dr. Nada Fawzy", jobs=[Step.DESIGN, Step.DESIGN_CHECK],
                                         fee_per_unit=Decimal("150"), phone="01000000031", sort_order=2),
        "mahmoud": LabWorker.objects.create(name="Mahmoud Ali", jobs=[Step.MILLING, Step.SINTERING, Step.PRINTING,
                                                                       Step.METAL_PRINTING], sort_order=3),
        "ayman": LabWorker.objects.create(name="Ayman Saad", jobs=[Step.CASTING, Step.CERAMIC, Step.STAIN_GLAZE],
                                          sort_order=4),
        "samir": LabWorker.objects.create(name="Samir Adel", jobs=[Step.MODELS, Step.SETUP, Step.PROCESSING],
                                          sort_order=5),
        "reda": LabWorker.objects.create(name="Reda Hassan", jobs=[Step.FINISHING], sort_order=6),
        "hossam": LabWorker.objects.create(name="Dr. Hossam", user=head, jobs=[Step.QC], sort_order=7),
    }
    doers = {}
    for worker in workers.values():
        for job in worker.jobs:
            doers.setdefault(job, []).append(worker)

    # Clients and their price lists
    places = {code: services.client_for_place(Branch.objects.get(code=code)) for code in ("CIA", "CIC", "PVT")}
    LabPriceList.objects.filter(name="PVT prices").update(name="EK prices")
    outside_list = LabPriceList.objects.create(name="Outside clinics", notes="Every clinic outside our places")
    outside = [
        LabClient.objects.create(name="عيادة د. مصطفى كامل — المعادي", kind=LabClient.Kind.CLINIC,
                                 price_list=outside_list, contact="Dr. Moustafa Kamel", phone="01112223334",
                                 address="Maadi, Cairo"),
        LabClient.objects.create(name="Smile Dental Center", kind=LabClient.Kind.CLINIC, price_list=outside_list,
                                 contact="Dr. Heba Salah", phone="01223334445", address="Heliopolis, Cairo"),
        LabClient.objects.create(name="د. رامي سعد", kind=LabClient.Kind.DOCTOR, price_list=outside_list,
                                 contact="Dr. Ramy Saad", phone="01556667778"),
    ]
    types = {t.name_en: t for t in LabWorkType.objects.all()}
    for name, factor in LISTS:
        price_list = LabPriceList.objects.get(name=name) if name != "Outside clinics" else outside_list
        for work, base in BASE_PRICES.items():
            if work in types:
                LabPrice.objects.create(price_list=price_list, work_type=types[work],
                                        price=_round50(Decimal(base) * factor))
    other_lab = Lab.objects.create(name="معمل ألفا للتيتانيوم", name_en="Alpha Titanium Lab", phone="0224445555",
                                   contact_person="Eng. Walid")

    # The lab's stock
    items = {}
    for category, name, unit, cost, quantity in LAB_STOCK:
        item = StockItem.objects.create(name=name, unit=unit, branch=lab_place, unit_cost=Decimal(cost),
                                        category=StockCategory.objects.get(name_en=category),
                                        min_quantity=Decimal("1"), created_by=manager)
        record_movement(item, StockMovement.Kind.IN, quantity, manager, branch=lab_place, unit_cost=Decimal(cost),
                        moved_at=now - timedelta(days=50), notes="First stock of the lab")
        items[name] = item

    # Blocks: a finished zirconia disc, one in use, a PMMA disc in use, e.max blocks (one crown each)
    zirconia = services.open_block(items["Zirconia disc multilayer 98×14 mm A2"], manager, lot="ZR2409A", shade="A2")
    zirconia2 = services.open_block(items["Zirconia disc multilayer 98×14 mm A2"], manager, lot="ZR2409A", shade="A2")
    pmma = services.open_block(items["PMMA disc 98×20 mm A2"], manager, lot="PM88", shade="A2")
    LabBlock.objects.filter(pk=zirconia.pk).update(opened_at=now - timedelta(days=40))
    LabBlock.objects.filter(pk__in=[zirconia2.pk, pmma.pk]).update(opened_at=now - timedelta(days=12))

    # Cases: six weeks of work, each walked through its steps until now
    work_mix = [("Zirconia crown", "36", 1), ("Zirconia crown", "11 21", 2), ("Bridge", "44 45 46", 3),
                ("E.max crown", "12", 1), ("E.max veneer", "13 12 11 21 22 23", 6), ("PFM crown", "46", 1),
                ("Screw-retained implant crown", "36", 1), ("Screw-retained implant crown", "46 47", 2),
                ("Temporary (PMMA)", "14 15 16", 3), ("Surgical guide", "36 46", 1), ("Complete denture", "", 1),
                ("Night guard / splint", "", 1), ("Printed CoCr framework", "", 1), ("Custom abutment", "11", 1),
                ("Printed model", "", 2)]
    patients = ["أحمد محمود علي", "منى حسن إبراهيم", "Karim Fathy", "سارة عبد الله", "هشام مصطفى", "Laila Nabil",
                "محمد السيد", "نادية فؤاد", "Omar Sami", "ياسمين عادل", "طارق حسين", "Rana Adel"]
    doctors = {"CIA": [("Dr. Mona Refaat", "01000000006"), ("Dr. Sherif Nabil", "01000000007")],
               "CIC": [("Dr. Walid Fahmy", "01000000021")], "PVT": [("Dr. Laila Fouad", "01000000044"),
                                                                     ("Dr. Amr El Khadem", "01000000040")]}
    clients = [places["CIA"]] * 7 + [places["CIC"]] * 4 + [places["PVT"]] * 4 + outside * 2
    cases = []
    for number in range(34):
        client = rng.choice(clients)
        work, teeth, units = work_mix[number % len(work_mix)]
        if client.branch_id:
            doctor, phone = rng.choice(doctors[client.branch.code])
        else:
            doctor, phone = client.contact, client.phone
        if number < 22:  # six weeks of delivered work, then the last two and a half days still in the lab
            received = now - timedelta(days=42 - number * 1.75)
            received = received.replace(hour=rng.randint(10, 15), minute=rng.choice((0, 15, 30, 45)))
        else:
            received = now - timedelta(hours=60 - (number - 22) * 5)
        case = LabCase.objects.create(
            client=client, doctor=doctor, doctor_phone=phone, patient_name=rng.choice(patients),
            impression=LabCase.Impression.DIGITAL if number % 3 else LabCase.Impression.CONVENTIONAL,
            enclosures=["scan"] if number % 3 else ["impression", "opposing", "bite"],
            shade="A2" if "crown" in work.lower() or "veneer" in work.lower() or work == "Bridge" else "",
            urgent=number % 11 == 4, created_by=secretary)
        LabCaseItem.objects.create(case=case, work_type=types[work], teeth=teeth, units=units)
        services.start_case(case, secretary, received=True, now=received)
        if number % 7 == 3:  # promised too soon: delivered late
            LabCase.objects.filter(pk=case.pk).update(due_date=timezone.localdate(received) + timedelta(days=1))
        cases.append(_walk(case, received, now, rng, doers, manager, secretary))

    # A few late ones, on hold, at a try-in, and at another lab
    open_cases = [c for c in cases if c.step not in CLOSED_STEPS and c.step != Step.READY]
    for case in open_cases[:2]:
        LabCase.objects.filter(pk=case.pk).update(due_date=today - timedelta(days=1))
    hold = next((c for c in open_cases if c.step == Step.DESIGN), None)
    if hold is not None:
        services.move(hold, Step.ON_HOLD, manager, notes="Waiting for the bite registration from the doctor",
                      now=hold.step_since + (now - hold.step_since) / 2)
    denture = LabCase.objects.create(client=outside[0], doctor=outside[0].contact, doctor_phone=outside[0].phone,
                                     patient_name="الحاجة فاطمة", impression=LabCase.Impression.CONVENTIONAL,
                                     enclosures=["impression", "models", "bite"], created_by=secretary)
    LabCaseItem.objects.create(case=denture, work_type=types["Complete denture"], units=1)
    started = now - timedelta(days=6)
    services.start_case(denture, secretary, received=True, now=started)
    for step, worker, hours in ((Step.MODELS, workers["samir"], 3), (Step.SETUP, workers["samir"], 20)):
        services.move(denture, step, manager, worker=worker, now=started + timedelta(hours=1))
        started += timedelta(hours=hours)
    services.move(denture, Step.TRY_IN, secretary, notes="Wax try-in at the clinic", now=started + timedelta(hours=2))
    titanium = LabCase.objects.create(client=places["PVT"], doctor="Dr. Amr El Khadem", doctor_phone="01000000040",
                                      patient_name="Hesham Farouk", impression=LabCase.Impression.DIGITAL,
                                      enclosures=["scan", "scan_bodies"], created_by=secretary)
    LabCaseItem.objects.create(case=titanium, work_type=types["Printed titanium framework, milled finish"], units=1)
    started = now - timedelta(days=9)
    services.start_case(titanium, secretary, received=True, now=started)
    services.move(titanium, Step.DESIGN, manager, worker=workers["nada"], now=started + timedelta(hours=1))
    services.move(titanium, Step.DESIGN_CHECK, head, worker=workers["nada"], now=started + timedelta(hours=16))
    sent = services.outsource(titanium, other_lab, "Titanium printing of the full-arch framework", manager,
                              cost=Decimal("6000"), due_date=today + timedelta(days=2))
    LabCaseStep.objects.filter(case=titanium, step=Step.OUTSOURCED).update(started_at=started + timedelta(hours=20))
    LabCaseStep.objects.filter(case=titanium, step=Step.DESIGN_CHECK).update(done_at=started + timedelta(hours=20))
    type(sent).objects.filter(pk=sent.pk).update(sent_at=started + timedelta(hours=20))
    LabCase.objects.filter(pk=titanium.pk).update(step_since=started + timedelta(hours=20))

    # Remakes: one the lab's own mistake (free), one an impression problem of the clinic (charged)
    delivered = [c for c in cases if c.step == Step.DELIVERED]
    shade_case = next(c for c in delivered if c.items.first().work_type.category in ("zirconia", "emax"))
    services.make_remake(shade_case, secretary, LabCase.RemakeReason.SHADE, LabCase.Fault.LAB,
                         "The shade is lighter than A2 at the cervical third", in_hand=True)
    fit_case = next(c for c in delivered if c.pk != shade_case.pk and c.client.branch_id)
    services.make_remake(fit_case, secretary, LabCase.RemakeReason.IMPRESSION, LabCase.Fault.CLINIC,
                         "Distorted impression: new impression taken", in_hand=False)

    # The cases of our places that the clinics sent to the lab (their lab requests)
    for lab_request in LabRequest.objects.filter(lab__branch=lab_place):
        case = LabCase.objects.filter(request=lab_request).first() or services.case_from_request(lab_request,
                                                                                               secretary)
        services.fill_prices(case)  # the prices were written after the clinics sent their work
        if lab_request.status in (LabRequest.Status.RECEIVED, LabRequest.Status.DELIVERED):
            # Back at the clinic: the lab's steps between sending and receiving.
            sent_at = now - timedelta(days=5)
            arrived = sent_at + timedelta(hours=2)
            LabCaseStep.objects.filter(case=case).delete()
            LabCase.objects.filter(pk=case.pk).update(step=case.route[0], step_since=arrived, received_at=arrived,
                                                      received_by=secretary, delivered_at=None, delivered_by=None)
            case.refresh_from_db()
            LabCaseStep.objects.create(case=case, step=case.step, started_at=arrived)
            _walk(case, arrived, now - timedelta(hours=3), rng, doers, manager, secretary, finish=True)
        else:
            sent_at = now - timedelta(hours=20)
            LabCaseStep.objects.filter(case=case, step=Step.INCOMING).update(started_at=sent_at)
            LabCase.objects.filter(pk=case.pk).update(step_since=sent_at)
            case.refresh_from_db()
            if case.step == Step.INCOMING and lab_request.pk % 2:
                services.receive(case, secretary, case.enclosures, now=sent_at + timedelta(hours=3))
                _walk(case, sent_at + timedelta(hours=3), now, rng, doers, manager, secretary)

    # Units milled from the blocks
    for case in LabCase.objects.filter(items__work_type__category__in=("zirconia", "pmma", "emax")).distinct():
        milled = case.steps.filter(step=Step.MILLING, done_at__isnull=False).first()
        if milled is None:
            continue
        category = case.items.first().work_type.category
        units = case.units
        if category == "emax":
            block = services.open_block(items["E.max CAD block LT A2 C14"], manager, lot="EM55", shade="A2")
            services.use_block(block, case, 1, manager)
            services.finish_block(block)
            continue
        block = pmma if category == "pmma" else (zirconia if milled.done_at < now - timedelta(days=12)
                                                 else zirconia2)
        use = services.use_block(block, case, units, manager)
        type(use).objects.filter(pk=use.pk).update(used_at=milled.done_at)
    services.finish_block(zirconia)
    LabBlock.objects.filter(pk=zirconia.pk).update(finished_at=now - timedelta(days=12))

    # Liquids, stains and bond used
    for name, quantity, days in (("Glaze paste", 1, 20), ("Bond / opaquer", 1, 15), ("Model resin", 1, 8),
                                 ("Heat-cure acrylic", 2, 6), ("Denture teeth (set of 28)", 2, 6)):
        record_movement(items[name], StockMovement.Kind.OUT, quantity, manager, branch=lab_place,
                        moved_at=now - timedelta(days=days), destination="Lab work")

    # Receipts: the places pay monthly, the outside clinics on delivery (one still owes)
    balances = services.balances()
    for client in list(places.values()) + outside[:2]:
        owed = balances.get(client.pk, {}).get("balance", Decimal("0"))
        if owed > 0:
            LabPayment.objects.create(client=client, amount=_round50(owed * Decimal("0.7")),
                                      method=PaymentMethod.BANK if client.branch_id else PaymentMethod.CASH,
                                      paid_on=today - timedelta(days=rng.randint(1, 10)), received_by=secretary,
                                      reference="TR-%d" % rng.randint(10000, 99999) if client.branch_id else "")
    wrong = LabPayment.objects.create(client=outside[0], amount=Decimal("500"), method=PaymentMethod.CASH,
                                      paid_on=today - timedelta(days=3), received_by=secretary)
    wrong.cancelled_at, wrong.cancelled_by, wrong.cancel_reason = now, head, "Written twice by mistake"
    wrong.save()

    # WhatsApp: the doctors were told of the cases received this week
    for case in LabCase.objects.filter(received_at__gte=now - timedelta(days=7)).exclude(step=Step.INCOMING)[:6]:
        from .whatsapp import message_text

        LabMessage.objects.create(case=case, client=case.client, kind=LabMessage.Kind.RECEIVED,
                                  phone=case.whatsapp_phone, text=message_text(case, LabMessage.Kind.RECEIVED),
                                  by=secretary, sent_at=case.received_at + timedelta(minutes=10))
    # The notifications of the sample weeks are read, except those of the cases still open.
    still_open = {c.get_absolute_url() for c in LabCase.objects.exclude(step__in=CLOSED_STEPS)}
    Notification.objects.filter(url__startswith="/lab/").exclude(url__in=still_open).update(read_at=now)
    LabCase.objects.filter(received_at__isnull=False).update(created_at=F("received_at"))
    return {"cases": LabCase.objects.count()}


def _walk(case, start, until, rng, doers, manager, secretary, finish=False):
    """Move the case on its road with the usual time of each step, until ``until`` (or to the end)."""
    moment = start
    while True:
        step = case.step
        low, high = HOURS.get(step, (1, 4))
        done = moment + timedelta(hours=rng.uniform(low, high))
        if done > until and not finish:
            break
        nxt = services.next_step(case)
        if nxt is None:
            break
        people = doers.get(nxt, [])
        worker = rng.choice(people) if people else None
        user = secretary if nxt == Step.DELIVERED else manager
        services.move(case, nxt, user, worker=worker, now=min(done, until) if finish else done)
        moment = min(done, until) if finish else done
        if nxt == Step.DELIVERED:
            break
    case.refresh_from_db()
    return case
