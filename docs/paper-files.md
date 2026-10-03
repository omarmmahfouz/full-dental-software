# Old paper files: the Paper Reader

The CIA's old paper files no longer need typing. They are scanned, **Claude** (the AI of the company Anthropic) reads
them, the reception checks what was read, and the checked files go into the patients' files of the dental system.

The reading is done by a **separate program, the Paper Reader** (the `reader` folder), on **one PC with the internet**.
The dental system itself never goes on the internet for it: the two programs pass two files to each other, by a USB
stick or a shared folder.

```
 Dental system (clinic server, no internet)              Paper Reader (a PC with the internet)
 ─────────────────────────────────────────               ──────────────────────────────────────
 Old paper files → Download the lists  ── lists file ──▶  Settings → Lists from the dental system
 Old paper files → Print cover sheets                     Send scanned files → Claude reads them
                                                          The files → To check → Approve
 Old paper files → Import a package   ◀── package ────   Send to the dental system → Make the package
 (every value is checked again; then saved)
```

Nothing reaches a patient's file before a person approves it in the reader **and** the dental system has checked it
again with its own forms. The original scan is always kept.

This first part reads **the patient's data** (registration form and ID card), **the medical and dental history** of the
CIA paper chart, and **sorts the pages** into the patient's documents. The dental chart, the treatment plan, the
visits and the old payments are kept as pages for now; reading them is the second part.

## 1. Setting up the Paper Reader (the owner, once)
1. Choose a PC with the internet in the clinic (not the clinic's server). Install **Python 3.12** or newer from
   python.org ("Add python.exe to PATH" ticked).
2. Copy the whole system folder (the same one as the server's) to it. In its `reader` folder double-click
   **`start-windows.bat`** (on a Mac or Linux: `sh start-mac-linux.sh`). The first time it prepares itself (a few
   minutes), then opens **http://localhost:8100**. The reception PCs open it at `http://<this PC's address>:8100`
   (shown in the window). Close the window to stop it.
3. The first page asks for the login of **the person in charge**: make it (a long password).
4. **The key to Claude**:
   - Open **platform.claude.com**, make an account for the clinic, add credit (it is prepaid) and set a **monthly
     spending limit** there too.
   - Make an **API key** and copy it.
   - Open the file `reader\.env` with Notepad, write `ANTHROPIC_API_KEY=sk-ant-…` on its own line (remove the `#`),
     save, then start the reader again. **Never** send the key on WhatsApp, by e-mail or in a message.
5. **The lists from the dental system**: in the dental system, *Patients → Old paper files → Download the lists*. Bring
   the file to the reader's PC and open *Settings → Lists from the dental system → Bring in*. It holds what to read,
   the system's lists (diseases, dentists, how the patient heard of us…) and the place's registered patients, so the
   reader knows whose file a paper file is. **Bring in new lists before each big batch** (new patients, new dentists).
   One reader works for one place at a time (the place is shown in its top bar).
6. *Settings → Reading and the key*:
   - **Check the key (free)**: it says whether the key works.
   - **Send the scanned pages to Claude to read**: off until you switch it on (read *Privacy* below first).
   - **Model**: *Claude Opus 5.5* (the most accurate; the usual choice) or *Claude Sonnet 5.5* (half the price).
   - **How hard it thinks**: *Medium* is the usual; *High* for very hard handwriting (costs more).
   - **Read each page twice and compare**: on by default. Where the two readings differ the value is marked for
     checking. It catches more mistakes and costs twice as much.
   - **Usual way of sending**: *In a batch* (half price, usually within an hour, at most a day) or *Now* (about a minute).
   - **Monthly limit (US dollars)**: nothing more is sent this month when it is reached.
7. *Settings → People*: add a login for each secretary who checks files (not in charge: they do not see the settings).

## 2. Scanning
- 300 dpi, colour or grey, the pages straight, staples out, nothing covering the writing.
- **One PDF for each patient.** Name the file as you like (e.g. the name or the old file number).
- For a patient **already registered**, print the **cover sheet** in the dental system (*Patients → Old paper files →
  Print cover sheets*, or *More → Print the cover sheet* in the patient's file) and put it on top before scanning: the
  reader then proposes that patient by itself. Blank cover sheets can be printed for new files.
- Photos from a phone or tablet also work: one photo per page, the page filling the photo.

## 3. Reading and checking (the reception, in the Paper Reader)
1. *Send scanned files*: choose the PDFs (many at once), *Now* or *In a batch*, *Send*.
2. When the files are read they appear under **To check** (the number shows in the top bar).
3. The review page:
   - **Green** = sure. **Yellow** = please check. **Red** = cannot be read. Each yellow or red value shows why (e.g.
     *the two readings differ: 01145567781 / 01145567787*) and a **cut-out of the paper** around it, larger.
   - Correct what is wrong, fill what is red, then **Approve**.
   - **Whose file**: a new patient, or a patient already registered (the reader proposes one when the cover sheet,
     the national ID or a mobile matches; type a file number, a name or a mobile to choose another). A new patient
     whose national ID or mobile is already registered is refused: choose that patient instead. Into a registered
     patient only the empty fields are filled; a different value replaces the old one only when you tick *replace*.
   - *Save for later*, *Keep only the pages* (the pages into a registered patient's documents, the data typed by hand),
     *Set aside*, *Read again* (it costs again), *Open it again* (after approving). A page can be turned or its kind
     changed on the right.
4. *Send to the dental system → Make the package*: one ZIP file with every approved file. Download it and bring it to
   the dental system (a USB stick or a shared folder).

## 4. Importing (the reception or the heads, in the dental system)
1. *Patients → Old paper files → Import a package*: choose the ZIP, **Look inside**. Nothing is saved yet: the page
   shows what will happen to each file (a new patient file, or which registered patient, or why it cannot be imported).
   A package of another place is refused (open the system at that place).
2. **Import**: each file is checked again with the system's own registration and history forms and saved on its own.
   A file with a problem is left out and says why; correct it in the reader (*Open it again*) and send it again.
   A file is never imported twice.
3. In the patient's file:
   - **Documents**: the whole file as one clean PDF (in order, upright, without the blank pages and cover sheets); the
     ID card in its place (unless the file has one already), the X-rays under *X-rays & CBCT*, the consents in theirs.
   - The patient's data: a new file is opened, or a registered patient's **empty** fields are filled. A value ticked
     *replace* changes the file directly for the heads, and through the head's **approval** for the reception.
   - The **history** appears as a history taken at the reception: the dentist starts from it; the newest one gives the
     file its list of diseases.
4. The package's ZIP is not kept by the dental system after the import (the documents are in the patients' files);
   the reader keeps its copy.

## 5. What it costs
Claude Opus 5.5 costs $4 per million tokens read and $20 per million written; a batch costs half. A clear A4 page is
about 5,000 tokens in and 1,500–3,000 out. So, roughly:

| | One reading | Two readings (usual) |
|---|---|---|
| A page, now | $0.05–0.08 | $0.10–0.16 |
| A page, in a batch | $0.025–0.04 | $0.05–0.08 |
| A file of 10 pages, in a batch | $0.25–0.40 | $0.50–0.80 |
| 1,000 files of 10 pages, in a batch | $250–400 | $500–800 |

Claude Sonnet 5.5 costs half of these. The real cost of each file and of the month is shown to the person in charge
(the review page, the list of files, the settings). Measure it on the first 50 real files before sending them all.

## 6. Privacy and safety
- The pages **leave the reader's PC** and go to Anthropic over the internet (encrypted) to be read. The dental system's
  server sends nothing out.
- Anthropic does not use the data sent through its API to train its models. For medical files, ask Anthropic about
  **zero data retention** (nothing kept after the answer).
- Egypt's data protection law treats health data as sensitive: check the consent wording with your lawyer before
  switching the reading on.
- The reader keeps the scans, its database and the packages in `reader\data`: patients' files. Keep that PC locked,
  with BitLocker, and copy the `data` folder to a backup disk (stop the reader first). The reader opens only on the
  clinic's network (`READER_ALLOWED_NETWORKS` in its `.env`), and only to the people with a login there.
- The key is only in `reader\.env` on that PC.
- The dental system trusts nothing in a package: every value goes through its own forms, each document is checked to
  be a real PDF or picture, and a package of another place is refused.

## 7. Limits (honestly)
- It is **not 100% right**. Arabic handwriting, doctors' shorthand, crossed-out words and faded pencil are the weakest
  points: they come out yellow or red, and a person must look at them.
- A wrong number that still looks valid (e.g. another real mobile number) can pass the checks; reading twice is the
  guard against it, which is why it is on by default.
- The place of the cut-out is close, not exact: it is cut with a margin, and the whole page is one click away.
- X-rays, photos, signatures and stamps are kept as pictures, not read.
- The teeth, the plan, the visits and the payments are not read yet (second part).
- The two programs do not talk to each other: the lists and the packages are carried as files. A patient registered
  after the lists were brought in is unknown to the reader until new lists are brought in (the import then still finds
  the patient by the national ID).
- One reader works for one place at a time (bring in the other place's lists to switch).
- The costs above are estimates until measured on your own files.

## 8. A practice copy
`reader\trial-windows.bat` (or `sh trial-mac-linux.sh`) opens a practice reader with two sample files (logins *owner*
and *secretary*, password `demo12345`); nothing is sent to Claude. Its data is in `reader\data-trial`, apart from the
real reader. The dental system's practice copy already has two sample packages (one imported, one waiting).
