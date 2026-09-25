from django.urls import path

from . import views

app_name = "purchasing"

urlpatterns = [
    path("", views.purchase_list, name="purchase_list"),
    path("new/", views.purchase_create, name="purchase_create"),
    path("<int:pk>/", views.purchase_detail, name="purchase_detail"),
    path("<int:pk>/edit/", views.purchase_update, name="purchase_update"),
    path("suppliers/", views.SupplierListView.as_view(), name="supplier_list"),
    path("suppliers/new/", views.SupplierCreateView.as_view(), name="supplier_create"),
    path("suppliers/<int:pk>/", views.supplier_detail, name="supplier_detail"),
    path("suppliers/<int:pk>/edit/", views.SupplierUpdateView.as_view(), name="supplier_update"),
]
