"""The bar at the bottom of the screen on tablets and phones: the four places each person uses
most, then "Menu", which opens the full menu from the side."""

from django.urls import Resolver404, resolve, reverse
from django.utils.translation import gettext_lazy as _

from .roles import (
    DENTISTS, FRONT_DESK, GRADER, HEAD_CIA, LAB_DESK, LAB_STAFF, MODERATOR, OWNER, SECRETARY, STOCK,
    is_only_dentist, user_roles,
)


def _item(url_name, icon, label, match=None, query=""):
    url = reverse(url_name)
    return {"url": url + query, "icon": icon, "label": label, "match": match or url}


def bottom_nav(user, path, hidden_areas, at_lab=False):
    """[{url, icon, label, match, active}], at most four, for this person. ``at_lab``: the person works at the lab
    now (the owner, a doctor who designs): the lab's buttons."""
    roles = user_roles(user)
    items = [_item("core:dashboard", "bi-house-door", _("Home"), match="/")]
    front_desk = bool(roles & set(FRONT_DESK))
    patients = "patients" not in hidden_areas and bool(roles & set(FRONT_DESK + DENTISTS))
    schedule = "schedule" not in hidden_areas
    lab_only = bool(roles & set(LAB_STAFF)) and (at_lab or not roles & set(FRONT_DESK + DENTISTS + (MODERATOR, STOCK)))
    if lab_only and "dental_lab" not in hidden_areas:
        items.append(_item("lab:board", "bi-kanban", _("Board"), match="/lab/"))
        if roles & set(LAB_DESK):
            items.append(_item("lab:case_create", "bi-inbox", _("Receive")))
            items.append(_item("lab:whatsapp", "bi-whatsapp", _("WhatsApp")))
        else:
            items.append(_item("lab:my_work", "bi-person-workspace", _("My work")))
            items.append(_item("lab:case_list", "bi-list-ul", _("Cases")))
    elif front_desk:
        if schedule:
            items.append(_item("scheduling:today", "bi-display", _("Reception"), match="/schedule/"))
        if patients:
            items.append(_item("patients:list", "bi-people", _("Patients"), match="/patients/"))
        if SECRETARY in roles and schedule:
            items.append(_item("scheduling:appointment_create", "bi-calendar-plus", _("Book")))
        elif roles & {OWNER, HEAD_CIA}:
            items.append(_item("core:overview", "bi-speedometer2", _("Dashboard")))
        elif "reports" not in hidden_areas:
            items.append(_item("reports:index", "bi-bar-chart-line", _("Reports"), match="/reports/"))
    elif roles & set(DENTISTS):
        if schedule:
            items.append(_item("scheduling:appointment_list", "bi-calendar-check",
                               _("My visits") if is_only_dentist(user) else _("Visits"), match="/schedule/"))
        if patients:
            items.append(_item("patients:list", "bi-people", _("My patients"), match="/patients/", query="?mine=on"))
        if "treatments" not in hidden_areas:
            items.append(_item("clinical:step_list", "bi-list-check", _("Treatments"), match="/clinical/"))
    elif roles == {GRADER}:
        items.append(_item("clinical:supervise", "bi-patch-check", _("Approve"), match="/clinical/approve/"))
    elif MODERATOR in roles:
        if "clinics" not in hidden_areas:
            items.append(_item("clinics:doctors", "bi-people", _("Doctors"), match="/clinics/"))
            items.append(_item("clinics:report", "bi-clipboard-data", _("Report")))
            items.append(_item("clinics:rules", "bi-percent", _("Fee rules")))
    elif STOCK in roles:
        if "stock" not in hidden_areas:
            items.append(_item("stock:item_list", "bi-boxes", _("Stock"), match="/stock/"))
            items.append(_item("stock:use", "bi-box-arrow-right", _("Take out")))
        if "purchases" not in hidden_areas:
            items.append(_item("purchasing:purchase_list", "bi-receipt", _("Purchases"), match="/purchases/"))
    items = items[:4]
    # The longest address that starts the current page is the active place ("/" only for the home page).
    best = max((item for item in items if item["match"] == path or (item["match"] != "/" and path.startswith(item["match"]))),
               key=lambda item: len(item["match"]), default=None)
    for item in items:
        item["active"] = item is best
    return items


def _get_allowed(view):
    """False for a view that only takes a sent form (``require_POST``): it is never a page to go up to."""
    while view is not None:
        code = getattr(view, "__code__", None)
        if code is not None and "request_method_list" in code.co_freevars:
            methods = view.__closure__[code.co_freevars.index("request_method_list")].cell_contents
            if "GET" not in methods:
                return False
        view = getattr(view, "__wrapped__", None)
    return True


def opens(user, url):
    """Can this person open the page at ``url``? Read from the roles its view asks for (``role_required`` /
    ``RoleRequiredMixin``) and the parts of the system closed for the person in Settings → Access. A view that checks
    inside itself counts as open."""
    from .access import area_levels, area_of

    try:
        view = resolve(url.partition("?")[0]).func
    except Resolver404:
        return False
    if not _get_allowed(view):
        return False
    if user is None or not user.is_authenticated:
        return True
    roles = getattr(getattr(view, "view_class", view), "allowed_roles", None)
    if roles and not user.is_superuser and not user_roles(user) & set(roles):
        return False
    return area_levels(user).get(area_of(url)) != "hidden"


def up_url(path, user=None):
    """The page above this one, from its address: /lab/cases/5/edit/ → /lab/cases/5/ → /lab/cases/ → the home page.
    With ``user``, a page this person cannot open is passed over (a doctor's own page went up to the list of
    dentists, which only the reception opens): the next page above that opens, in the end the home page."""
    parts = [part for part in path.split("/") if part]
    while parts:
        parts.pop()
        candidate = "/" + "/".join(parts) + "/" if parts else "/"
        try:
            resolve(candidate)
        except Resolver404:
            continue
        if user is not None and candidate != "/" and not opens(user, candidate):
            continue
        return candidate
    return "/"


# The names of the pages "Up" most often opens (round 14); other pages show just "Up".
UP_NAMES = {
    "core:dashboard": _("Home"),
    "core:time_report": _("Time in the system"),
    "patients:list": _("Patients"),
    "patients:detail": _("Patient file"),
    "patients:lead_list": _("Call list"),
    "patients:calls_today": _("Calls today"),
    "scheduling:appointment_list": _("Appointments"),
    "scheduling:today": _("Reception"),
    "clinical:step_list": _("Treatment log"),
    "clinical:lab_list": _("Lab requests"),
    "charting:chart": _("Dental chart"),
    "charting:photos": _("Photos"),
    "surgery:list": _("Implant surgeries"),
    "dentists:list": _("Dentists"),
    "complaints:list": _("Complaints"),
    "academy:candidate_list": _("Candidates"),
    "academy:course_list": _("Courses"),
    "billing:bill_list": _("Bills"),
    "billing:payment_list": _("Patient payments"),
    "purchasing:purchase_list": _("Purchases"),
    "purchasing:supplier_list": _("Suppliers"),
    "purchasing:return_list": _("Returns to suppliers"),
    "stock:item_list": _("Stock items"),
    "reports:index": _("Reports"),
    "lab:board": _("Lab board"),
    "lab:case_list": _("Lab cases"),
    "lab:clients": _("Clients and accounts"),
    "settings:home": _("Settings"),
    "specialties:cases": _("Specialist cases"),
    "clinics:doctors": _("Doctors"),
}


def up_name(url):
    """The name of the page at ``url`` for the Up button, or None."""
    try:
        return UP_NAMES.get(resolve(url).view_name)
    except Resolver404:
        return None


def up_target(path, patient=None, user=None):
    """Where "Up" goes from the page at ``path`` (round 14: the page above it, not back one step): the patient's file
    for a page about a patient (a visit, an edit form...), unless the page above is itself one of the patient's pages
    (e.g. the log book → the patient's photos); else the address one level up. With ``user``, only a page this person
    can open."""
    from apps.patients.models import Patient

    url = up_url(path, user)
    if isinstance(patient, Patient) and patient.pk:
        file_url = patient.get_absolute_url()
        if file_url != path and f"/{patient.pk}/" not in url and (user is None or opens(user, file_url)):
            return {"url": file_url, "name": _("Patient file")}
    return {"url": url, "name": up_name(url)}
