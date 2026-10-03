from django.urls import path

from . import views

app_name = "reading"

urlpatterns = [
    path("", views.paper_list, name="list"),
    path("send/", views.upload, name="upload"),
    path("files/<int:pk>/", views.review, name="review"),
    path("files/<int:pk>/pages/<int:page_pk>/", views.page_edit, name="page_edit"),
    path("files/<int:pk>/again/", views.read_again, name="read_again"),
    path("files/<int:pk>/delete/", views.delete, name="delete"),
    path("values/<int:pk>/paper.jpg", views.spot, name="spot"),
    path("patients/lookup/", views.lookup, name="lookup"),
    path("to-the-system/", views.export, name="export"),
    path("to-the-system/<int:pk>/download/", views.export_download, name="export_download"),
    path("settings/", views.settings_page, name="settings"),
    path("settings/check/", views.check_key, name="check_key"),
    path("settings/lists/", views.lists_page, name="lists"),
    path("settings/people/", views.people, name="people"),
    path("settings/people/<int:pk>/", views.people, name="person"),
]
