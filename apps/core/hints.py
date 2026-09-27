"""Hints: one short tip at the top of the main pages, on what to do there.

Keyed by the page's address name ("namespace:name"). A hint can differ by role: the first
matching role group wins, then "default". Each person can close a hint on one page (kept in
their browser) or switch all hints off from the user menu (kept on their profile)."""

from django.utils.translation import gettext_lazy as _

from .roles import DENTISTS, FRONT_DESK, STOCK, has_role

ROLE_GROUPS = {"front_desk": FRONT_DESK, "dentist": DENTISTS, "stock": (STOCK,)}

HINTS = {
    "core:dashboard": {
        "front_desk": _("Start here: find a patient with the search box, or tap a big button. "
                        "Below them you see who comes next and who is waiting."),
        "dentist": _("Your week is below: tap a patient to open the visit page. "
                     "The bell at the top rings when your patient arrives."),
        "stock": _("Items running low and expiring soon are listed here. Tap one to receive or take out stock."),
        "default": _("The numbers are live: tap a box to open the list behind it."),
    },
    "core:notifications": _("Tap a notification to open what it is about. New ones are marked in blue."),
    "core:approvals": _("Changes made at the reception wait here. Compare the old and the new values, then approve or refuse."),
    "patients:list": _("Type part of a name, a mobile or a file number. Tap a row to open the patient's file."),
    "patients:create": _("Type the national ID first: the date of birth and the gender fill in by themselves. "
                         "Fields with a red * are needed."),
    "patients:detail": _("Everything about this patient is on this page. The buttons at the top book, bill and print."),
    "patients:lead_list": _("People who called but have no file yet. When one comes in, open the call and turn it "
                            "into a patient file in one click."),
    "patients:calllist_list": _("Lists of patients to call, sent by the dentists or the heads. Open a list, call each "
                                "patient and write the answer."),
    "scheduling:today": _("Tap Arrived when the patient comes in, then In the room and Left. "
                          "The panel at the top follows the clock of this computer."),
    "scheduling:day_planner": _("One column per room, in 15-minute steps. Tap a green place to book it, "
                                "or tap a booking to open it."),
    "scheduling:appointment_create": _("Choose the patient and the dentist, then tap a green place in the day grid "
                                       "under the form, or use Nearest free times."),
    "scheduling:appointment_list": {
        "dentist": _("Your appointments. Tap one to open the visit page and record what was done."),
        "default": _("Filter by day, dentist or status. Tap an appointment to open it."),
    },
    "scheduling:room_schedule": {
        "dentist": _("Your shifts: which room and which hours, and the surgery days."),
        "default": _("Who works in which room this week. Add a shift, or fill the week from last week in one click."),
    },
    "scheduling:whatsapp": _("Tap Send: WhatsApp opens with the message ready. Press send there, then come back "
                             "for the next one."),
    "scheduling:waiting_list": _("Patients waiting for a place. When a place frees up, you are told who to call."),
    "scheduling:visit": _("Follow the tiles in order: the treatment or the surgery chart first, then the "
                          "prescription and the instructions."),
    "scheduling:requests_mine": _("Add the patients you want on your days, with the step and the time needed. "
                                  "The supervisor approves the list, then the reception calls them."),
    "scheduling:requests_reception": _("Call the patients in order. Book fills the booking form in one step; "
                                       "if one cannot come, the page says who to call instead."),
    "clinical:step_list": _("Every treatment recorded. Filter by dentist or date, and tap a row for the details."),
    "clinical:step_create": _("Write the teeth and choose the treatment. Check how the chart will change before saving."),
    "clinical:lab_list": _("Each lab work from the request to the fitting. Late work is marked in red."),
    "clinical:visits_missing_notes": _("Visits with nothing written in the patient's file. Open each one and "
                                       "record what was done."),
    "charting:chart": _("Tap a tooth to see its history. The buttons above the chart open the examination, "
                        "the plan and the photos."),
    "charting:plan_finder": _("Choose the filters, then send the patients found to the reception to call them."),
    "surgery:list": _("Every surgery chart. Tap one to open it, or start a new surgery chart."),
    "surgery:create": _("Fill in the team first, then one card per tooth. An implant chosen from stock fills in "
                        "its size and lot."),
    "surgery:finder": _("Choose filters, then group by one or two columns for the statistics. "
                        "Export to Excel for publications."),
    "complaints:list": _("Open complaints come first. Tap one to follow it up or to write what was done."),
    "complaints:create": _("Write what the patient said, in their words. The supervisors and the owner are told at once."),
    "academy:candidate_list": _("Course candidates. Tap one for the enrollment, the installments and the implants done."),
    "academy:installments_month": _("What each candidate pays this month. Tap the WhatsApp button to remind them."),
    "academy:overdue": _("Installments past their date. Call or send a WhatsApp reminder, then record the payment."),
    "billing:bill_create": _("Tap a quick button for the usual services, or add lines yourself. Tick Pay now to "
                             "take the money at once."),
    "billing:bill_list": _("Bills to collect are at the top. Tap a bill to take a payment or print it."),
    "billing:payment_list": _("The day's collections by payment method are at the top. Tap a payment to print its receipt."),
    "billing:fawry": _("Card payments appear here by themselves. Add bills paid on the machine, money put on it and "
                       "Fawry's transfers to the bank."),
    "dentists:list": _("Every dentist by type. Tap a name to see their cases, surgeries and implants."),
    "stock:item_list": _("Red rows are below their reorder level. Tap an item to receive, take out or count it."),
    "stock:use": _("Choose who takes the items, then add one line per item. The stock goes down when you save."),
    "stock:movement_list": _("Every stock movement, with who and for whom. Filter by item or date."),
    "purchasing:purchase_list": _("Every purchase with what is still owed. Tap one for its lines and invoice photo."),
    "purchasing:purchase_create": _("Add one line per item with its category. Link a line to a stock item to fill the stock."),
    "reports:index": _("Choose a report. Each one can be filtered by dates, and most can be exported."),
    "settings:home": _("Lists, clinic options and logins. Nothing is deleted: untick active to stop using an item."),
    "clinics:doctors": _("Each doctor of the place: visits, time in the chair, what the patients paid and the "
                         "doctor's share. Tap a doctor for the details and to record a payment to them."),
    "clinics:statement": {
        "dentist": _("Your services and visits at this place, the share of each one, and what you were paid."),
        "default": _("Every service and visit of the doctor with its share. Record each payment to the doctor under "
                     "the list: what is still owed goes down."),
    },
    "clinics:rules": _("How each doctor is paid: a percentage, a fixed amount for each service (each tooth) or for "
                       "each visit. To change it from a date, add a new rule from that date."),
    "clinics:report": _("The place over the period: what the patients paid, visits and time, the doctors' shares, "
                        "the materials used, and what is left for the clinic."),
}


def hint_for(request):
    """The hint of the page being shown, as {"key", "text"}, or None."""
    match = getattr(request, "resolver_match", None)
    if match is None or not match.view_name:
        return None
    hint = HINTS.get(match.view_name)
    if isinstance(hint, dict):
        for group, roles in ROLE_GROUPS.items():
            if group in hint and has_role(request.user, *roles):
                hint = hint[group]
                break
        else:
            hint = hint.get("default")
    if not hint:
        return None
    return {"key": match.view_name, "text": hint}
