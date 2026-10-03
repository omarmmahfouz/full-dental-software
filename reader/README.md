# The Paper Reader

A small program, apart from the dental system, that reads the old paper files with **Claude** (Anthropic's AI) on a
PC with the internet. The reception checks what was read, approves it, and sends the approved files to the dental
system as one package file. The whole guide is in [`../docs/paper-files.md`](../docs/paper-files.md).

## Start it
- **Windows**: double-click `start-windows.bat` (needs Python 3.12+ from python.org). It opens http://localhost:8100.
- **Mac / Linux**: `sh start-mac-linux.sh`.
- **A practice copy with sample files** (nothing sent to Claude): `trial-windows.bat` or `sh trial-mac-linux.sh`;
  logins `owner` and `secretary`, password `demo12345`.

The first run asks for the login of the person in charge. Then:
1. Write the key in `.env`: `ANTHROPIC_API_KEY=sk-ant-…` (only on this PC), and start the reader again.
2. *Settings → Lists from the dental system*: bring in the file from the dental system (*Patients → Old paper files →
   Download the lists*).
3. *Settings → Reading and the key*: check the key, choose the model, switch the reading on (after the patients'
   consent).
4. *Settings → People*: a login for each secretary.

## For the developer
- Django 5.2, SQLite (`data/reader.sqlite3`), the dental system's look (`../static` is served as `shared/`).
- `reading/`: `models.py` (the lists, the files, pages, readings, values, packages), `catalogue.py` (the values to
  read, from the lists file), `claude.py` (instructions, the answer's JSON form, sending now or in a batch),
  `checks.py` (cleaning and comparing the readings), `pages.py` (PDF pages, turns, cut-outs, the clean PDF),
  `worker.py` (the background reading; `python manage.py read_paper_files`), `exchange.py` (the lists file and the
  package: the format both programs share), `views.py`, `demo.py` (`python manage.py load_reader_demo --password …`).
- Tests (Claude is never called): `python manage.py test reading`.
- Settings come from `.env` (see `.env.example`): `READER_SECRET_KEY`, `ANTHROPIC_API_KEY`,
  `READER_ALLOWED_NETWORKS`, `READER_ALLOWED_HOSTS`, `READER_DATA_DIR`, `READER_DEBUG`.
