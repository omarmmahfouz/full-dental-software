from django.contrib import admin

from .models import Complaint, ComplaintFollowUp


class FollowUpInline(admin.TabularInline):
    model = ComplaintFollowUp
    extra = 0


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = ("number", "patient", "category", "severity", "status", "assigned_to", "follow_up_due", "created_at")
    list_filter = ("status", "category", "severity")
    search_fields = ("number", "patient__full_name", "description")
    raw_id_fields = ("patient",)
    inlines = [FollowUpInline]
