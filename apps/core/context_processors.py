from django.conf import settings

from .models import ChangeRequest, branch_for_user
from .roles import (
    ALL_ROLES,
    CLINICAL,
    DENTISTS,
    FRONT_DESK,
    HEAD_CIA,
    MANAGEMENT,
    OWNER,
    PATIENT_VIEWERS,
    PURCHASE_ROLES,
    STOCK_ROLES,
    SUPERVISOR,
    TEAM_HEAD,
    is_only_dentist,
    user_roles,
)


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
                "sees_patients": bool(roles & set(PATIENT_VIEWERS)),
                "can_stock": bool(roles & set(STOCK_ROLES)),
                "can_purchase": bool(roles & set(PURCHASE_ROLES)),
                "sees_reports": bool(roles & set(MANAGEMENT + (TEAM_HEAD,))),
                "only_dentist": is_only_dentist(user),
            }
        )
        from .access import area_levels, area_of

        levels = area_levels(user)
        context["hidden_areas"] = {area for area, level in levels.items() if level == "hidden"}
        context["read_only_here"] = (levels.get(area_of(request.path)) or levels.get("*")) == "read"
        context["can_stock"] = context["can_stock"] and "stock" not in context["hidden_areas"]
        context["can_purchase"] = context["can_purchase"] and "purchases" not in context["hidden_areas"]
        if roles & {OWNER, HEAD_CIA}:
            context["pending_approvals"] = ChangeRequest.objects.filter(status=ChangeRequest.Status.PENDING).count()
        if roles & set(DENTISTS + (SUPERVISOR,)):
            from apps.dentists.models import Dentist

            context["my_dentist"] = Dentist.for_user(user)
    return context
