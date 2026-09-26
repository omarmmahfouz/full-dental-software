from django.urls import path

from . import views

app_name = "surgery"

urlpatterns = [
    path("", views.surgery_list, name="list"),
    path("new/", views.surgery_edit, name="create"),
    path("<int:pk>/", views.surgery_detail, name="detail"),
    path("<int:pk>/edit/", views.surgery_edit, name="update"),
    path("implant/<int:pk>/", views.implant_detail, name="implant"),
    path("implant-lots/", views.implant_lots, name="implant_lots"),
    path("prostheses/new/<int:patient_pk>/", views.prosthesis_edit, name="prosthesis_create"),
    path("prostheses/<int:pk>/", views.prosthesis_edit, name="prosthesis_update"),
    path("prostheses/<int:pk>/delete/", views.prosthesis_delete, name="prosthesis_delete"),
    path("finder/", views.finder, name="finder"),
    path("finder/save/", views.finder_save, name="finder_save"),
    path("finder/<int:pk>/delete/", views.finder_delete, name="finder_delete"),
]
