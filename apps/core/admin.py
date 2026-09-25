from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import Branch, Notification, UserProfile

User = get_user_model()


class LookupAdmin(admin.ModelAdmin):
    """Shared admin for bilingual list values."""

    list_display = ("name_ar", "name_en", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    search_fields = ("name_ar", "name_en")
    list_filter = ("is_active",)


@admin.register(Branch)
class BranchAdmin(LookupAdmin):
    list_display = ("name_ar", "name_en", "code", "kind", "phone", "is_active")
    list_editable = ()


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = _("staff profile")


admin.site.unregister(User)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [UserProfileInline]
    list_display = ("username", "first_name", "last_name", "roles", "is_active", "last_login")
    list_filter = ("groups", "is_active", "is_staff")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (_("Personal info"), {"fields": ("first_name", "last_name", "email")}),
        (
            _("Roles and access"),
            {
                "fields": ("is_active", "groups", "is_staff", "is_superuser"),
                "description": _(
                    "Choose the roles (groups): secretary, intern, supervisor, owner. "
                    "'Staff status' allows opening this settings area."
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )

    @admin.display(description=_("roles"))
    def roles(self, obj):
        return ", ".join(obj.groups.values_list("name", flat=True))


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "recipient", "level", "created_at", "read_at")
    list_filter = ("level", "read_at")
    search_fields = ("title", "message", "recipient__username")
