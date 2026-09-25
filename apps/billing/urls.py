from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("patient/<int:pk>/", views.patient_account, name="account"),
    path("payments/", views.payment_list, name="payment_list"),
    path("payments/<int:pk>/receipt/", views.receipt, name="receipt"),
]
