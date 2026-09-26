# Notes for Claude: the CIA dental system

Read this first, then `README.md` (what the system does, role by role) and the checklists in `docs/`.

## The project and how the owner works
- A Django system for the **Cairo Implant Academy (CIA)**. The private clinic (`PVT`), the dental lab (`LAB`) and
  **CIC** (a future economical clinic) come later; their branches already exist.
- It runs **on the clinic's own server or PC**, with no cloud. Fonts, icons and scripts are in `static/vendor`, so it works offline.
- The owner sends **numbered lists of changes** ("rounds"). For each round:
  1. Build every point.
  2. Add tests.
  3. Add the Arabic translations.
  4. Add demo data for each new feature.
  5. Update `README.md` and the checklists: mark new features `(new)`, remove the old markers, and add a numbered
     "New in this version" section to each checklist.
  6. Commit and push.
  7. End with a plain-English report:
     - explain every point of the list;
     - say how to test (below);
     - be honest about limits.
- The owner writes quick English with typos. Answer in plain English, and ask only when truly blocked.
- Decisions already taken:
  - Supervisors, course candidates and training dentists **do not log in**; they are chosen by name.
  - Tablets: no changes for now, but keep pages usable by touch at 768–1024 px.

## Where to work
- Branch **`claude/cairo-implant-academy-system-jqrd1f`** has all the work. Develop, commit and push there.
- Open a pull request only if asked.
- End commit messages with the attribution lines the session gives you. Never put model names in commits or code.
- Never commit patient data: `data/`, `.env` and `*.sqlite3` are ignored.

## Language
- Each person has their own language:
  - Secretaries and the stock manager get **Arabic (right to left)**.
  - Dentists, the heads and the owner get **English**.
- Messages to patients (WhatsApp, printed instructions) are **Arabic**.
- Write English in the code and templates (`gettext` / `{% trans %}`), then translate:
  ```bash
  DJANGO_DEBUG=1 .venv/bin/python manage.py makemessages -l ar --ignore=.venv --ignore=staticfiles
  # fill every untranslated / fuzzy entry in locale/ar/LC_MESSAGES/django.po (polib works well)
  DJANGO_DEBUG=1 .venv/bin/python manage.py compilemessages -l ar
  ```
- Keep the `.po` 100% translated with no fuzzy entries.
  - Arabic has **6 plural forms**.
  - Keep `%(name)s`, `%%` and `{}` placeholders as they are.
  - Commit the compiled `.mo`.
- Use simple Arabic words for the secretary; `docs/secretary-guide-ar.md` is in Egyptian Arabic.

## Roles (`apps/core/roles.py`)
- `owner` sees everything, including the money reports and all settings.
- `head_cia` sees everything except money and logins.
- `team_head` is a CIA dentist who also sees the dentists' follow-up report.
- `dentist` is a CIA dentist. `is_only_dentist(user)` means he sees only his own schedule, work and complaints.
- `secretary` does the reception work (front desk).
- `supervisor` is kept for later.
- `stock` is the stock manager.
- Groups used in views: `FRONT_DESK`, `MANAGEMENT`, `CLINICAL`, `DENTISTS`, `PATIENT_VIEWERS`.

## Code map and conventions
- Apps are in `apps/`:
  - `core`: settings, notifications, approvals, backups
  - `patients`
  - `dentists`
  - `scheduling`: board, day grid, free times, waiting list, WhatsApp
  - `clinical`: treatment log, lab cycle, visit notes
  - `charting`: examination, tooth chart rules, plans, photos
  - `surgery`: surgery chart, implants, prostheses, case finder
  - `prescriptions`
  - `billing`: services, charges, bills, payments, **Fawry ledger** in `billing/fawry.py`
  - `stock`: every change goes through `stock.services.record_movement`; implants by lot are in `stock/implants.py`
  - `complaints`, `academy`, `purchasing`, `reports` (money and balance sheet are owner-only)
- **Approvals** (`apps/core/approvals.py`: `needs_approval`, `request_change`) go to the head of CIA or the owner.
  They cover:
  - patient data edited by the reception;
  - corrected visit times;
  - an operator changed after saving.
- **Notifications** use `apps/core/notify.py` (`notify_users`, `notify_roles`) with `gettext_lazy` text and
  `params`, so each person reads them in their own language. The page polls for new ones every 30 s and plays a sound.
- Forms:
  - Use `StyledForm` / `StyledModelForm`, with `fieldsets` and `field.col`.
  - Dates are **dd/mm/yyyy** (flatpickr), and times are in 15-minute steps.
  - Patients are chosen with `PatientLookupField`; `lookup_value(patient)` gives `"FILE — name"`.
- The JavaScript is in `static/js/app.js`, with no build step. Its hooks:
  - `data-formset` / `data-formset-add`
  - `data-teeth-picker="multi|single"`
  - `data-confirm`
- The **unsaved-changes warning** watches POST forms:
  - Opt a form out with `data-no-leave-warning`.
  - Wrap links that the page handles itself (e.g. the booking day grid) in `data-in-page-links`.
- Tooth chart:
  - `charting/rules.py` has `plan_changes` and `apply_changes` (every change is kept in the tooth's history).
  - Implant stages move forward only, through `SurgerySite.advance`.
  - `SurgerySite.objects.done_by(dentist)` counts the per-tooth operator.
- `setup_clinic` (lists, rooms, branches) can be run many times. `load_demo_data` works on an **empty** database only.

## Commands
- Tests (about 4 minutes; the bare label `apps` does not find the tests, so list the modules):
  ```bash
  DJANGO_DEBUG=1 .venv/bin/python manage.py test apps.academy.tests apps.billing.tests apps.charting.tests \
    apps.clinical.tests apps.complaints.tests apps.core.tests apps.dentists.tests apps.patients.tests \
    apps.prescriptions.tests apps.purchasing.tests apps.reports.tests apps.scheduling.tests apps.stock.tests \
    apps.surgery.tests
  ```
- A throw-away demo copy. Keep it outside the repo, e.g. in a scratch folder:
  ```bash
  export SQLITE_PATH=/tmp/x/demo.sqlite3 MEDIA_ROOT=/tmp/x/uploads BACKUP_DIR=/tmp/x/backups DJANGO_DEBUG=1
  .venv/bin/python manage.py migrate && .venv/bin/python manage.py load_demo_data --password demo12345
  .venv/bin/python manage.py runserver 127.0.0.1:8000 --noreload   # restart after code or template changes
  ```
- Stop the server with ``kill $(pgrep -f "[m]anage.py runserver")``. A plain `pkill -f "manage.py ..."` also matches
  and kills your own shell.
- Before pushing:
  - Open every page as every role, in Arabic and English, and look for errors.
  - Take screenshots at 1400, 1024 and 768 px, and check nothing scrolls sideways.
  - Run `python -m pyflakes apps`.

## Testing notes for the owner's report
- To get the new sample data: delete the `data` folder, then run `trial-windows.bat` (or `sh trial-mac-linux.sh`).
- Logins (password `demo12345`): owner, headcia, teamhead, dentist1, dentist2, secretary, secretary2 (no academy), stock.
- Known limits to state honestly:
  - Fawry is a ledger typed by the reception; there is no link to the machine itself.
  - WhatsApp opens one message per click; there is no automatic sending.
  - The alert sound needs one click on the page first.
  - The ID card photo is cropped, but its text is not read.
  - The drug doses need a doctor's review in Settings.
  - There is no freehand pen drawing or on-screen signature yet.
