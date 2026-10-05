from django.urls import path

from . import views

app_name = "specialties"

urlpatterns = [
    path("", views.cases, name="cases"),
    path("patient/<int:pk>/", views.patient_records, name="patient"),
    path("referrals/", views.referral_list, name="referrals"),
    path("referrals/new/", views.referral_create, name="referral_create"),
    path("referrals/<int:pk>/", views.referral_detail, name="referral"),
    path("referrals/<int:pk>/status/", views.referral_status, name="referral_status"),
    path("endo/new/", views.endo_edit, name="endo_create"),
    path("endo/<int:pk>/", views.endo_detail, name="endo"),
    path("endo/<int:pk>/edit/", views.endo_edit, name="endo_edit"),
    path("tmj/new/", views.tmj_edit, name="tmj_create"),
    path("tmj/<int:pk>/", views.tmj_detail, name="tmj"),
    path("tmj/<int:pk>/edit/", views.tmj_edit, name="tmj_edit"),
    path("ortho/new/", views.ortho_edit, name="ortho_create"),
    path("ortho/<int:pk>/", views.ortho_detail, name="ortho"),
    path("ortho/<int:pk>/edit/", views.ortho_edit, name="ortho_edit"),
    path("prostho/new/", views.prostho_edit, name="prostho_create"),
    path("prostho/<int:pk>/", views.prostho_detail, name="prostho"),
    path("prostho/<int:pk>/edit/", views.prostho_edit, name="prostho_edit"),
    path("shade/new/", views.shade_edit, name="shade_create"),
    path("shade/<int:pk>/", views.shade_detail, name="shade"),
    path("shade/<int:pk>/edit/", views.shade_edit, name="shade_edit"),
]
