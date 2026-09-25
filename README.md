# Dental Group System — Cairo Implant Academy

One system for the owner's three connected places:

| Branch | Code | Status |
|---|---|---|
| **Cairo Implant Academy** — teaching institute, economic dental service, course candidates, dentists | `CIA` | **In use: secretary + dentists** |
| Private clinic — specialists and freelance doctors | `PVT` | planned (data model ready) |
| Dental lab — serves both clinics and outside clinics | `LAB` | planned (lab requests already flow to it) |

It runs **on the clinic's own server**, with no cloud. Staff open it in a browser on the clinic network.
Everything works offline, including fonts, icons and styles.
The language follows the person, not the PC:
- Secretaries get **Arabic (right to left)**.
- Dentists, supervisors and the owner get **English**.
- Anyone can switch from the user menu, and the system remembers their choice. One person switching does not change it for the others on a shared PC.

---

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
| Full-time dentist | staff dentist |
| Supervisor | supervises regular days and surgery days |
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
- **Treatment plans**: phases (urgent, preparation, surgical, prosthetic, maintenance), approved by a supervisor.
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
- **Case report**: the whole case on one printable page (chart, plan, surgeries, treatments), with a switch to **hide the patient's identity** for teaching or publication.
- **Dentist file**: every surgery and treatment they did, and for candidates **implants placed / required / remaining** for their course.
  - Also their batch, their payments, and all their cases, even ones they were not present for.

### Supervisors
- Review and approve lab requests before they go to the lab.
- Check and **grade** each dentist's treatments, and approve treatment plans.
- Follow up complaints.

### Case finder & statistics (owner and supervisors)
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

### Roles

| Role (group) | Can use |
|---|---|
| `secretary` | reception board, call list, patients, schedule, lab send/receive, complaints, academy, purchases |
| `dentist` | own patients (assigned, booked, treated or operated on), their dental charts, treatment log, surgery charts, plans, photos, own lab requests, room schedule, their own dentist file |
| `supervisor` | everything clinical + review lab requests + check treatments + approve plans + complaints + case finder + reports (not money/purchases) |
| `owner` | everything, including money reports and the settings screens |

Uploaded files (ID scans, invoices) are **never public**. They open only for logged-in staff with the right role.
A dentist can open only their own patients' documents and photos.

---

## How to test it now (trial on any PC)

This makes a **practice copy** with sample data: patients, visits, lab work and installments, plus dentists of every type, dental charts, treatment plans and 14 implant surgeries with implants at every stage. Nothing you do there touches real data.

**Windows**
1. Install **Python 3.12 or newer** from https://www.python.org/downloads/. On the first installer screen, tick **"Add python.exe to PATH"**.
2. Download this project:
   1. On GitHub, open the branch `claude/cairo-implant-academy-system-jqrd1f`.
   2. Click **Code → Download ZIP**.
   3. Unzip it, e.g. to `C:\CIA-trial`.
3. Double-click **`trial-windows.bat`**. The first run takes a few minutes while it installs. The browser then opens at http://localhost:8000.
   - Other PCs or tablets on the same Wi-Fi can open the address the window prints, e.g. `http://192.168.1.20:8000`. Allow Python in the Windows Firewall when asked.
4. Log in with one of these users. The password is `demo12345` for all of them.

   | User | Role | Language |
   |---|---|---|
   | `secretary` | secretary | Arabic |
   | `dentist1` … `dentist4` | dentists: course candidates of batch IMP-2026-A | English |
   | `dentist5` | training dentist | English |
   | `dentist6` | full-time dentist | English |
   | `supervisor` | supervisor | English |
   | `owner` | owner | English |

5. Follow the checklists step by step:
   - **[docs/secretary-test-checklist.md](docs/secretary-test-checklist.md)** for the secretary
   - **[docs/dentist-test-checklist.md](docs/dentist-test-checklist.md)** for dentists, supervisors and the owner

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
