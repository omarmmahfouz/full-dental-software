from django.contrib import admin

from apps.core.admin import LookupAdmin

from .models import Lead, LeadCall, MedicalCondition, Patient, PatientDocument, PatientRelation, ReferralSource


@admin.register(ReferralSource)
class ReferralSourceAdmin(LookupAdmin):
    list_display = ("name_ar", "name_en", "asks_for_patient", "sort_order", "is_active")


@admin.register(MedicalCondition)
class MedicalConditionAdmin(LookupAdmin):
    list_display = ("name_ar", "name_en", "is_alert", "sort_order", "is_active")


class PatientDocumentInline(admin.TabularInline):
    model = PatientDocument
    extra = 0


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("file_number", "full_name", "national_id", "phone_primary", "assigned_dentist", "status")
    list_filter = ("status", "branch", "assigned_dentist")
    search_fields = ("file_number", "full_name", "national_id", "phone_primary", "phone_secondary")
    readonly_fields = ("file_number", "created_at", "created_by")
    raw_id_fields = ("referred_by",)
    inlines = [PatientDocumentInline]


class LeadCallInline(admin.TabularInline):
    model = LeadCall
    extra = 0


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("full_name", "phone_primary", "missing_teeth", "status", "next_call_at", "created_at")
    list_filter = ("status", "missing_teeth", "referral_source")
    search_fields = ("full_name", "phone_primary", "phone_secondary")
    inlines = [LeadCallInline]


@admin.register(PatientRelation)
class PatientRelationAdmin(admin.ModelAdmin):
    list_display = ("patient", "relation", "related_patient")
    raw_id_fields = ("patient", "related_patient")
