from django.urls import path

from . import views

app_name = "papers"

urlpatterns = [
    path("", views.home, name="list"),
    path("lists/", views.lists_download, name="lists"),
    path("covers/", views.covers, name="covers"),
    path("imports/<int:pk>/", views.import_detail, name="import_detail"),
    path("imports/<int:pk>/cancel/", views.import_cancel, name="import_cancel"),
]
