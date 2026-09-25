from django.urls import path

from . import approvals, views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("notifications/", views.notification_list, name="notifications"),
    path("approvals/", approvals.approval_list, name="approvals"),
    path("approvals/<int:pk>/", approvals.approval_decide, name="approval_decide"),
    path("notifications/<int:pk>/", views.notification_open, name="notification_open"),
    path("notifications/read-all/", views.notification_mark_all_read, name="notifications_read_all"),
]
