from django.urls import path

from . import views

app_name = "dentists"

urlpatterns = [
    path("", views.dentist_list, name="list"),
    path("new/", views.dentist_edit, name="create"),
    path("<int:pk>/", views.dentist_detail, name="detail"),
    path("<int:pk>/edit/", views.dentist_edit, name="update"),
    path("<int:pk>/login/", views.create_login, name="create_login"),
    path("<int:pk>/signature/", views.dentist_signature, name="signature"),
    path("<int:pk>/lists/", views.toggle_lists, name="toggle_lists"),
]
