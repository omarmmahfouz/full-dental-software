from decimal import Decimal

from django.test import TestCase

from apps.core.testing import PASSWORD, make_user, setup_clinic
from apps.purchasing.models import Purchase, PurchaseCategory, Supplier


class PurchaseTests(TestCase):
    def setUp(self):
        setup_clinic()
        make_user("sec", "secretary")
        make_user("sup", "supervisor")
        self.client.login(username="sec", password=PASSWORD)
        self.supplier = Supplier.objects.create(name="Market")
        self.tea = PurchaseCategory.objects.get(name_en="Tea, coffee & sugar")
        self.gloves = PurchaseCategory.objects.get(name_en="Consumables (gloves, masks, gauze...)")

    def post(self, items):
        data = {
            "supplier": self.supplier.pk, "purchase_date": "2026-09-20", "payment_method": "cash", "payment_status": "paid",
            "items-TOTAL_FORMS": str(len(items)), "items-INITIAL_FORMS": "0", "items-MIN_NUM_FORMS": "0", "items-MAX_NUM_FORMS": "1000",
        }
        for i, (category, description, qty, price) in enumerate(items):
            data.update({f"items-{i}-category": category.pk, f"items-{i}-description": description,
                         f"items-{i}-quantity": qty, f"items-{i}-unit_price": price})
        return self.client.post("/purchases/new/", data)

    def test_purchase_with_items_under_categories(self):
        self.post([(self.tea, "Tea", "2", "75.50"), (self.gloves, "Gloves box", "3", "120")])
        purchase = Purchase.objects.get()
        self.assertEqual(purchase.total, Decimal("511.00"))
        self.assertEqual(purchase.unpaid, Decimal("0"))
        report = self.client.get("/purchases/", {"date_from": "2026-09-01", "date_to": "2026-09-30"})
        self.assertEqual(report.context["total"], Decimal("511.00"))
        by_kind = self.client.get("/purchases/", {"date_from": "2026-09-01", "date_to": "2026-09-30", "kind": "non_dental"})
        self.assertEqual(by_kind.context["total"], Decimal("151.00"))

    def test_at_least_one_item_required(self):
        response = self.post([])
        self.assertFalse(Purchase.objects.exists())
        self.assertTrue(response.context["formset"].non_form_errors())

    def test_supervisor_cannot_open_purchases(self):
        self.client.login(username="sup", password=PASSWORD)
        self.assertEqual(self.client.get("/purchases/").status_code, 403)


class Round13PricesAndReturnsTests(TestCase):
    """The price of each stock item followed purchase after purchase, and giving bought items back to the
    supplier in three steps."""

    def setUp(self):
        from datetime import date

        from apps.stock.models import StockCategory, StockItem
        from apps.stock.services import sync_purchase

        self.branch = setup_clinic()
        self.stock = make_user("stock", "stock")
        self.owner = make_user("owner", "owner")
        self.client.login(username="stock", password=PASSWORD)
        self.supplier = Supplier.objects.create(name="Dental Co")
        self.category = PurchaseCategory.objects.get(name_en="Anaesthesia")
        self.item = StockItem.objects.create(name="Articaine", category=StockCategory.objects.first(), unit="carpule")
        self.first = Purchase.objects.create(branch=self.branch, supplier=self.supplier, purchase_date=date(2026, 9, 1),
                                             created_by=self.stock)
        self.line = self.first.items.create(category=self.category, description="Articaine", quantity=50,
                                            unit_price=Decimal("18"), stock_item=self.item)
        sync_purchase(self.first, self.stock)
        self.sync = sync_purchase

    def buy_again(self, price, day):
        from datetime import date

        purchase = Purchase.objects.create(branch=self.branch, supplier=self.supplier,
                                           purchase_date=date(2026, 9, day), created_by=self.stock)
        purchase.items.create(category=self.category, description="Articaine", quantity=10, unit_price=Decimal(price),
                              stock_item=self.item)
        self.sync(purchase, self.stock)
        return purchase

    def test_the_price_of_each_purchase_is_followed(self):
        from apps.core.models import Notification
        from apps.purchasing.views import _tell_price_rises
        from apps.stock.prices import before_purchase, changes, history, last_prices

        dearer = self.buy_again("21", 20)
        line = dearer.items.get()
        self.assertEqual(before_purchase(dearer)[line.pk], (Decimal("18"), Decimal("16.7")))
        _tell_price_rises(dearer, self.stock)
        self.assertTrue(Notification.objects.filter(recipient=self.owner, url=self.item.get_absolute_url()).exists())
        rows, summary = history(self.item)
        self.assertEqual([row["price"] for row in rows], [Decimal("21"), Decimal("18")])
        self.assertEqual((summary["lowest"], summary["highest"], summary["times"]), (Decimal("18"), Decimal("21"), 2))
        from datetime import date

        found = changes(date(2026, 9, 10), date(2026, 9, 30))
        self.assertEqual([(row["item"], row["before"], row["price"]) for row in found],
                         [(self.item, Decimal("18"), Decimal("21"))])
        self.assertEqual(last_prices([self.item])[self.item.pk]["price"], "21.00")
        page = self.client.get("/stock/prices/?date_from=01/09/2026&date_to=30/09/2026")
        self.assertContains(page, "16.7")
        item_page = self.client.get(self.item.get_absolute_url())
        self.assertContains(item_page, 'id="prices"')  # the stock manager reads it in Arabic
        self.assertEqual(len(item_page.context["prices"]), 2)
        self.assertContains(self.client.get(dearer.get_absolute_url()), "16.7")
        cheaper = self.buy_again("17", 25)  # cheaper: no warning
        Notification.objects.all().delete()
        _tell_price_rises(cheaper, self.stock)
        self.assertFalse(Notification.objects.exists())

    def test_giving_back_to_the_supplier_step_by_step(self):
        from apps.purchasing.models import PurchaseReturn

        url = f"/purchases/{self.first.pk}/give-back/"
        too_many = self.client.post(url, {"returned_on": "02/10/2026", "reason": "expired", f"line_{self.line.pk}": "60"})
        self.assertIn(f"line_{self.line.pk}", too_many.context["form"].errors)
        nothing = self.client.post(url, {"returned_on": "02/10/2026", "reason": "expired"})
        self.assertTrue(nothing.context["form"].non_field_errors())
        response = self.client.post(url, {"returned_on": "02/10/2026", "reason": "expired",
                                          f"line_{self.line.pk}": "10"})
        back = PurchaseReturn.objects.get()
        self.assertRedirects(response, back.get_absolute_url(), fetch_redirect_response=False)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, Decimal("40"))  # step 1: out of the stock at once
        self.assertEqual((back.status, back.value), (PurchaseReturn.Status.WAITING, Decimal("180.00")))
        self.client.post(f"/purchases/returns/{back.pk}/taken/", {"t-taken_on": "03/10/2026", "t-taken_by": "Sameh"})
        back.refresh_from_db()
        self.assertEqual(back.status, PurchaseReturn.Status.TAKEN)
        missing = self.client.post(f"/purchases/returns/{back.pk}/refund/", {"s-settlement": "money",
                                                                            "s-settled_on": "05/10/2026"})
        self.assertIn("method", missing.context["settle_form"].errors)
        self.client.post(f"/purchases/returns/{back.pk}/refund/", {"s-settlement": "money", "s-method": "cash",
                                                                  "s-settled_on": "05/10/2026"})
        back.refresh_from_db()
        self.assertEqual((back.status, back.refunded), (PurchaseReturn.Status.DONE, Decimal("180.00")))
        self.assertEqual(self.first.refunded, Decimal("180.00"))
        self.assertContains(self.client.get(self.first.get_absolute_url()), "180")
        self.assertContains(self.client.get("/purchases/returns/"), "Dental Co")
        # The owner's balance sheet counts the money back.
        self.client.login(username="owner", password=PASSWORD)
        sheet = self.client.get("/reports/balance/", {"date_from": "01/10/2026", "date_to": "31/10/2026"})
        refunds = [row for row in sheet.context["cost_rows"] if "suppliers" in str(row["label"])]
        self.assertEqual(refunds[0]["total"], Decimal("-180.00"))

    def test_a_return_written_by_mistake_is_cancelled_and_the_items_come_back(self):
        from apps.purchasing.models import PurchaseReturn

        self.client.post(f"/purchases/{self.first.pk}/give-back/", {"returned_on": "02/10/2026", "reason": "wrong",
                                                                    f"line_{self.line.pk}": "5"})
        back = PurchaseReturn.objects.get()
        self.client.post(f"/purchases/returns/{back.pk}/cancel/", {"reason": ""})  # a reason is needed
        back.refresh_from_db()
        self.assertEqual(back.status, PurchaseReturn.Status.WAITING)
        self.client.post(f"/purchases/returns/{back.pk}/cancel/", {"reason": "Wrong purchase chosen"})
        back.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual((back.status, self.item.quantity), (PurchaseReturn.Status.CANCELLED, Decimal("50")))
        self.assertEqual(self.first.items.get().returned_quantity(), 0)


class Round15PlacesAndGroupsTests(TestCase):
    """Round 15: each place has its own purchases, and what is bought is dental or not, then a group (implants and
    surgery, materials, instruments...), then the category."""

    def setUp(self):
        from apps.core.models import Branch

        self.cia = setup_clinic()
        self.cic = Branch.objects.get(code="CIC")
        make_user("owner", "owner")
        self.client.login(username="owner", password=PASSWORD)
        self.supplier = Supplier.objects.create(name="Dental depot")
        self.bone = PurchaseCategory.objects.get(name_en="Bone grafts & membranes")
        self.tea = PurchaseCategory.objects.get(name_en="Tea, coffee & sugar")

    def post(self, place, category, price):
        return self.client.post("/purchases/new/", {
            "branch": place.pk, "supplier": self.supplier.pk, "purchase_date": "2026-09-20", "payment_method": "cash",
            "payment_status": "paid", "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0", "items-MAX_NUM_FORMS": "1000", "items-0-category": category.pk,
            "items-0-description": "x", "items-0-quantity": "1", "items-0-unit_price": price})

    def test_the_categories_are_grouped(self):
        self.assertEqual((self.bone.kind, self.bone.group), ("dental", "implants"))
        self.assertEqual((self.tea.kind, self.tea.group), ("non_dental", "hospitality"))
        other = PurchaseCategory.objects.create(name_ar="ليزر", name_en="Laser tips", kind="non_dental",
                                                group="instruments")
        self.assertEqual(other.kind, "dental")  # the type follows the group
        page = self.client.get("/purchases/new/")
        labels = [label for label, _rows in page.context["formset"].forms[0].fields["category"].choices][1:]
        self.assertEqual(labels[0], "Dental · Implants and surgery")
        self.assertContains(page, "<optgroup")

    def test_each_place_has_its_own_purchases(self):
        self.post(self.cia, self.bone, "3000")
        self.post(self.cic, self.tea, "200")
        self.assertEqual(Purchase.objects.get(branch=self.cic).total, Decimal("200"))
        dates = {"date_from": "01/09/2026", "date_to": "30/09/2026"}
        here = self.client.get("/purchases/", dates)  # the owner works at CIA now
        self.assertEqual(here.context["total"], Decimal("3000"))
        self.assertEqual(here.context["by_kind"][0]["groups"][0]["label"], "Implants and surgery")
        cic = self.client.get("/purchases/", dict(dates, place=self.cic.pk))
        self.assertEqual(cic.context["total"], Decimal("200"))
        both = self.client.get("/purchases/", dict(dates, place="all"))
        self.assertEqual(both.context["total"], Decimal("3200"))
        dental = self.client.get("/purchases/", dict(dates, place="all", group="implants"))
        self.assertEqual(dental.context["total"], Decimal("3000"))
