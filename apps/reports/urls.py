from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.index, name="index"),
    path("visits/", views.visits_report, name="visits"),
    path("dentists/", views.dentists_report, name="dentists"),
    path("lab/", views.lab_report, name="lab"),
    path("money/", views.money_report, name="money"),
    path("balance/", views.balance_sheet, name="balance"),
    path("patients/", views.patients_report, name="patients"),
]
