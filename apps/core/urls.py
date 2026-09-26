from django.urls import path

from . import approvals, problems, views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("notifications/", views.notification_list, name="notifications"),
    path("approvals/", approvals.approval_list, name="approvals"),
    path("approvals/<int:pk>/", approvals.approval_decide, name="approval_decide"),
    path("notifications/<int:pk>/", views.notification_open, name="notification_open"),
    path("notifications/poll/", views.notification_poll, name="notification_poll"),
    path("problems/", problems.problem_list, name="problems"),
    path("problems/report/", problems.problem_report, name="problem_report"),
    path("problems/export/", problems.problem_export, name="problem_export"),
    path("problems/<int:pk>/", problems.problem_update, name="problem_update"),
    path("notifications/read-all/", views.notification_mark_all_read, name="notifications_read_all"),
]
