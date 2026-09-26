from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("patient/<int:pk>/", views.patient_account, name="account"),
    path("payments/", views.payment_list, name="payment_list"),
    path("payments/<int:pk>/receipt/", views.receipt, name="receipt"),
    path("bills/", views.bill_list, name="bill_list"),
    path("bills/new/", views.bill_create, name="bill_create"),
    path("bills/<int:pk>/", views.bill_detail, name="bill"),
    path("bills/<int:pk>/pay/", views.bill_pay, name="bill_pay"),
    path("fawry/", views.fawry_ledger, name="fawry"),
    path("fawry/new/", views.fawry_move_create, name="fawry_create"),
    path("fawry/<int:pk>/edit/", views.fawry_move_update, name="fawry_update"),
    path("fawry/<int:pk>/delete/", views.fawry_move_delete, name="fawry_delete"),
]
