from django.urls import path

from . import views

app_name = "clinics"

urlpatterns = [
    path("", views.doctors, name="doctors"),
    path("doctor/<int:pk>/", views.statement_view, name="statement"),
    path("mine/", views.my_shares, name="mine"),
    path("rules/", views.rules, name="rules"),
    path("rules/new/", views.rule_edit, name="rule_create"),
    path("rules/<int:pk>/edit/", views.rule_edit, name="rule_update"),
    path("payouts/<int:pk>/delete/", views.payout_delete, name="payout_delete"),
    path("report/", views.report, name="report"),
]
