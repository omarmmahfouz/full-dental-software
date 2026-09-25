from django.urls import path

from . import plan_finder, views

app_name = "charting"

urlpatterns = [
    path("patient/<int:patient_pk>/", views.chart, name="chart"),
    path("patient/<int:patient_pk>/tooth/<int:tooth>/", views.tooth_edit, name="tooth"),
    path("patient/<int:patient_pk>/exam/new/", views.exam_edit, name="exam_create"),
    path("patient/<int:patient_pk>/plan/new/", views.plan_edit, name="plan_create"),
    path("patient/<int:patient_pk>/photos/", views.photos, name="photos"),
    path("patient/<int:patient_pk>/photos/logbook/", views.logbook, name="logbook"),
    path("patient/<int:patient_pk>/photos/zip/", views.photos_zip, name="photos_zip"),
    path("patient/<int:patient_pk>/case-report/", views.case_report, name="case_report"),
    path("exam/<int:pk>/", views.exam_detail, name="exam_detail"),
    path("exam/<int:pk>/edit/", views.exam_edit, name="exam_edit"),
    path("plan/<int:pk>/", views.plan_detail, name="plan_detail"),
    path("plan/<int:pk>/edit/", views.plan_edit, name="plan_edit"),
    path("plan/<int:pk>/action/", views.plan_action, name="plan_action"),
    path("photo/<int:pk>/delete/", views.photo_delete, name="photo_delete"),
    path("preview/", views.chart_preview, name="preview"),
    path("plans/", plan_finder.plan_finder, name="plan_finder"),
]
