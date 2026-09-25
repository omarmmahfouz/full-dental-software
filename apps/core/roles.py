"""User roles.

Roles are Django groups with fixed names (created by ``manage.py setup_clinic``).
A user may hold several roles; superusers are treated as holding every role.

Who logs in at the Cairo Implant Academy:
- owner: the owner / CEO - everything.
- head_cia: the head of CIA - everything except the money report and creating logins.
- team_head: the head of the CIA dentists team - what a CIA dentist can do, plus the
  follow-up report of the CIA dentists (not the course candidates).
- secretary: reception, patients, schedule, lab send/receive, complaints, academy, purchases.
- dentist: CIA dentists (full or part time). They see the patients, the complaints,
  their own schedule and cases, and record the clinical work - also the work of the
  course candidates, choosing the candidate's and the supervisor's names.
- stock: the stock manager - stock of materials, instruments, food and beverage, and purchases.
- supervisor: kept for later. Supervisors and course candidates do not log in for now;
  they are chosen by name on the clinical forms.
"""

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

OWNER = "owner"
HEAD_CIA = "head_cia"
TEAM_HEAD = "team_head"
SUPERVISOR = "supervisor"
SECRETARY = "secretary"
DENTIST = "dentist"
STOCK = "stock"

ROLE_CHOICES = [
    (OWNER, _("Owner / CEO")),
    (HEAD_CIA, _("Head of CIA")),
    (TEAM_HEAD, _("Head of CIA dentists team")),
    (SUPERVISOR, _("Supervisor")),
    (SECRETARY, _("Secretary")),
    (DENTIST, _("CIA dentist")),
    (STOCK, _("Stock manager")),
]
ALL_ROLES = tuple(code for code, _label in ROLE_CHOICES)

# Common role sets used by views.
MANAGEMENT = (OWNER, HEAD_CIA, SUPERVISOR)
FRONT_DESK = (OWNER, HEAD_CIA, SUPERVISOR, SECRETARY)
CLINICAL = (OWNER, HEAD_CIA, SUPERVISOR, TEAM_HEAD, DENTIST)
DENTISTS = (TEAM_HEAD, DENTIST)
PATIENT_VIEWERS = FRONT_DESK + DENTISTS
STOCK_ROLES = (OWNER, HEAD_CIA, STOCK)
PURCHASE_ROLES = (OWNER, HEAD_CIA, SECRETARY, STOCK)
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


def is_only_dentist(user):
    """True for CIA dentists without a desk, management or team-head role: in the
    schedule and work lists they see only their own shifts, visits and work."""
    roles = user_roles(user)
    return DENTIST in roles and not roles & set(FRONT_DESK + (TEAM_HEAD,))


def users_with_role(*roles):
    return (
        get_user_model()
        .objects.filter(is_active=True, groups__name__in=roles)
        .distinct()
        .order_by("first_name", "last_name", "username")
    )
