from django.contrib import admin

from apps.core.admin import LookupAdmin

from .models import Purchase, PurchaseCategory, PurchaseItem, Supplier


@admin.register(PurchaseCategory)
class PurchaseCategoryAdmin(LookupAdmin):
    list_display = ("name_ar", "name_en", "kind", "sort_order", "is_active")
    list_filter = ("kind", "is_active")


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "contact_person", "is_active")
    search_fields = ("name",)


class PurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    extra = 0


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ("purchase_date", "supplier", "invoice_number", "payment_method", "payment_status")
    list_filter = ("supplier", "payment_method", "payment_status")
    date_hierarchy = "purchase_date"
    inlines = [PurchaseItemInline]
