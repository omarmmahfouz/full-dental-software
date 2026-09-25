from django.contrib import admin

from .models import Appointment, Room, RoomShift


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("name", "name_en", "branch", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    list_filter = ("branch",)


@admin.register(RoomShift)
class RoomShiftAdmin(admin.ModelAdmin):
    list_display = ("date", "day_type", "room", "start_time", "end_time", "dentist", "supervisor")
    list_filter = ("day_type", "room", "dentist")
    date_hierarchy = "date"


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("scheduled_at", "patient", "dentist", "room", "status", "arrived_at", "entered_room_at", "left_at")
    list_filter = ("status", "room", "dentist", "is_walk_in")
    search_fields = ("patient__full_name", "patient__file_number")
    raw_id_fields = ("patient",)
    date_hierarchy = "scheduled_at"
