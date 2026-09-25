# Installing on the clinic server (on-premise)

The system runs on **one computer in the clinic**, called the server. Every other PC, laptop or tablet on the clinic network opens it in a browser at `http://<server-ip>/`.
No internet or cloud is needed.

**Server recommendations**
- A PC that stays on during working hours. 8 GB RAM and an SSD are plenty.
- A **fixed LAN IP**, for example `192.168.1.10`. Set it on the router with a DHCP reservation.
- A UPS.
- An external disk for backups.

---

## Option A — Docker (recommended: Linux, or Windows with Docker Desktop)

```bash
git clone <this repository> dental && cd dental
cp .env.example .env
nano .env        # set DJANGO_SECRET_KEY, DB_PASSWORD, the server IP in ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS
docker compose up -d --build
docker compose exec web python manage.py createsuperuser     # the owner account
```

That starts four services:

| Service | What it does |
|---|---|
| `db` | PostgreSQL. The data lives in `./data/postgres` |
| `web` | The system on port **80**. Uploads go to `./data/media` |
| `reminders` | Creates the daily reminders at 07:00: overdue complaints and late lab work |
| `backup` | A nightly database backup into `./backups`, kept for 30 days |

To update to a new version:

```bash
git pull && docker compose up -d --build
```

The database migrations run automatically.

## Option B — Windows without Docker

1. Install **Python 3.12** and tick "Add python.exe to PATH".
2. Install **PostgreSQL 16**. Create a database `dental` owned by a user `dental`. For a small trial you can skip this and set `DB_ENGINE=sqlite`.
3. Copy the project folder to e.g. `C:\dental`.
4. Run `deploy\windows\install.bat`.
   - The first run opens `.env` for you to fill in. Set `DB_HOST=localhost`.
   - Run it again after saving `.env`.
   - To update to a new version later, copy the new files over the folder and run `install.bat` again. It applies the database changes and adds any new list items. Your data is kept.
5. Run `deploy\windows\start_server.bat`. Make it start automatically in **Task Scheduler** with these settings:
   - Trigger: "At startup"
   - "Run whether user is logged on or not"
   - "Run with highest privileges"
6. Allow port 80 in Windows Firewall, for private networks only.
7. Schedule `deploy\windows\backup.bat` daily and `deploy\windows\reminders.bat` daily at 07:00. Before that, edit the `PGPASSWORD` line in `backup.bat`.

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

- The database and the uploaded ID scans are the clinic's most important data.
- **Docker**: back up the `backups/` folder (database dumps) **and** the `data/media/` folder (uploaded files). Copy both to an external disk at least weekly, and keep one copy outside the clinic.
- **Windows**: `backup.bat` puts both into `backups\YYYY-MM-DD\`.
- **Restore a Docker database backup**:
  ```bash
  docker compose exec -T db pg_restore -U dental -d dental --clean < backups/dental-2026-09-25.dump
  ```
- **Full backup from the system** (any installation): the owner opens *Settings → Backup and export → Make a full backup now*,
  or the server runs `python manage.py backup` every night (Windows Task Scheduler / cron). Each backup is one ZIP in
  `data/backups` (change with `BACKUP_DIR` in `.env`; the newest `BACKUP_KEEP`, default 10, are kept) holding:
  - `database.json`: every record, to put back with `python manage.py restore_backup backup_….zip` (after `migrate` on a new PC).
    The data there before restoring is saved as a new backup first.
  - `database.sqlite3`: the database file itself (SQLite installations).
  - `excel/all-data.xlsx` and `csv/*.csv`: every table with readable column names, to open or move into any other program.
  - `media/`: all uploaded files, with the clinical photos in readable folders (`media/Patient photos/…`).
- **Before a big change to the system** (new version, moving to another program): make a full backup and copy it outside the PC.
- Test a restore on another PC once. A backup that has never been restored is only a hope.

## Security notes

- Every page needs a login. Sessions end when the browser closes, or after 12 hours.
- Uploaded files are served only through a permission check. They are never public web files.
- Keep `DJANGO_DEBUG=0` on the server. Never share the `.env` file.
- If the system is ever reached from outside the clinic, put it behind HTTPS first and set `DJANGO_HTTPS=1`. The branches will be connected later, and a VPN between them is the safest way to do that.
