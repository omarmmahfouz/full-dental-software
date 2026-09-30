from django.contrib import admin

from .models import (
    LabBlock, LabBlockUse, LabCase, LabCaseItem, LabCaseStep, LabClient, LabMessage, LabOutsource, LabPayment,
    LabPrice, LabPriceList, LabWorker,
)


class ItemInline(admin.TabularInline):
    model = LabCaseItem
    extra = 0


class StepInline(admin.TabularInline):
    model = LabCaseStep
    extra = 0


@admin.register(LabCase)
class LabCaseAdmin(admin.ModelAdmin):
    list_display = ["number", "client", "patient_name", "step", "due_date", "total"]
    list_filter = ["step", "client"]
    search_fields = ["number", "patient_name", "doctor"]
    inlines = [ItemInline, StepInline]


class PriceInline(admin.TabularInline):
    model = LabPrice
    extra = 0


@admin.register(LabPriceList)
class LabPriceListAdmin(admin.ModelAdmin):
    inlines = [PriceInline]


admin.site.register([LabClient, LabWorker, LabBlock, LabBlockUse, LabOutsource, LabPayment, LabMessage])
