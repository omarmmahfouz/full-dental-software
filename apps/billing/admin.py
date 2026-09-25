from django.contrib import admin

from .models import Charge, PatientPayment, Service


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name_ar", "name_en", "price", "is_active")


@admin.register(Charge)
class ChargeAdmin(admin.ModelAdmin):
    list_display = ("patient", "service", "charged_on", "price", "discount_percent")
    raw_id_fields = ("patient",)


@admin.register(PatientPayment)
class PatientPaymentAdmin(admin.ModelAdmin):
    list_display = ("receipt_number", "patient", "amount", "method", "paid_on")
    raw_id_fields = ("patient", "charge")
