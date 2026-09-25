from django.urls import path

from . import views

app_name = "stock"

urlpatterns = [
    path("", views.item_list, name="item_list"),
    path("new/", views.item_edit, name="item_create"),
    path("<int:pk>/", views.item_detail, name="item_detail"),
    path("<int:pk>/edit/", views.item_edit, name="item_update"),
    path("take-out/", views.use, name="use"),
    path("movements/", views.movement_list, name="movement_list"),
    path("import/", views.import_list, name="import"),
]
