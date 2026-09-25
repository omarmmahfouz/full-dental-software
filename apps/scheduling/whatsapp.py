"""WhatsApp messages from the reception without any cloud service: the system writes
the message and opens WhatsApp (on the PC or the phone) with it ready; the secretary
presses send. Every message opened is kept on the appointment."""

from urllib.parse import quote

from django.utils import formats, timezone, translation

from apps.core.models import Branch, ClinicSettings
from apps.core.utils import normalize_phone

from .models import MessageTemplate, SentMessage

DEFAULT_TEXTS = {
    MessageTemplate.Kind.CONFIRMATION: (
        "أهلًا {patient}، تم حجز موعدك في {clinic} يوم {day} {date} الساعة {time} مع {dentist}.\n"
        "العنوان: {address}\nللتعديل أو الاعتذار اتصل بنا على {phone}."
    ),
    MessageTemplate.Kind.REMINDER: (
        "تذكير من {clinic}: موعدك يوم {day} {date} الساعة {time} مع {dentist}.\n"
        "برجاء الحضور قبل الموعد بعشر دقائق. للاعتذار اتصل بنا على {phone}."
    ),
    MessageTemplate.Kind.NO_SHOW: (
        "أهلًا {patient}، افتقدناك في موعدك يوم {date} في {clinic}. نتمنى أن تكون بخير.\n"
        "برجاء الاتصال بنا على {phone} أو الرد على هذه الرسالة لتحديد موعد جديد."
    ),
}


def load_default_templates():
    added = 0
    for kind, text in DEFAULT_TEXTS.items():
        _obj, created = MessageTemplate.objects.get_or_create(kind=kind, defaults={"text": text})
        added += created
    return added


def whatsapp_number(phone, country_code=None):
    """01001234567 -> 201001234567 (the international form wa.me needs)."""
    phone = normalize_phone(phone or "")
    if not phone:
        return ""
    if phone.startswith("+"):
        return phone[1:]
    code = country_code or ClinicSettings.get().whatsapp_country_code
    return f"{code}{phone[1:]}" if phone.startswith("0") else f"{code}{phone}"


class _Keep(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def message_text(kind, appointment):
    template = MessageTemplate.objects.filter(kind=kind, is_active=True).first()
    text = template.text if template else DEFAULT_TEXTS[kind]
    branch = appointment.branch or Branch.default()
    when = timezone.localtime(appointment.scheduled_at)
    with translation.override("ar"):
        values = {
            "patient": appointment.patient.full_name,
            "day": formats.date_format(when, "l"),
            "date": when.strftime("%d/%m/%Y"),
            "time": formats.time_format(when, "g:i A"),
            "dentist": str(appointment.dentist or ""),
            "clinic": branch.name_ar if branch else "",
            "phone": branch.phone if branch else "",
            "address": branch.address if branch else "",
        }
    return text.format_map(_Keep(values))


def whatsapp_url(phone, text):
    return f"https://wa.me/{whatsapp_number(phone)}?text={quote(text)}"


def record(kind, appointment, user):
    phone = appointment.patient.preferred_number
    text = message_text(kind, appointment)
    SentMessage.objects.create(appointment=appointment, patient=appointment.patient, kind=kind, phone=phone,
                               text=text, sent_by=user)
    return whatsapp_url(phone, text)
