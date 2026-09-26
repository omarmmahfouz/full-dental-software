from django.urls import path

from . import patient_requests, views, waiting

app_name = "scheduling"

urlpatterns = [
    path("today/", views.today_board, name="today"),
    path("walk-in/", views.walk_in, name="walk_in"),
    path("day/", views.day_planner, name="day_planner"),
    path("free-times/", views.free_times_json, name="free_times"),
    path("dentist-day/", views.dentist_day_json, name="dentist_day"),
    path("appointments/", views.AppointmentListView.as_view(), name="appointment_list"),
    path("appointments/new/", views.appointment_create, name="appointment_create"),
    path("appointments/<int:pk>/", views.appointment_detail, name="appointment_detail"),
    path("appointments/<int:pk>/edit/", views.appointment_update, name="appointment_update"),
    path("appointments/<int:pk>/action/", views.appointment_action, name="appointment_action"),
    path("appointments/<int:pk>/times/", views.appointment_times, name="appointment_times"),
    path("appointments/<int:pk>/move/", views.appointment_reschedule, name="appointment_reschedule"),
    path("visit/<int:pk>/", views.visit, name="visit"),
    path("rooms/", views.room_schedule, name="room_schedule"),
    path("rooms/shift/new/", views.shift_edit, name="shift_create"),
    path("rooms/shift/<int:pk>/", views.shift_edit, name="shift_update"),
    path("rooms/shift/<int:pk>/delete/", views.shift_delete, name="shift_delete"),
    path("rooms/copy-week/", views.copy_previous_week, name="copy_week"),
    path("my-patient-list/", patient_requests.my_requests, name="requests_mine"),
    path("my-patient-list/<int:pk>/remove/", patient_requests.request_cancel, name="request_cancel"),
    path("patient-lists/approve/", patient_requests.approve_requests, name="requests_approve"),
    path("patient-lists/", patient_requests.reception_requests, name="requests_reception"),
    path("patient-lists/<int:pk>/cannot-come/", patient_requests.request_cannot_come, name="request_cannot_come"),
    path("waiting/", waiting.waiting_list, name="waiting_list"),
    path("waiting/<int:pk>/remove/", waiting.waiting_remove, name="waiting_remove"),
    path("whatsapp/", views.whatsapp_list, name="whatsapp"),
    path("whatsapp/<int:pk>/<slug:kind>/", views.whatsapp_send, name="whatsapp_send"),
    path("whatsapp/mark/<slug:kind>/", views.whatsapp_mark, name="whatsapp_mark"),
]
