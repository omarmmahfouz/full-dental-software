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
    path("lists/<slug:key>/", views.list_rows, name="list"),
    path("lists/<slug:key>/new/", views.list_edit, name="list_create"),
    path("lists/<slug:key>/<int:pk>/", views.list_edit, name="list_update"),
]
