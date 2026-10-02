# Old paper files read by Claude

The CIA's old paper files no longer need typing. They are scanned, **Claude** (the AI of the company Anthropic) reads
them, the system checks every value, and a person approves what goes into the patient's file. Nothing reaches a
patient's file before a person approves it, and the original scan is always kept.

This first part reads **the patient's data** (registration form and ID card), **the medical and dental history** of the
CIA paper chart, and **sorts the pages** into the patient's documents. The dental chart, the treatment plan, the
visits and the old payments are kept as pages for now; reading them is the second part.

## 1. Setting it up (the owner, once)
1. Open **platform.claude.com** and make an account for the clinic. Add credit (it is prepaid) and set a **monthly
   spending limit** there too.
2. Make an **API key** and copy it.
3. On the server, write it in the `.env` file: `ANTHROPIC_API_KEY=sk-ant-…`, then start the server again. The server
   needs the internet for this (out only, to `api.anthropic.com`); see [deployment.md](deployment.md).
4. In the system: **Settings → Old paper files (Claude)**:
   - **Check the key (free)**: it says whether the key works.
   - **Send the scanned pages to Claude to read**: off until you switch it on (read *Privacy* below first).
   - **Model**: *Claude Opus 5.5* (the most accurate; the usual choice) or *Claude Sonnet 5.5* (half the price).
   - **How hard it thinks**: *Medium* is the usual; *High* for very hard handwriting (costs more).
   - **Read each page twice and compare**: on by default. Where the two readings differ the value is marked for
     checking. It catches more mistakes and costs twice as much.
   - **Usual way of sending**: *In a batch* (half price, usually within an hour, at most a day) or *Now* (about a minute).
   - **Monthly limit (US dollars)**: nothing more is sent this month when it is reached, and you are told.

## 2. Scanning
- 300 dpi, colour or grey, the pages straight, staples out, nothing covering the writing.
- **One PDF for each patient.** Name the file as you like (e.g. the name or the old file number).
- For a patient **already registered**, print the **cover sheet** (*Patients → Old paper files → Cover sheets*, or
  *More → Print the cover sheet* in the patient's file) and put it on top before scanning: the file then goes to that
  patient by itself. Blank cover sheets can be printed for new files (the number is written by hand).
- Photos from the tablet also work: one photo per page, the page filling the photo.

## 3. Sending and checking (the reception)
1. *Patients → Old paper files → Send scanned files*: choose the PDFs (many at once), *Now* or *In a batch*, *Send*. Or,
   from a patient's file, *More → Read the old paper file*.
2. When the files are read, the person who sent them gets a notification. Open the file from **To check**.
3. The review page:
   - **Green** = sure. **Yellow** = please check. **Red** = cannot be read. Each yellow or red value shows why (e.g.
     *the two readings differ: 01145567781 / 01145567787*) and a **cut-out of the paper** around it, larger.
   - Correct what is wrong, fill what is red, then **Approve and save into the patient's file**.
   - **Whose file**: a new patient, or a patient already registered (the system proposes one when the cover sheet,
     the national ID or a mobile matches). Into a registered patient only the empty fields are filled; a different
     value replaces the old one only when you tick *replace* (and the reception's replacements go to the head for
     approval).
   - *Save for later*, *Keep only the pages* (the pages into a patient's documents, the data typed by hand), *Set
     aside*, *Read again* (it costs again). A page can be turned or its kind changed on the right.
4. After approval the patient's **Documents** have the whole file as one clean PDF (in order, upright, without the
   blank pages and cover sheets); the ID card is in its place, the X-rays under *X-rays & CBCT*, the consents in theirs.
   The history appears in the file as a history taken at the reception: the dentist starts from it.

## 4. What it costs
Claude Opus 5.5 costs $4 per million tokens read and $20 per million written; a batch costs half. A clear A4 page is
about 5,000 tokens in and 1,500–3,000 out. So, roughly:

| | One reading | Two readings (usual) |
|---|---|---|
| A page, now | $0.05–0.08 | $0.10–0.16 |
| A page, in a batch | $0.025–0.04 | $0.05–0.08 |
| A file of 10 pages, in a batch | $0.25–0.40 | $0.50–0.80 |
| 1,000 files of 10 pages, in a batch | $250–400 | $500–800 |

Claude Sonnet 5.5 costs half of these. The real cost of each file and of the month is on the review page and in the
settings (the owner only). Measure it on the first 50 real files before sending them all.

## 5. Privacy
- The pages **leave the clinic's server** and go to Anthropic over the internet (encrypted) to be read. This is the only
  part of the system that sends patient data out.
- Anthropic does not use the data sent through its API to train its models. For medical files, ask Anthropic about
  **zero data retention** (nothing kept after the answer).
- Egypt's data protection law treats health data as sensitive: check the consent wording with your lawyer before
  switching it on.
- Each file sent is written in the security log (*Settings → Security*: data taken out). The paper files of a place are
  seen only at that place, by the reception and the heads; the key stays in the server's `.env` file.

## 6. Limits (honestly)
- It is **not 100% right**. Arabic handwriting, doctors' shorthand, crossed-out words and faded pencil are the weakest
  points: they come out yellow or red, and a person must look at them.
- A wrong number that still looks valid (e.g. another real mobile number) can pass the checks; reading twice is the
  guard against it, which is why it is on by default.
- The place of the cut-out is close, not exact: it is cut with a margin, and the whole page is one click away.
- X-rays, photos, signatures and stamps are kept as pictures, not read.
- The teeth, the plan, the visits and the payments are not read yet (second part).
- The costs above are estimates until measured on your own files.
