from django.urls import path

from . import implant_life, views

app_name = "surgery"

urlpatterns = [
    path("", views.surgery_list, name="list"),
    path("new/", views.surgery_edit, name="create"),
    path("<int:pk>/", views.surgery_detail, name="detail"),
    path("<int:pk>/edit/", views.surgery_edit, name="update"),
    path("implant/<int:pk>/", views.implant_detail, name="implant"),
    path("implant/<int:pk>/check/", implant_life.implant_check, name="implant_check"),
    path("implant/<int:pk>/check/<int:check_pk>/", implant_life.implant_check, name="implant_check_edit"),
    path("implant/<int:pk>/complication/", implant_life.implant_complication, name="implant_complication"),
    path("implant/<int:pk>/complication/<int:complication_pk>/", implant_life.implant_complication,
         name="implant_complication_edit"),
    path("patient/<int:patient_pk>/implants/", implant_life.patient_implants, name="patient_implants"),
    path("complications/", implant_life.complications, name="complications"),
    path("implant-lots/", views.implant_lots, name="implant_lots"),
    path("prostheses/new/<int:patient_pk>/", views.prosthesis_edit, name="prosthesis_create"),
    path("prostheses/<int:pk>/", views.prosthesis_edit, name="prosthesis_update"),
    path("prostheses/<int:pk>/delete/", views.prosthesis_delete, name="prosthesis_delete"),
    path("prostheses/<int:pk>/delivery/", views.delivery_check, name="delivery_check"),
    path("<int:pk>/follow-up/", views.follow_up_ask, name="follow_up"),
    path("finder/", views.finder, name="finder"),
    path("finder/save/", views.finder_save, name="finder_save"),
    path("finder/<int:pk>/delete/", views.finder_delete, name="finder_delete"),
]
