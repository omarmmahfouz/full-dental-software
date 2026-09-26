# Dental Group System — Cairo Implant Academy

One system for the owner's three connected places:

| Branch | Code | Status |
|---|---|---|
| **Cairo Implant Academy** — teaching institute, economic dental service, course candidates, dentists | `CIA` | **In use: secretary + dentists** |
| Private clinic — specialists and freelance doctors | `PVT` | planned (data model ready) |
| Dental lab — serves both clinics and outside clinics | `LAB` | planned (lab requests already flow to it) |
| CIC — the future economical clinic | `CIC` | planned (its money already goes through the Fawry machine and the balance sheet) |

It runs **on your own PC or the clinic's own server**, with no cloud. Staff open it in a browser on the clinic network.
Everything works offline, including fonts, icons and styles.
The language follows the person, not the PC:
- Secretaries and the stock manager get **Arabic (right to left)**.
- Dentists, the heads and the owner get **English**. Reports, lists, rooms and notifications follow the same language.
- Anyone can switch from the user menu, and the system remembers their choice. One person switching does not change it for the others on a shared PC.

---

## Who uses it

| Person | Login | What they see |
|---|---|---|
| Owner / CEO | `owner` | everything, including the money report and **all the settings**: logins, access and time limits |
| Head of CIA | `head_cia` | everything except the money report; in the settings, the lists (implant companies, treatments, drugs…) but not logins or access |
| Head of the CIA dentists team | `team_head` | what a CIA dentist sees, plus the follow-up report of the **CIA dentists** (not the candidates) and the treatment plan finder |
| CIA dentists (full or part time) | `dentist` | every patient, the complaints about them, **only their own schedule**, and their cases. They record the clinical work: their own, and the course candidates' work, choosing the candidate's and the supervisor's names. In surgery they are usually the **assistant** |
| Secretary (reception) | `secretary` | reception, patients, the **day planner**, WhatsApp messages, **patient payments**, lab send / receive, CBCT and blood test requests, complaints, academy (if allowed in Settings), purchases, and the **patients to call** lists. Not the dental chart, treatment log or surgeries: the patient file shows her the plan and the treatments done, in plain Arabic. Her edits of patient data and visit times wait for the head of CIA's approval |
| Stock manager | `stock` | the stock of materials, instruments, food and beverage, and purchases |
| Supervisors | no login for now | chosen by name: on treatments, surgeries, plans and lab requests |
| Course candidates | **no login** | followed through their dentist file: batch, payments, implants done and remaining, every case |
| Training dentists | no login | chosen by name |

## What it does

### Secretary (Arabic interface)
- **Call list (expected patients)**: people who call to become patients. The call records:
  - the full name
  - 2 mobiles and which one is preferred
  - age
  - missing teeth (single / multiple / full arch / both arches)
  - medical history as the caller describes it, from a checklist plus notes
  - how they heard about us

  Other features:
  - Call log with the result of each call, and the next call date.
  - A "calls due today" list.
  - When the patient comes in, one click turns the call into a full patient file.
- **Patient registration**:
  - Full name and national ID. The date of birth and gender are read from the Egyptian national ID. Passports are supported too.
  - Mobiles.
  - **ID card scan upload** (front and back, from a scanner or a tablet camera).
  - **Who referred you**: the source, and the referring patient if another patient referred them.
  - **Relatives or friends among our patients**.
  - The **responsible dentist**.
- **No duplicates**:
  - The national ID and the **primary mobile** are unique.
  - A mobile is recognised however it is typed (`+20 100…`, `0100…`, Arabic digits `٠١٠٠…`).
  - The error message names the existing file.
  - Every patient gets a unique file number (`CIA-00001`).
- **Room schedule**:
  - A weekly grid of the **5 rooms**, showing which dentist works in which room and when, with the supervisor of the day.
  - Each day is a **regular day** or a **surgery day** (with its own supervisor).
  - It blocks double-booking of a room or a dentist.
  - "Copy previous week" in one click.
- **Appointments and the reception board**:
  - One click each for **arrived → entered the room → left**.
  - Live waiting counters.
  - Walk-ins, no-shows, cancellations, and undo for a mistaken click.
- **WhatsApp messages to patients**:
  - **Booking confirmation** after a new appointment, **reminder** the day before, and a message after a **missed appointment** asking the patient to book again.
  - One click opens WhatsApp (WhatsApp Desktop or WhatsApp Web on the PC, or the app on a phone) with the patient's number and the message ready: name, day, date, time, dentist, and the clinic's address and phone. The secretary presses send.
  - The page "رسائل واتساب" lists what is still to send (new bookings, tomorrow's reminders, missed appointments), and every message sent is kept on the appointment with the time and who sent it.
  - No cloud service and no monthly fee: it uses the clinic's own WhatsApp. The owner changes the texts in the settings.
- **Lab work**:
  - The secretary sends and receives lab work, and must tick **"work checked against the lab request"** each time.
  - A **"lab work" badge** appears next to the patient's name everywhere.
- **Complaints**:
  - The secretary records the complaint and **the main supervisors and the owner are notified right away**.
  - Follow-up timeline with next-follow-up dates, and reminders when a complaint is overdue.
- **Course candidates and installments**:
  - Courses, candidates, and enrollment with a discount.
  - A down payment plus a monthly installment plan. Each enrollment is **in the academy (offline) or online**.
  - **Installments of the month**: what each candidate pays this month, what is collected and what is left, with a **WhatsApp reminder** button (also on the overdue list and the WhatsApp page).
  - Each payment records the **payment method**: cash, card, InstaPay, mobile wallet, bank transfer or cheque, with the transaction reference.
  - Printable receipts, and an overdue installments list.
- **Easier booking**:
  - Type part of the patient's **name** (any spelling of أ/ا, ة/ه, ى/ي), mobile or file number, and choose from the list.
  - Every date is **dd/mm/yyyy**, from a calendar or typed. Times are chosen in **15-minute steps** (9:00, 9:15, 9:30…).
  - Under the form, the **day's appointments** room by room: click a free (green) place and its time, room and dentist are filled in.
  - **Schedule → Day planner**: one column per room with the dentist working there, 15-minute steps, every booked patient, and the week at the top (booked and free places per day).
- **Room schedule**: CIA dentists in one list, and supervisors, candidates and training dentists in a second list. Thursday and Friday are surgery days by default (changeable in Settings). A surgery day is set per room, so one room can have a candidate's surgery while the others work as usual. **Extra rooms** appear only on the days they are opened. "Same as last week" fills the week with last week's timetable.
- **Patient file**:
  - The **ID scan** is cut out of the background, turned upright and shown as a card; the original photo is kept, and it can be turned by hand.
  - **File opened on** for old paper files, a list of all **governorates**, patients labelled **out** with a reason, and the call list sorted by the **first-call date**.
  - Mobiles with the wrong number of digits are refused, and duplicates name the other patient, in a **pop-up**.
  - **Treatment plan** and **treatment steps** tabs in plain Arabic, with a simple explanation of each treatment and each tooth number (36 = الضرس الأول السفلي الأيسر). The **missing teeth** and the **medical history** follow the dentist's chart and examination.
  - Editing the data, or correcting forgotten arrival / room / leaving times, is sent to the **head of CIA for approval**.
- **Patient payments**: services from a price list (CBCT, consultation, implant…), discounts up to 100% with the reason, payment in parts, receipts, and the day's collections by payment method.
- **CBCT and blood test requests**, printed for the patient to take. The CBCT request asks the centre to send the DICOM files to **ciapts@gmail.com** (changeable in Settings).
- **Back** button on every page.
- **Patients the dentists asked for**: each CIA dentist sends the list of patients he wants on his days (step, time needed, order, and a backup list). After the head of CIA approves it, the reception calls them in order and books them with one click (patient, dentist, time and step filled in). When a patient cannot come, the page says which backup patient to call next.
- **Medical and dental history at the reception**: the same questions as the paper chart (blood pressure, sugar, allergies, smoking…), from the patient file. The dentist sees them at the next examination.
- **Save before leaving?**: leaving a page with data not saved yet asks *Save*, *Leave without saving* or *Stay*.
- **Report a problem**: user menu → *Report a problem*, with a screenshot if wanted. The owner reads them, answers, and the person is told.
- **Reception now** (new): the home page and *Reception today* sort the day's patients by the time on the PC, updated every minute: *late — not here yet*, *expected now*, *next 2 hours*, *waiting*, *here now*. Filters (all / still to come / here / finished), a search box and a short list make a busy day easy to read.
- **Walk-ins and the next visit** (new):
  - A patient who comes without an appointment but has other bookings: the reception is asked to cancel or move them.
  - A patient who leaves without a next appointment: *Book the next visit* (with what the dentist wrote), or *No next visit needed*.
- **Came late, not seen** (new): a status of its own (not a no-show), and the page to book another time opens at once. The dentist is told.
- **Waiting time** (new): a patient who comes early waits from the appointment time, not from the arrival.
- **Smarter booking** (new):
  - Choose the dentist: the screen says if he works that day and in which room (the room is filled in, and can be changed).
  - *Nearest free times*: for the chosen dentist, or for any dentist when none is chosen. Click one to fill the date, time, room and dentist.
  - Booking a dentist on a day or hour that is not on the room schedule is allowed, but the supervisor is told, and a button sends the dentist a WhatsApp message.
  - The procedure is chosen from a list (Arabic names for the secretary), with a box for the teeth and notes. The dentist who asked for the visit and a **second dentist in the room** are shown on the board.
- **WhatsApp: send all / mark as sent** (new): tick the messages already sent, or *Send the next one* to go down the list one message after another.
- **Bills** (new): *Patients → New bill*, with one-click buttons for the first-visit examination and the CBCT, several services with teeth and discounts, *pay now*, and a printed bill. Bills made by the dentists after a treatment appear on the reception board to collect.
- **Waiting list** (new): patients who want a place on a busy day (also short 5–10 minute visits). When an appointment is cancelled, missed or moved, the reception is told that a place is free and who is waiting.
- **Lab cycle** (new): the dentist makes the request → the reception **takes the impression / model from the dentist** (a digital scan goes by itself) → sends it → receives the work → the patient is booked for the fitting (the reception is told when the work is back).
- **Complaints** (new): the concerned dentist is told at once; the reception writes **what she did** and the **current situation** of the case (shown in the list), and can correct her notes.
- **Fawry machine** (new): *Patients → Fawry machine*. Card payments taken on the machine for patients and course candidates appear by themselves with Fawry's percentage; the reception adds bills paid through the machine (mobile, electricity, internet…), money put on it and Fawry's transfers to the bank, for the academy, the private clinic or CIC. The page shows what Fawry still holds.
- **Up button** (new): a round arrow at the bottom corner of long pages goes back to the top.
- **Purchases**:
  - Dental and non-dental purchases from different suppliers.
  - Each item goes under a category (tea/coffee, stationery, food/candies, cleaning, implants, consumables…).
  - Invoice photo, and paid / partly paid / on credit.

### Dentists (English interface)
The people who treat patients are all **dentists**, of these types:

| Type | Who |
|---|---|
| Course candidate | pays for the course. Created automatically from Academy → Candidates, so it is linked to their batch, payments and implant count |
| Training dentist | helps without paying |
| CIA dentist (full / part time) | staff dentist; the only type that logs in |
| Supervisor | supervises regular days and surgery days; chosen by name |
| Specialist / freelance dentist | for the private clinic later |

What dentists do:
- **Home page**: **my week** (my shifts and patients for the next 7 days), the **latest changes** to my appointments (new, moved, cancelled, did not come), and complaints waiting for my answer.
- **Dental chart (digital version of the CIA paper chart)**:
  - Drawn like **real teeth**: each tooth has its own crown and roots (incisors, canines, premolars, molars with 2 or 3 roots), and a round 5-surface diagram under it for caries and fillings. It shows root canals, crowns, implants (healing or loaded), bridge pontics, missing teeth, root remnants, impacted, mobility and hopeless teeth.
  - **Examination & history**: every field of the paper chart. This covers the chief complaint, the teeth lists, CBCT, blood pressure, glucose, HbA1c, allergies, drugs, the dental history and the scores.
  - A new examination starts from the last one, so only what changed needs typing.
- **Treatment log, with the chart following the treatment**:
  - The dentist writes the tooth numbers and the treatment, e.g. `12` + *Composite restoration* + `MO`.
  - Before saving, the screen shows how the chart will change: *12: caries MO → filled composite (MO)*. The dentist confirms with a tick box.
  - Other examples: *46 Implant failure* → 46 becomes **missing**, and the implant is marked **failed**. *36 Extraction* → missing. *Second stage / impression / delivery* → the implant moves to its next stage.
  - Every change is kept in the tooth's history.
- **Treatment log form**: the treatment is chosen from a list, with a **notes** box right under it.
- **Treatment plans**: phases (urgent, preparation, surgical, prosthetic, maintenance), and the **case difficulty** (simple, moderate, advanced). The dentist picks the name of the supervisor who approved it.
  - Two parts: **Implant and surgery** and **Restorative and other**; each treatment's part is set in Settings → Treatments.
  - **Tooth picker**: a button next to every teeth box opens the tooth chart; click all the teeth that get the same procedure (e.g. simple implant on 36, 46 and 16). "All missing teeth" picks the teeth missing on the chart.
  - Planned teeth show in blue on the chart.
  - Items are ticked **automatically** when the same treatment is recorded on the same teeth.
- **Implant surgery chart**: the CIA surgery chart, field by field:
  - The team: instructor, operator 1, operator 2 and assistant.
  - The case difficulty.
  - Per tooth: extraction, flap, simple / immediate / guided implant, expansion, splitting, closed / open sinus and GBR.
  - **Same procedures on several teeth**: tick the procedures, choose the teeth, and a card is made for each tooth.
  - Per implant: company and line, diameter × length, lot, sticker photo, torque, ISQ and subcrestal.
  - GBR (block graft, donor site, particles, % autogenous), membrane and tacks, soft tissue, suture, temporary and X-ray.
- **Implant life**: placed → uncovered → impression / scan → loaded, or failed, with the dates.
  - It moves by itself from the treatment log.
  - So you always know who is **waiting for 2nd stage, scan / impression or delivery**.
- **Photo checklist**: the 8 stages of the CIA photo protocol, with photo or video upload.
  - **Log book pages**: the case photos printed in frames of a fixed size (6 or 12 on an A4 page), each named by its shot, one stage per page, with the description of the procedure written from the surgery chart and treatment log (editable before printing), and the patient's identity hidden if wanted.
  - **Readable photo folders**: on the server PC the photos are saved in `data/media/Patient photos/<file number and name>/1 Preoperative photos (1st visit)/…`, one folder per stage, each file named by its shot, teeth and date (e.g. `Implant_placed_with_cover_screw_36_29-08-2026.jpg`). Copy them from there without opening the system, or press *Download all photos (ZIP)*.
- **My patient list**: instead of filling the calendar, add the patients you want on your days with the step, the time needed, the order, and a backup list. The head of CIA approves it (and can change the time), then the reception calls and books them.
- **Complaints**: the dentist of the patient writes the answer and what will be done. If there is no answer in time, the dentist and the head of CIA are alerted.
- **Moving an appointment**: *Move to another time* keeps the old time and the reason, tells the dentist, and the reception sends the new time on WhatsApp.
- **Post-op instructions, printed with the patient's name and surgery**: the sheets that fit the surgery are chosen by themselves (general, sinus lift, bone graft, soft tissue graft), in Arabic or English.
- **Prescriptions with interchangeable drugs** (new: **injections IM / IV** — ceftriaxone, clindamycin, dexamethasone, diclofenac, ketorolac; the doctor reviews the doses in Settings): ready prescriptions (after implant, after sinus lift, after extraction, and versions for penicillin allergy) are chosen from the surgery. Each drug can be swapped for any brand of the same group, e.g. Augmentin ↔ Megamox ↔ Hibiotic. The patient's penicillin allergy is flagged. It prints with the patient's name, age and date.
- **Lab requests**: the dentist chooses the name of the supervisor who checked the request, and it goes straight to the secretary to send.
- **Case report**: the whole case on one printable page (chart, plan, surgeries, treatments), with a switch to **hide the patient's identity** for teaching or publication.
- **Word file**: the patient's whole file (data, history, chart, plans, treatments, surgeries, appointments, payments) as a Word document.
- **Dentist file**: every surgery and treatment they did, and for candidates **implants placed / required / remaining** for their course.
  - Also their batch, their payments, and all their cases, even ones they were not present for.

- **Visit page** (new): when the patient arrives the dentist gets a notification **with a sound**. The visit page leads step by step: restorative / other treatment (with or without a bill), or surgery → the suggested prescription → the post-op instructions.
- **Visits without notes** (new): a visit with nothing written in the patient's file reminds the dentist after one hour, and the supervisors after one day. A banner shows how many are waiting.
- **Bill for the procedure** (new): on the treatment form, choose the paid service; the reception sees the bill to collect.
- **Photos by session** (new): each follow-up is a session (date + teeth). A new date or other teeth start a new session, so the photos of the right side, the left side and a later follow-up do not mix; *Show all* shows everything. Steps that are not on the checklist can be added with their own name.
- **Operators** (new): any dentist can be chosen as operator while writing; after saving, changing the operator needs the head of CIA's approval. **Operator 2 works on other teeth**, not the same tooth: each tooth has its operator, and it counts for that dentist.
- **Lab requests** (new): the patient is filled in, the shade list follows the guide (**VITA classical** or **3D-Master**), and the date needed back comes from the usual days of the work type (set in Settings).
- **Implants from stock** (new): on the surgery chart choose the company, then the implant in stock: its size and **lot** are filled in and saving takes it out of stock (put back if the tooth is changed or removed).
- **Prostheses on implants** (new): single crown, **bridge** (which teeth, on which implants; the others are pontics), **full arch fixed** (All-on-X) and **overdenture**, with retention, material and stage. When delivered, the implants become loaded and the pontics show on the chart. Shown on the chart, the patient file, the implant page and the case finder.
- **Complaints** (new): each dentist sees only the complaints about him; the heads see all.

### Head of CIA
- Approves lab requests that were sent without a supervisor's name.
- Checks and **grades** the dentists' treatments, and approves treatment plans.
- Follows up complaints.

### Treatment plan finder, and patients to call (head of CIA, team head, owner)
- Find plans by case difficulty (e.g. simple or moderate), planned procedure (e.g. **every case planned for guided surgery**), status, phase, teeth, planned by, patient's gender and age, and **no upcoming appointment**.
- Export to Excel.
- **Send the patients to the reception** with one button, and a line on what to tell them. The secretaries are notified, call each patient, and **write each answer**: booked, call again, not interested, no answer or wrong number. The sender sees the answers, and is told when the list is finished.
- The case finder can send its patients the same way, e.g. everyone *waiting for 2nd stage*.

### Stock (stock manager)
- Every item under a category: dental materials, instruments, implants, anaesthesia and drugs, consumables, equipment, **food & beverage**, cleaning, stationery.
- Quantity, unit, place, **reorder level**, last price and stock value.
- Received, taken out (one item, or several at once for a room or the kitchen), damaged / expired, and stock counts. Every movement is kept with who and for whom.
- **Low stock** and **expiring soon** (within 60 days, changeable in the settings), on the home page and as notifications.
- Purchase lines can be added to a stock item, so buying fills the stock.
- **Import a list** from Excel or CSV, like your *Dental_Material_and_Instrument* list (it is already loaded in the practice copy).

### Case finder & statistics (owner and head of CIA)
- Filter every documented implant or surgical site by:
  - the patient: gender, age, smoker, diabetic, medical conditions, governorate, referral source
  - the team: dentist in any role, operator 1, dentist type, batch, instructor
  - the surgery: difficulty, bone particle, block graft and donor, membrane, soft tissue graft, temporary, suture
  - the site: teeth, jaw, anterior / posterior, tooth type, procedures (any of / all of)
  - the implant: company, line, diameter, length, torque, subcrestal, status
  - the surgery date
- **Statistics grouped by any one or two of these**:
  - number of implants, sites and patients
  - failures and **survival %**
  - loaded, and mean **days to loading**
  - mean torque
- **Export to Excel (CSV)**, one row per implant with every detail, for publications.
- Quick searches, e.g. *healing – waiting 2nd stage* or *impression taken – waiting delivery*. You can also save your own searches.
- **Totals** (new): patients, surgeries and cases (sites), and a table **by procedure** with the cases, surgeries and patients of each one (one patient can have an open sinus and a simple implant, or two simple sites). Click a procedure or an implant status to filter by it.
- **Prostheses** (new): filter by prosthesis (single crown, bridge, full arch, none yet), group by it, and see how many units sit on the implants found.

### Owner: reports
- **Visits and timing**: who came late and by how much, waiting time, time in the chair, total stay, and no-shows, per dentist and per room.
- **Dentist follow-up**:
  - surgeries and implants, the **implants remaining** in each candidate's course, and failures
  - treatments by type, the share checked by a supervisor, and the average grade
  - lab requests and remakes, active patients and complaints
  - scheduled hours versus chair hours
  - filters by dentist type and batch
- **Lab**: turnaround days per lab, remakes, and late work.
- **Patients**: call list conversion, referral sources, the patients who referred others most, and complaint categories.
- **Money** (owner only): installments collected and outstanding, and purchases by category, supplier, and dental vs non-dental.
- **Balance sheet** (new, owner only): income and costs of the academy, the private clinic and CIC side by side: patient and course payments, cash taken for bills paid on the Fawry machine, Fawry's percentage and charges, bills paid through the machine, purchases, and the net. Also how the money came in (cash, Fawry, InstaPay…), what Fawry still holds, and what patients, candidates and suppliers still owe.
- The head of the CIA dentists team sees only the **dentist follow-up** of the CIA dentists.

### Settings: change the system without changing the program (owner)
User menu → **Settings**.
- **Lists** (the owner and the head of CIA) including paid services and prices, reasons for a patient being out, and a simple Arabic explanation for each treatment:
  - implant companies and types
  - treatments (with what each one does to the dental chart)
  - the photo checklist
  - drug groups (interchangeable brands), ready prescriptions and post-op instruction sheets
  - rooms, labs and lab work types
  - how patients heard about us, and medical conditions
  - purchase and stock categories
  - the WhatsApp message texts

  Nothing is deleted, because old records use it: untick *active* to stop using an item.
- **Dentists**: CIA dentists, training dentists and supervisors are added in *Academy → Dentists*, and candidates in *Academy → Candidates*.
- **Clinic options**: the name, phone and address printed on prescriptions and post-op instructions, and used in the WhatsApp messages. Also when a patient counts as late, the usual appointment length, complaint follow-up days, stock expiry warning, how many days before to send reminders, and the country code for WhatsApp.
- **People and logins**: create logins and choose each person's roles. For each person you can also set:
  - **read only everywhere**: they can open their pages but cannot save anything
  - **access starts on / ends on**, e.g. the end of a course or a contract
  - **days allowed**, e.g. Saturday to Thursday
  - **from hour / to hour**, e.g. 9:00 to 21:00

  Outside these times the login is refused. Anyone already logged in is logged out on their next click.
- **Parts of the system for one person**: on a person's page, choose for each part "as the role", normal, read only or no access, e.g. only some secretaries work with the academy.
- **Clinic options**: appointment hours (9 to 5), the usual length (30 minutes), the usual surgery days, the e-mail for CBCT files, and **Fawry's percentage** on card payments.
- **Lists** (new): the **usual days at the lab** for each lab work type, which paid services get a **quick button** on a new bill, and implants in stock (company, diameter and length on the stock item).
- **Backup and export** (new, owner): one button makes a **full backup** (a ZIP with all records to put back into the system, the same data as **Excel** and **CSV** to open in any other program, and all uploaded files). *Download the Excel file* gives every table on its own sheet. Keep a copy outside the clinic, and always before a big change to the system. See [Backups](docs/deployment.md#backups-please-read).
- **Problem reports** (new, owner and head of CIA): what the staff reported, and pages that stopped with an error (recorded automatically), with a download to send to whoever maintains the system.
- **Access by role**: make one part of the system (patients, schedule, charts, surgeries, stock, reports…) **read only** or **closed** for a role.
  - It can only take access away, never give more than the role normally has.
  - When a person has two roles and either is limited in a part, the person is limited there.
  - The owner is never limited, so the owner cannot be locked out.

Uploaded files (ID scans, invoices) are **never public**. They open only for logged-in staff with the right role.
Only the roles that see patients can open patient documents and photos.

---

## How to test it now (trial on any PC)

This makes a **practice copy on your PC** with sample data (now also bills, the waiting list, the Fawry machine, implants in stock by lot, prostheses, a late patient, a visit without notes and two dentists in one room): patients, visits, lab work and installments, plus dentists of every type, dental charts, treatment plans, 14 implant surgeries with implants at every stage, the stock list, a prescription, a list of patients to call, and next week's appointments waiting for their WhatsApp reminders. Nothing you do there touches real data, and nothing goes to the cloud.

**Windows**
1. Install **Python 3.12 or newer** from https://www.python.org/downloads/. On the first installer screen, tick **"Add python.exe to PATH"**.
2. Download this project:
   1. On GitHub, open the branch `claude/cairo-implant-academy-system-jqrd1f`.
   2. Click **Code → Download ZIP**.
   3. Unzip it, e.g. to `C:\CIA-trial`.
3. Double-click **`trial-windows.bat`**. The first run takes a few minutes while it installs. The browser then opens at http://localhost:8000.
   - Other PCs or tablets on the same Wi-Fi can open the address the window prints, e.g. `http://192.168.1.20:8000`. Allow Python in the Windows Firewall when asked.
4. Log in with one of these users. The password is `demo12345` for all of them.

   | User | Who | Language |
   |---|---|---|
   | `owner` | owner / CEO | English |
   | `headcia` | head of CIA | English |
   | `teamhead` | head of the CIA dentists team (also a CIA dentist) | English |
   | `dentist1`, `dentist2` | CIA dentists | English |
   | `secretary` | secretary | Arabic |
   | `secretary2` | a second secretary who does not work with the academy | Arabic |
   | `stock` | stock manager | Arabic |

   The 4 course candidates (batch IMP-2026-A), the training dentist and the supervisors have no login, as agreed.

5. Follow the checklists step by step:
   - **[docs/secretary-test-checklist.md](docs/secretary-test-checklist.md)** for the secretary
   - **[docs/dentist-test-checklist.md](docs/dentist-test-checklist.md)** for the CIA dentists, the heads and the owner, including the settings
   - **[docs/stock-test-checklist.md](docs/stock-test-checklist.md)** for the stock manager

To stop, close the black window. To start again, double-click `trial-windows.bat`. Your practice data is kept.
To start over with fresh sample data, delete the `data` folder and run it again.

> **Already tried an earlier version?** Your practice data is kept and converted, and nothing is lost. Interns become dentists: those linked to a course candidate stay linked, and the others become training dentists. The new sample dentists, charts and surgeries are only added to an **empty** practice database, though. To see them, delete the `data` folder and run the trial again.

**Mac / Linux:** run `sh trial-mac-linux.sh` in the project folder, then open http://localhost:8000.

## Tablets in the clinic

The system works in the browser of a tablet on the clinic Wi-Fi, with nothing to install: open the server's address (e.g. `http://192.168.1.20:8000`) and add it to the home screen. It was checked at tablet sizes (1024 and 768 pixels wide): nothing needs sideways scrolling, and wide tables scroll inside their box.

Suggestion, when you decide to buy:
- An **11-inch tablet used in landscape**: e.g. Samsung Galaxy Tab S9 FE / A9+ (Android) or an iPad 10th generation / iPad Air 11". Landscape gives the full-width forms and the tooth chart.
- A **wall or desk holder** in each room (a swivel arm or a stand), and a **cover with a stylus** makes writing on the tooth chart easier with gloves off.
- Keep the tablets on the **clinic Wi-Fi** only (the server is not on the internet). Each dentist logs in with his own user; logins end at the time limits set in Settings.

## Installing on the clinic server

See **[docs/deployment.md](docs/deployment.md)** for these topics:
- Docker (recommended)
- Windows without Docker
- Backups and restore
- The first setup: users, roles, rooms and lists

## Daily use guide for the secretaries (Arabic)

**[docs/secretary-guide-ar.md](docs/secretary-guide-ar.md)**

---

## For developers

- Python 3.11+, Django 5.2 LTS, PostgreSQL 16 (SQLite for trials). The pages are server-rendered with Bootstrap 5 RTL, and there is no JavaScript build step.
- Apps:
  - `core`: branches, roles, notifications, per-user language
  - `patients`
  - `dentists`: every type of dentist, and their file
  - `scheduling`
  - `clinical`: treatment log and lab workflow
  - `charting`: examination, odontogram, chart rules, plans, photos, case report
  - `surgery`: surgery chart, implant life, case finder
  - `prescriptions`: drug groups, ready prescriptions, post-op instruction sheets
  - `stock`: stock items, movements, low stock, import
  - `complaints`, `academy`, `purchasing`, `reports`
- Run the tests: `DJANGO_DEBUG=1 python manage.py test apps`
- Backups: `python manage.py backup` (full ZIP into `BACKUP_DIR`, default `data/backups`), `python manage.py restore_backup <zip>`,
  and `python manage.py organize_photos` (moves photos saved by older versions into the readable folders).
- Translations: write English in the code and templates, then run:
  ```bash
  python manage.py makemessages -l ar --ignore=.venv --no-location
  # edit locale/ar/LC_MESSAGES/django.po
  python manage.py compilemessages -l ar --ignore=.venv
  ```
  The compiled `.mo` file is committed, so the server does not need gettext.
- Business rules you can change in `.env`:
  - the late threshold (10 minutes)
  - the default appointment length
  - the complaint follow-up period
