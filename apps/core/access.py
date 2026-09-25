"""Access the owner sets in Settings, on top of what each role normally allows:
- a part of the system can be made read only or hidden for a role;
- a person can be read only everywhere, or limited to dates, days and hours.
The owner (and superusers) are never limited, so they cannot lock themselves out."""

from django.contrib import messages
from django.contrib.auth import logout
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from .models import AreaAccess
from .roles import OWNER, user_roles

# Parts of the system and the addresses that belong to them (longest first wins).
AREAS = [
    ("patients", gettext_lazy("Patients"), ["/patients/"]),
    ("calls", gettext_lazy("Call lists and patients to call"), ["/patients/calls/", "/patients/to-call/"]),
    ("schedule", gettext_lazy("Schedule and appointments"), ["/schedule/"]),
    ("charts", gettext_lazy("Dental charts, examinations and plans"), ["/chart/"]),
    ("treatments", gettext_lazy("Treatment log"), ["/clinical/steps/"]),
    ("lab", gettext_lazy("Lab requests"), ["/clinical/lab/"]),
    ("surgery", gettext_lazy("Implant surgeries"), ["/surgery/"]),
    ("finder", gettext_lazy("Case finder & statistics"), ["/surgery/finder/"]),
    ("prescriptions", gettext_lazy("Prescriptions and instructions"), ["/prescriptions/"]),
    ("complaints", gettext_lazy("Complaints"), ["/complaints/"]),
    ("academy", gettext_lazy("Academy"), ["/academy/"]),
    ("dentists", gettext_lazy("Dentists"), ["/dentists/"]),
    ("purchases", gettext_lazy("Purchases"), ["/purchases/"]),
    ("stock", gettext_lazy("Stock"), ["/stock/"]),
    ("reports", gettext_lazy("Reports"), ["/reports/"]),
]
AREA_LABELS = {code: label for code, label, _prefixes in AREAS}
_PREFIXES = sorted(((prefix, code) for code, _label, prefixes in AREAS for prefix in prefixes), key=lambda p: -len(p[0]))

# Always allowed, whatever the limits: logging out, the language, changing one's own password.
FREE_PATHS = ("/login/", "/logout/", "/i18n/", "/password/", "/static/", "/favicon")
RANK = {AreaAccess.Level.FULL: 2, AreaAccess.Level.READ: 1, AreaAccess.Level.HIDDEN: 0}


def area_of(path):
    for prefix, code in _PREFIXES:
        if path.startswith(prefix):
            return code
    return None


def is_exempt(user):
    return user.is_superuser or OWNER in user_roles(user)


def area_levels(user):
    """{area: level} for the areas where this person is limited (cached on the user)."""
    cached = getattr(user, "_area_levels", None)
    if cached is not None:
        return cached
    levels = {}
    if not is_exempt(user):
        for rule in AreaAccess.objects.filter(role__in=user_roles(user)).exclude(level=AreaAccess.Level.FULL):
            # If any of the person's roles is limited in an area, the person is limited there.
            if rule.area not in levels or RANK[rule.level] < RANK[levels[rule.area]]:
                levels[rule.area] = rule.level
        profile = getattr(user, "profile", None)
        if profile is not None and profile.read_only:
            for code, _label, _prefixes in AREAS:
                levels.setdefault(code, AreaAccess.Level.READ)
            levels["*"] = AreaAccess.Level.READ
    user._area_levels = levels
    return levels


def time_problem(user):
    if is_exempt(user):
        return ""
    profile = getattr(user, "profile", None)
    return profile.access_problem() if profile is not None else ""


class AccessControlMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        path = request.path
        if user is not None and user.is_authenticated and not path.startswith(FREE_PATHS):
            problem = time_problem(user)
            if problem:
                logout(request)
                messages.error(request, problem)
                return redirect("login")
            levels = area_levels(user)
            area = area_of(path)
            level = levels.get(area) if area else levels.get("*")
            if level == AreaAccess.Level.HIDDEN:
                raise PermissionDenied(_("This part of the system is closed for you."))
            if level == AreaAccess.Level.READ and request.method not in ("GET", "HEAD", "OPTIONS"):
                raise PermissionDenied(_("You have read-only access here: you can look but not save changes."))
        return self.get_response(request)
