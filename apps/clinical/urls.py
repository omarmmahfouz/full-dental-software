from django.urls import path

from . import views

app_name = "clinical"

urlpatterns = [
    path("steps/", views.StepListView.as_view(), name="step_list"),
    path("steps/new/", views.step_create, name="step_create"),
    path("steps/<int:pk>/", views.step_detail, name="step_detail"),
    path("steps/<int:pk>/operator/", views.step_operator, name="step_operator"),
    path("visits-without-notes/", views.visits_missing_notes, name="visits_missing_notes"),
    path("lab/", views.LabListView.as_view(), name="lab_list"),
    path("lab/new/", views.lab_create, name="lab_create"),
    path("lab/<int:pk>/", views.lab_detail, name="lab_detail"),
    path("lab/<int:pk>/edit/", views.lab_edit, name="lab_edit"),
    path("lab/<int:pk>/action/", views.lab_action, name="lab_action"),
    path("lab/<int:pk>/print/", views.lab_print, name="lab_print"),
    path("requests/new/", views.outside_create, name="outside_create"),
    path("requests/<int:pk>/", views.outside_print, name="outside_print"),
]
