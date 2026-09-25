from django.contrib import admin

from apps.core.admin import LookupAdmin

from .models import (
    Drug,
    DrugGroup,
    InstructionSheet,
    Prescription,
    PrescriptionLine,
    PrescriptionTemplate,
    PrescriptionTemplateLine,
)


class DrugInline(admin.TabularInline):
    model = Drug
    extra = 2


@admin.register(DrugGroup)
class DrugGroupAdmin(LookupAdmin):
    list_display = ("name_ar", "name_en", "kind", "dose", "sort_order", "is_active")
    inlines = [DrugInline]


class TemplateLineInline(admin.TabularInline):
    model = PrescriptionTemplateLine
    extra = 1


@admin.register(PrescriptionTemplate)
class PrescriptionTemplateAdmin(LookupAdmin):
    list_display = ("name_ar", "name_en", "procedures", "for_penicillin_allergy", "sort_order", "is_active")
    inlines = [TemplateLineInline]


admin.site.register(InstructionSheet, LookupAdmin)


class PrescriptionLineInline(admin.TabularInline):
    model = PrescriptionLine
    extra = 0


@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display = ("patient", "prescribed_on", "dentist", "surgery")
    inlines = [PrescriptionLineInline]
    raw_id_fields = ("patient", "surgery")
