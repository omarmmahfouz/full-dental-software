"""The bar at the bottom of the screen on tablets and phones: the four places each person uses
most, then "Menu", which opens the full menu from the side."""

from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from .roles import DENTISTS, FRONT_DESK, SECRETARY, STOCK, is_only_dentist, user_roles


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
    if front_desk:
        if schedule:
            items.append(_item("scheduling:today", "bi-display", _("Reception"), match="/schedule/"))
        if patients:
            items.append(_item("patients:list", "bi-people", _("Patients"), match="/patients/"))
        if SECRETARY in roles and schedule:
            items.append(_item("scheduling:appointment_create", "bi-calendar-plus", _("Book")))
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
