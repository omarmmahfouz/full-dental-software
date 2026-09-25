from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.index, name="index"),
    path("visits/", views.visits_report, name="visits"),
    path("interns/", views.interns_report, name="interns"),
    path("lab/", views.lab_report, name="lab"),
    path("money/", views.money_report, name="money"),
    path("patients/", views.patients_report, name="patients"),
]
