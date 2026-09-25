from django.contrib import admin

from apps.core.admin import LookupAdmin

from .models import Lab, LabRequest, LabRequestEvent, LabWorkType, TreatmentStep, TreatmentStepType

admin.site.register(TreatmentStepType, LookupAdmin)
admin.site.register(LabWorkType, LookupAdmin)


@admin.register(Lab)
class LabAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "phone", "contact_person", "is_active")


@admin.register(TreatmentStep)
class TreatmentStepAdmin(admin.ModelAdmin):
    list_display = ("performed_at", "patient", "step_type", "teeth", "performed_by", "verified_by", "grade")
    list_filter = ("step_type", "performed_by")
    raw_id_fields = ("patient", "appointment")
    date_hierarchy = "performed_at"


class LabRequestEventInline(admin.TabularInline):
    model = LabRequestEvent
    extra = 0
    readonly_fields = ("action", "by", "at", "checked_against_request", "notes")
    can_delete = False


@admin.register(LabRequest)
class LabRequestAdmin(admin.ModelAdmin):
    list_display = ("number", "patient", "work_type", "lab", "requested_by", "status", "due_date")
    list_filter = ("status", "lab", "work_type")
    search_fields = ("number", "patient__full_name", "patient__file_number")
    raw_id_fields = ("patient", "appointment")
    inlines = [LabRequestEventInline]
