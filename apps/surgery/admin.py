from django.contrib import admin

from .models import ImplantSystem, SavedSearch, Surgery, SurgerySite


@admin.register(ImplantSystem)
class ImplantSystemAdmin(admin.ModelAdmin):
    list_display = ("company", "line", "is_active")
    list_editable = ("is_active",)
    search_fields = ("company", "line")


class SurgerySiteInline(admin.TabularInline):
    model = SurgerySite
    extra = 0
    fields = ("tooth", "implant_system", "implant_diameter", "implant_length", "implant_status", "loaded_on", "failed_on")


@admin.register(Surgery)
class SurgeryAdmin(admin.ModelAdmin):
    list_display = ("number", "date", "patient", "operator_1", "operator_2", "instructor", "difficulty")
    list_filter = ("difficulty", "date")
    search_fields = ("number", "patient__full_name", "patient__file_number")
    raw_id_fields = ("patient", "appointment")
    inlines = [SurgerySiteInline]


@admin.register(SavedSearch)
class SavedSearchAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "shared", "created_at")
