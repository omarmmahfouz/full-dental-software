# Dental Group System — Cairo Implant Academy (phase 1)

One system for the owner's three connected places:

| Branch | Code | Status |
|---|---|---|
| **Cairo Implant Academy** — teaching institute, economic dental service, course candidates, interns | `CIA` | **Phase 1 (this release)** |
| Private clinic — specialists and freelance doctors | `PVT` | planned (data model ready) |
| Dental lab — serves both clinics and outside clinics | `LAB` | planned (lab requests already flow to it) |

It runs **on the clinic's own server**, with no cloud. Staff open it in a browser on the clinic network.
Everything works offline, including fonts, icons and styles.
The interface is **Arabic (right-to-left) by default**. Anyone can switch to English from the user menu.

---

## What phase 1 does

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
  - The **responsible intern**.
- **No duplicates**:
  - The national ID and the **primary mobile** are unique.
  - A mobile is recognised however it is typed (`+20 100…`, `0100…`, Arabic digits `٠١٠٠…`).
  - The error message names the existing file.
  - Every patient gets a unique file number (`CIA-00001`).
- **Room schedule**:
  - A weekly grid of the **5 rooms**, showing which intern works in which room and when.
  - It blocks double-booking of a room or an intern.
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

### Interns
- The intern sees their own patients, schedule and appointments.
- They record every **treatment step** (teeth, implant system and size, notes).
- They create lab requests and send them for supervisor review.

### Supervisors
- Review and approve lab requests before they go to the lab.
- Check and **grade** each intern's steps.
- Follow up complaints.

### Owner: reports
- **Visits and timing**: who came late and by how much, waiting time, time in the chair, total stay, and no-shows, per intern and per room.
- **Intern follow-up**: steps by type, the share of steps checked by a supervisor, average grade, lab requests and remakes, active patients, complaints, scheduled hours versus chair hours.
- **Lab**: turnaround days per lab, remakes, and late work.
- **Patients**: call list conversion, referral sources, the patients who referred others most, and complaint categories.
- **Money** (owner only): installments collected and outstanding, and purchases by category, supplier, and dental vs non-dental.

### Roles

| Role (group) | Can use |
|---|---|
| `secretary` | reception board, call list, patients, schedule, lab send/receive, complaints, academy, purchases |
| `intern` | own patients, room schedule, own appointments, treatment steps, lab requests |
| `supervisor` | everything clinical + review lab requests + check steps + complaints + reports (not money/purchases) |
| `owner` | everything, including money reports and the settings screens |

Uploaded files (ID scans, invoices) are **never public**. They open only for logged-in staff with the right role.
An intern can open only their own patients' documents.

---

## Quick trial on one PC (5 minutes)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # set DJANGO_DEBUG=1 and DB_ENGINE=sqlite for a trial
python manage.py migrate
python manage.py load_demo_data --password demo12345   # sample data, trial only
python manage.py runserver 0.0.0.0:8000
```

Open http://localhost:8000 and log in as `secretary`, `intern1`, `supervisor` or `owner` (password `demo12345`).

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
- Apps: `core` (branches, roles, notifications), `patients`, `scheduling`, `clinical` (steps and lab workflow), `complaints`, `academy`, `purchasing`, `reports`.
- Run the tests: `DJANGO_DEBUG=1 python manage.py test apps`
- Translations: write English in the code and templates, then run:
  ```bash
  python manage.py makemessages -l ar --ignore=.venv --no-location
  # edit locale/ar/LC_MESSAGES/django.po
  python manage.py compilemessages -l ar
  ```
  The compiled `.mo` file is committed, so the server does not need gettext.
- Business rules you can change in `.env`:
  - the late threshold (10 minutes)
  - the default appointment length
  - the complaint follow-up period
