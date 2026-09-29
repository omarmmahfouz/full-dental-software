from django.contrib import admin

from .models import EndoCanal, EndoCase, EndoVisit, OrthoCase, OrthoVisit, Referral, ShadeRecord, TMJExam, TMJVisit


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = ["number", "patient", "from_dentist", "to_dentist", "to_outside", "status", "created_at"]
    list_filter = ["branch", "status", "urgency"]


class CanalInline(admin.TabularInline):
    model = EndoCanal
    extra = 0


class EndoVisitInline(admin.TabularInline):
    model = EndoVisit
    extra = 0


@admin.register(EndoCase)
class EndoCaseAdmin(admin.ModelAdmin):
    list_display = ["patient", "tooth", "dentist", "started_on", "status"]
    list_filter = ["branch", "status", "difficulty"]
    inlines = [CanalInline, EndoVisitInline]


class TMJVisitInline(admin.TabularInline):
    model = TMJVisit
    extra = 0


@admin.register(TMJExam)
class TMJExamAdmin(admin.ModelAdmin):
    list_display = ["patient", "dentist", "exam_date", "opening", "pain_vas"]
    inlines = [TMJVisitInline]


class OrthoVisitInline(admin.TabularInline):
    model = OrthoVisit
    extra = 0


@admin.register(OrthoCase)
class OrthoCaseAdmin(admin.ModelAdmin):
    list_display = ["patient", "dentist", "status", "appliance", "bonded_on"]
    inlines = [OrthoVisitInline]


@admin.register(ShadeRecord)
class ShadeRecordAdmin(admin.ModelAdmin):
    list_display = ["patient", "teeth", "guide", "shade", "stump", "taken_on"]
