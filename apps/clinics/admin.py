from django.contrib import admin

from .models import DoctorPayout, FeeRule


@admin.register(FeeRule)
class FeeRuleAdmin(admin.ModelAdmin):
    list_display = ["dentist", "branch", "service", "method", "value", "starts_on", "ends_on", "is_active"]
    list_filter = ["branch", "method", "is_active"]


@admin.register(DoctorPayout)
class DoctorPayoutAdmin(admin.ModelAdmin):
    list_display = ["dentist", "branch", "paid_on", "amount", "method"]
    list_filter = ["branch", "method"]
