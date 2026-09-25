from django.contrib import admin

from apps.core.admin import LookupAdmin

from .models import StockCategory, StockItem, StockMovement

admin.site.register(StockCategory, LookupAdmin)


class MovementInline(admin.TabularInline):
    model = StockMovement
    extra = 0
    fields = ("moved_at", "kind", "quantity", "change", "destination", "created_by")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(StockItem)
class StockItemAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "quantity", "unit", "min_quantity", "location", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("name", "code")
    readonly_fields = ("quantity",)
    inlines = [MovementInline]
