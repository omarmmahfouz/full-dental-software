from django.urls import path

from . import views

app_name = "scheduling"

urlpatterns = [
    path("today/", views.today_board, name="today"),
    path("walk-in/", views.walk_in, name="walk_in"),
    path("appointments/", views.AppointmentListView.as_view(), name="appointment_list"),
    path("appointments/new/", views.appointment_create, name="appointment_create"),
    path("appointments/<int:pk>/", views.appointment_detail, name="appointment_detail"),
    path("appointments/<int:pk>/edit/", views.appointment_update, name="appointment_update"),
    path("appointments/<int:pk>/action/", views.appointment_action, name="appointment_action"),
    path("rooms/", views.room_schedule, name="room_schedule"),
    path("rooms/shift/new/", views.shift_edit, name="shift_create"),
    path("rooms/shift/<int:pk>/", views.shift_edit, name="shift_update"),
    path("rooms/shift/<int:pk>/delete/", views.shift_delete, name="shift_delete"),
    path("rooms/copy-week/", views.copy_previous_week, name="copy_week"),
    path("whatsapp/", views.whatsapp_list, name="whatsapp"),
    path("whatsapp/<int:pk>/<slug:kind>/", views.whatsapp_send, name="whatsapp_send"),
]
