from django.contrib import admin

from .models import Dentist


@admin.register(Dentist)
class DentistAdmin(admin.ModelAdmin):
    list_display = ("full_name", "kind", "candidate", "user", "phone", "is_active")
    list_filter = ("kind", "is_active", "branch")
    search_fields = ("full_name", "phone", "candidate__code")
    raw_id_fields = ("candidate",)
