from django.contrib import admin

from .models import Appointment, Room, RoomShift


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    list_filter = ("branch",)


@admin.register(RoomShift)
class RoomShiftAdmin(admin.ModelAdmin):
    list_display = ("date", "room", "start_time", "end_time", "intern", "supervisor")
    list_filter = ("room", "intern")
    date_hierarchy = "date"


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("scheduled_at", "patient", "intern", "room", "status", "arrived_at", "entered_room_at", "left_at")
    list_filter = ("status", "room", "intern", "is_walk_in")
    search_fields = ("patient__full_name", "patient__file_number")
    raw_id_fields = ("patient",)
    date_hierarchy = "scheduled_at"
