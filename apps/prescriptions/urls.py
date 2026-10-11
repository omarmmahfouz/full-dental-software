from django.urls import path

from . import papers, views

app_name = "prescriptions"

urlpatterns = [
    path("patient/<int:patient_pk>/new/", views.prescription_create, name="create"),
    path("patient/<int:patient_pk>/instructions/", views.instructions, name="instructions"),
    path("<int:pk>/", views.prescription_print, name="print"),
    path("patient/<int:patient_pk>/sick-leave/", papers.sick_leave_create, name="sick_leave_create"),
    path("sick-leave/<int:pk>/", papers.sick_leave_print, name="sick_leave"),
    path("patient/<int:patient_pk>/consent/", papers.consent_create, name="consent_create"),
    path("consent/<int:pk>/", papers.consent_detail, name="consent"),
]
