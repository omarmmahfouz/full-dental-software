# Dental Group System — Cairo Implant Academy

One system for the owner's three connected places:

| Branch | Code | Status |
|---|---|---|
| **Cairo Implant Academy** — teaching institute, economic dental service, course candidates, dentists | `CIA` | **In use: secretary + dentists** |
| Private clinic — specialists and freelance doctors | `PVT` | planned (data model ready) |
| Dental lab — serves both clinics and outside clinics | `LAB` | planned (lab requests already flow to it) |

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
| CIA dentists (full or part time) | `dentist` | every patient, the complaints (read only), **only their own schedule**, and their cases. They record the clinical work: their own, and the course candidates' work, choosing the candidate's and the supervisor's names. In surgery they are usually the **assistant** |
| Secretary (reception) | `secretary` | reception, patients, schedule, **WhatsApp messages**, lab send / receive, complaints, academy, purchases, and the **patients to call** lists |
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
  - A down payment plus a monthly installment plan.
  - Each payment records the **payment method**: cash, card, InstaPay, mobile wallet, bank transfer or cheque, with the transaction reference.
  - Printable receipts, and an overdue installments list.
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
- **Dental chart (digital version of the CIA paper chart)**:
  - A professional odontogram with 5 surfaces per tooth: caries, fillings, root canals, crowns, implants (healing or loaded), missing teeth, root remnants, mobility and hopeless teeth.
  - **Examination & history**: every field of the paper chart. This covers the chief complaint, the teeth lists, CBCT, blood pressure, glucose, HbA1c, allergies, drugs, the dental history and the scores.
  - A new examination starts from the last one, so only what changed needs typing.
- **Treatment log, with the chart following the treatment**:
  - The dentist writes the tooth numbers and the treatment, e.g. `12` + *Composite restoration* + `MO`.
  - Before saving, the screen shows how the chart will change: *12: caries MO → filled composite (MO)*. The dentist confirms with a tick box.
  - Other examples: *46 Implant failure* → 46 becomes **missing**, and the implant is marked **failed**. *36 Extraction* → missing. *Second stage / impression / delivery* → the implant moves to its next stage.
  - Every change is kept in the tooth's history.
- **Treatment log form**: the treatment is chosen from a list, with a **notes** box right under it.
- **Treatment plans**: phases (urgent, preparation, surgical, prosthetic, maintenance), and the **case difficulty** (simple, moderate, advanced). The dentist picks the name of the supervisor who approved it.
  - Planned teeth show in blue on the chart.
  - Items are ticked **automatically** when the same treatment is recorded on the same teeth.
- **Implant surgery chart**: the CIA surgery chart, field by field:
  - The team: instructor, operator 1, operator 2 and assistant.
  - The case difficulty.
  - Per tooth: extraction, flap, simple / immediate / guided implant, expansion, splitting, closed / open sinus and GBR.
  - Per implant: company and line, diameter × length, lot, sticker photo, torque, ISQ and subcrestal.
  - GBR (block graft, donor site, particles, % autogenous), membrane and tacks, soft tissue, suture, temporary and X-ray.
- **Implant life**: placed → uncovered → impression / scan → loaded, or failed, with the dates.
  - It moves by itself from the treatment log.
  - So you always know who is **waiting for 2nd stage, scan / impression or delivery**.
- **Photo checklist**: the 8 stages of the CIA photo protocol, with photo or video upload.
- **Post-op instructions, printed with the patient's name and surgery**: the sheets that fit the surgery are chosen by themselves (general, sinus lift, bone graft, soft tissue graft), in Arabic or English.
- **Prescriptions with interchangeable drugs**: ready prescriptions (after implant, after sinus lift, after extraction, and versions for penicillin allergy) are chosen from the surgery. Each drug can be swapped for any brand of the same group, e.g. Augmentin ↔ Megamox ↔ Hibiotic. The patient's penicillin allergy is flagged. It prints with the patient's name, age and date.
- **Lab requests**: the dentist chooses the name of the supervisor who checked the request, and it goes straight to the secretary to send.
- **Case report**: the whole case on one printable page (chart, plan, surgeries, treatments), with a switch to **hide the patient's identity** for teaching or publication.
- **Dentist file**: every surgery and treatment they did, and for candidates **implants placed / required / remaining** for their course.
  - Also their batch, their payments, and all their cases, even ones they were not present for.

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
- The head of the CIA dentists team sees only the **dentist follow-up** of the CIA dentists.

### Settings: change the system without changing the program (owner)
User menu → **Settings**.
- **Lists** (the owner and the head of CIA):
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
- **Access by role**: make one part of the system (patients, schedule, charts, surgeries, stock, reports…) **read only** or **closed** for a role.
  - It can only take access away, never give more than the role normally has.
  - When a person has two roles and either is limited in a part, the person is limited there.
  - The owner is never limited, so the owner cannot be locked out.

Uploaded files (ID scans, invoices) are **never public**. They open only for logged-in staff with the right role.
Only the roles that see patients can open patient documents and photos.

---

## How to test it now (trial on any PC)

This makes a **practice copy on your PC** with sample data: patients, visits, lab work and installments, plus dentists of every type, dental charts, treatment plans, 14 implant surgeries with implants at every stage, the stock list, a prescription, a list of patients to call, and next week's appointments waiting for their WhatsApp reminders. Nothing you do there touches real data, and nothing goes to the cloud.

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
