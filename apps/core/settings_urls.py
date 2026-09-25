from django.urls import path

from . import settings_views as views

app_name = "settings"

urlpatterns = [
    path("", views.settings_home, name="home"),
    path("options/", views.options_edit, name="options"),
    path("users/", views.user_list, name="users"),
    path("users/new/", views.user_edit, name="user_create"),
    path("users/<int:pk>/", views.user_edit, name="user_update"),
    path("access/", views.role_access, name="access"),
    path("backup/", views.backup_home, name="backup"),
    path("backup/excel/", views.export_excel, name="export_excel"),
    path("backup/<str:name>/", views.backup_download, name="backup_download"),
    path("lists/<slug:key>/", views.list_rows, name="list"),
    path("lists/<slug:key>/new/", views.list_edit, name="list_create"),
    path("lists/<slug:key>/<int:pk>/", views.list_edit, name="list_update"),
]
