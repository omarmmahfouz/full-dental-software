from django.conf import settings

from .models import branch_for_user
from .roles import ALL_ROLES, CLINICAL, DENTIST, FRONT_DESK, MANAGEMENT, SUPERVISOR, user_roles


def app_context(request):
    context = {"CLINIC": settings.CLINIC}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        roles = user_roles(user)
        context.update(
            {
                "roles": {role: role in roles for role in ALL_ROLES},
                "is_front_desk": bool(roles & set(FRONT_DESK)),
                "is_management": bool(roles & set(MANAGEMENT)),
                "unread_notifications": user.notifications.filter(read_at__isnull=True).count(),
                "current_branch": branch_for_user(user),
                "is_clinical": bool(roles & set(CLINICAL)),
            }
        )
        if roles & {DENTIST, SUPERVISOR}:
            from apps.dentists.models import Dentist

            context["my_dentist"] = Dentist.for_user(user)
    return context
