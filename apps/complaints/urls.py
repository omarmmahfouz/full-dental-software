from django.urls import path

from . import views

app_name = "complaints"

urlpatterns = [
    path("", views.ComplaintListView.as_view(), name="list"),
    path("new/", views.complaint_create, name="create"),
    path("<int:pk>/", views.complaint_detail, name="detail"),
    path("<int:pk>/edit/", views.complaint_update, name="update"),
    path("<int:pk>/follow-up/", views.complaint_follow_up, name="follow_up"),
    path("<int:pk>/answer/", views.complaint_answer, name="answer"),
    path("<int:pk>/situation/", views.complaint_situation, name="situation"),
    path("<int:pk>/follow-up/<int:follow_up_pk>/edit/", views.complaint_follow_up_edit, name="follow_up_edit"),
]
