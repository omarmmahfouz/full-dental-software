"""Hints: one short tip at the top of the main pages, on what to do there.

Keyed by the page's address name ("namespace:name"). A hint can differ by role: the first
matching role group wins, then "default". Each person can close a hint on one page (kept in
their browser) or switch all hints off from the user menu (kept on their profile)."""

from django.utils.translation import gettext_lazy as _

from .roles import DENTISTS, FRONT_DESK, LAB_DESK, LAB_STAFF, STOCK, has_role

ROLE_GROUPS = {"front_desk": FRONT_DESK, "dentist": DENTISTS, "stock": (STOCK,), "lab_desk": LAB_DESK[1:],
               "lab": LAB_STAFF[1:]}

HINTS = {
    "core:dashboard": {
        "lab_desk": _("The lab's day: receive a case, check in the work coming from our clinics, and tell the doctors "
                      "on WhatsApp. The numbers open the lists behind them."),
        "lab": _("The cases given to you are under With me now. Open one and press Done when your step is finished."),
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
                         "Fields with a red * are needed. The medical history is the dentist's: skip it if you like."),
    "patients:detail": {
        "dentist": _("The file step by step: the yellow button opens the next step. Record opens a treatment, a "
                     "surgery chart, a request or a prescription."),
        "default": _("Everything about this patient is on this page. The buttons at the top book, bill and print."),
    },
    "patients:medical_followup": _("Patients whose readings need a physician's opinion before surgery, the letters "
                                   "waiting for an answer, and the surgeries postponed for a medical reason."),
    "patients:consult_create": _("The letter is written from the medical history: tick the procedure, check the "
                                 "medicines, then save and print it for the patient."),
    "patients:consult_detail": _("Print the letter for the patient. When he brings the answer back, record it with "
                                 "a photo of the paper: the dentist is told."),
    "patients:records": _("Tap what you did today: the impression, the scan or the CBCT. Or skip it: it is not "
                          "needed for every patient."),
    "patients:lead_list": _("People who called but have no file yet. When one comes in, open the call and turn it "
                            "into a patient file in one click."),
    "patients:calllist_list": _("Lists of patients to call, sent by the dentists or the heads. Open a list, call each "
                                "patient and write the answer."),
    "scheduling:today": _("Tap Arrived when the patient comes in, then In the room and Left. "
                          "The panel at the top follows the clock of this computer."),
    "scheduling:day_planner": _("One column per room (or per doctor: By doctor), in 15-minute steps. Tap a green "
                                "place to book it, or tap a booking to open it."),
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
    "clinical:step_create": _("Tap the kind of work, then the step (e.g. Endodontics, then Obturation). Write the "
                              "teeth and check how the chart will change before saving."),
    "clinical:step_detail": _("Take the photos and periapical X-rays this step needs: each box opens the tablet's "
                              "camera."),
    "clinical:lab_list": _("Each lab work from the request to the fitting. Late work is marked in red."),
    "clinical:visits_missing_notes": _("Visits with nothing written in the patient's file. Open each one and "
                                       "record what was done."),
    "charting:chart": _("Tap a tooth to see its history. The buttons above the chart open the examination, "
                        "the plan and the photos."),
    "charting:plan_finder": _("Choose the filters, then send the patients found to the reception to call them."),
    "surgery:list": _("Every surgery chart. Tap one to open it, or start a new surgery chart."),
    "surgery:create": _("Choose a tool (implant, pontic, extraction...) and tap the teeth, like on a scanner. Choose "
                        "the implant company once, then the sizes and lots implant by implant."),
    "surgery:update": _("Tap the teeth to change the design; each tooth's details are in the list below it."),
    "surgery:delivery_check": _("Tap each point as you do it and write the torque. Save it as delivered at the end: "
                                "the implants become loaded on the chart."),
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
    "billing:day": {
        "front_desk": _("All the receipts of the day at this place. Before you leave, count the cash in the drawer and "
                        "close the day. A receipt written by mistake is cancelled from the receipt itself."),
        "default": _("The day's receipts, bills and changes. Tick the day as reviewed when it is right."),
    },
    "billing:month": _("Each day of the month with its total, whether it was closed and reviewed, and the difference "
                       "in the drawer. Tap a day to open it."),
    "billing:receipt_change": _("Correct the amount or the way of paying, cancel a receipt written by mistake, or give "
                                "money back. Write why: the owner sees every change."),
    "billing:bill": {
        "dentist": _("The reception is told of this bill and takes the payment. Press WhatsApp to ask the reception "
                     "to send it to the patient."),
        "default": _("Take the payment under the bill; the receipt opens after saving."),
    },
    "clinical:outside_print": _("Print the request for the patient. When the scan is done, press Done here or at the "
                                "centre and write the folder of the scan: it then opens with one click."),
    "patients:medical_history": _("Ask the questions in order and tick the answers. Save and go on: the file goes "
                                  "step by step to the dental history, the examination and the plan."),
    "charting:photo_edit": _("Draw a frame to crop (4:3 fits the log book), turn or mirror, then save. The original "
                             "photo is kept and can be put back."),
    "stock:categories": _("The stock is in groups (dental, implants, beverage, stationery...), each with its "
                          "categories. Add or rename a category here; the clock button shows its movements."),
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
    "settings:backup": _("Green means the last backup worked. Every night the data is saved as a ZIP and the new "
                         "photos are copied to the backup disk. Make a backup now before any big change."),
    "settings:security": _("A yellow line is something to fix, with how. Below: who is logged in now, the logins "
                           "closed after wrong passwords (Open lets them try again) and everything done with the "
                           "logins and the files taken out."),
    "settings:deleted": _("Whatever anyone deletes is kept here for a year: open a line to see what it held, then "
                          "write it again if it was a mistake."),
    "core:problems": _("Problems told by the staff, and pages that stopped with an error (written down by "
                       "themselves). Mark each one when it is being looked at or solved."),
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
    "clinics:prices": _("A doctor's own price for a service (e.g. the TMJ specialist's examination) and its usual lab "
                        "or implant cost. His bills take this price by themselves."),
    "specialties:cases": _("The specialists' charts at this place: endodontics, TMJ, orthodontics and shades. Tap a "
                           "row to open it; new ones start from the patient's file → Specialists."),
    "specialties:patient": {
        "front_desk": _("The patient's referrals. Tap Book on a referral to book the patient with the specialist."),
        "default": _("Refer the patient, or open a specialist's chart. The referrals and every chart of the patient "
                     "are listed below."),
    },
    "specialties:referrals": {
        "front_desk": _("Referrals to book: open one and tap Book, the specialist and the patient are filled in."),
        "default": _("The referrals of this place: the ones sent to you, the ones you sent, and their answers."),
    },
    "specialties:referral": {
        "front_desk": _("Book the patient with the specialist from here, and print the letter for the patient."),
        "default": _("The letter prints with the place's letterhead. The specialist writes his answer at the bottom: "
                     "the referring doctor is told."),
    },
    "specialties:endo": _("Add each visit with the medication left in the canals. When the tooth is obturated, tap "
                          "Obturated: the dental chart shows the root canal."),
    "specialties:tmj": _("Add each follow-up with the mouth opening and the pain: the bars show the progress."),
    "specialties:ortho": _("Add each adjustment visit: the wires of the last visit are filled in, change what is new."),
    "specialties:shade": _("The shade of each third of the tooth for the ceramist. Tap Lab request to send it with "
                           "the work."),
    # The dashboard and the dental lab
    "core:overview": _("Every place side by side. Choose today, 7 days or this month; rest the mouse on a column to "
                       "see its number, or open Show the numbers."),
    "lab:board": {
        "lab_desk": _("One column per step. Press the button under a case when its step is done: it goes on to the "
                      "next step, and to the person who does it."),
        "default": _("One column per step. The cases with you have your name; press Done when your step is "
                     "finished."),
    },
    "lab:case_create": _("Choose the client and write the work: the price comes from the client's price list and the "
                         "steps from the kind of work. Then print the label for the box."),
    "lab:incoming": _("Work sent by CIA, CIC or El Khadem. When it arrives, tick what came with it and press "
                      "Received."),
    "lab:case_detail": _("The big button moves the case to its next step. The bars show how long each step took. A "
                         "remake opens a new case linked to this one."),
    "lab:my_work": _("The cases given to you. Press the button when your step is finished: the next person is told."),
    "lab:blocks": _("Open a new block when you start it: then record on each case how many units were milled from "
                    "it, and close the block when it is finished."),
    "lab:clients": _("Each client with what was delivered, paid and still owed. Open one for its cases, receipts and "
                     "statement."),
    "lab:prices": _("Type the prices of each list and press Save. An empty box means no price for that work."),
    "lab:payments": _("Every receipt of the lab. A mistake is cancelled with its reason (never deleted)."),
    "lab:report": _("The time each step takes, the people, the remakes and their reasons, the blocks and the money. "
                    "Change the dates to compare months."),
    "lab:whatsapp": _("Type the case number or the doctor's mobile: the answer with the real status is written for "
                      "you. Press Send, then send it in WhatsApp."),
    "lab:staff": _("Tick the steps each person does: a case goes by itself to the only person who does a step."),
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
