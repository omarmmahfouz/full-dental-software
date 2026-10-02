from django.urls import path

from . import views

app_name = "papers"

urlpatterns = [
    path("", views.paper_list, name="list"),
    path("send/", views.upload, name="upload"),
    path("covers/", views.covers, name="covers"),
    path("settings/", views.settings_page, name="settings"),
    path("settings/check/", views.check_key, name="check_key"),
    path("<int:pk>/", views.review, name="review"),
    path("<int:pk>/pages/<int:page_pk>/", views.page_edit, name="page_edit"),
    path("<int:pk>/again/", views.read_again, name="read_again"),
    path("<int:pk>/delete/", views.delete, name="delete"),
    path("values/<int:pk>/paper.jpg", views.spot, name="spot"),
]
