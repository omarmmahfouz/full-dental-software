from django.urls import path

from . import views

app_name = "academy"

urlpatterns = [
    path("courses/", views.CourseListView.as_view(), name="course_list"),
    path("courses/new/", views.CourseCreateView.as_view(), name="course_create"),
    path("courses/<int:pk>/", views.course_detail, name="course_detail"),
    path("courses/<int:pk>/edit/", views.CourseUpdateView.as_view(), name="course_update"),
    path("candidates/", views.CandidateListView.as_view(), name="candidate_list"),
    path("candidates/new/", views.CandidateCreateView.as_view(), name="candidate_create"),
    path("candidates/<int:pk>/", views.candidate_detail, name="candidate_detail"),
    path("candidates/<int:pk>/edit/", views.CandidateUpdateView.as_view(), name="candidate_update"),
    path("candidates/<int:candidate_pk>/enroll/", views.enrollment_create, name="enrollment_create"),
    path("enrollments/<int:pk>/", views.enrollment_detail, name="enrollment_detail"),
    path("enrollments/<int:pk>/plan/", views.enrollment_plan_edit, name="enrollment_plan"),
    path("payments/", views.payment_list, name="payment_list"),
    path("payments/<int:pk>/receipt/", views.payment_receipt, name="payment_receipt"),
    path("overdue/", views.overdue_installments, name="overdue"),
    path("installments/", views.installments_month, name="installments_month"),
    path("installments/<int:pk>/whatsapp/", views.installment_whatsapp, name="installment_whatsapp"),
]
