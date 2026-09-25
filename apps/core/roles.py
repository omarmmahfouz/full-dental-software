"""User roles.

Roles are Django groups with fixed names (created by ``manage.py setup_clinic``).
A user may hold several roles; superusers are treated as holding every role.
"""

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

OWNER = "owner"
SUPERVISOR = "supervisor"
SECRETARY = "secretary"
INTERN = "intern"

ROLE_CHOICES = [
    (OWNER, _("Owner / Manager")),
    (SUPERVISOR, _("Supervisor")),
    (SECRETARY, _("Secretary")),
    (INTERN, _("Intern doctor")),
]
ALL_ROLES = tuple(code for code, _label in ROLE_CHOICES)

# Common role sets used by views.
MANAGEMENT = (OWNER, SUPERVISOR)
FRONT_DESK = (OWNER, SUPERVISOR, SECRETARY)
CLINICAL = (OWNER, SUPERVISOR, INTERN)
STAFF = ALL_ROLES


def user_roles(user):
    if not user or not user.is_authenticated:
        return frozenset()
    cached = getattr(user, "_clinic_roles", None)
    if cached is None:
        if user.is_superuser:
            cached = frozenset(ALL_ROLES)
        else:
            cached = frozenset(user.groups.filter(name__in=ALL_ROLES).values_list("name", flat=True))
        user._clinic_roles = cached
    return cached


def has_role(user, *roles):
    return bool(user_roles(user) & set(roles))


def is_only_intern(user):
    """True for interns who hold no desk/management role (they see only their own work)."""
    roles = user_roles(user)
    return INTERN in roles and not roles & set(FRONT_DESK)


def users_with_role(*roles):
    return (
        get_user_model()
        .objects.filter(is_active=True, groups__name__in=roles)
        .distinct()
        .order_by("first_name", "last_name", "username")
    )
