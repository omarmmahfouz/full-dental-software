from django.contrib import admin

from apps.core.admin import LookupAdmin

from .models import ClinicalPhoto, Examination, PhotoType, ToothChange, ToothState, TreatmentPlan


@admin.register(PhotoType)
class PhotoTypeAdmin(LookupAdmin):
    list_display = ("name_en", "name_ar", "stage", "optional", "sort_order", "is_active")
    list_filter = ("stage", "optional", "is_active")


@admin.register(Examination)
class ExaminationAdmin(admin.ModelAdmin):
    list_display = ("patient", "exam_date", "examined_by", "supervisor")
    raw_id_fields = ("patient",)
    date_hierarchy = "exam_date"


@admin.register(ToothState)
class ToothStateAdmin(admin.ModelAdmin):
    list_display = ("patient", "tooth", "status", "caries", "filled", "rct", "crown", "hopeless")
    list_filter = ("status",)
    raw_id_fields = ("patient", "implant_site")


@admin.register(ToothChange)
class ToothChangeAdmin(admin.ModelAdmin):
    list_display = ("patient", "tooth", "changed_at", "source", "summary", "changed_by")
    list_filter = ("source",)
    raw_id_fields = ("patient", "treatment", "surgery", "examination")


@admin.register(TreatmentPlan)
class TreatmentPlanAdmin(admin.ModelAdmin):
    list_display = ("patient", "title", "status", "dentist", "approved_by", "created_at")
    list_filter = ("status",)
    raw_id_fields = ("patient",)


@admin.register(ClinicalPhoto)
class ClinicalPhotoAdmin(admin.ModelAdmin):
    list_display = ("patient", "stage", "photo_type", "taken_on")
    list_filter = ("stage",)
    raw_id_fields = ("patient", "surgery")
