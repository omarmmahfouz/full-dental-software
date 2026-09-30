"""The bar at the bottom of the screen on tablets and phones: the four places each person uses
most, then "Menu", which opens the full menu from the side."""

from django.urls import Resolver404, resolve, reverse
from django.utils.translation import gettext_lazy as _

from .roles import (
    DENTISTS, FRONT_DESK, HEAD_CIA, LAB_DESK, LAB_STAFF, MODERATOR, OWNER, SECRETARY, STOCK, is_only_dentist,
    user_roles,
)


def _item(url_name, icon, label, match=None, query=""):
    url = reverse(url_name)
    return {"url": url + query, "icon": icon, "label": label, "match": match or url}


def bottom_nav(user, path, hidden_areas):
    """[{url, icon, label, match, active}], at most four, for this person."""
    roles = user_roles(user)
    items = [_item("core:dashboard", "bi-house-door", _("Home"), match="/")]
    front_desk = bool(roles & set(FRONT_DESK))
    patients = "patients" not in hidden_areas and bool(roles & set(FRONT_DESK + DENTISTS))
    schedule = "schedule" not in hidden_areas
    lab_only = bool(roles & set(LAB_STAFF)) and not roles & set(FRONT_DESK + DENTISTS + (MODERATOR, STOCK))
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


def up_url(path):
    """The page above this one, from its address: /lab/cases/5/edit/ → /lab/cases/5/ → /lab/cases/ → the home page.
    "Back" opens it when the tab has no page before (e.g. a page opened from a notification)."""
    parts = [part for part in path.split("/") if part]
    while parts:
        parts.pop()
        candidate = "/" + "/".join(parts) + "/" if parts else "/"
        try:
            resolve(candidate)
        except Resolver404:
            continue
        return candidate
    return "/"
