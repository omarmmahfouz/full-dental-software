import io
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.core.models import Notification
from apps.core.testing import PASSWORD, make_user, setup_clinic
from apps.purchasing.models import Purchase, PurchaseCategory, PurchaseItem, Supplier
from apps.stock.importer import parse
from apps.stock.models import StockCategory, StockItem, StockMovement
from apps.stock.services import record_movement, sync_purchase


class StockTests(TestCase):
    def setUp(self):
        self.branch = setup_clinic()
        self.manager = make_user("stock", "stock")
        self.category = StockCategory.objects.get(name_en="Dental materials")
        self.item = StockItem.objects.create(name="Composite A2", category=self.category, unit="syringe", min_quantity=2)
        self.client.login(username="stock", password=PASSWORD)

    def test_movements_keep_the_quantity_and_warn_when_low(self):
        record_movement(self.item, StockMovement.Kind.IN, 5, self.manager)
        record_movement(self.item, StockMovement.Kind.OUT, 2, self.manager, destination="Room 1")
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 3)
        self.assertFalse(Notification.objects.exists())
        other = make_user("stock2", "stock")
        record_movement(self.item, StockMovement.Kind.OUT, 1, self.manager)
        self.assertTrue(Notification.objects.filter(recipient=other, title__contains="Composite A2").exists())
        record_movement(self.item, StockMovement.Kind.COUNT, 7, self.manager)
        self.item.refresh_from_db()
        self.assertEqual((self.item.quantity, self.item.movements.first().change), (7, 5))

    def test_pages_and_taking_out_several_items(self):
        record_movement(self.item, StockMovement.Kind.IN, 10, self.manager)
        tea = StockItem.objects.create(name="Tea", category=StockCategory.objects.get(name_en="Food & beverage"))
        record_movement(tea, StockMovement.Kind.IN, 4, self.manager)
        response = self.client.post("/stock/take-out/", {
            "destination": "Room 2", "kind": "out", "notes": "",
            "lines-TOTAL_FORMS": 3, "lines-INITIAL_FORMS": 0, "lines-MIN_NUM_FORMS": 0, "lines-MAX_NUM_FORMS": 1000,
            "lines-0-item": self.item.pk, "lines-0-quantity": "3", "lines-1-item": tea.pk, "lines-1-quantity": "1",
        })
        self.assertRedirects(response, "/stock/", fetch_redirect_response=False)
        self.item.refresh_from_db()
        tea.refresh_from_db()
        self.assertEqual((self.item.quantity, tea.quantity), (7, 3))
        # More than in stock is refused.
        response = self.client.post(f"/stock/{tea.pk}/", {"kind": "out", "quantity": "9", "moved_at": "2026-09-25T10:00"})
        self.assertIn("quantity", response.context["form"].errors)
        for url in ["/stock/", "/stock/?low=on", "/stock/?expiring=on", f"/stock/{tea.pk}/", "/stock/movements/",
                    "/stock/import/", "/stock/new/", "/"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_only_stock_roles(self):
        make_user("sec", "secretary")
        self.client.login(username="sec", password=PASSWORD)
        self.assertEqual(self.client.get("/stock/").status_code, 403)
        self.assertEqual(self.client.get("/purchases/").status_code, 200)

    def test_import_the_academy_list(self):
        rows = [[None, 5, "syringe"], [None, 20, "carpule red egypt"], [None, None, "burs "], [None, None, None]]
        entries = parse(rows)
        self.assertEqual([(e["name"], e["quantity"]) for e in entries],
                         [("syringe", Decimal(5)), ("carpule red egypt", Decimal(20)), ("burs", None)])
        csv_file = SimpleUploadedFile("list.csv", 'name,quantity,category,min\nComposite A2,4,,1\nGloves,10,"Consumables (gloves, masks, gauze...)",20\n'.encode())
        response = self.client.post("/stock/import/", {"file": csv_file, "category": self.category.pk, "as_count": "on"})
        self.assertRedirects(response, "/stock/", fetch_redirect_response=False)
        self.item.refresh_from_db()
        gloves = StockItem.objects.get(name="Gloves")
        self.assertEqual((self.item.quantity, self.item.min_quantity), (4, 1))
        self.assertEqual((gloves.quantity, gloves.category.name_en), (10, "Consumables (gloves, masks, gauze...)"))

    def test_import_excel(self):
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append([None, 3, "Fuji 9"])
        sheet.append([None, 25, "discs"])
        buffer = io.BytesIO()
        workbook.save(buffer)
        upload = SimpleUploadedFile("Dental_Material_and_Instrument.xlsx", buffer.getvalue())
        self.client.post("/stock/import/", {"file": upload, "category": self.category.pk})
        self.assertEqual(StockItem.objects.get(name="discs").quantity, 25)

    def test_purchases_add_to_stock_and_edits_correct_it(self):
        supplier = Supplier.objects.create(name="Supplier")
        purchase = Purchase.objects.create(branch=self.branch, supplier=supplier)
        line = PurchaseItem.objects.create(purchase=purchase, category=PurchaseCategory.objects.first(),
                                           description="Composite", quantity=6, unit_price=Decimal("300"),
                                           stock_item=self.item)
        self.assertEqual(sync_purchase(purchase, self.manager), 1)
        self.assertEqual(sync_purchase(purchase, self.manager), 0)  # only once
        self.item.refresh_from_db()
        self.assertEqual((self.item.quantity, self.item.unit_cost), (6, Decimal("300")))
        line.quantity = 4
        line.save()
        sync_purchase(purchase, self.manager)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 4)
        line.delete()
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 0)
