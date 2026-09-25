from django import forms, template
from django.template.defaultfilters import floatformat
from django.utils.translation import gettext as _

from apps.core.roles import has_role as _has_role

register = template.Library()


@register.filter
def has_role(user, roles):
    """{% if request.user|has_role:"secretary,owner" %}"""
    return _has_role(user, *[r.strip() for r in roles.split(",")])


@register.filter
def field_col(bound_field):
    """Bootstrap grid column for a form field (wide widgets take the full row)."""
    col = getattr(bound_field.field, "col", None)
    if col:
        return col
    widget = bound_field.field.widget
    if isinstance(widget, (forms.Textarea, forms.CheckboxSelectMultiple)):
        return "col-12"
    return "col-md-6 col-lg-4"


@register.filter
def is_checkbox(bound_field):
    return isinstance(bound_field.field.widget, forms.CheckboxInput)


@register.filter
def is_multi_checkbox(bound_field):
    return isinstance(bound_field.field.widget, (forms.CheckboxSelectMultiple, forms.RadioSelect))


@register.filter
def minutes(value):
    """Show a number of minutes as '45 min' or '1 h 20 min'."""
    if value is None or value == "":
        return "—"
    value = int(round(float(value)))
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value < 60:
        return sign + _("%(m)s min") % {"m": value}
    return sign + _("%(h)s h %(m)s min") % {"h": value // 60, "m": value % 60}


@register.filter
def money(value):
    if value is None or value == "":
        return "—"
    return floatformat(value, "2g")


STATUS_COLORS = {
    # leads
    "new": "primary", "follow_up": "warning", "booked": "info", "converted": "success",
    "not_interested": "secondary", "unreachable": "dark",
    # appointments
    "scheduled": "secondary", "confirmed": "primary", "arrived": "warning", "in_room": "info",
    "completed": "success", "no_show": "danger", "cancelled": "dark",
    # lab
    "draft": "secondary", "pending_review": "warning", "approved": "primary", "sent": "info",
    "received": "success", "delivered": "dark",
    # complaints
    "open": "danger", "in_progress": "warning", "resolved": "success", "closed": "secondary",
    # patients / enrollments
    "active": "success", "finished": "dark", "inactive": "secondary", "withdrawn": "secondary",
    # installments
    "paid": "success", "partial": "warning", "due": "secondary", "overdue": "danger", "credit": "danger",
    # severity
    "low": "secondary", "medium": "warning", "high": "danger",
}


@register.filter
def status_color(value):
    return STATUS_COLORS.get(str(value), "secondary")


@register.inclusion_tag("includes/status_badge.html")
def status_badge(obj, field="status"):
    value = getattr(obj, field)
    label = getattr(obj, f"get_{field}_display")()
    return {"color": STATUS_COLORS.get(str(value), "secondary"), "label": label}


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def attr(obj, name):
    """{{ site|attr:"extraction" }} — read an attribute whose name is in a variable."""
    return getattr(obj, str(name), None)
