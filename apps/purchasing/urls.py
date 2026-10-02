from django.urls import path

from . import returns, views

app_name = "purchasing"

urlpatterns = [
    path("", views.purchase_list, name="purchase_list"),
    path("new/", views.purchase_create, name="purchase_create"),
    path("<int:pk>/", views.purchase_detail, name="purchase_detail"),
    path("<int:pk>/edit/", views.purchase_update, name="purchase_update"),
    path("<int:purchase_pk>/give-back/", returns.return_create, name="return_create"),
    path("returns/", returns.return_list, name="return_list"),
    path("returns/<int:pk>/", returns.return_detail, name="return_detail"),
    path("returns/<int:pk>/taken/", returns.return_taken, name="return_taken"),
    path("returns/<int:pk>/refund/", returns.return_settle, name="return_settle"),
    path("returns/<int:pk>/cancel/", returns.return_cancel, name="return_cancel"),
    path("suppliers/", views.SupplierListView.as_view(), name="supplier_list"),
    path("suppliers/new/", views.SupplierCreateView.as_view(), name="supplier_create"),
    path("suppliers/<int:pk>/", views.supplier_detail, name="supplier_detail"),
    path("suppliers/<int:pk>/edit/", views.SupplierUpdateView.as_view(), name="supplier_update"),
]
