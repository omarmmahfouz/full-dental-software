"""The lab's WhatsApp: the messages to the doctors (case received, ready, sent back), the answer to "where is my case?"
with its real status, and the automatic answer.

Without any cloud service the secretary answers in one click: she types the case number (or the doctor's mobile), the
system writes the answer with the real status and opens WhatsApp with it. With the WhatsApp Business platform of Meta
(optional, Settings of the lab) a doctor who sends a case number is answered by itself, day and night."""

import hashlib
import hmac
import json
import logging
import re
import urllib.request
from urllib.parse import quote

from django.db.models import Q
from django.utils import formats, timezone, translation

from apps.core.utils import normalize_phone
from apps.scheduling.whatsapp import whatsapp_number

from .models import CLOSED_STEPS, LabCase, LabMessage, LabSettings, Step, lab_branch

log = logging.getLogger("clinic.lab")

# The steps told to a doctor in plain words (what the step means for them).
STATUS_WORDS = {
    Step.INCOMING: "لسه ما وصلش المعمل",
    Step.RECEIVED: "وصل المعمل ومستني يبدأ",
    Step.MODELS: "بنصب الموديلات ونعمل سكان للطبعة",
    Step.DESIGN: "في مرحلة التصميم",
    Step.DESIGN_CHECK: "التصميم خلص وبيتراجع",
    Step.MILLING: "في مرحلة التفريز (الميلنج)",
    Step.PRINTING: "في مرحلة الطباعة ثلاثية الأبعاد",
    Step.METAL_PRINTING: "في مرحلة طباعة المعدن",
    Step.CASTING: "في مرحلة الشمع والصب",
    Step.SINTERING: "في الفرن (التلبيد)",
    Step.CERAMIC: "في مرحلة بناء البورسلين",
    Step.STAIN_GLAZE: "في مرحلة التلوين والجليز",
    Step.SETUP: "في مرحلة رص الأسنان",
    Step.PROCESSING: "في مرحلة تجهيز الأكريليك",
    Step.FINISHING: "في مرحلة التشطيب والتلميع",
    Step.QC: "في المراجعة النهائية للجودة",
    Step.READY: "جاهز للتسليم",
    Step.DELIVERED: "خرج من المعمل واتسلم",
    Step.TRY_IN: "عندكم في العيادة للتجربة",
    Step.OUTSOURCED: "في معمل متخصص لجزء من الشغل",
    Step.ON_HOLD: "متوقف: مستنيين رد حضرتك",
    Step.CANCELLED: "اتلغى",
}


class _Keep(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _values(case):
    lab = lab_branch()
    with translation.override("ar"):
        return {
            "doctor": case.doctor.replace("Dr. ", "").replace("د. ", "") if case.doctor else str(case.client),
            "patient": case.patient_name or "—", "number": case.number,
            "work": case.work_summary(), "lab": lab.name_ar if lab else "",
            "due": formats.date_format(case.due_date, "l d/m/Y") if case.due_date else "—",
            "phone": lab.phone if lab else "",
        }


def message_text(case, kind):
    options = LabSettings.get()
    text = {LabMessage.Kind.RECEIVED: options.received_text, LabMessage.Kind.READY: options.ready_text,
            LabMessage.Kind.DELIVERED: options.delivered_text}.get(kind) or ""
    if kind == LabMessage.Kind.STATUS or not text:
        return status_text(case)
    return text.format_map(_Keep(_values(case)))


def status_text(case):
    """The real status of a case, in Arabic, as the doctor will read it."""
    values = _values(case)
    now = timezone.localtime()
    lines = [f"حالة رقم {case.number}", f"المريض: {values['patient']}", f"الشغل: {values['work']}",
             f"الحالة: {STATUS_WORDS.get(case.step, case.get_step_display())}"]
    if case.step not in CLOSED_STEPS and case.step != Step.INCOMING:
        since = timezone.localtime(case.step_since)
        lines.append("من " + ("النهارده" if since.date() == now.date() else since.strftime("%d/%m")) +
                     " الساعة " + since.strftime("%I:%M").lstrip("0"))
    if case.step == Step.DELIVERED and case.delivered_at:
        lines.append("يوم " + timezone.localtime(case.delivered_at).strftime("%d/%m/%Y"))
    elif case.step not in CLOSED_STEPS and case.due_date:
        late = case.due_date < now.date()
        lines.append(("كان متوقع يوم " if late else "الميعاد المتوقع: ") + values["due"] +
                     (" — متأخر وبنعتذر، بنخلّصه في أقرب وقت" if late else ""))
    if values["phone"]:
        lines.append(f"للاستفسار: {values['phone']} — {values['lab']}")
    return "\n".join(lines)


def link(phone, text):
    number = whatsapp_number(phone)
    return f"https://wa.me/{number}?text={quote(text)}" if number else ""


def record(case, kind, user, phone=None, text=None, client=None):
    phone = phone if phone is not None else (case.whatsapp_phone if case else "")
    text = text if text is not None else message_text(case, kind)
    return LabMessage.objects.create(case=case, client=client or (case.client if case else None), kind=kind,
                                     phone=normalize_phone(phone), text=text, by=user)


# ------------------------------------------------------------ finding a case from a message
NUMBER = re.compile(r"(?:[A-Za-z]{2,4}\s*-?\s*)?(\d{1,6})")


def cases_for(query, phone=""):
    """The cases a number or a mobile points to. A mobile (the doctor's or the client's) gives their open cases."""
    query = (query or "").strip()
    from apps.core.utils import normalize_digits

    query = normalize_digits(query)
    found = LabCase.objects.none()
    mobile = normalize_phone(query) if re.fullmatch(r"[+\d\s-]{10,}", query) else ""
    if mobile:
        found = LabCase.objects.filter(Q(doctor_phone=mobile) | Q(client__phone=mobile) | Q(client__whatsapp=mobile))
        return found.exclude(step__in=CLOSED_STEPS).select_related("client").order_by("-pk")[:10]
    numbers = [int(n) for n in NUMBER.findall(query) if n.isdigit() and int(n) > 0]
    if numbers:
        found = LabCase.objects.filter(pk__in=numbers)
        if phone:  # an answer by itself: only to the doctor or the client of the case
            phone = normalize_phone(phone)
            found = found.filter(Q(doctor_phone=phone) | Q(client__phone=phone) | Q(client__whatsapp=phone))
    return found.select_related("client")[:10]


# ------------------------------------------------------------ the automatic answer (WhatsApp Business platform)
HELP_TEXT = ("أهلاً بحضرتك في {lab}. لمعرفة حالة الشغل ابعت رقم الحالة المكتوب على الإيصال "
             "(مثال: {example}).")
NOT_FOUND = ("مش لاقيين حالة بالرقم ده على الموبايل ده. اتأكد من الرقم أو كلّمنا على {phone}.")


def signature_ok(body, header, secret):
    if not secret:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header or "")


def answer_for(text, phone):
    """What the lab answers to a message from ``phone``."""
    lab = lab_branch()
    cases = list(cases_for(text, phone=phone))
    if not NUMBER.search(text or ""):
        return HELP_TEXT.format(lab=lab.name_ar if lab else "", example=f"{lab.badge if lab else 'LAB'}-00123"), []
    if not cases:
        return NOT_FOUND.format(phone=lab.phone if lab else ""), []
    return "\n\n".join(status_text(case) for case in cases), cases


def handle_webhook(payload):
    """Answer every text message of a webhook call. Returns how many answers were sent."""
    options = LabSettings.get()
    sent = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for message in change.get("value", {}).get("messages", []) or []:
                if message.get("type") != "text":
                    continue
                phone = "+" + message.get("from", "")
                text, cases = answer_for(message.get("text", {}).get("body", ""), phone)
                if send(options, message.get("from", ""), text):
                    sent += 1
                    for case in cases or [None]:
                        LabMessage.objects.create(case=case, client=case.client if case else None,
                                                  kind=LabMessage.Kind.AUTO, phone=normalize_phone(phone), text=text)
    return sent


def send(options, to, text):
    """Send one text through the WhatsApp Business platform (needs the internet)."""
    if not (options.wa_phone_number_id and options.wa_token and to):
        return False
    body = json.dumps({"messaging_product": "whatsapp", "to": to, "type": "text",
                       "text": {"body": text[:4000]}}).encode()
    request = urllib.request.Request(
        f"https://graph.facebook.com/v20.0/{options.wa_phone_number_id}/messages", data=body, method="POST",
        headers={"Authorization": f"Bearer {options.wa_token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return 200 <= response.status < 300
    except Exception as error:  # no internet, a wrong token...: the secretary answers by hand
        log.warning("WhatsApp answer not sent: %s", error)
        return False
