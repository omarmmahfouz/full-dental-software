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
def wa_number(phone):
    """01001234567 -> 201001234567, for a WhatsApp link."""
    from apps.scheduling.whatsapp import whatsapp_number

    return whatsapp_number(phone)


@register.filter
def preview(file, size="small"):
    """The address of a picture's small copy: {{ photo.file|preview }} for grids, {{ photo.file|preview:"medium" }}
    for large photos. Files that are not pictures (PDF, video) keep their own address."""
    from django.core.files.storage import default_storage

    from apps.core import previews

    name = getattr(file, "name", file) or ""
    if not name:
        return ""
    if not previews.can_preview(name) or size not in previews.SIZES:
        return default_storage.url(name)
    return default_storage.url(previews.preview_name(name, size))


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
    "completed": "success", "no_show": "danger", "cancelled": "dark", "late_not_seen": "danger", "pending": "warning",
    # lab
    "draft": "secondary", "pending_review": "warning", "approved": "primary", "sent": "info",
    "received": "success", "delivered": "dark",
    # complaints
    "open": "danger", "in_progress": "warning", "resolved": "success", "closed": "secondary",
    "out": "danger",
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
def opens_dentist(user, dentist):
    """{% if user|opens_dentist:step.operator %} — show the name as a link only if the file opens for them."""
    from apps.dentists.access import can_open_dentist_file

    return can_open_dentist_file(user, dentist)


@register.filter
def attr(obj, name):
    """{{ site|attr:"extraction" }} — read an attribute whose name is in a variable."""
    return getattr(obj, str(name), None)


@register.filter
def teeth_explained(text):
    """For Arabic pages: each tooth number with its plain Arabic name (empty list in English)."""
    from django.utils.translation import get_language

    from apps.charting.teeth import teeth_explained_ar

    if not text or not (get_language() or "").startswith("ar"):
        return []
    return teeth_explained_ar(text)


@register.filter
def explain(step_type):
    """The simple Arabic explanation of a treatment, on Arabic pages only."""
    from django.utils.translation import get_language

    if step_type is None or not (get_language() or "").startswith("ar"):
        return ""
    return getattr(step_type, "description_ar", "")


@register.filter
def teeth_in_text(text):
    """For Arabic pages: the tooth numbers found in a sentence ("Guided implant 36, 46"), each with its name."""
    import re

    from django.utils.translation import get_language

    from apps.charting.teeth import tooth_name_ar

    if not text or not (get_language() or "").startswith("ar"):
        return []
    found = []
    for number in re.findall(r"(?<!\d)([1-8][1-8])(?!\d)", str(text)):
        name = tooth_name_ar(number)
        if name and (number, name) not in found:
            found.append((number, name))
    return found


@register.filter
def shade_colour(value):
    """The colour of a shade tab (A2, 3M2, ND3…) on the screen, or of the main shade of a shade record."""
    from apps.specialties.shades import COLOURS

    return COLOURS.get(str(getattr(value, "shade", value) or ""), "#EEE9DD")


@register.simple_tag
def shade_guides():
    """The tabs of each shade guide with their colours, for the shade picker on the page."""
    from apps.specialties.shades import picker_data

    return picker_data()
