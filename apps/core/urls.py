from django.urls import path

from . import approvals, overview, problems, signatures, views, worktime

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("dashboard/", overview.overview, name="overview"),
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
    path("hints/", views.toggle_hints, name="hints_toggle"),
    path("place/", views.switch_place, name="switch_place"),
    path("place/all/", views.all_places, name="all_places"),
    path("time/", worktime.time_report, name="time_report"),
    path("time/<int:pk>/", worktime.time_person, name="time_person"),
    path("place/<str:code>/logo/", views.place_logo, name="place_logo"),
    path("kept/<str:token>/", views.kept_upload, name="kept_upload"),
    path("signature/", signatures.my_signature, name="my_signature"),
]
