from django.contrib import admin

from .models import Candidate, Course, Enrollment, Installment, Payment


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "start_date", "end_date", "fee", "is_active")
    list_filter = ("is_active", "branch")


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ("full_name", "phone_primary", "national_id", "university", "graduation_year")
    search_fields = ("full_name", "phone_primary", "national_id")


class InstallmentInline(admin.TabularInline):
    model = Installment
    extra = 0


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ("receipt_number",)


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("candidate", "course", "agreed_fee", "discount", "status", "enrolled_on")
    list_filter = ("course", "status")
    inlines = [InstallmentInline, PaymentInline]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("receipt_number", "enrollment", "amount", "method", "paid_on", "created_by")
    list_filter = ("method", "paid_on")
    search_fields = ("receipt_number", "reference", "enrollment__candidate__full_name")
