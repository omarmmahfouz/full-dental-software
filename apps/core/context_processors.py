from django.conf import settings

from .models import ChangeRequest, ProblemReport, branch_for_user, switch_places
from .roles import (
    ALL_ROLES,
    CLINIC_MANAGERS,
    CLINICAL,
    DENTISTS,
    FRONT_DESK,
    LAB_DESK,
    LAB_MANAGERS,
    LAB_MONEY,
    LAB_STAFF,
    HEAD_CIA,
    MANAGEMENT,
    MODERATOR,
    OWNER,
    PATIENT_VIEWERS,
    PURCHASE_ROLES,
    ROLE_CHOICES,
    STOCK_ROLES,
    SUPERVISOR,
    TEAM_HEAD,
    is_only_dentist,
    user_roles,
)


def app_context(request):
    match = getattr(request, "resolver_match", None)
    # The part of the system the page belongs to gives the page its accent colour (see app.css).
    context = {"CLINIC": settings.CLINIC, "section": (match.namespace if match and match.namespace else "home"),
               "test_copy": settings.TEST_COPY}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        roles = user_roles(user)
        context.update(
            {
                "roles": {role: role in roles for role in ALL_ROLES},
                "is_front_desk": bool(roles & set(FRONT_DESK)),
                "is_management": bool(roles & set(MANAGEMENT)),
                "unread_notifications": user.notifications.filter(read_at__isnull=True).count(),
                "last_notification_id": user.notifications.order_by("-pk").values_list("pk", flat=True).first() or 0,
                "current_branch": branch_for_user(user),
                "is_clinical": bool(roles & set(CLINICAL)),
                "sees_patients": bool(roles & set(PATIENT_VIEWERS)),
                "can_stock": bool(roles & set(STOCK_ROLES)),
                "can_purchase": bool(roles & set(PURCHASE_ROLES)),
                "sees_reports": bool(roles & set(MANAGEMENT + (TEAM_HEAD,))),
                "only_dentist": is_only_dentist(user),
                "is_clinic_manager": bool(roles & set(CLINIC_MANAGERS)),
                "sees_dashboard": bool(roles & {OWNER, HEAD_CIA, MODERATOR}),
                "is_lab": bool(roles & set(LAB_STAFF)),
                "is_lab_desk": bool(roles & set(LAB_DESK)),
                "is_lab_manager": bool(roles & set(LAB_MANAGERS)),
                "is_lab_money": bool(roles & set(LAB_MONEY)),
            }
        )
        current = context["current_branch"]
        context["at_lab"] = current is not None and current.kind == current.Kind.LAB
        # The academy's courses are CIA's: its menu shows when working at CIA (round 14).
        context["academy_here"] = current is None or current.code == settings.CLINIC["DEFAULT_BRANCH_CODE"]
        if context["at_lab"]:
            # Working at the lab: the menus of the clinics (patients, reception, academy, the clinics' doctors,
            # finders) are not shown; they come back at a clinic (round 14).
            for key in ("is_front_desk", "is_clinical", "sees_patients", "is_clinic_manager"):
                context[key] = False
        from .access import area_levels, area_of

        levels = area_levels(user)
        context["hidden_areas"] = {area for area, level in levels.items() if level == "hidden"}
        from .hints import hint_for
        from .navigation import bottom_nav, up_url

        profile = getattr(user, "profile", None)
        context["hints_on"] = profile is None or profile.show_hints
        context["page_hint"] = hint_for(request) if context["hints_on"] else None
        context["hints_reset"] = request.session.pop("hints_reset", False)
        context["bottom_nav"] = bottom_nav(user, request.path, context["hidden_areas"], at_lab=context["at_lab"])
        context["back_url"] = up_url(request.path)
        context["role_labels"] = [label for code, label in ROLE_CHOICES if code in roles]
        places = switch_places(user)
        context["working_places"] = places if len(places) > 1 else []
        context["read_only_here"] = (levels.get(area_of(request.path)) or levels.get("*")) == "read"
        context["can_stock"] = context["can_stock"] and "stock" not in context["hidden_areas"]
        context["can_purchase"] = context["can_purchase"] and "purchases" not in context["hidden_areas"]
        if roles & {OWNER, HEAD_CIA, MODERATOR}:
            from .approvals import changes_for

            context["pending_approvals"] = changes_for(user).filter(status=ChangeRequest.Status.PENDING).count()
        if roles & {OWNER, HEAD_CIA}:
            context["new_problems"] = ProblemReport.objects.filter(status=ProblemReport.Status.NEW).count()
        from apps.scheduling.models import PatientRequest

        # The numbers beside the menu entries count this place's patients only: at CIC the secretary saw CIA's
        # patients to call, and the list was empty (round 15).
        here = context["current_branch"]
        if roles & {OWNER, HEAD_CIA, TEAM_HEAD, SUPERVISOR}:
            context["requests_to_approve"] = PatientRequest.objects.filter(
                status=PatientRequest.Status.PROPOSED, patient__branch=here).count()
        if context["is_front_desk"] or context["is_clinical"]:
            from apps.specialties.models import Referral

            context["referrals_to_book"] = Referral.objects.filter(
                branch=context["current_branch"], status=Referral.Status.SENT).exclude(to_dentist=None).count() \
                if context["is_front_desk"] else 0
        if context["sees_patients"] and "lab" not in context["hidden_areas"] and (
                context["is_front_desk"] or context["is_management"]):
            # The lab requests waiting for this person (round 15, the menu entry of its own): to review for the
            # supervisors and the heads, to take from the dentist and send for the reception.
            from apps.clinical.models import LabRequest

            waiting = [LabRequest.Status.APPROVED, LabRequest.Status.COLLECTED] if context["is_front_desk"] else []
            if context["is_management"]:
                waiting.append(LabRequest.Status.PENDING_REVIEW)
            context["lab_to_act"] = LabRequest.objects.filter(patient__branch=here, status__in=waiting).count()
        if context["is_front_desk"]:
            from apps.scheduling.models import WaitingEntry

            context["requests_to_call"] = PatientRequest.objects.filter(
                status=PatientRequest.Status.APPROVED, patient__branch=here).count()
            context["waiting_count"] = WaitingEntry.objects.filter(
                status=WaitingEntry.Status.WAITING, patient__branch=here).count()
        if roles & set(DENTISTS + (SUPERVISOR,)):
            from apps.dentists.models import Dentist

            context["my_dentist"] = Dentist.for_user(user)
            if context["my_dentist"] is not None:
                context["my_fee_rules"] = context["my_dentist"].fee_rules.exists()
                from apps.clinical.visit_notes import visits_without_notes

                context["missing_notes"] = len(visits_without_notes(context["my_dentist"]))
    return context
