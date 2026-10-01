# Dental Group System — Cairo Implant Academy

One system for the owner's connected places:

| Place | Code | Status |
|---|---|---|
| **Cairo Implant Academy** — teaching institute, economic dental service, course candidates, dentists | `CIA` | **In use: secretary + dentists** |
| **Cairo Implant Center** — private economical clinic, mainly implants, many doctors paid by percentage or fixed amounts | `CIC` | **In use**: the same secretary, shared patients, doctors' shares, its own stock and the clinic report; **its own logo** |
| **El Khadem Dental Clinic** — Dr. Amr El Khadem's private clinic: specialists, doctors who bring their own patients, 4 shared rooms | `PVT` (files `EK-…`) | **In use**: its own reception, the specialists' charts, 40% / 30% shares, the elite look |
| **GDIL Dental Lab** — works for CIA, CIC, El Khadem and outside clinics, each with its own prices; **its GDIL logo** | `LAB` (cases `LAB-…`) | **In use**: its secretary, manager, designers and head; every case step by step, blocks, receipts, WhatsApp answers, the lab report |

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
| CIA dentists (full or part time) | `dentist` | every patient, the complaints about them, **only their own schedule**, and their cases. They record the clinical work: their own, and the course candidates' work, choosing the candidate's and the supervisor's names. In surgery they are usually the **assistant** |
| Secretary (reception) | `secretary` | reception, patients, the **day planner**, WhatsApp messages, **patient payments** and the **end of the day**, lab send / receive, CBCT and blood test requests, complaints, academy (if allowed in Settings), purchases, and the **patients to call** lists. Not the dental chart, treatment log or surgeries: in the patient file she sees the data, the visits, the payments and a **medical summary**, and the parts the owner ticks in *Settings → Access*. She books; the dentists do not. Her edits of patient data and visit times wait for the head of CIA's approval (at El Khadem: Dr. Amr's) |
| Stock manager | `stock` | the stock of materials, instruments, food and beverage, and purchases |
| Clinic manager (moderator) | `moderator` | the **Clinics** menu: how each doctor of CIC (and later the other clinics) is paid, the doctors' shares, payments to the doctors, and the clinic report |
| Dr. Amr El Khadem | `amr` | owner and manager of El Khadem, and a doctor there (prosthodontist): its **Clinics** menu (fee rules, doctors' prices, shares, report), the specialists' charts, referrals, the day planner, and he **approves the changes of El Khadem's reception** |
| El Khadem reception | `khadem` | the reception work of El Khadem only (Arabic): its patients, bookings in the 4 shared rooms, bills, payments, the referrals to book. No academy, no CIA or CIC patients |
| El Khadem specialists | `endo`, or no login | the endodontist, TMJ specialist, orthodontist, oral surgeon and prosthodontist: each with his specialty, his own prices, and his charts |
| Head of the lab | `lab_head` | the whole lab: every case, the **prices** of each client, the receipts and their cancelling, the costs, the **lab report** with the money, the lab's options |
| Lab manager | `lab_manager` | gives out the work (who designs, mills, finishes…), moves any case, sends work to another lab, the lab report without the money, the lab staff |
| Lab secretary | `lab_secretary` | the lab's reception (Arabic): receives the cases and prints their labels, checks in the work of our clinics, WhatsApp to the doctors and the **answer with the real status**, deliveries, receipts, the clients' accounts |
| Lab designers | `lab_designer` (e.g. CIA doctors), or no login | **My lab work**: the cases given to them; they finish their step and the case goes on. Technicians without a login are recorded by the manager |
| CIC doctors | `dentist`, or no login | booked at CIC; the ones with a login see **My shares**. A doctor can work at CIA and CIC |
| Supervisors | no login for now | chosen by name: on treatments, surgeries, plans and lab requests |
| Course candidates | **no login** | followed through their dentist file: batch, payments, implants done and remaining, every case |
| Training dentists | no login | chosen by name |

## What it does

### New in this version: protected from hackers, the data kept safe, smooth and fast (new)
For the owner: *Settings → Security and health*. The steps to try are in every checklist (the owner's in
[docs/dentist-test-checklist.md](docs/dentist-test-checklist.md) section U); what the server needs is in
[docs/deployment.md](docs/deployment.md#security).
1. **Protection from hackers**:
   - **Wrong passwords close the login**: after 5 wrong passwords in a row a username is closed for 15 minutes (the
     right password too), and after 20 from one device that device is closed. The person is told how long to wait; the
     owner gets a red notification and can **open it again** at once. The admin pages are closed the same way.
   - **Easy passwords** (short, common, like the name, or the sample `demo12345`) are noted at login: a yellow notice
     asks the person to change it, and the owner sees who. The owner can make them change it at their next login.
   - **A PC left open logs out by itself** after 60 minutes without use (Clinic options; 0 = never). An unsaved form is
     not lost (point 2).
   - **Only the clinic's network can open the system**: a device from the internet gets a short refusal, even if the
     server is opened to the internet by mistake (the lab's WhatsApp address stays open for Meta).
   - **The security log**: logins, wrong passwords, closed logins, log outs, passwords changed, **files taken out**
     (Word, Excel, CSV, photo ZIPs, backups), pages refused and visits from outside, with who, when and which device.
   - **Who is logged in now**, on which device, since when: the owner can log one person out on every device, or
     everyone else.
   - **Uploads are checked by what they hold**: a program or a web page renamed `photo.jpg` is refused; only photos,
     videos and PDFs open in the browser, anything else is only downloaded. Names and notes can no longer run as a
     script on a page (two places fixed), and other sites cannot frame the pages or run scripts in them.
   - **The checks**: *Settings → Security and health* lists what is right and what to fix, with how (test mode off,
     secret key, network, HTTPS, idle log out, easy passwords, backups checked and copied, disk space).
     `python manage.py security_check` prints the same on the server.
2. **The data kept safe**:
   - **Each night's backup is opened again and checked** (every part reads back, the records are counted, the database
     copy passes its own check) and **copied to a second disk** (`BACKUP_COPY_DIR`) and compared. A problem is shown in
     *Settings → Backup* and the owner is notified.
   - **Deleted records are kept a year** with everything they held, who deleted them, when and from which page
     (*Settings → Security → Deleted records*): a mistake can be seen and typed back.
   - **Nothing typed is lost**: when a form is sent, the browser keeps what was typed for a day; if the network or the
     server stopped, the form offers to put it back (**Put it back** / **Drop it**). Each person sees only their own.
3. **Smooth and fast**:
   - **Pages are sent compressed** (about a fifth of their size: quicker on the tablets' Wi-Fi); photos and videos are
     not (they are compressed already).
   - **Quicker look-ups** for the day's appointments, the bills and payments of a period, the treatment log, the
     examinations, the photos and the bell (new database indexes), and the database is tidied every night.
   - The server **keeps its database connection** instead of opening one per page.
   - **Health**: the database's size, free space on the photo and backup disks, the slow pages and page errors of the
     last day, on the owner's Security page.

### Earlier: the medical follow-up, the surgery design, the delivery checklist, the file step by step
Checklists: [docs/dentist-test-checklist.md](docs/dentist-test-checklist.md) section T, and the new sections of the
others.
1. **Medical follow-up and the fitness for surgery** (CIA, CIC and every place):
   - The readings of the day come first in the medical history: **blood pressure, random blood sugar, HbA1c**. A reading
     above the limits (HbA1c above **7%**, random sugar above 200 mg/dl, blood pressure from 160/100: the owner changes
     them in *Settings → Clinic options*) puts the patient on the **Medical follow-up** list (*Patients → Medical
     follow-up*), with a yellow box on the file and on the surgery chart.
   - **The ready consultation letter** (English, for the physician): the reasons (HbA1c, sugar, pressure, heart, blood
     thinners, bone drugs, other), the history, medicines and readings written from the file, **the procedure** (tick
     it), the duration and bleeding, **the anaesthesia (Artinibsa 4%: articaine 4% with epinephrine 1:100,000)** and
     **the medicines after the surgery** (from the prescription that fits the procedure, allergy-safe), and the question
     *is he fit?* Printed on the place's paper with a reply part: fit / fit with precautions / postpone / not fit.
   - **The answer**: the reception or the dentist records what the physician wrote, with **a photo of the paper**; the
     dentist is told. Postponed patients come back on the list on the date to check again. A dentist can also note
     *no consultation needed*.
2. **The delivery checklist of a prosthesis on implants**: from the dental chart (*Deliver: the checklist*), big points
   to tap: before the patient sits, seating (passive fit, periapical X-ray, contacts, occlusion, torque, screw holes
   sealed or cement removed, attachments for an overdenture), and the patient (satisfied, photos, cleaning, the printed
   instructions, the next check). Only the points that fit the prosthesis are shown. **Save: delivered** loads the
   implants and marks the pontics on the chart.
3. **The surgery chart designed like a scanner's order form**: choose a tool (**implant**, **extraction + immediate
   implant**, **pontic**, extraction, or add a sinus lift, GBR, expansion… to a tooth) and tap the teeth on the arch.
   **Pontics in the gaps** fills a full arch between the implants. Choose the **implant company once**. Then **sizes
   and lots, implant by implant**: tap the diameter and length, tap the implant used **from our stock** (its lot is
   filled in), or type the lot or **take a photo of the sticker** with the tablet; torque and ISQ; *Same as the implant
   before*. Saved, the chart shows the **pontics as pontics** (not missing), the saved surgery shows the arch drawn,
   and the **prosthesis is planned by itself** (a full arch, a bridge, or a crown for each implant).
4. **The patient's file, the way the dentist works**:
   - The registration of the reception is shorter: the teeth and medical history *as told by the patient* are folded
     (optional); the dentist takes the history.
   - **The file step by step**: medical history and readings → dental history and habits → dental examination (the
     histories just taken are folded) → **impression or diagnostic scan** → **CBCT** (taken here or asked from a centre)
     → **planning on the CBCT and the treatment plan** (two ticks: *planned on the CBCT*, *chart checked again*) →
     **fit for surgery** (when needed) → surgery → **restorative work** (how many steps are left) → **delivery on the
     implants**. The yellow **Next** button opens the next step; the impression and the CBCT can be skipped.
   - **Fewer buttons** on the patient's page: *Next*, *Dental chart*, **Record** (treatment, surgery chart, lab, CBCT,
     medical tests, consultation, prescription, instructions) and **The file** (photos, case report, specialists,
     Word / Excel / PDF); for the reception *Book*, *New bill* and **More**.
   - **Treatments by kind, then step**: tap the kind of work (diagnosis, surgery, teeth on implants, **endodontics**,
     fillings, crowns and bridges, dentures, gums, orthodontics…) then the step, e.g. endodontics → **access**, **access,
     cleaning and shaping**, **obturation**, **all in a single visit**, pulpotomy. Each step asks for its **photos and
     periapical X-rays** (before, working length, master cone, after…), taken with the tablet's camera on the step's
     page. The list and the shots of each step are in *Settings → Treatments*.
   - **After the surgery**: the prescription, the instructions, and **the next visit by what was done**: after a sinus
     lift a check after 2 days, after a graft a week, otherwise **suture removal after a week** (days in *Settings →
     Clinic options*). It is printed on the instructions; the dentist taps *Ask the reception to book it* (the patient
     goes on the reception's list) or the reception books it.
5. **The logos of CIC and the lab**: CIC's logo and the lab's **GDIL — The art of dentistry** logo (the lab is now *GDIL
   Dental Lab*) show on the login page, the top bar and every printed paper (bills, receipts, prescriptions,
   instructions, CBCT requests, surgery charts, case reports, lab papers).

### Earlier: the dental lab, the dashboard, an easier system
The dental lab opens as the fourth place. Checklist: [docs/lab-test-checklist.md](docs/lab-test-checklist.md).
- **The login page with the four places** (the owner's choice): one login page for every PC; tap your place (CIA,
  CIC, El Khadem or the lab), the page takes its look and that place opens after logging in. The PC remembers the
  last place tapped. Someone who does not work at the place tapped is told, and her own place opens.
- **Clients and prices**: CIA, CIC and El Khadem are clients of the lab, each with **its own price list**, and every
  outside clinic or doctor is a client on the outside list (or its own). *Lab prices* shows all the lists side by side.
- **A case step by step**: the secretary **receives** a case (the client, the doctor and his mobile, the patient,
  **digital scan or conventional impression**, what came with the work, the stage, the shade) with its work (zirconia,
  e.max, PFM, printing, titanium milling, printed metal then milled, dentures, splints…); the price comes from the
  client's list and the date promised from the usual days of the work. Each kind of work has its **steps**: e.g.
  zirconia is designed, milled, sintered, stained and glazed, checked and ready; a conventional impression is poured
  and scanned first. Print the **label** for the box and the **case sheet**.
- **The manager gives out the work**: the **Lab board** has a column per step with every case, who has it, since when
  and the date promised (late in red, urgent with a flame). *Done: go on to…* moves a case to its next step and to the
  person who does it (by itself when only one person does that step); the person with a login is told. Any step can
  be chosen (e.g. back to milling after the check), and a case can be **on hold** (it resumes the same step), **at the
  clinic for a try-in**, or **at another lab** (what, the cost, back by).
- **Designers** (mostly CIA doctors, with their own login) see **My lab work**, finish their step, and see the units
  they designed this month and their fees (a fee per unit, set by the head).
- **Remakes**: a remake opens a new case linked to the first, with **the reason** (fit, contacts, occlusion, shade,
  fracture, design, impression…) and **whose fault** (the lab's own mistake is remade free). A clinic returning work
  for a remake opens one by itself.
- **Blocks and the lab's stock**: the lab's items (blocks and discs, liquids, stains and glaze, porcelain and bond,
  resins, metal powders, plaster and acrylic, burs) belong to the lab in the shared stock. **Opening a block** takes it
  out of stock; each case records the units milled from it; the report says **how many crowns each block gave** and the
  cost per crown.
- **Money**: each client's account (work delivered, paid, still owed, and the work still in the lab), **receipts**
  (80 mm; cancelled with a reason, never deleted), a **statement** for any period (printed or its total on WhatsApp).
- **The lab report**: cases received and delivered, **on time %**, late now, the **time of each step** (average,
  middle, longest), from received to delivered **by kind of work**, each person's steps, time, units designed and the
  remakes of their designs, the remakes by reason and fault, the blocks, the clients, and the money (work delivered,
  received, materials used, other labs, designers' fees, **left for the lab**).
- **WhatsApp from the lab**: one click tells the doctor the case was received (with its number), is ready, or left the
  lab. **"Where is my case?"**: the secretary types the number or the doctor's mobile and the answer with the **real
  status** is written for her. With the WhatsApp Business platform (optional) the lab **answers by itself** to a doctor
  who sends a case number (see the limits).
- **Our clinics and the lab**: a lab request sent to **our lab** waits there as *on the way* until the lab checks it
  in; the request shows **where the work is at the lab**; the lab's price becomes the request's **lab cost**; when the
  lab delivers, the clinic's reception is told.
- **The universal lab request**: a blank A4 request to print for outside clinics, with every kind of work to tick.
- **Dashboard** (owner, head of CIA, clinic managers): every place side by side for today, 7 days, this month or any
  dates: bookings, visits finished, missed, new files, money (owner and managers), complaints, the lab; a column
  chart of each day; and what waits for someone now (approvals, late lab work, complaints, low stock, passwords).
- **Back goes up one page**: *Back* opens the page you came from, never a form already saved and never the same page
  twice; the browser's own back button no longer shows a saved form again. A page opened from a notification goes
  up one level (a case → the cases).
- **Saving once**: a form sent shows *Saving…* and a second tap does nothing (no double bills or bookings on a slow
  network). With SQLite (the trial and single-PC servers) pages keep opening while someone saves, and a save waits
  for its turn instead of failing.
- **Quicker pages**: pages show at once (the boxes no longer come in one after another), the lab board reads the
  database once for all its cards, and every new page has a speed budget in the automatic tests.

### Earlier: El Khadem Dental Clinic
Dr. Amr El Khadem's private clinic is the third place (`PVT`, files `EK-…`). Checklist:
[docs/khadem-test-checklist.md](docs/khadem-test-checklist.md).
- **Its own place and reception**: El Khadem has its own patients, its own reception (Arabic) and 4 rooms. Its reception
  does not see CIA's or CIC's patients, nor the academy, and the other receptions do not see El Khadem's. **Dr. Amr** is
  a doctor there and its manager: fee rules, prices, shares, the clinic report, and he **approves the changes of his
  reception** (a patient's data, visit times) instead of the head of CIA.
- **Specialties**: each doctor has a specialty (endodontist, TMJ specialist, orthodontist, oral surgeon,
  prosthodontist, periodontist, pedodontist, general…) and a title, shown on bookings, letters and the printed papers.
- **The doctor's own patients**: when a doctor brings his own patient, the reception chooses him under *Who referred
  you → the doctor's own patient*. Otherwise the patient is the clinic's.
- **Referrals**: Dr. Amr (or any doctor) refers a patient to a specialist of the clinic, with the reason, the teeth and
  the urgency, or to a place outside (e.g. a radiology centre). The specialist and the reception are told; the reception
  books it with one button (patient and doctor filled in); the specialist writes his **answer**, and the referring
  doctor is told. The **letter** prints on the clinic's letterhead with the medical alerts and the signature.
- **40% / 30% after the lab and implant cost**: a fee rule can be for *his own patients* or *the clinic's patients*,
  and can **take off the lab / implant cost first**. Each service given keeps its cost (from the price list, the
  doctor's price or typed on the bill; changed later on the doctor's statement). The statement shows, for each service,
  own / clinic patient, the cost taken off and the share.
- **Each doctor's own prices** (*Clinics → Doctors' prices*): e.g. the TMJ specialist's examination is 1,200 while
  Dr. Amr's is 800. A new bill takes the doctor's price by itself.
- **Interchangeable schedule**: the 4 rooms are **shared**: a doctor has no fixed room. A booking without a room gets a
  **free room** by itself; a room taken at that time is refused; a doctor with another patient at that time is warned.
  The **day planner** shows one column per room or **one per doctor**, and a patient can be moved to another room or
  **swap rooms** with one tap (or dragged on a PC). *Nearest free times* looks for a free room and a free doctor.
  *Reception today* shows who is in each room now and who is next. Opening hours and closed days are set per place.
- **Endodontic chart**: the tooth, the pulpal and apical diagnosis (AAE terms), the **case difficulty** (AAE: minimal,
  moderate, high, and why), the tests (cold, EPT, percussion, palpation, mobility, probing), each **canal** with its
  reference point, **working length** and how it was measured, master apical file, master cone and curvature
  (drawn as bars), the files, the irrigation and activation, the **intracanal medication** at each visit, the obturation and the restoration. Finishing
  the case writes it in the treatment log and shows the root canal on the dental chart.
- **TMJ examination**: the complaint, pain (0–10), **mouth opening** (with and without pain), protrusion and lateral
  moves, the deviation, the **joint sounds** on each side, the tender **muscles**, the joints to the touch, bruxism, the
  diagnosis (DC/TMD) and the plan (splint, physiotherapy, medicines…). Each follow-up adds the opening and the pain, and
  the bars show the progress.
- **Orthodontic case**: the molar and canine class on each side, overjet, overbite, crowding, midlines, crossbite, the
  profile, the **cephalometric values** next to the usual ones (SNA, SNB, ANB, FMA, IMPA…), the appliance and bracket
  system, the extractions and the time expected; each **adjustment visit** keeps the wires, elastics and what was done.
- **Shade guide for the prosthodontist**: the shade of each third (cervical, middle, incisal) on the **VITA classical**
  or **3D-Master** guide, tapped on coloured tabs, the **stump shade**, the translucency, the surface and the characters to copy, with a
  drawing of the tooth; *Lab request with this shade* fills the lab request.
- **The treatment plan printed for the patient**: an elite A4 page with the letterhead, the diagnosis, the chart, the
  treatment **phase by phase** with the doctor and the fee of each step, the total and the expected duration, the
  other options, the consent and the signatures. A **comprehensive case** shows **Your treatment team** (each doctor with
  his specialty and his part). In English or Arabic, whatever the doctor's language.
- **Detailed lab request**: the stage (final, framework try-in, bisque try-in…), the shades of the three thirds and the
  stump, the finish line, the pontic, the occlusion, the implant retention and parts, and **what is sent with the work**.
  Its **print** has the letterhead, the teeth on a small chart, the shade tabs in colour and three signatures.
- **An elite look for a place** (*Settings → Places*): *the look of the screens* standard or **elite** (navy and gold
  for El Khadem), a colour, a **logo** (top bar, login page and every printed paper), the file number prefix, a line
  under the name and an e-mail.
- **The login page of a PC**: `/login/?place=EK` shows the place's own login page, and the PC remembers it; logging in
  there opens that place for someone who works in more than one (now a place to tap on the login page, see above).
- **Shared**: the stock (each take-out still names its place) and the **two Fawry machines**. The reception is not
  shared: each place has its own.

### Earlier: bills, receipts, places and the file step by step
- **Doctors write the bill, the reception takes the money**: at CIA and CIC a dentist's bill has no payment; the
  reception is told, sees it under *Doctors' bills to collect* and records what was paid and how (big buttons).
- **Receipts**: a green message after saving and the **80 mm receipt** opens; a Fawry payment shows *Fawry POS machine*
  and the machine (the Arabic word was wrong before, so it read as cash). Save as a **picture or PDF**, or **send it to
  the patient** on WhatsApp. **Correct, cancel or refund** a receipt with a reason: nothing is deleted, every change is
  written on it, and the owner is told. **End of the day**: every receipt of the day at the place, by payment method
  and by who received it; the reception counts the drawer and closes the day; the owner reviews each day and **the
  month**.
- **A5 prescription** with **Rx** before each drug, and the bill, the instructions and the case report as picture / PDF.
- **Each place has its own patients**: CIA and CIC do not see each other's patients, complaints, waiting list or calls.
  Moving a patient (rare) opens a **new file** at the other place and closes the old one (out), with a link between them.
- **Bookings**: the other appointments of the patient are shown before saving (keep them or cancel them); a booking
  outside the dentist's days or hours **waits for approval** by the dentist or the head. The **waiting list** records
  each call and follows the booked patient to the visit. **Up to 4 numbered extra rooms** per place, shown only on a
  day they are booked or given a shift. Only the reception books.
- **Patient names** in Arabic, at least three names. **ID photo on the tablet**: the photo is checked (light, shine,
  sharpness, distance), the card is cut out of the table, and the **ID number is read** from it (offline) and written
  in the form, to be checked.
- **The file step by step** for the dentist: medical history → dental history → examination → treatment plan →
  surgery chart, each saved page going on to the next (round 10 adds the impression, the CBCT, the fitness for surgery,
  the restorative work and the delivery). The medical history is taken by the dentist; the reception
  sees a **summary**. The owner chooses what else the reception sees in a file (*Settings → Access*).
- **CBCT**: ticking *CBCT requested* opens the CBCT request; it is marked **done in our clinic** (where there is a CBCT
  machine) or at the centre, with the folder of the scan, which then opens from the examination.
- **Dental chart**: mark all the other teeth missing at once (one tooth left); the chart history reads in each
  person's language. An **implant icon** replaces the scissors. The file exports to **Word, Excel or PDF**.
- **Photos**: crop (4:3 for the log book), turn, mirror and lighten a photo before the log book; the original is kept.
- **WhatsApp from a dentist's tablet** becomes a request in the reception's WhatsApp list.
- **Stock in groups**: dental materials, implants & surgery, infection control, medicines, instruments, beverage &
  hospitality, cleaning, stationery & printing, each with its categories; the stock manager edits them and sees what
  each group used.
- **Forgot your password?** on the login page: the owner is told and gives a temporary password (shown once, with a
  WhatsApp button); the person chooses their own at the next login.

### Speed and safety with a lot of data
Checked with **10,000 patients, 60,000 visits, 30,000 bills and 30,000 photos**: the reception and dentist pages open in
0.03–0.15 s, the owner's money pages in 0.2–1.2 s (before: 15–25 s). Details and the server to buy: [docs/deployment.md](docs/deployment.md#many-photos-and-many-users).
- **Quick money pages**: the home page, balance sheet, money report, doctors' shares, clinic report and bills add up all the
  balances in a few database look-ups instead of one per patient; the visits report reads the clinic options once.
- **Photo previews**: each photo gets a small copy when it is uploaded. Photo pages, the patient's documents and the
  surgery chart load the small copies, and only as they scroll into view; tapping a photo opens the original. The log
  book and case report use a larger copy. The browser keeps photos it has already shown.
- **Long lists in pages**: bills and payments show 200 rows a page; the totals stay for the whole period.
- **Backups for a big photo folder**: every night a ZIP of all the data, and a copy of the **new** photos only to a backup
  disk (nothing is deleted there). *Settings → Backup and export* shows how each part went; the owner's home page shows a
  red **Check the backup** box, and the owner is notified, when a backup failed or has not run for a day and a half.
- **X-rays & CBCT**: X-rays may be up to 60 MB. A CBCT (too big to upload) is kept as **where it is**: a folder on the server
  or the centre's viewer link, next to its report or screenshots. A new tab on the patient file, **X-rays & CBCT**, shows
  them to the dentists too, with a button to copy the folder.
- **Error and slow-page logs** on the server's disk (`data/logs`), besides the *Problems* list.
- **Test copy**: `test_copy.bat` starts a copy with today's data on port 8001, with a yellow **TEST COPY** banner, to try
  a new version or a big change first. **Safe updates**: `update.bat` (Windows) and `deploy/update-docker.sh` make a backup
  first, and stop if it fails.
- **Speed tests**: the automatic tests fill the database with 1,500 patients and fail when a page becomes slow with more
  patients, so this cannot come back unnoticed.

### CIC — the Cairo Implant Center
- **Places**: CIA and CIC share one system. People who work in both (e.g. the secretary) tick both in *Settings → People and logins*, and a coloured switch in the top bar (**CIA** green, **CIC** blue) chooses where they work now. The line under the top bar takes the place's colour, so nobody books or bills in the wrong place. Everything then works for that place: the reception board, the day planner, rooms and room schedule, bookings, free times, bills and payments, stock use.
- **Each place has its own patients**: CIA and CIC do not see each other's patients, not even their names. New files opened at CIC are numbered `CIC-…`. A patient who moves (rare) gets a new file at the other place (*Move to another place*); the old file is closed as *out*, with a link to the new one.
- **Doctors**: many doctors, some at CIA and CIC. Each dentist's *works at* places are set in *Academy → Dentists*; bookings and the room schedule of a place offer its own doctors only. CIC has 3 rooms to start (renamed or added in *Settings → Rooms*).
- **How each doctor is paid** (*Clinics → Doctors' fee rules*, set by the moderator or the owner): a **percentage** of what the patient paid, a **fixed amount for each service** (for each tooth, e.g. 1,500 per implant), or a **fixed amount for each visit**. A rule for one service comes before the rule for every service (e.g. implants fixed, the rest 25%). To change a percentage from a date, add a new rule from that date.
- **Doctors' shares** (*Clinics → Doctors' shares*): for a place and a period, each doctor's visits, **time in the chair**, patients, what was billed and **paid**, their **share**, what was **paid to them** and what is **still owed**. Each doctor's **statement** lists every service with its rule and share, every visit, and the payments to the doctor, with a form to record a new payment. A doctor with a login sees his own statement (*My shares*).
- **Clinic report** (*Clinics → Clinic report*): what the patients paid (by payment method and by Fawry machine), visits and appointments, patients seen and new files, time in the chair, the doctors' shares and payouts, the **materials used** from stock, and **what is left for the clinic**, with a day-by-day view. The home page of the owner and the moderator shows this month at CIC.
- **Prices per place**: a paid service can be for one place only (*Settings → Paid services → only at*), e.g. a CIC price list; each place's bills offer its own services and those of every place. Bills, services given and payments keep their place, and printed bills and receipts carry CIC's name, phone and address.
- **Two Fawry machines**: every card payment says which machine took it (*Fawry machine* on the payment). *Patients → Fawry machine* shows what each machine still holds at Fawry, and can be filtered by machine. The machines are named in *Settings → Fawry machines*.
- **Stock of each place**: an item can be **shared** or **belong to CIC** (material bought for it only). Every take-out says **for which place**, so *Stock movements* shows what each place used and its value, and CIC's own material cannot be taken out for CIA. Implants bought for CIC are offered on CIC's surgery charts only.
- **Balance sheet**: patient payments are counted where they were paid, and the payments to the doctors are a cost of their place.
- **Places list** (*Settings → Places*): each place's name, phone and address, used in WhatsApp messages and printouts.

### The look, for everyone
- **A colour for each part**: patients teal, schedule blue, clinical purple, complaints rose, academy amber, stock and purchases orange, reports indigo, settings grey. The menu entry, the icon of the page title and the line under the title share the colour, and the menu entry of the open page is marked.
- **Clear separators**: page titles have a line under them, long forms are split into numbered parts (1, 2, 3…) with a line after each title, and cards, tables and lists have soft borders and headers.
- **Motion**: the page slides in, the boxes and tiles appear one after another, the numbers on the home page count up, menus and pop-ups open smoothly, and buttons react when pressed. A thin green line at the top shows that the next page is loading. People whose device asks for less motion get none.
- **Hints**: a short tip at the top of each main page says what to do there, in the person's language (for example on *Reception today*: tap *Arrived*, then *In the room*, then *Left*). ✕ closes it on that page; the user menu → *Hints: on / off* switches all of them, per person. With a mouse, resting on an icon button shows what it does.
- **Tablets and touch** (a browser window under 1200 px wide):
  - A **bar at the bottom** with each person's four main places and *Menu*: the reception gets *Home, Reception, Patients, Book*; the dentists *Home, My visits, My patients, Treatments*; the stock manager *Home, Stock, Take out, Purchases*; the owner and the head of CIA *Home, Reception, Patients, Reports*.
  - *Menu* slides the whole menu in from the side, in big rows, with the person's name and roles at the top. The bell and the approvals stay at the top of the screen.
  - Bigger buttons, boxes and tick boxes. On long forms *Save* and *Cancel* stay at the bottom of the screen.
  - A table row with one destination opens from anywhere on the row.
- **Messages**: "saved" messages fade away by themselves after a few seconds; errors and warnings stay until closed.
- **Home page**: *Good morning / afternoon / evening* with the person's name, and an icon on each number box.
- **Log-in page**: the CIA panel beside the form, icons in the boxes, and an eye button to show the password.
- **No dead links**: a link shows only when the person can open it. For example, dentists see other dentists' names as plain text, and the reception sees a dentist's cases with links to the patient file rather than the chart.

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
  - A down payment plus a monthly installment plan. Each enrollment is **in the academy (offline) or online**.
  - **Installments of the month**: what each candidate pays this month, what is collected and what is left, with a **WhatsApp reminder** button (also on the overdue list and the WhatsApp page).
  - Each payment records the **payment method**: cash, card, InstaPay, mobile wallet, bank transfer or cheque, with the transaction reference.
  - Printable receipts, and an overdue installments list.
- **Easier booking**:
  - Type part of the patient's **name** (any spelling of أ/ا, ة/ه, ى/ي), mobile or file number, and choose from the list.
  - Every date is **dd/mm/yyyy**, from a calendar or typed. Times are chosen in **15-minute steps** (9:00, 9:15, 9:30…).
  - Under the form, the **day's appointments** room by room: click a free (green) place and its time, room and dentist are filled in.
  - **Schedule → Day planner**: one column per room with the dentist working there, 15-minute steps, every booked patient, and the week at the top (booked and free places per day).
- **Room schedule**: CIA dentists in one list, and supervisors, candidates and training dentists in a second list. Thursday and Friday are surgery days by default (changeable in Settings). A surgery day is set per room, so one room can have a candidate's surgery while the others work as usual. **Extra rooms** appear only on the days they are opened. "Same as last week" fills the week with last week's timetable.
- **Patient file**:
  - The **ID scan** is cut out of the background, turned upright and shown as a card; the original photo is kept, and it can be turned by hand.
  - **File opened on** for old paper files, a list of all **governorates**, patients labelled **out** with a reason, and the call list sorted by the **first-call date**.
  - Mobiles with the wrong number of digits are refused, and duplicates name the other patient, in a **pop-up**.
  - **Treatment plan** and **treatment steps** tabs in plain Arabic, with a simple explanation of each treatment and each tooth number (36 = الضرس الأول السفلي الأيسر), when the owner shows them to the reception (*Settings → Access*). The **missing teeth** and the **medical summary** follow the dentist's chart and examination.
  - Editing the data, or correcting forgotten arrival / room / leaving times, is sent to the **head of CIA for approval**.
- **Patient payments**: services from a price list (CBCT, consultation, implant…), discounts up to 100% with the reason, payment in parts, receipts, and the day's collections by payment method.
- **CBCT and blood test requests**, printed for the patient to take. The CBCT request asks the centre to send the DICOM files to **ciapts@gmail.com** (changeable in Settings).
- **Back** button on every page.
- **Patients the dentists asked for**: each CIA dentist sends the list of patients he wants on his days (step, time needed, order, and a backup list). After the head of CIA approves it, the reception calls them in order and books them with one click (patient, dentist, time and step filled in). When a patient cannot come, the page says which backup patient to call next.
- **Medical and dental history at the reception**: the same questions as the paper chart (blood pressure, sugar, allergies, smoking…), from the patient file. The dentist sees them at the next examination.
- **Save before leaving?**: leaving a page with data not saved yet asks *Save*, *Leave without saving* or *Stay*.
- **Report a problem**: user menu → *Report a problem*, with a screenshot if wanted. The owner reads them, answers, and the person is told.
- **Reception now**: the home page and *Reception today* sort the day's patients by the time on the PC, updated every minute: *late — not here yet*, *expected now*, *next 2 hours*, *waiting*, *here now*. Filters (all / still to come / here / finished), a search box and a short list make a busy day easy to read.
- **Walk-ins and the next visit**:
  - A patient who comes without an appointment but has other bookings: the reception is asked to cancel or move them.
  - A patient who leaves without a next appointment: *Book the next visit* (with what the dentist wrote), or *No next visit needed*.
- **Came late, not seen**: a status of its own (not a no-show), and the page to book another time opens at once. The dentist is told.
- **Waiting time**: a patient who comes early waits from the appointment time, not from the arrival.
- **Smarter booking**:
  - Choose the dentist: the screen says if he works that day and in which room (the room is filled in, and can be changed).
  - *Nearest free times*: for the chosen dentist, or for any dentist when none is chosen. Click one to fill the date, time, room and dentist.
  - Booking a dentist on a day or hour that is not on the room schedule is allowed, but the supervisor is told, and a button sends the dentist a WhatsApp message.
  - The procedure is chosen from a list (Arabic names for the secretary), with a box for the teeth and notes. The dentist who asked for the visit and a **second dentist in the room** are shown on the board.
- **WhatsApp: send all / mark as sent**: tick the messages already sent, or *Send the next one* to go down the list one message after another.
- **Bills**: *Patients → New bill*, with one-click buttons for the first-visit examination and the CBCT, several services with teeth and discounts, *pay now*, and a printed bill. Bills made by the dentists after a treatment appear on the reception board to collect.
- **Waiting list**: patients who want a place on a busy day (also short 5–10 minute visits). When an appointment is cancelled, missed or moved, the reception is told that a place is free and who is waiting.
- **Lab cycle**: the dentist makes the request → the reception **takes the impression / model from the dentist** (a digital scan goes by itself) → sends it → receives the work → the patient is booked for the fitting (the reception is told when the work is back).
- **Complaints**: the concerned dentist is told at once; the reception writes **what she did** and the **current situation** of the case (shown in the list), and can correct her notes.
- **Fawry machine**: *Patients → Fawry machine*. Card payments taken on the machine for patients and course candidates appear by themselves with Fawry's percentage; the reception adds bills paid through the machine (mobile, electricity, internet…), money put on it and Fawry's transfers to the bank, for the academy, the private clinic or CIC. The page shows what Fawry still holds.
- **Up button**: a round arrow at the bottom corner of long pages goes back to the top.
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
| Specialist / freelance dentist | the doctors of El Khadem and CIC, each with a **specialty** (endodontist, TMJ specialist, orthodontist, oral surgeon, prosthodontist…) and a title |

What dentists do:
- **Home page**: **my week** (my shifts and patients for the next 7 days), the **latest changes** to my appointments (new, moved, cancelled, did not come), and complaints waiting for my answer.
- **Dental chart (digital version of the CIA paper chart)**:
  - Drawn like **real teeth**: each tooth has its own crown and roots (incisors, canines, premolars, molars with 2 or 3 roots), and a round 5-surface diagram under it for caries and fillings. It shows root canals, crowns, implants (healing or loaded), bridge pontics, missing teeth, root remnants, impacted, mobility and hopeless teeth.
  - **Examination & history**: every field of the paper chart. This covers the chief complaint, the teeth lists, CBCT, blood pressure, glucose, HbA1c, allergies, drugs, the dental history and the scores.
  - A new examination starts from the last one, so only what changed needs typing.
- **Treatment log, with the chart following the treatment**:
  - The dentist writes the tooth numbers and the treatment, e.g. `12` + *Composite restoration* + `MO`.
  - Before saving, the screen shows how the chart will change: *12: caries MO → filled composite (MO)*. The dentist confirms with a tick box.
  - Other examples: *46 Implant failure* → 46 becomes **missing**, and the implant is marked **failed**. *36 Extraction* → missing. *Second stage / impression / delivery* → the implant moves to its next stage.
  - Every change is kept in the tooth's history.
- **Treatment log form**: the treatment is chosen from a list, with a **notes** box right under it.
- **Treatment plans**: phases (urgent, preparation, surgical, prosthetic, maintenance), and the **case difficulty** (simple, moderate, advanced). The dentist picks the name of the supervisor who approved it.
  - Two parts: **Implant and surgery** and **Restorative and other**; each treatment's part is set in Settings → Treatments.
  - **Tooth picker**: a button next to every teeth box opens the tooth chart; click all the teeth that get the same procedure (e.g. simple implant on 36, 46 and 16). "All missing teeth" picks the teeth missing on the chart.
  - Planned teeth show in blue on the chart.
  - Items are ticked **automatically** when the same treatment is recorded on the same teeth.
- **Implant surgery chart**: the CIA surgery chart, field by field:
  - The team: instructor, operator 1, operator 2 and assistant.
  - The case difficulty.
  - **The design** (like a scanner): tap the teeth with a tool (implant, immediate implant, pontic, extraction, sinus,
    GBR…), the implant company once, then the sizes and lots implant by implant (from stock, typed, or the sticker's
    photo).
  - Per tooth: extraction, flap, simple / immediate / guided implant, expansion, splitting, closed / open sinus and GBR.
  - Per implant: company and line, diameter × length, lot, sticker photo, torque, ISQ and subcrestal.
  - GBR (block graft, donor site, particles, % autogenous), membrane and tacks, soft tissue, suture, temporary and X-ray.
- **Implant life**: placed → uncovered → impression / scan → loaded, or failed, with the dates.
  - It moves by itself from the treatment log.
  - So you always know who is **waiting for 2nd stage, scan / impression or delivery**.
- **Photo checklist**: the 8 stages of the CIA photo protocol, with photo or video upload.
  - **Log book pages**: the case photos printed in frames of a fixed size (6 or 12 on an A4 page), each named by its shot, one stage per page, with the description of the procedure written from the surgery chart and treatment log (editable before printing), and the patient's identity hidden if wanted.
  - **Readable photo folders**: on the server PC the photos are saved in `data/media/Patient photos/<file number and name>/1 Preoperative photos (1st visit)/…`, one folder per stage, each file named by its shot, teeth and date (e.g. `Implant_placed_with_cover_screw_36_29-08-2026.jpg`). Copy them from there without opening the system, or press *Download all photos (ZIP)*.
- **My patient list**: instead of filling the calendar, add the patients you want on your days with the step, the time needed, the order, and a backup list. The head of CIA approves it (and can change the time), then the reception calls and books them.
- **Complaints**: the dentist of the patient writes the answer and what will be done. If there is no answer in time, the dentist and the head of CIA are alerted.
- **Moving an appointment**: *Move to another time* keeps the old time and the reason, tells the dentist, and the reception sends the new time on WhatsApp.
- **Post-op instructions, printed with the patient's name and surgery**: the sheets that fit the surgery are chosen by themselves (general, sinus lift, bone graft, soft tissue graft), in Arabic or English.
- **Prescriptions with interchangeable drugs** (with **injections IM / IV** — ceftriaxone, clindamycin, dexamethasone, diclofenac, ketorolac; the doctor reviews the doses in Settings): ready prescriptions (after implant, after sinus lift, after extraction, and versions for penicillin allergy) are chosen from the surgery. Each drug can be swapped for any brand of the same group, e.g. Augmentin ↔ Megamox ↔ Hibiotic. The patient's penicillin allergy is flagged. It prints with the patient's name, age and date.
- **Lab requests**: the dentist chooses the name of the supervisor who checked the request, and it goes straight to the secretary to send.
- **Case report**: the whole case on one printable page (chart, plan, surgeries, treatments), with a switch to **hide the patient's identity** for teaching or publication.
- **Word file**: the patient's whole file (data, history, chart, plans, treatments, surgeries, appointments, payments) as a Word document.
- **Dentist file**: every surgery and treatment they did, and for candidates **implants placed / required / remaining** for their course.
  - Also their batch, their payments, and all their cases, even ones they were not present for.

- **Visit page**: when the patient arrives the dentist gets a notification **with a sound**. The visit page leads step by step: restorative / other treatment (with or without a bill), or surgery → the suggested prescription → the post-op instructions.
- **Visits without notes**: a visit with nothing written in the patient's file reminds the dentist after one hour, and the supervisors after one day. A banner shows how many are waiting.
- **Bill for the procedure**: on the treatment form, choose the paid service; the reception sees the bill to collect.
- **Photos by session**: each follow-up is a session (date + teeth). A new date or other teeth start a new session, so the photos of the right side, the left side and a later follow-up do not mix; *Show all* shows everything. Steps that are not on the checklist can be added with their own name.
- **Operators**: any dentist can be chosen as operator while writing; after saving, changing the operator needs the head of CIA's approval. **Operator 2 works on other teeth**, not the same tooth: each tooth has its operator, and it counts for that dentist.
- **Lab requests**: the patient is filled in, the shade list follows the guide (**VITA classical** or **3D-Master**), and the date needed back comes from the usual days of the work type (set in Settings).
- **Implants from stock**: on the surgery chart choose the company, then the implant in stock: its size and **lot** are filled in and saving takes it out of stock (put back if the tooth is changed or removed).
- **Prostheses on implants**: single crown, **bridge** (which teeth, on which implants; the others are pontics), **full arch fixed** (All-on-X) and **overdenture**, with retention, material and stage. When delivered, the implants become loaded and the pontics show on the chart. Shown on the chart, the patient file, the implant page and the case finder.
- **Complaints**: each dentist sees only the complaints about him; the heads see all.

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
- **Totals**: patients, surgeries and cases (sites), and a table **by procedure** with the cases, surgeries and patients of each one (one patient can have an open sinus and a simple implant, or two simple sites). Click a procedure or an implant status to filter by it.
- **Prostheses**: filter by prosthesis (single crown, bridge, full arch, none yet), group by it, and see how many units sit on the implants found.

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
- **Balance sheet** (owner only): income and costs of the academy, the private clinic and CIC side by side: patient and course payments, cash taken for bills paid on the Fawry machine, Fawry's percentage and charges, bills paid through the machine, purchases, and the net. Also how the money came in (cash, Fawry, InstaPay…), what Fawry still holds, and what patients, candidates and suppliers still owe.
- The head of the CIA dentists team sees only the **dentist follow-up** of the CIA dentists.

### Settings: change the system without changing the program (owner)
User menu → **Settings**.
- **Lists** (the owner and the head of CIA) including paid services and prices, reasons for a patient being out, and a simple Arabic explanation for each treatment:
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
- **Parts of the system for one person**: on a person's page, choose for each part "as the role", normal, read only or no access, e.g. only some secretaries work with the academy.
- **Clinic options**: appointment hours (9 to 5), the usual length (30 minutes), the usual surgery days, the e-mail for CBCT files, and **Fawry's percentage** on card payments.
- **Lists**: the **usual days at the lab** for each lab work type, which paid services get a **quick button** on a new bill, and implants in stock (company, diameter and length on the stock item).
- **Backup and export** (owner): each backup is **checked after saving** and copied to a **second disk** when one is
  set (new). One button makes a **backup of all the data** (a ZIP with all records to put back into the system, and the same data as **Excel** and **CSV** to open in any other program). The photos and files are copied every night to the backup disk, only the new ones. The page shows the last good backup of each part and any error. *Download the Excel file* gives every table on its own sheet. Keep a copy outside the clinic, and always before a big change to the system. See [Backups](docs/deployment.md#backups-please-read).
- **Security and health** (owner, new): the checks (what is right and what to fix), who is logged in now (log a person
  out), the logins closed after wrong passwords (open them), the security log (logins, wrong passwords, files taken
  out, pages refused), the disks' free space and the slow pages, and **Deleted records** (whatever was deleted, kept a
  year). *Clinic options* has **log out after (minutes without use)** and **people with an easy password must change
  it**. See [Security](docs/deployment.md#security).
- **Problem reports** (owner and head of CIA): what the staff reported, and pages that stopped with an error (recorded automatically), with a download to send to whoever maintains the system.
- **Access by role**: make one part of the system (patients, schedule, charts, surgeries, stock, reports…) **read only** or **closed** for a role.
  - It can only take access away, never give more than the role normally has.
  - When a person has two roles and either is limited in a part, the person is limited there.
  - The owner is never limited, so the owner cannot be locked out.

Uploaded files (ID scans, invoices) are **never public**. They open only for logged-in staff with the right role.
Only the roles that see patients can open patient documents and photos.

---

## How to test it now (trial on any PC)

This makes a **practice copy on your PC** with sample data (now also **the dental lab**: its head, manager, secretary
and designers (Dr. Sherif of CIA designs too), four technicians without a login, CIA, CIC, El Khadem and three outside
clinics with their price lists, the lab's stock and blocks, six weeks of cases in every step with the time of each
step, two remakes, a case at another lab, one on hold and one at a try-in, receipts and WhatsApp messages; **El Khadem**: Dr. Amr, its reception, six specialists with their own prices and the 40% / 30% rules, eight `EK-…` patients (two brought by Dr. Tarek), a month of visits in the 4 shared rooms and today's and tomorrow's bookings, referrals, two endodontic cases, a TMJ examination with its follow-ups, an orthodontic case, a shade record and its lab request, and a full-rehabilitation treatment plan; also **X-rays and two CBCTs kept on the server and on a centre's viewer** for one patient, and a **backup history** with one failed night; **CIC**: three doctors paid in three ways, a month of CIC visits with bills and payments, some on the second Fawry machine, a payment to a doctor, CIC's own implants and drapes in stock, and each place's use of the shared stock; hints are on for every sample login; also bills, the waiting list, the Fawry machine, implants in stock by lot, prostheses, a late patient, a visit without notes and two dentists in one room): patients, visits, lab work and installments, plus dentists of every type, dental charts, treatment plans, 14 implant surgeries with implants at every stage, the stock list, a prescription, a list of patients to call, and next week's appointments waiting for their WhatsApp reminders. Nothing you do there touches real data, and nothing goes to the cloud.

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
   | `dentist1`, `dentist2` | CIA dentists (`dentist2`, Dr. Sherif, also works at CIC) | English |
   | `secretary` | secretary, at **CIA and CIC** (the switch in the top bar) | Arabic |
   | `secretary2` | a second secretary who does not work with the academy | Arabic |
   | `stock` | stock manager | Arabic |
   | `moderator` | CIC clinic manager: doctors' fee rules, shares, payments to doctors, clinic report | English |
   | `cicdoctor` | Dr. Walid Hamdy, a CIC doctor paid 1,500 per implant and 25% of the rest | English |
   | `amr` | Dr. Amr El Khadem: a doctor at El Khadem and its manager | English |
   | `khadem` | El Khadem's reception (El Khadem only) | Arabic |
   | `endo` | Dr. Yasser Hamed, El Khadem's endodontist | English |
   | `labhead` | Dr. Hossam, the head of the lab | English |
   | `labmanager` | Eng. Karim, the lab manager who gives out the work | English |
   | `labsec` | the lab's secretary | Arabic |

   The 4 course candidates (batch IMP-2026-A), the training dentist and the supervisors have no login, as agreed.

5. Follow the checklists step by step:
   - **[docs/lab-test-checklist.md](docs/lab-test-checklist.md)** for the dental lab and the login page with the places
   - **[docs/khadem-test-checklist.md](docs/khadem-test-checklist.md)** for El Khadem: its reception, Dr. Amr, the specialists and the printed papers
   - **[docs/cic-test-checklist.md](docs/cic-test-checklist.md)** for CIC: the secretary, the moderator, the owner and a CIC doctor
   - **[docs/secretary-test-checklist.md](docs/secretary-test-checklist.md)** for the secretary
   - **[docs/dentist-test-checklist.md](docs/dentist-test-checklist.md)** for the CIA dentists, the heads and the owner, including the settings
   - **[docs/stock-test-checklist.md](docs/stock-test-checklist.md)** for the stock manager

To stop, close the black window. To start again, double-click `trial-windows.bat`. Your practice data is kept.
To start over with fresh sample data, delete the `data` folder and run it again.

> **Already tried an earlier version?** Your practice data is kept and converted, and nothing is lost. Interns become dentists: those linked to a course candidate stay linked, and the others become training dentists. The new sample dentists, charts and surgeries are only added to an **empty** practice database, though. To see them, delete the `data` folder and run the trial again.

**Mac / Linux:** run `sh trial-mac-linux.sh` in the project folder, then open http://localhost:8000.

## Tablets in the clinic

The system works in the browser of a tablet on the clinic Wi-Fi, with nothing to install: open the server's address (e.g. `http://192.168.1.20:8000`) and add it to the home screen. It was checked at tablet sizes (1024 and 768 pixels wide): nothing needs sideways scrolling, and wide tables scroll inside their box.
On a tablet each person gets a bar at the bottom with their main places and *Menu*, the full menu slides in from the side, buttons and boxes are bigger for fingers, and *Save* stays in view on long forms (see *The look, for everyone* above).

Suggestion, when you decide to buy:
- An **11-inch tablet used in landscape**: e.g. Samsung Galaxy Tab S9 FE / A9+ (Android) or an iPad 10th generation / iPad Air 11". Landscape gives the full-width forms and the tooth chart.
- A **wall or desk holder** in each room (a swivel arm or a stand), and a **cover with a stylus** makes writing on the tooth chart easier with gloves off.
- Keep the tablets on the **clinic Wi-Fi** only (the server is not on the internet). Each dentist logs in with his own user; logins end at the time limits set in Settings.

## Installing on the clinic server

See **[docs/deployment.md](docs/deployment.md)** for these topics:
- The server to buy for 10,000 patients and 1–3 TB of photos
- Docker (recommended), with nginx sending the photos
- Windows without Docker
- Backups and restore: the data every night, the new photos to a backup disk
- The test copy, and safe updates
- Many photos and many users: measured speeds, previews, logs, X-rays and CBCT
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
  - `clinics`: how the doctors of a clinic are paid (fee rules by patient source, the cost taken off first), their
    shares, payments to them, the doctors' own prices (`clinics/prices.py`) and the clinic report
  - `specialties`: referrals and the specialists' charts (endodontic, TMJ, orthodontic, shade); `shades.py` has the
    shade guides; `demo.py` fills El Khadem
- Places: `branch_for_user(user)` is the place the person works in now (the switch in the top bar keeps it in the session,
  `WorkingPlaceMiddleware`); `working_places(user)` lists the places they can choose. Bills, services given, payments,
  appointments, rooms and stock movements carry their place. A place with **shared rooms** (`Branch.rooms_shared`)
  books by free room (`scheduling/rooms.py`: `free_room`, `room_clash`, `change_room`); its hours and closed days
  are on the place. The look of a place (`Branch.theme`, colour, logo) sets `theme-elite` on `<body>` and the
  letterhead of the printed papers (`includes/place_letterhead.html`). `/login/?place=EK` keeps the place of a PC in
  a cookie (`core.views.PlaceLoginView`).
- The look (no build step):
  - `static/css/app.css` starts with the colours, lines, shadows and motion as CSS variables. Each part of the system
    has an accent colour (`.sec-patients`, `.sec-scheduling`…), set on `<body>` from the page's address and on each menu entry.
  - `static/js/app.js` adds the motion, the loading line, the tooltips, the rows that open from anywhere, and the sticky *Save*.
  - Page hints are in `apps/core/hints.py`, keyed by the page's address name, with a text per role where needed.
    The bottom bar of each role is in `apps/core/navigation.py`.
- Run the tests: `DJANGO_DEBUG=1 python manage.py test apps` (as GitHub does on every push; test files import with
  `apps.…`, not relative imports), or list the modules:
  ```bash
  DJANGO_DEBUG=1 python manage.py test apps.academy.tests apps.billing.tests apps.charting.tests apps.clinical.tests \
    apps.complaints.tests apps.core.tests apps.dentists.tests apps.patients.tests apps.prescriptions.tests \
    apps.purchasing.tests apps.reports.tests apps.scheduling.tests apps.stock.tests apps.surgery.tests apps.clinics.tests \
    apps.specialties.tests apps.lab.tests
  ```
- The dental lab is `apps/lab`: `models.py` (the steps `Step` and the usual road of each kind of work `ROUTES`,
  `LabCase` with its items and steps, clients, price lists, workers, blocks, receipts, messages), `services.py` (every
  change of a case: `start_case`, `move`, `next_step`, `assign`, `receive`, `make_remake`, `outsource`, the blocks,
  `balances`; `case_from_request` / `clinic_received` link the clinics' lab requests), `stats.py` (the report),
  `whatsapp.py` (the texts, the status answer and the WhatsApp Business webhook) and `demo.py` (the sample data).
- Backups: `python manage.py backup` (the data ZIP into `BACKUP_DIR`, default `data/backups`, then the new files to
  `FILES_BACKUP_DIR`; each run is a `BackupRun`), `python manage.py restore_backup <zip>`, `python manage.py restore_files`,
  and `python manage.py organize_photos` (moves photos saved by older versions into the readable folders).
- Speed: `apps/billing/models.py` has `paid_by_charge`, `balances` and `bill_totals` (many patients or bills in a few
  look-ups); `apps/clinics/shares.totals` is the quick form of `statement`. Previews are in `apps/core/previews.py`
  (`{{ photo.file|preview }}`, `make_previews`); files are sent by `apps.core.views.send_file` (ETag, and
  `MEDIA_SENDFILE=nginx` for X-Accel-Redirect). `SpeedTests` in `apps/core/tests.py` gives each page a budget of
  database look-ups with 1,500 patients (`apps/core/bigdata.py`; `python manage.py fill_big_data` on a test copy).
- Logs: `LOG_DIR` (default `data/logs`) holds `errors.log` and `slow-pages.log` (`SLOW_PAGE_SECONDS`, default 3).
  `python manage.py make_test_copy [--serve 8001]` makes a test copy (`TEST_COPY=1` shows the banner).
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
