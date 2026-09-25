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
