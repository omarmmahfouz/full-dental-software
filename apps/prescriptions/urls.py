from django.urls import path

from . import views

app_name = "prescriptions"

urlpatterns = [
    path("patient/<int:patient_pk>/new/", views.prescription_create, name="create"),
    path("patient/<int:patient_pk>/instructions/", views.instructions, name="instructions"),
    path("<int:pk>/", views.prescription_print, name="print"),
]
