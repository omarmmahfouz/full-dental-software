import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, UpdateView

from apps.core.forms import clean_digits_value
from apps.core.mixins import AuditMixin, RoleRequiredMixin, SearchMixin, role_required
from apps.core.models import branch_for_user
from apps.core.roles import HEAD_CIA, OWNER, SECRETARY, SUPERVISOR
from apps.core.utils import normalize_phone
from apps.scheduling.whatsapp import record_installment

from .forms import (
    CandidateFilterForm,
    CandidateForm,
    CourseForm,
    EnrollmentForm,
    InstallmentFormSet,
    PaymentFilterForm,
    PaymentForm,
)
from .models import Candidate, Course, Enrollment, Installment, Payment, PaymentMethod
from .reminders import installment_rows

ACADEMY_ROLES = (OWNER, HEAD_CIA, SUPERVISOR, SECRETARY)
MONEY_DESK = (OWNER, HEAD_CIA, SECRETARY)
COURSE_MANAGERS = (OWNER, HEAD_CIA)  # courses (batches, fees) are set by the management, not the reception


# ------------------------------------------------------------ courses
class CourseListView(RoleRequiredMixin, ListView):
    allowed_roles = ACADEMY_ROLES
    template_name = "academy/course_list.html"

    def get_queryset(self):
        return Course.objects.annotate(
            students=Count("enrollments", filter=~Q(enrollments__status=Enrollment.Status.WITHDRAWN))
        )


class CourseCreateView(RoleRequiredMixin, AuditMixin, CreateView):
    allowed_roles = COURSE_MANAGERS
    model = Course
    form_class = CourseForm
    template_name = "includes/form_page.html"
    extra_context = {"title": gettext_lazy("New course")}

    def form_valid(self, form):
        form.instance.branch = branch_for_user(self.request.user)
        return super().form_valid(form)


class CourseUpdateView(RoleRequiredMixin, AuditMixin, UpdateView):
    allowed_roles = COURSE_MANAGERS
    model = Course
    form_class = CourseForm
    template_name = "includes/form_page.html"
    extra_context = {"title": gettext_lazy("Edit course")}


@role_required(*ACADEMY_ROLES)
def course_detail(request, pk):
    course = get_object_or_404(Course, pk=pk)
    today = timezone.localdate()
    rows, totals = [], {"net": Decimal("0"), "paid": Decimal("0"), "balance": Decimal("0"), "overdue": Decimal("0")}
    for enrollment in course.enrollments.select_related("candidate").order_by("candidate__full_name"):
        row = {
            "enrollment": enrollment,
            "net": enrollment.net_fee,
            "paid": enrollment.total_paid,
            "overdue": enrollment.overdue_amount(today),
        }
        row["balance"] = row["net"] - row["paid"]
        for key in totals:
            totals[key] += row[key]
        rows.append(row)
    return render(request, "academy/course_detail.html", {"course": course, "rows": rows, "totals": totals})


# ------------------------------------------------------------ candidates
class CandidateListView(RoleRequiredMixin, SearchMixin, ListView):
    allowed_roles = ACADEMY_ROLES
    template_name = "academy/candidate_list.html"
    paginate_by = 40

    def get_queryset(self):
        self.filter_form = CandidateFilterForm(self.request.GET or None)
        qs = Candidate.objects.prefetch_related("enrollments__course").select_related("dentist")
        if self.filter_form.is_valid() and self.filter_form.cleaned_data.get("course"):
            qs = qs.filter(enrollments__course=self.filter_form.cleaned_data["course"])
        q = clean_digits_value(self.get_search_query())
        if q:
            query = (Q(full_name__icontains=q) | Q(national_id__icontains=q) | Q(university__icontains=q)
                     | Q(code__iexact=q))
            phone = normalize_phone(q)
            if phone:
                query |= Q(phone_primary__contains=phone) | Q(phone_secondary__contains=phone)
            qs = qs.filter(query).distinct()
        return qs.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        return context


class CandidateCreateView(RoleRequiredMixin, AuditMixin, CreateView):
    allowed_roles = ACADEMY_ROLES
    model = Candidate
    form_class = CandidateForm
    template_name = "includes/form_page.html"
    extra_context = {"title": gettext_lazy("New candidate")}


class CandidateUpdateView(RoleRequiredMixin, AuditMixin, UpdateView):
    allowed_roles = ACADEMY_ROLES
    model = Candidate
    form_class = CandidateForm
    template_name = "includes/form_page.html"
    extra_context = {"title": gettext_lazy("Edit candidate")}


@role_required(*ACADEMY_ROLES)
def candidate_detail(request, pk):
    candidate = get_object_or_404(Candidate.objects.select_related("dentist", "referral_source"), pk=pk)
    enrollments = candidate.enrollments.select_related("course")
    dentist = getattr(candidate, "dentist", None)
    placed = 0
    if dentist is not None:
        from apps.surgery.models import SurgerySite

        placed = SurgerySite.objects.filter(surgery__operator_1=dentist).exclude(implant_status="").count()
    return render(request, "academy/candidate_detail.html", {
        "candidate": candidate, "enrollments": enrollments, "dentist": dentist, "implants_placed": placed,
    })


@role_required(*ACADEMY_ROLES)
def enrollment_create(request, candidate_pk):
    candidate = get_object_or_404(Candidate, pk=candidate_pk)
    form = EnrollmentForm(request.POST or None, candidate=candidate)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            enrollment = form.save(commit=False)
            enrollment.candidate = candidate
            enrollment.created_by = request.user
            enrollment.save()
            plan, down = form.build_plan()
            Installment.objects.bulk_create(
                Installment(enrollment=enrollment, number=i, due_date=due, amount=amount)
                for i, (due, amount) in enumerate(plan, start=1)
            )
            if down > 0:
                Payment.objects.create(
                    enrollment=enrollment, amount=down, paid_on=enrollment.enrolled_on,
                    method=form.cleaned_data["down_payment_method"], notes=_("Down payment"), created_by=request.user,
                )
        messages.success(request, _("Candidate enrolled and installment plan created."))
        return redirect(enrollment)
    return render(
        request, "includes/form_page.html",
        {"form": form, "title": _("Enroll %(name)s in a course") % {"name": candidate.full_name},
         "cancel_url": candidate.get_absolute_url()},
    )


@role_required(*ACADEMY_ROLES)
def enrollment_detail(request, pk):
    enrollment = get_object_or_404(Enrollment.objects.select_related("candidate", "course"), pk=pk)
    form = PaymentForm(request.POST or None, request.FILES or None, enrollment=enrollment,
                       initial={"paid_on": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        payment = form.save(commit=False)
        payment.enrollment = enrollment
        payment.created_by = request.user
        payment.save()
        messages.success(request, _("Payment saved. Receipt %(number)s.") % {"number": payment.receipt_number})
        return redirect("academy:payment_receipt", pk=payment.pk)
    return render(
        request,
        "academy/enrollment_detail.html",
        {
            "enrollment": enrollment,
            "schedule": installment_rows([enrollment], lambda row: True),
            "payments": enrollment.payments.select_related("created_by"),
            "payment_form": form,
        },
    )


@role_required(*MONEY_DESK)
def enrollment_plan_edit(request, pk):
    enrollment = get_object_or_404(Enrollment.objects.select_related("candidate", "course"), pk=pk)
    formset = InstallmentFormSet(request.POST or None, instance=enrollment)
    if request.method == "POST" and formset.is_valid():
        with transaction.atomic():
            formset.save()
            for number, installment in enumerate(enrollment.installments.order_by("due_date", "pk"), start=1):
                if installment.number != number:
                    installment.number = number
                    installment.save(update_fields=["number"])
        total = enrollment.installments.aggregate(total=Sum("amount"))["total"] or Decimal("0")
        if total != enrollment.net_fee:
            messages.warning(
                request,
                _("Installments total %(total)s but the fee after discount is %(net)s.")
                % {"total": total, "net": enrollment.net_fee},
            )
        else:
            messages.success(request, _("Installment plan saved."))
        return redirect(enrollment)
    return render(request, "academy/plan_edit.html", {"enrollment": enrollment, "formset": formset})


# ------------------------------------------------------------ payments
@role_required(*ACADEMY_ROLES)
def payment_list(request):
    form = PaymentFilterForm(request.GET or None)
    today = timezone.localdate()
    date_from, date_to = today.replace(day=1), today
    payments = Payment.objects.select_related("enrollment__candidate", "enrollment__course", "created_by")
    if form.is_valid():
        data = form.cleaned_data
        date_from = data.get("date_from") or date_from
        date_to = data.get("date_to") or date_to
        if data.get("method"):
            payments = payments.filter(method=data["method"])
        if data.get("course"):
            payments = payments.filter(enrollment__course=data["course"])
    payments = payments.filter(paid_on__range=(date_from, date_to))
    labels = dict(PaymentMethod.choices)
    by_method = [
        (labels.get(row["method"], row["method"]), row["total"], row["n"])
        for row in payments.values("method").annotate(total=Sum("amount"), n=Count("id")).order_by("-total")
    ]
    return render(
        request,
        "academy/payment_list.html",
        {
            "filter_form": form,
            "payments": payments,
            "by_method": by_method,
            "total": payments.aggregate(total=Sum("amount"))["total"] or Decimal("0"),
            "date_from": date_from,
            "date_to": date_to,
        },
    )


@role_required(*ACADEMY_ROLES)
def payment_receipt(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related("enrollment__candidate", "enrollment__course", "created_by"), pk=pk
    )
    return render(request, "academy/receipt.html", {"payment": payment, "enrollment": payment.enrollment})


@role_required(*ACADEMY_ROLES)
def overdue_installments(request):
    today = timezone.localdate()
    rows = []
    for enrollment in Enrollment.objects.filter(status=Enrollment.Status.ACTIVE).select_related("candidate", "course"):
        overdue = [row for row in enrollment.installment_schedule(today) if row["state"] == "overdue"]
        if overdue:
            rows.append(
                {
                    "enrollment": enrollment,
                    "amount": sum((row["remaining"] for row in overdue), Decimal("0")),
                    "oldest": overdue[0]["installment"].due_date,
                    "days": (today - overdue[0]["installment"].due_date).days,
                }
            )
    rows.sort(key=lambda row: row["oldest"])
    reminders = installment_rows([row["enrollment"] for row in rows], lambda row: row["state"] == "overdue", today)
    oldest = {}
    for reminder in reminders:  # remind about the oldest unpaid installment
        oldest.setdefault(reminder["enrollment"].pk, reminder)
    for row in rows:
        row["reminder"] = oldest.get(row["enrollment"].pk)
    return render(
        request, "academy/overdue.html",
        {"rows": rows, "total": sum((row["amount"] for row in rows), Decimal("0")), "today": today},
    )



@role_required(*MONEY_DESK)
def installments_month(request):
    """Every installment due in one month: how much each candidate pays, what is collected, what is left."""
    today = timezone.localdate()
    try:
        year, month = (int(part) for part in request.GET.get("month", "").split("-"))
        first = date(year, month, 1)
    except ValueError:
        first = today.replace(day=1)
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    enrollments = (Enrollment.objects.filter(status=Enrollment.Status.ACTIVE, installments__due_date__range=(first, last))
                   .distinct().select_related("candidate", "course"))
    rows = installment_rows(enrollments, lambda row: first <= row["installment"].due_date <= last, today)
    totals = {key: sum((row[key] for row in rows), Decimal("0")) for key in ("paid", "remaining")}
    totals["expected"] = totals["paid"] + totals["remaining"]
    return render(request, "academy/installments_month.html", {
        "rows": rows, "totals": totals, "month": first,
        "prev_month": (first - timedelta(days=1)).replace(day=1), "next_month": last + timedelta(days=1),
    })


@role_required(*MONEY_DESK)
@require_POST
def installment_whatsapp(request, pk):
    """Keep the reminder, then open WhatsApp with it ready to send."""
    installment = get_object_or_404(Installment.objects.select_related("enrollment__candidate", "enrollment__course"),
                                    pk=pk)
    enrollment = installment.enrollment
    row = next(r for r in enrollment.installment_schedule() if r["installment"].pk == installment.pk)
    return redirect(record_installment(row, enrollment, request.user))
