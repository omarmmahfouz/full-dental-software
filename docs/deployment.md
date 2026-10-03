# Installing on the clinic server (on-premise)

The system runs on **one computer in the clinic**, called the server. Every other PC, laptop or tablet on the clinic network opens it in a browser at `http://<server-ip>/`.
No internet or cloud is needed.

**Server recommendations**
- A PC that stays on during working hours, with a **fixed LAN IP**, for example `192.168.1.10`. Set it on the router with a DHCP reservation.
- **A UPS** (backup power). Power cuts are the most common way a database gets damaged.
- For a trial or a small start: 8 GB RAM and an SSD are plenty.
- For **10,000 patients, 1–3 TB of photos and X-rays, and 30–50 staff working at once** (see [Many photos and many users](#many-photos-and-many-users)):

  | Part | What to buy |
  |---|---|
  | Processor and memory | 4–8 cores, 16 GB RAM (32 GB is better) |
  | System and database | 2 SSDs of 500 GB–1 TB that copy each other (RAID 1) |
  | Photos and X-rays | 2 hard disks of 4 TB that copy each other (RAID 1), or a NAS. Room for 3–4 years |
  | Backup | An external disk of 8 TB for the nightly copy, and a second one swapped every week and kept outside the clinic |
  | Network | Wired gigabit to the server and the reception PCs; good Wi-Fi 6 access points for the tablets |
- Use **PostgreSQL** for real work (the trial's SQLite file is for one PC).

---

## Option A — Docker (recommended: Linux, or Windows with Docker Desktop)

```bash
git clone <this repository> dental && cd dental
cp .env.example .env
nano .env        # set DJANGO_SECRET_KEY, DB_PASSWORD, the server IP in ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS
docker compose up -d --build
docker compose exec web python manage.py createsuperuser     # the owner account
```

That starts these services:

| Service | What it does |
|---|---|
| `db` | PostgreSQL. The data lives in `./data/postgres` |
| `nginx` | The front door on port **80**. It sends the photos and files itself, after the system has checked who may open them, and compresses the pages for the tablets |
| `web` | The system itself (4 workers × 4 threads: 16 pages at the same time; change with `WEB_WORKERS` and `WEB_THREADS` in `.env`). Uploads go to `./data/media`, the error and slow-page logs to `./logs` |
| `reminders` | Creates the daily reminders at 07:00: overdue complaints and late lab work. The reminders for visits without notes (the dentist after 1 hour, the supervisors after 1 day) are also checked when someone opens the home page |
| `nightly` | At 2 am: the ZIP of all the data into `./backups`, the copy of the new photos to `FILES_BACKUP_HOST_DIR`, and the previews of new photos |
| `backup` | PostgreSQL's own nightly copy of the database into `./backups`, kept for 30 days |

Set **`FILES_BACKUP_HOST_DIR`** in `.env` to a folder on another disk (e.g. `/mnt/backup-disk/cia-files`) before the first night.

To update to a new version: `sh deploy/update-docker.sh`. It makes a backup of all the data first, then takes the new version and restarts. The database changes run by themselves.

## Option B — Windows without Docker

1. Install **Python 3.12** and tick "Add python.exe to PATH".
2. Install **PostgreSQL 16**. Create a database `dental` owned by a user `dental`. For a small trial you can skip this and set `DB_ENGINE=sqlite`.
3. Copy the project folder to e.g. `C:\dental`.
4. Run `deploy\windows\install.bat`.
   - The first run opens `.env` for you to fill in. Set `DB_HOST=localhost`.
   - Run it again after saving `.env`.
   - To update to a new version later: run `deploy\windows\update.bat` when the folder came from GitHub (`git clone`). It makes a backup of all the data first; if the backup fails, nothing is changed. Otherwise make a backup from *Settings → Backup* first, then copy the new files over the folder and run `install.bat` again. Your data is kept.
5. Run `deploy\windows\start_server.bat`. It makes up to 16 pages at the same time (`WEB_THREADS`). Make it start automatically in **Task Scheduler** with these settings:
   - Trigger: "At startup"
   - "Run whether user is logged on or not"
   - "Run with highest privileges"
6. Allow port 80 in Windows Firewall, for private networks only.
7. Set **`FILES_BACKUP_DIR`** in `.env` to a folder on another disk, e.g. `FILES_BACKUP_DIR=E:\CIA backup\files`.
8. Schedule `deploy\windows\backup.bat` every night (e.g. 2 am) and `deploy\windows\reminders.bat` daily at 07:00. Before that, edit the `PGPASSWORD` line in `backup.bat`.

---

## First setup after installing

1. Log in with the owner account. Open **Settings, users and lists**, which is Django admin at `/admin/`.
2. **Users**:
   - Create one account per person, with their first and last name.
   - Tick the right **group**: `owner`, `head_cia` (head of CIA), `team_head` (head of the CIA dentists team, together with `dentist`), `dentist` (CIA dentist), `secretary` or `stock` (stock manager).
   - Supervisors, course candidates and training dentists get **no login**: add them under **Academy → Dentists** (candidates come from **Academy → Candidates**) and they are chosen by name on the forms.
   - Set the **branch** in the staff profile to *Cairo Implant Academy*.
   - Tick "Staff status" only for people who may edit the settings lists, usually just the owner.
3. **Rooms**: 5 rooms are created for you (`غرفة 1` … `غرفة 5`). You can rename them or add more.
4. **Lists**: every list is already filled in and can be edited. All of them have Arabic and English names:
   - referral sources
   - medical conditions
   - treatment step types
   - lab work types
   - labs
   - purchase categories
5. **Courses**: add the current course batches from *Academy → Courses*.

## Backups: please read

The data and the photos are backed up apart, because the photos grow to hundreds of gigabytes while the records stay small:

- **The data**: every night a ZIP of all the records in `data/backups` (Docker: `./backups`; change with `BACKUP_DIR`; the newest `BACKUP_KEEP`, default 10, are kept). With 10,000 patients it takes about 2 minutes and is about 40 MB. It holds:
  - `database.json`: every record, to put back with `python manage.py restore_backup backup_….zip` (after `migrate` on a new PC). The data there before restoring is saved as a new backup first.
  - `database.sqlite3`: the database file itself (SQLite installations).
  - `excel/all-data.xlsx` and `csv/*.csv`: every table with readable column names, to open or move into any other program.
- **The photos and files** (ID scans, clinical photos, X-rays, stickers, invoices): every night they are copied as they are to `FILES_BACKUP_DIR` (Docker: `FILES_BACKUP_HOST_DIR`). **Only new and changed files are copied**, so after the first night it takes minutes, even with 1 TB. **Nothing is deleted there**, so a photo deleted by mistake is still in the copy. The previews are not copied (the system makes them again). Put this folder on **another disk** than the system's.
- `python manage.py backup` does both (`--no-files`: only the data; `--zip-files`: the files in the ZIP too, to move a small system in one file). The Windows `backup.bat` and the Docker `nightly` service run it every night.
- **Checked and copied**: each night's ZIP is **opened again and checked** (every part reads back, the records are
  counted, the database copy passes its own check), then **copied to a second place** when `BACKUP_COPY_DIR` is set
  (another disk or a network folder, e.g. `F:\CIA second copy`); the copy is compared with the original. A failed
  check or copy is written on the run and the owner is notified. The nightly run also tidies the database
  (`PRAGMA optimize` on SQLite, `ANALYZE` on PostgreSQL) and removes log lines older than a year.
- **Is it working?** *Settings → Backup and export* shows the last good backup of each part, the last runs and any error. The owner's home page shows a red **Check the backup** box when a part failed or has not run for more than a day and a half, and the owner gets a notification when a backup fails.
- **Restore on a new PC**:
  ```bash
  python manage.py migrate
  python manage.py restore_backup "backup_2026-01-31_02-00-00.zip"
  python manage.py restore_files --from "E:\CIA backup\files"
  ```
- **Restore a Docker database dump** (PostgreSQL's own copy):
  ```bash
  docker compose exec -T db pg_restore -U dental -d dental --clean < backups/dental-2026-09-25.dump
  ```
- **Outside the clinic**: swap a second backup disk every week and keep it at home (the 3-2-1 rule: three copies, two disks, one outside).
- **Before a big change to the system** (new version, moving to another program): make a backup (the update scripts do it by themselves) and copy it outside the PC.
- Test a restore on another PC (or on the [test copy](#test-copy)) once. A backup that has never been restored is only a hope.

## Test copy

Try a new version, or a big change to the lists, on a copy first:

- Windows: `deploy\windows\test_copy.bat`. Docker: `docker compose run --rm -p 8001:8001 --entrypoint python web manage.py make_test_copy --serve 8001`.
- It makes a backup of today's data, puts it in a separate small database (`test-copy/`), and starts it on port **8001**: `http://<server-ip>:8001/`. The same logins work.
- Every page shows a yellow **TEST COPY** banner. Nothing done there changes the real system, and running it again makes a fresh copy.
- The photos are not copied (they stay in the real system only), so photo pages are empty there.
- WhatsApp buttons still open real WhatsApp messages: do not send them from the test copy.

## Many photos and many users

What was measured with **10,000 patients, 60,000 visits, 30,000 bills and 30,000 photos** (a test copy on an ordinary PC):

| Page | Time |
|---|---|
| Reception now, day planner, patient search, patient file, bills, payments | 0.03 – 0.15 s |
| Tooth chart, photos page, treatment steps | under 0.1 s |
| Owner's home page, doctors' shares, clinic report (a year) | about 1.2 s |
| Money report (9 months) | 0.7 s |
| Balance sheet | 0.2 s |
| Visits report (9 months, 22,000 visits) | about 2 s |

How it stays quick:
- **Previews**: every photo gets a small copy (about 40 KB instead of several MB) when it is uploaded. Photo grids load only the previews, and only when they scroll into view; opening a photo gives the original at full quality. The log book and the case report use a larger copy (1600 px). `python manage.py make_previews` makes the previews of old photos (the nightly backup runs it too).
- **The browser keeps the photos** it has shown and asks the server only whether they changed.
- **nginx sends the files** (Docker): the system checks who may open a file, then nginx sends it (`MEDIA_SENDFILE=nginx`), so a tablet opening many photos does not keep the system busy. On Windows the system sends them itself, with 16 threads.
- **The money pages** add up all the patients' balances in a few database look-ups, not one per patient; long lists (bills, payments) are split into pages of 200.
- **Speed tests**: the automatic tests fill the database with 1,500 patients and fail when a page starts reading the database once per patient, visit or bill. `python manage.py fill_big_data` (test copies only) adds 10,000 made-up patients to try it yourself.
- **Logs**: `data/logs/errors.log` keeps every page that stopped with an error (they are also in *Problems*, and the owner is notified), and `data/logs/slow-pages.log` every page that took more than 3 seconds (`SLOW_PAGE_SECONDS`), with who opened it. Docker: `./logs`.

**X-rays and CBCT**:
- Periapical and panoramic X-rays are small pictures: upload them as documents of type *X-ray / CBCT* (up to 60 MB, `MAX_XRAY_UPLOAD_MB`) or as clinical photos.
- A **CBCT** is a folder of DICOM files (hundreds of MB) that a browser cannot show. Keep it in the viewer software or a shared folder on the server, and add a document of type *X-ray / CBCT* with the report (PDF) or a few screenshots, and **where the full scan is kept** (a folder such as `\\CIA-SERVER\CBCT\CIA-00020`, or the centre's viewer link). The patient's **X-rays & CBCT** tab shows them to the dentists, with a button to copy the folder.

## Security

Run `python manage.py security_check` (Docker: `docker compose exec web python manage.py security_check`) after
installing or changing the server: it prints what is right and what to fix. The owner sees the same list in
*Settings → Security and health*.

**What the system does by itself**
- **Every page needs a login.** Sessions end when the browser closes, after 12 hours, or after
  *Settings → Clinic options → log out after (minutes without use)* (60 by default; 0 = never). The bell's own checks
  every 30 s do not keep a PC awake.
- **Wrong passwords**: after 5 wrong passwords in a row a username is closed for 15 minutes, and after 20 from one
  device (any usernames) that device is closed too (`LOGIN_LOCK_AFTER`, `LOGIN_IP_LOCK_AFTER`, `LOGIN_LOCK_MINUTES`).
  The owner is notified and can open them again in *Settings → Security*. The admin pages are closed the same way.
- **Easy passwords** (short, common, like the username, or the sample `demo12345`) are noted at login: the person
  sees a yellow notice, and the owner a list. Tick *People with an easy password must change it* in Clinic options to
  make them choose another at their next login.
- **The clinic's network only** (`ALLOWED_NETWORKS`): by default the private networks (`192.168.x`, `10.x`,
  `172.16–31.x`), the VPN range `100.64.x` and the server itself. A request from any other address gets a short
  refusal and is written in the security log, so a server opened to the internet by mistake still shows nothing.
  `*` lets everyone try: use it only behind HTTPS and a VPN. The lab's WhatsApp address (`/lab/whatsapp/hook/`) is
  always open, because Meta's servers call it, and it checks Meta's signature itself.
- **Behind our nginx** (Docker) the device's address is the one nginx saw (`TRUSTED_PROXIES`, set in
  `docker-compose.yml`); a device on the network cannot pretend to be another. nginx also slows down many logins from
  one address (10 a minute).
- **The security log** (*Settings → Security*): logins, wrong passwords, closed logins, log outs (by hand, after
  minutes without use, or by the owner), passwords changed or given by the owner, **files taken out** (Word, Excel,
  CSV, ZIP of photos, backups), pages refused, and visits from outside the network. Kept a year.
- **Who is logged in now**, on which device and since when; the owner can log one person out on every device, or
  everyone else.
- **Deleted records are kept**: whatever is deleted (a document, a photo's record, a payout, a booking shift…) is kept
  a year with everything it held, who deleted it, when and from which page (*Settings → Security → Deleted records*).
- **Files are checked by what they hold**, not only by their name: a program or a web page renamed `photo.jpg` is
  refused. Only photos, videos and PDFs open in the browser (in a sandbox); any other file is only downloaded.
- **Headers** that stop other sites from framing the pages or running scripts in them (Content-Security-Policy,
  X-Frame-Options, nosniff, same-origin referrer), cookies that scripts cannot read, and no caching of patient pages in
  shared caches.
- **Typed data is not lost**: when a form is sent, the browser keeps what was typed for a day. If the network or the
  server stopped, the next time the form is opened a bar offers to put it back. A good save drops it. Each person sees
  only their own; passwords and files are never kept.

**What the clinic must do**
- Keep `DJANGO_DEBUG=0` and a long random `DJANGO_SECRET_KEY` (the installer writes one) in `.env`. **Never share the
  `.env` file**; it is not in the backups.
- Give each person their **own login** and a password of 10+ letters and numbers. Do not share logins: the log then
  says who did what.
- **Guests on another Wi-Fi**: the patients' Wi-Fi must be a separate network (a "guest network" on the router) from
  the staff's PCs, tablets and the server. Change the router's own password.
- **Never forward a port** of the router to the server. To reach it from home or between the branches, use a **VPN**
  (e.g. WireGuard or Tailscale: its 100.64.x addresses are already allowed), then turn HTTPS on.
- **HTTPS**: `DJANGO_HTTPS=1` (secure cookies, HTTPS only, the browser remembers it for 30 days: `DJANGO_HSTS_SECONDS`)
  once nginx has a certificate. On the clinic's own network only, HTTP is acceptable.
- **Windows**: turn on **BitLocker** on the server's disks and on the backup disks, so a stolen PC or disk shows
  nothing. Keep Windows updated, keep its firewall on, and lock the server's screen (Win + L).
- **Two backup disks**: set `BACKUP_COPY_DIR` to a second disk or a network folder (each night's ZIP is copied there
  and compared), and swap a disk kept outside the clinic every week.

## Old paper files: the Paper Reader (round 13)
The reading of the old paper files is done by a **separate program, the Paper Reader** (`reader/`), on **one PC with
the internet** (not the clinic server). The clinic server stays off the internet: it only gives the lists file and
imports the packages (*Patients → Old paper files*). See [paper-files.md](paper-files.md) for the steps, the costs and
the privacy questions.
- **Install**: copy the system folder to that PC, install Python 3.12+, and double-click `reader\start-windows.bat`
  (or `sh reader/start-mac-linux.sh`). It makes its own virtual environment, its `.env` with a random
  `READER_SECRET_KEY`, its database in `reader\data`, and serves on port **8100** with waitress. To start it with
  Windows, put a shortcut to `start-windows.bat` in the Startup folder (`shell:startup`).
- **The key**: `ANTHROPIC_API_KEY=sk-ant-…` in `reader\.env` only (start the reader again after changing it). Nothing
  is sent until the person in charge switches the reading on in the reader's *Settings → Reading and the key*; *Check
  the key* there tests it for free.
- **The internet**: that PC must reach `https://api.anthropic.com` (port 443, out only). Nothing needs to come in.
  Behind a company proxy, set `HTTPS_PROXY=http://proxy:port` in `reader\.env`.
- **Who opens it**: the clinic's network only (`READER_ALLOWED_NETWORKS`, the private addresses by default); the
  reception opens `http://<that PC>:8100`. Allow port 8100 in that PC's firewall for the clinic's network only.
- **The reading runs inside the reader** (a background thread), started when a file is sent and when the list of
  files is opened; a batch is asked about every minute. After a restart it goes on when someone opens the list, or run
  `python manage.py read_paper_files` in `reader\` (`--once` does one round).
- **Space and backups**: the scans, the page pictures (about 0.5 MB a page) and the packages are in `reader\data`.
  They are patients' files: turn on BitLocker on that PC, and copy `reader\data` to a backup disk (stop the reader
  first). After a package is imported, the documents are also in the dental system (in its nightly backup).
- **Uploads**: one scanned file may be up to 120 MB; the reader makes each package at most 250 MB (more files go in
  the next package), which the dental system takes (its nginx allows 320 MB).
- **The dental server needs nothing new**: no key, no internet, no new Python packages.

