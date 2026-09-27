# Notes for Claude: the CIA dental system

Read this first, then `README.md` (what the system does, role by role) and the checklists in `docs/`.

## The project and how the owner works
- A Django system for the **Cairo Implant Academy (CIA)** and **CIC, the Cairo Implant Center** (a private economical
  clinic, mainly implants, whose many doctors are paid by percentage or fixed amounts). The dental lab (`LAB`) and
  El Khadem dental clinic (likely the `PVT` branch; confirm with the owner) come next; their branches already exist.
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
  - Tablets: under 1200 px each role gets a bottom bar (`apps/core/navigation.py`) and the menu slides in from the side.
    Keep pages usable by touch at 768–1024 px, with no sideways scrolling.

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
- `moderator` is the clinic manager: doctors' fee rules, shares, payouts and the clinic report (`CLINIC_MANAGERS` = owner + moderator).
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
  - `clinics`: `FeeRule` (percent of what was paid / fixed per unit / fixed per visit, per doctor and place),
    `DoctorPayout`, `shares.py` (statement, owed, summary), the clinic report
- **Places** (CIA, CIC...): `branch_for_user(user)` is the place worked in now (session "place", set by the top-bar switch
  through `WorkingPlaceMiddleware`); `working_places(user)` = the owner's all, else `profile.places` + `profile.branch`.
  - Bills, charges (with `dentist`), patient payments, appointments, rooms, room shifts and stock movements carry a place.
  - Patients are shared (one file); new files take the place's prefix (`CIC-…`).
  - `Dentist.places` + `Dentist.objects.working_at(place)`; `Service.branch` ("only at") + `Service.for_place(place)`;
    `StockItem.branch` = belongs to (empty = shared).
  - Two Fawry machines (`FawryMachine`): each card payment and Fawry move names its machine.
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
- The look: `static/css/app.css` opens with CSS variables (colours, lines, shadows, motion). Each app has an accent
  colour through `.sec-<namespace>` on `<body>` and on the menu entries. Page titles use `<h1><i class="bi …"></i> …</h1>`
  (the icon becomes a coloured chip). Motion must respect `prefers-reduced-motion`.
  - Do not put `transform`, `filter` or `backdrop-filter` on an element that holds pop-ups or the side menu:
    it traps `position: fixed` children (the top bar's blur sits on its `::before` for this reason).
- Page hints: `apps/core/hints.py` (keyed by `namespace:url_name`, a text per role where needed). Add one for each new
  main page, in plain words, and translate it. Each person can switch hints off (user menu, `UserProfile.show_hints`).
- Links: show a link only when the reader can open it (e.g. `user|opens_dentist:dentist`, `hidden_areas`, `is_clinical`).
- The JavaScript is in `static/js/app.js`, with no build step. Its hooks:
  - `data-formset` / `data-formset-add`
  - `data-teeth-picker="multi|single"`
  - `data-confirm`
  - `data-tip="…"` (a tooltip with a mouse), `data-show-password="#id"`, `data-no-progress` (a form that opens a download)
  - Automatic: table rows with one link open from anywhere; the last row of buttons of a long POST form stays in view.
- The **unsaved-changes warning** watches POST forms:
  - Opt a form out with `data-no-leave-warning`.
  - Wrap links that the page handles itself (e.g. the booking day grid) in `data-in-page-links`.
- Tooth chart:
  - `charting/rules.py` has `plan_changes` and `apply_changes` (every change is kept in the tooth's history).
  - Implant stages move forward only, through `SurgerySite.advance`.
  - `SurgerySite.objects.done_by(dentist)` counts the per-tooth operator.
- `setup_clinic` (lists, rooms, branches) can be run many times. `load_demo_data` works on an **empty** database only.
- **Speed with a lot of data** (10,000 patients must stay quick):
  - Never call `account(patient)` in a loop: use `paid_by_charge`, `balances`, `patients_owe`, `bill_totals`
    (`billing/models.py`) and `clinics.shares.totals` (the quick `statement`). Read lists with `values_list` when
    only numbers are needed.
  - `ClinicSettings.get()` is kept for one page (`PageCacheMiddleware`); the home page's alert checks run at most
    every 3 minutes.
  - `SpeedTests` (`apps/core/tests.py`) fills 1,500 patients (`apps/core/bigdata.py`) and gives each page a budget of
    database look-ups: add new main pages to it. `fill_big_data` adds 10,000 patients to a test copy.
  - Pictures: show `{{ file|preview }}` (small, 480 px) or `|preview:"medium"` (1600 px) with `loading="lazy"`, never
    the original in a grid (`apps/core/previews.py`). Files are sent by `core.views.send_file` (ETag; X-Accel-Redirect
    with `MEDIA_SENDFILE=nginx`).
  - Long lists get pages (`Paginator`, `includes/pagination.html`); keep totals for the whole period.
- **Backups**: `backup` = the data ZIP (no photos) + `copy_files` (new files only, to `FILES_BACKUP_DIR`, never deletes);
  each run is a `BackupRun`, shown in Settings → Backup and on the owner's home page. Logs are in `LOG_DIR`
  (`errors.log`, `slow-pages.log`). `make_test_copy` makes a test copy (`TEST_COPY=1` banner).

## Commands
- Tests (about 4 minutes). GitHub runs `manage.py test apps` on every push (`.github/workflows/tests.yml`); that finds
  every `apps/*/tests.py` but loads them as top-level modules (`apps/` has no `__init__.py`), so **test files must
  import with `apps.…`, never relative (`from .models`)**, or GitHub fails with "isn't in INSTALLED_APPS".
  Run `DJANGO_DEBUG=1 .venv/bin/python manage.py test apps --parallel 4` before pushing, or list the modules:
  ```bash
  DJANGO_DEBUG=1 .venv/bin/python manage.py test apps.academy.tests apps.billing.tests apps.charting.tests \
    apps.clinical.tests apps.complaints.tests apps.core.tests apps.dentists.tests apps.patients.tests \
    apps.prescriptions.tests apps.purchasing.tests apps.reports.tests apps.scheduling.tests apps.stock.tests \
    apps.surgery.tests apps.clinics.tests
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
- Logins (password `demo12345`): owner, headcia, teamhead, dentist1, dentist2 (also at CIC), secretary (CIA and CIC),
  secretary2 (no academy), stock, moderator (CIC manager), cicdoctor (a CIC doctor).
- CIC's steps are in `docs/cic-test-checklist.md`.
- Known limits to state honestly:
  - Fawry is a ledger typed by the reception; there is no link to the machine itself.
  - WhatsApp opens one message per click; there is no automatic sending.
  - The alert sound needs one click on the page first.
  - The ID card photo is cropped, but its text is not read.
  - The drug doses need a doctor's review in Settings.
  - There is no freehand pen drawing or on-screen signature yet.
  - A doctor's percentage is taken of what the patient has paid so far, counted on the date the service was given;
    nothing is taken off first (e.g. lab or implant cost) unless the owner asks for it.
  - CIC has no logo of its own yet: its bills print its name, phone and address.
  - Speeds were measured on a test copy with made-up data on an ordinary PC, with SQLite; the real server with
    PostgreSQL should be similar or faster. Photo download times depend on the Wi-Fi.
  - A CBCT is kept as a folder or link: the system does not open DICOM files. The test copy has no photos.
