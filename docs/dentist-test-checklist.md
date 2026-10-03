# CIA dentists, heads and owner: test checklist

Start the trial with `trial-windows.bat` (see the README). All passwords are **`demo12345`**.
The practice database already has everything below, so every screen has something in it:
- dentists of every type
- dental charts and treatment plans
- 14 implant surgeries, with implants at every stage and one failed implant
- a prescription and a list of patients to call

| User | Who |
|---|---|
| `owner` | owner / CEO |
| `headcia` | head of CIA |
| `teamhead` | head of the CIA dentists team (also a CIA dentist) |
| `dentist1`, `dentist2` | CIA dentists |

The 4 course candidates (batch IMP-2026-A, 10 implants required each), the training dentist and the 2 supervisors have **no login**. Their names are chosen on the forms.

If you used an earlier trial, delete the `data` folder first so the new sample data is created.

When something is wrong or missing, note three things:
- the **step number**
- **what you did**
- **what you expected to happen**

A screenshot helps a lot.

## A. Language and access
1. Log in as **dentist1**. Every screen should be in **English**, left to right. The menu has Patients, Schedule, Clinical and Complaints only.
2. Open the user menu and click **العربية**. The screens switch to Arabic. Log out and log in as **secretary**: still Arabic. Log in again as **dentist1**: Arabic, because it remembers the choice. Switch back to English.
3. As **dentist1**:
   - **Patients → All patients** lists every patient. **My patients** lists only yours.
   - **Complaints** opens, but there is no button to record or edit a complaint.
   - **Schedule → My schedule** shows only your own shifts.
4. Log in with a course candidate's name: there is no such login. If someone gives a candidate a login in the settings, the login page refuses it.
5. As **owner**, open **Reports**, then as **headcia**: head of CIA sees every report except *Money*.

## B. Dental chart
6. As **dentist1**, open a patient and click **Dental chart**.
   - Missing teeth have an X, fillings are blue and caries are red.
   - Implants show a screw: grey while healing, with a green crown once loaded.
   - Planned treatment shows as blue tooth numbers. The legend is under the chart.
7. Click a tooth, e.g. **17**. Tick *caries* with surface *D*, and save. The chart shows it, and **Chart history** shows *17: … → caries* with your name.
8. Click **Examination & history**.
   - The medical history is already filled in from the last examination or from what the patient told the secretary.
   - Write teeth in *Missed* (e.g. `18, 28`), choose the supervisor's name, keep **Write these teeth onto the dental chart** ticked, and save. Those teeth become missing on the chart.

## C. Treatment log: recording the candidates' work
9. On the chart of a patient of a candidate, click **Record treatment**.
   - **Operator** is already the candidate the patient belongs to, and **Assistant** is you.
   - Choose the treatment from the list (*Treatment done*), and write something in **Notes** right under it.
10. Choose *Composite restoration*, teeth `17`, surfaces `D`, and the supervisor's name.
    - Before saving, the box **Dental chart changes** should show *17: caries D → filled composite (D)*.
    - Save with **Update the dental chart** ticked. Tooth 17 is now filled.
11. Record *Extraction* on a sound tooth. It becomes **missing**.
12. Open a patient with an implant. Record *Implant failure / removal* on that tooth.
    - The preview says the tooth becomes **missing** and the implant becomes **Failed / removed**.
    - After saving, check both on the chart and on the implant.
13. Record a treatment with **Update the dental chart** unticked. The treatment is saved, but the chart does not change.
14. **Clinical → Treatment log** shows the treatments you wrote down, including those done by the candidates.

## D. Treatment plan
15. On the chart, click **Treatment plan**.
    - Set the **case difficulty** (e.g. *Simple*).
    - Add *Composite restoration* on `25` (phase 2) and *Guided implant surgery* on `36, 46` (phase 3).
    - Choose the supervisor who approved it in **Approved by supervisor**. Save. The plan shows as approved.
    - The planned teeth show in blue on the chart.
16. Record *Guided implant* in a surgery chart for **36 only** (see E). The plan item for 36 is ticked **done** automatically, and 46 stays planned.

## E. Implant surgery chart, instructions and prescription
17. Open **Clinical → New surgery chart**. It follows the CIA paper chart.
    - The team: instructor (a supervisor), operator 1 and operator 2 (candidates, shown as *name — batch*), and **you as assistant**.
    - For each tooth, tick the procedures (extraction, flap, simple / immediate / guided implant, expansion, splitting, closed / open sinus, GBR).
    - Fill in the implant type, diameter, length, lot, sticker photo, torque and ISQ. Use **Add tooth** for more teeth.
    - Open the GBR, sinus, membrane, soft tissue and suture sections.
18. Try these mistakes. Each should be refused with a clear message:
    - an implant ticked without its size
    - the same tooth twice
    - the same dentist twice in the team
    - a bone *mix* without the % autogenous
19. Save.
    - The surgery gets a number (SUR-…).
    - The chart shows the implants, and extracted teeth become missing.
    - The surgery page looks like the paper chart, and **Print surgery chart** prints it.
20. On the surgery page click **Post-op instructions**.
    - The sheets that fit are ticked by themselves: always the general sheet, plus sinus lift or bone graft when those were done.
    - The patient's name, the surgery date, the teeth and the dentist are filled in. Switch to English and back, then print.
21. Click **Prescription**.
    - The ready prescription that fits the surgery is chosen (e.g. *After sinus lift*).
    - Change *Augmentin 1 g* to *Megamox 1 g*: the dose stays.
    - If the patient's examination says **allergic to penicillin**, a red warning shows and the penicillin-free prescription is chosen.
    - **Save and print**: the prescription prints in Arabic with the patient's name, age and date.
22. Open an implant from the surgery page or the chart.
    - It shows its stage: *Placed – healing → Uncovered → Impression / scan taken → Loaded*, or *Failed*, with the dates.
    - Record *Second stage / healing abutment*, then *Digital scan*, then *Final prosthesis delivery* on that tooth in the treatment log. The stage moves forward by itself each time.

## F. Lab request with the supervisor's name
23. From a patient, click **Lab request**. Choose the candidate as dentist and a supervisor in **Reviewed by supervisor**, then **Save and send**. It goes straight to *Approved*, and the secretary is notified to send it.
24. Make another one **without** a supervisor's name. It waits for review. Log in as **headcia** and approve it.

## G. Photos, case report and the dentist file
25. On the chart, click **Photos**. You should see the 8 stages of the CIA photo checklist. Upload a photo and a short video for one item. Items with a photo get a green tick.
26. Click **Case report**. Click **Hide patient identity** and check that the name and mobile disappear. Print it or save it as a PDF.
27. As **dentist1**, open **Clinical → My cases and implants**. Try to open another dentist's file by changing the number in the address bar. It should be refused.
28. As **secretary**, open **Academy → Candidates** and a candidate. **Cases and implants** opens their file:
    - the batch and the payments
    - implants placed as operator 1 against the 10 required, with **implants remaining**
    - every case, even those the candidate was not present for
29. As **owner**, open **Academy → Dentists**. **Create login** appears only for CIA dentists, not for candidates, training dentists or supervisors.

## H. Head of the CIA dentists team
30. Log in as **teamhead**.
    - **CIA dentists** lists the CIA dentists, training dentists and supervisors, not the candidates.
    - **Reports** shows only **Dentist follow-up**, without the candidates.
    - **Schedule → Room schedule** shows every dentist's shifts.

## I. Treatment plan finder and patients to call
31. As **headcia**, open **Clinical → Treatment plan finder**.
    - Choose *Guided implant surgery* in **Planned procedure** and tick **Simple** and **Moderate**. You get every open plan waiting for guided surgery.
    - Tick **No upcoming appointment** to keep only patients who have not booked yet.
    - **Export to Excel (CSV)** gives the same list.
32. In **Send these patients to the reception to call**, write what to tell them (e.g. *please come to book the surgery day*) and click **Send to reception**.
33. Log in as **secretary**. The home page shows **Patients to call**. Open the list, call each patient and save an answer (*Booked*, *No answer*...). **Book appointment** opens the booking with the patient filled in.
34. Log in as **headcia** again: the list shows every answer, and a notification says when every patient was called.

## J. Head of CIA: checks and case finder
35. As **headcia**, open **Clinical → Treatment log** and tick *Not checked yet*. Open a treatment, grade it and add a comment.
36. Open **Clinical → Case finder & statistics**. The top cards show the implants, the survival %, the loaded implants and those waiting, the mean days to loading and the mean torque.
37. Click the quick searches *Healing – waiting 2nd stage*, *Uncovered – waiting impression / scan* and *Impression taken – waiting delivery*. Each gives the list of patients waiting for that step, and **Send to reception** works here too.
38. Combine filters: gender *Female*, company *Dentium*, procedure *GBR*, diameter from 4, jaw *Lower*.
    - Set **statistics by** *Implant company*, then by *Implant status*.
    - The table shows the survival % and the days to loading for each group.
39. Click **Export to Excel (CSV)** and open the file in Excel. There is one row per implant, with every detail, and the Arabic names are readable.
40. Open **Reports → Patient visits and timing** in English: the rooms show as *Room 1*, *Room 2*… and the lab as *Our dental lab*.

## K. Owner: settings, access and time limits
41. As **owner**, open the user menu → **Settings**. The page has four cards (**Clinic options**, **People and logins**, **Access by role**, **Dentists**) and every list under its group.
42. **Clinic options**: change the clinic phone and save. Print a prescription (step 21): it shows the new phone. You can also change *a patient is late after (minutes)*, the usual appointment length and *send appointment reminders (days before)* here.
43. **Implant companies and types** → **Add**: add *Zimmer — TSV*. It is in the implant list of a new surgery chart straight away. Untick *active* on it: it leaves the list, and old surgeries keep it.
44. **Treatments** → **Add** a treatment, e.g. *Night guard* with chart change *No change to the dental chart*. It appears in **Treatment done** when you record a treatment.
45. **Drug groups (interchangeable drugs)**: open *Amoxicillin + clavulanic acid 1 g* and add a brand. It is offered on the prescription. Also open **Ready prescriptions**, **Post-op instruction sheets** and **WhatsApp messages** and change a line.
46. **People and logins** → open **dentist2**:
    - Tick **Read only everywhere** and save. Log in as dentist2: a grey banner says *Read only*. Pages open, but saving a treatment is refused with *You have read-only access here*.
    - Untick it. In **Days allowed**, tick only a day that is not today. Log in as dentist2: the login page says *You cannot use the system on this day*.
    - Untick the days. Set **Access ends on** to yesterday: the login is refused with the date. Try **From hour / To hour** outside the current time: refused with the hours.
    - Clear the limits again.
47. **New login**: make a login for a new secretary with the role *Secretary*, and leave the password empty. A password is made up and shown once. Log in with it: the screens are in Arabic.
48. **Access by role**:
    - Set **Purchases** to *Read only* for *Secretary* and save. As **secretary**, purchases open but saving one is refused.
    - Set **Reports** to *No access* for *Head of CIA*. As **headcia**, the Reports menu is gone.
    - Set both back to *Normal access*.
49. As **headcia**, **Settings** shows the lists, but not Clinic options, People and logins or Access by role.

## L. New in this version (2)
50. **Home page** (dentist1): *My week* shows your shifts and patients for the next 7 days, and *Latest changes to my appointments* lists new, moved and cancelled ones.
51. **Real-looking chart**: open a patient's **Dental chart**. The teeth are drawn with their own crowns and roots (molars with 2 or 3 roots); caries and fillings show on the round diagram under each tooth, root canals as red lines, implants as a screw (healing) or with a green crown (loaded), missing teeth crossed.
52. **Treatment plan in two parts**: **New treatment plan**. The first part is *Implant and surgery* (its procedure list has only implants, grafts, sinus lifts…), the second *Restorative and other*. Click the tooth button next to *Teeth*: pick 36, 46 and 16 → **Done**: "16, 46, 36" is written, the same procedure on the three teeth. *All missing teeth* picks the chart's missing teeth. The plan page shows the two parts.
53. **Surgery chart, several teeth at once**: **New surgery chart** → *Same procedures on several teeth*: tick *Simple implant* and *GBR*, **Choose the teeth**, pick 36 and 37 → a card is made for each tooth with both ticked. Fill the implant sizes and save.
54. **My patient list** (Schedule menu, or from *My week*): add a patient with the step, the time you need, the list (main or backup) and the order. As **headcia**, *Schedule → Approve the dentists' patient lists*: change a time and approve. As **secretary** the patient is now in *Patients the dentists asked for* (secretary checklist 66–68).
55. **Complaints**: open a complaint about your patient: write *your answer and what will be done* and send. If nobody answers in time, the dentist and the head of CIA get an alert.
56. **Move an appointment**: on an appointment, *Move to another time*, write why: the old time is kept, you are told, and the reception sends the new time on WhatsApp.
57. **Prescriptions**: *Injections* (IM / IV) are in the drug list. On the post-op instructions page, ticking *Extra instructions after sinus lift* or *bone graft* changes the printout at once.
58. **Photos → Log book pages (print)** on the patient of the newest surgery (it has sample photos): one page per stage, 6 photos of the same size per page, each named by its shot, and the description of the procedure (click it to change the text). Try 3 photos a row, *Whole photo*, and *Hide patient identity*, then print or save as PDF.
59. **Download all photos (ZIP)**: the ZIP has one folder per stage, e.g. *1 Preoperative photos (1st visit)*, and each photo is named by its shot and date. On the server PC the same folders are in `data/media/Patient photos/`.
60. **Word file** on a patient file: the whole file opens in Word.
61. As **owner**: *Settings → Backup and export* → **Make a full backup now**, then **Download** it and open the ZIP: `excel/all-data.xlsx` has a sheet per table (Patients, Appointments, Surgeries…). **Download the Excel file** gives the same workbook alone.
62. As **owner**: the user menu → *Problem reports* shows what the staff reported (secretary checklist 71); write an answer, set *Solved*: the person is told.

## M. New in this version (3)
63. **Arrival alert**: as **secretary** press "وصل" for one of Dr. Mona's patients. As **dentist1** (another browser or PC) a notification appears within 30 seconds **with a sound** (click the page once after logging in; the sound can be turned off in the user menu).
64. **Visit page**: on *My week* click a patient: the visit page shows the history and the plan, and the next step: *Restorative or other treatment* (with or without a bill) or *Surgery chart* → the suggested prescription → the post-op instructions.
65. **Visits without notes**: yesterday's visit of Dr. Mona has nothing written: a yellow banner says so; *Write them now* lists it. After one hour the dentist is reminded, after one day the head of CIA and the team head.
66. **Bill for the procedure**: record a treatment and choose a paid service under *Bill*: the reception sees it to collect.
67. **Photos by session**: *Photos* of the newest surgery patient: the sessions bar has the right side (46) and the left side (36) apart. *New session*, change the teeth, upload: it goes to the new session. *Show all* shows everything. Write a name under *Steps that are not on the checklist* to add your own shot.
68. **Operators**: on a surgery chart, *Operator 2 (other teeth)* is for a dentist working on other teeth; choose him as *operator of this tooth* on his teeth. Each dentist's file counts his own teeth. Change the operator of a saved surgery or treatment: it goes to the head of CIA for approval.
69. **Lab request**: from a patient, *Lab request*: the patient is filled in. Choose *VITA 3D-Master*: the shade list changes. The date needed back comes from the work type (Settings → Lab work types → usual days).
70. **Implants from stock** (surgery chart): choose *Osstem TS III*: *Implant from stock (lot)* lists the Osstem implants in stock with size, lot, expiry and how many left. Choose one: the size and lot fill in. Save: the stock item goes down by one (Stock → the item → *Lots in stock*). Remove the tooth and save: it goes back.
71. **Prostheses**: open the dental chart of the patient with implants 46 and 47: *Prostheses on implants* shows the bridge 45–47 (2 implants, 3 units, 1 pontic), and 45 is a pontic on the chart. *Add* → *Bridge on implants*, teeth 34-37, tick the implants: the line under the form counts units, implants and pontics. Stage *Delivered* marks the implants loaded. Try *Full arch — overdenture* (choose the jaw).
72. **Complaints**: as **dentist1** the list says *You see the complaints about you only*; another dentist's complaint does not open. As **headcia** all are listed.
73. **Case finder** (headcia / owner): the cards show patients, surgeries and cases; *By procedure* counts cases, surgeries and patients per procedure. Click *Open sinus*, then click it again. *Prostheses on these implants*, and the *Prosthesis on it* filter in *Implant*.
74. **Balance sheet** (owner): *Reports → Balance sheet*: income and costs per place (academy, private clinic, CIC), Fawry's percentage, bills paid through Fawry, purchases and the net; how the money came in; what Fawry still holds; what is still owed. Set the Fawry percentage in *Settings → Clinic options*.
75. **Tablet**: open the system on a tablet on the same Wi-Fi (the address the trial window prints) in landscape: the visit page, the chart and the surgery chart fit the screen.

## N. New in this version (4): the new look
76. **Home** (dentist1): "Good morning / Good afternoon / Good evening, Dr. …". The boxes appear one after another and the numbers count up. The **Hint** box says what to do on the page: close it with ✕, or turn all hints off from the user menu (*Hints: on* → *Hints: off*; pressing it again brings them all back).
77. **Colours**: Patients teal, Schedule blue, Clinical purple, Complaints rose, Academy amber, Stock and purchases orange, Reports indigo, Settings grey. The menu, the icon of the page title and the line under it share the colour; the menu entry of the open page is marked.
78. **Tablet** (a real tablet, or a browser window under 1200 px): the bar at the bottom has *Home*, *My visits*, *My patients*, *Treatments* and *Menu*. *Menu* slides the full menu in from the side. As **owner** or **headcia** the bar has *Home*, *Reception*, *Patients*, *Reports*.
79. **Forms on a tablet**: *Record treatment* and the surgery chart have bigger boxes and tick boxes; on long forms *Save* stays at the bottom of the screen. The tooth picker buttons are taller.
80. **Tooltips**: with a mouse, rest on an icon button (the bell, print, approvals): a short label says what it does. On touch screens they do not appear.
81. **Links that open**: as **dentist1**, open one of your surgery charts: your name is a link to your file, the other operator's name is plain text (his file is closed to you). As **owner** both are links. As **secretary**, a dentist's file lists the cases with links to the patient file, not to the chart.
82. **Log-in page**: the CIA panel beside the form, and the eye button to show the password.

## O. New in this version (5): CIC, the Cairo Implant Center
All the steps are in **[cic-test-checklist.md](cic-test-checklist.md)**, sections C, D and F. In short:
83. **Moderator** (`moderator`): *Clinics → Doctors' shares*, the statement of each doctor with the payments to him, *Doctors' fee rules* (a percentage, a fixed amount per service or tooth, or per visit), and the *Clinic report*.
84. **CIC doctor** (`cicdoctor`): *Clinical → My shares* opens his own statement.
85. **dentist2** works at CIA and CIC: the place button next to the logo, and his CIC share under *My shares*.
86. **Owner**: *Settings → Places*, *Fawry machines*, the "only at" column of *Paid services*, "works at" of people and dentists; the balance sheet counts payments where they were paid and the payments to the doctors as a cost.

## P. New in this version (6): speed and safety with a lot of data
Delete the `data` folder and run `trial-windows.bat` again to get the new sample data.
87. **X-rays & CBCT** (as **dentist1**): open patient **CIA-00005** → the tab **X-rays & CBCT**: the panoramic X-ray, a CBCT kept on the server (the folder, with a copy button: paste it in the CBCT viewer or File Explorer) and a CBCT on the centre's viewer (*Open the scan*).
88. **Photos**: open a patient's *Photos*. The grid shows small copies (they load as you scroll); tapping a photo opens the original at full size. The *Log book* and the *Case report* use a larger copy, still sharp when printed.
89. **Owner, backup**: the home page shows a small green line *Backup OK (last: …)*. *Settings → Backup and export*: a box for **All the data (ZIP)** and one for **Copy of the photos and files**, each with the last good backup, and under them *Last backup runs*, with a failed night 4 days ago (*No space left on device*). Press *Make a backup now*: a new ZIP appears in the list.
90. **Owner, when the backup stops**: the trial PC has no nightly backup, so about a day after loading the sample data the home page shows a red box *Check the backup* with a link to *Backup and export*. *Make a backup now* turns the data part green again (on the real server the nightly backup keeps both green).
91. **Owner, speed**: the home page, *Reports → Balance sheet*, *Money*, *Visits* and *Clinics → Doctors' shares* open at once. To try them with **10,000 patients**, on the trial copy only: close the trial window, open a command window in the project folder and run `.venv\Scripts\python manage.py fill_big_data` (about half a minute), then start `trial-windows.bat` again. The pages should still open in about a second. Delete the `data` folder afterwards to go back to the normal sample.
92. **Owner, problems**: *Problems* (user menu) has a hint at the top. A page that stops with an error is still recorded there, the owner is notified, and it is also written in `data\logs\errors.log`; a page slower than 3 seconds is written in `data\logs\slow-pages.log`.
93. **Test copy** (whoever installs the system): on the server, `deploy\windows\test_copy.bat` starts a copy with today's data at `http://<server-ip>:8001/`. Every page there has a yellow **TEST COPY** banner, and the page title starts with [TEST].

## Q. New in this version (7): the file step by step, bills, WhatsApp and photos
Delete the `data` folder and run `trial-windows.bat` again to get the new sample data. Log in as `dentist1`.
94. **The file, step by step**: open the new patient **هشام فؤاد عبد الحميد** (search "هشام"). Under the name: *The file, step by step*: 1 Medical history (done), 2 **Dental history (next)**, 3 Dental examination, 4 Treatment plan, 5 Surgery chart (only when an implant is planned). Press *Dental history*: save it with **Save and go to the next step**, then the examination, then the plan.
95. **The medical history is the dentist's**: *Take the medical history* / *Dental history* are two short pages. The reception sees only a medical summary (diseases, allergies).
96. **Implant icon**: the surgery buttons and the surgery days show a small implant (crown on a screw) instead of scissors.
97. **Export the file**: *Export the file* → Word, **Excel** (one sheet per part) or **PDF** (the case report, saved as a PDF of several pages).
98. **Write a bill, without the payment**: on the patient or the visit page, *Write the bill*: choose the services and **Send the bill to the reception**. The reception is told and takes the money.
99. **WhatsApp from the tablet**: on a prescription, the instructions or a bill, **Ask the reception to send it on WhatsApp**: the reception gets it in their WhatsApp list; you are told when it is sent.
100. **A5 prescription**: the prescription prints on A5, with **Rx** before each drug; *Save as a picture* / *Save as PDF*.
101. **CBCT requested**: in a new examination tick *CBCT requested* and save: the **CBCT request opens** to print. Where CIA has the CBCT machine, the request can be marked *Done in our clinic*; with the folder written, the examination shows **CBCT done** with the folder to open.
102. **One tooth left**: on the dental chart, *Mark many teeth at once* → choose tooth 33 → **All the other teeth are missing**. Implants are not touched; *These teeth are present* undoes it for the teeth chosen. Each tooth keeps the change in its history.
103. **Chart history in English**: the chart history ("sound → caries MO"...) reads in English for you even when it was written from an Arabic page.
104. **Edit a photo before the log book**: *Photos* → the crop button 🔲 under a photo: draw a frame (4:3 fits the log book), turn, mirror (mirror shots), lighter / contrast / colour, then *Save the photo*. The original is kept: *Put back the original* undoes it. (The trial copy has no photos: upload one first.)
105. **Bookings to approve**: as `dentist2` (Dr. Sherif), the home page shows **Bookings to approve**: a booking on a Friday, not his day. Open it: *Approve* or *Refuse* (the reception is told).
106. **Owner / head**: a booking outside a dentist's days also waits for the head of CIA; the owner sees a receipt's changes and every cancelled or refunded receipt in the notifications.

## R. New in this version (8): El Khadem Dental Clinic and the specialists
The whole of El Khadem is in **[khadem-test-checklist.md](khadem-test-checklist.md)** (log in as `amr` or `endo`). For
the CIA dentists, the heads and the owner:
107. **Specialty and title**: *Academy → Dentists → a dentist → Edit*: choose his **specialty** (endodontist, TMJ
     specialist, orthodontist, oral surgeon, prosthodontist…) and write his **title** (e.g. *Lecturer of endodontics*).
     They show on the dentist list, the letters and the printed plan.
108. **Specialists** tab on a patient's file (at every place): refer the patient to a specialist, or open an
     **endodontic chart**, a **TMJ examination**, an **orthodontic case** or a **shade**. *Clinical → Specialist cases*
     lists them.
109. **The treatment plan for the patient**: open a plan → **Plan for the patient**: an A4 page with the place's
     letterhead, the diagnosis, the chart, the phases with the doctor and the fee of each step, the total and the
     duration, the other options and the consent. *Edit* a plan: the diagnosis, the duration, the other options, and on
     each item **By the doctor** and **Fee**; tick **Comprehensive case** to print the treatment team. **العربية**
     prints it in Arabic for the patient.
110. **The lab request asks for more**: the stage (final, framework try-in, bisque try-in…), the **shade of the three
     thirds** tapped on the coloured tabs of the guide, the **stump shade**, the finish line, the pontic, the occlusion,
     the retention and parts on implants, and **what is sent with the work** (impression, scan, bite, photos…).
     **Print lab form**: the letterhead, the teeth on a small chart, the shades in colour and three signatures.
111. **Owner, the look of a place**: *Settings → Places → El Khadem*: the file prefix (EK), the line under the name,
     the e-mail, the **look of the screens** (standard / elite), a colour, a **logo**, the opening hours, the closed
     days and *rooms are shared*. Switch the top bar to **EK**: the screens become navy and gold.
112. **Owner, a PC's login page**: open `http://localhost:8000/login/?place=EK` once: that PC then shows El Khadem's
     login page, and logging in there opens El Khadem. `?place=CIA` puts it back.
113. **Owner, approvals**: *Changes to approve* shows the place of each change. The changes of El Khadem's reception are
     approved by Dr. Amr (`amr`), and the owner sees all of them.

## S. New in this version (9): the dental lab, the dashboard, an easier system
The whole lab is in **[lab-test-checklist.md](lab-test-checklist.md)** (log in as `labhead`, `labmanager` or `labsec`).
For the CIA dentists, the heads and the owner:
114. **Login page**: `http://localhost:8000/login/` shows the **four places** (CIA, El Khadem, CIC, the lab). Tap one:
     the page takes its look, and that place opens after logging in.
115. **Dr. Sherif designs for the lab** (`dentist2`): besides his CIA menus he has **Dental lab → My lab work**: the
     cases given to him. Open one and press **Done: go on to milling** when the design is finished.
116. **A lab request to our lab**: as `dentist1`, make a lab request to *Our dental lab*; as `secretary`, send it. On
     the request, a line shows **where the work is at our lab** (on the way, design, milling…), since when and the date
     promised.
117. **Owner / head of CIA, the Dashboard** (*Reports → Dashboard*, or the tile on the home page, or the bottom bar on a
     tablet): every place side by side for **Today, 7 days, This month** or any dates: booked, visits finished, did not
     come, new files, **paid** (owner only), complaints; a column for each day (rest the mouse on one, or *Show the
     numbers*); the lab; and **Waiting for someone now** (approvals, late lab work, complaints, low stock, passwords).
118. **Back**: open a patient, then a plan, *Edit*, save: **Back** returns to the patient's file (not the edit form).
     The browser's own back button, too, does not show the saved form again.
119. **Saving once**: on a slow network, tap *Save* twice: the button says *Saving…* and only one record is made.
120. **Owner**: the place button in the top bar has **LAB** too: the lab's home page, board and report.

## T. New in this version (10): medical follow-up, the surgery design, delivery checklist, the file step by step
Log in as `dentist1` (Dr. Mona) unless written otherwise.
121. **Medical follow-up** (*Patients → Medical follow-up*, tap **All the patients here**): *Readings above the limits*
     shows **CIA-00025** (HbA1c 8.4%, above 7%); *Waiting for the physician* shows **CIA-00026** (blood pressure
     172/104, letter sent 6 days ago); *Postponed* shows **CIA-00028** (HbA1c 9.8%, check again in 5 days). CIA-00027 is
     **cleared** (fit with precautions).
122. On CIA-00025 press **Write the consultation**: the reason (HbA1c), the history and readings, the anaesthesia
     (**Artinibsa 4%**) and the medicines after the surgery are already written. Tick *Implant placement* and *Sinus
     lift*: the medicines change (nose drops added). **Save and print the letter**: an A4 letter in English with the
     place's logo and the physician's reply part (fit / precautions / postpone / not fit).
123. As `secretary`, open the letter (from the patient's file or the follow-up list) → **Record the physician's
     answer**: *Fit, with precautions*, write the precautions, take a photo of the paper. Dr. Mona gets a notification;
     the patient's file shows a green box.
124. Take a medical history with **HbA1c 8** or blood pressure **170/100** on any patient: after saving, a yellow message
     says a physician's opinion is needed, and the patient is on the follow-up list. *Not needed* takes him off.
125. **The surgery design**: open **CIA-00029** → its surgery chart **SUR-00015**: the upper arch drawn with 6 implants,
     the teeth between them **P** (pontics) and a blue bar (a full arch). The dental chart shows those teeth as
     **pontics**, not missing, and *Prostheses on implants* has the **full arch planned** by itself.
126. **A new surgery chart** (on a tablet if you can): tool **Implant**, tap 16, 14, 24, 26; tool **Extraction** on 46;
     **Extraction + immediate implant** on 36; add **Closed sinus** to 16; press **Pontics in the gaps**: 15 to 25
     become pontics. Choose the **implant company** once. Press **Sizes and lots: implant by implant**: tap 4.0 and 10,
     tap a lot **from our stock** (or type one, or **Take a photo of the sticker**), torque, **Next implant**… *Same as
     the implant before* copies the size. Save: the chart, the planned prosthesis, and the message.
127. After the surgery the flow goes to the **prescription**, then the **instructions**: the box says the **next
     visit** (after a sinus lift: 2 days; otherwise suture removal after 7 days) and it is printed on the sheet. Press
     **Ask the reception to book it**: the patient is on the reception's list (*Patients the dentists asked for*).
128. **Delivery checklist**: on **CIA-00014**'s dental chart, *Prostheses on implants* → **Deliver: the checklist**:
     three points are ticked already. Tap the others (a screw-retained crown shows *torque* and *screw holes sealed*,
     not *cement*), write the torque, **Save: delivered**: the implant becomes **loaded**. CIA-00005 shows a finished
     checklist.
129. **The patient's page**: few buttons now: the yellow **Next: …**, *Dental chart*, **Record** (treatment, surgery
     chart, lab, CBCT, tests, consultation, prescription, instructions) and **The file** (photos, case report,
     specialists, Word / Excel / PDF).
130. **The file step by step** on **CIA-00031**: medical history and readings ✓, dental history ✓, examination ✓,
     **impression or diagnostic scan** ✓ (a scan was taken), **CBCT** is next: tap it: *CBCT taken here* or *Ask a CBCT
     from a centre*, or *Not needed: next step* → the **plan** (with the two ticks *planned on the CBCT* and *dental
     chart checked again*). A new patient's medical history starts with **today's blood pressure and blood sugar**;
     the examination page folds the histories taken just before.
131. **Treatments by kind**: *Record → Treatment step*: tap **Endodontics (root canal)**, then **Access, cleaning and
     shaping**, tooth 36, save: the step's page asks for the **periapical X-rays** (before, working length): each box
     opens the tablet's camera. **CIA-00030** has a root canal in two steps with its X-rays (one still to take).
132. **Logos**: the login page tiles and the top bar of **CIC** and the **lab (GDIL)** show their logos; a CIC bill,
     prescription or CBCT request prints CIC's logo.

## U. New in this version (11): protection from hackers, the data kept safe, smooth and fast
Log in as `owner` unless written otherwise. For the steps with "another browser", use a private window.
133. *Settings → Security and health*: the **checks**, each green or yellow with what to do. On the trial some are
     yellow on purpose (test mode on, the trial's secret key, no second backup disk, everybody uses `demo12345`).
     `python manage.py security_check` prints the same list on the server.
134. The **security log** of the sample data: the secretary's two wrong passwords then her login, **admin** closed
     after 5 wrong passwords from 192.168.1.77, a visit **from outside** the clinic's network (41.33.12.5) refused,
     `secretary2` refused on the money report, the owner's Excel downloads, Dr. Mona's password change. Filter by
     *What* or type a username or an address.
135. **Wrong passwords**: in another browser log in as `secretary` with a wrong password 5 times. The next try, even
     with the right password, says the login is **closed for 15 minutes**. You get a red notification; *Closed after
     wrong passwords* shows `secretary` → **Open**: she can log in at once.
136. **Who is logged in now**: with `secretary` logged in in the other browser, you see two lines (device, since, last
     used). **Log out** on her line: her next click opens the login page. *Log out everyone else* does it for all.
137. **A PC left open**: *Clinic options → log out after (minutes without use)*: set **1**, leave the page 2 minutes,
     then click a link: the login page says you were logged out, and after logging in you are back on that page. Set
     it back to **60** (0 = never).
138. **Easy passwords**: every sample login uses `demo12345`, so a yellow notice asks to change it (its × hides it for
     now). **Change my password** with a stronger one: the notice goes, and the check turns green when nobody is left.
     Tick *people with an easy password must change it*: at their next login they must choose a new one first.
139. **Deleted records** (*Security → Deleted records*): the referral letter the secretary deleted yesterday: open it
     to see what it held, who deleted it, when and from which page. Delete a document on any patient: it is at the top.
140. **Files taken out**: download a patient's file as Word or Excel (*The file*): the security log shows *Data taken
     out* with the file's name. The same for the backup ZIP, the Excel of all the data and the photo ZIPs.
141. **Uploads checked**: rename a text file to `photo.jpg` and upload it as a patient document or a photo: refused,
     *not a real picture or PDF*. Real photos, PDFs and the lab's scans still go in.
142. **Nothing typed is lost**: open a long form (e.g. a medical history), type, then stop the server (close its black
     window) and press Save: the page fails. Start the server, open the same form: a yellow bar says what you typed
     was not saved → **Put it back** fills it again. After a good save the bar never comes.
143. **Backups checked and copied**: *Settings → Backup*: last night's sample backup says *checked: 52,406 records
     read back* and *Second copy: F:/CIA second copy/…*. **Make a backup now**: the new line says checked too. Set
     `BACKUP_COPY_DIR` in `.env` (another disk) to get the second copy.
144. **Health** (on the Security page): the database's size, the free space on the photo and backup disks, the page
     errors and the slow pages of the last day.
145. As `headcia` or `dentist1`, open `/settings/security/`: refused (and written in the log). Pages open a little
     quicker on the tablets (they are sent compressed).

## V. New in this version (12): a finer, calmer interface
146. Open **Patients**: the *Under treatment* labels are soft green with a small dot; the file numbers and names are
     not underlined until you point at them.
147. Open the home page: the big buttons sit in the middle, and the red numbers (WhatsApp...) are still solid red.
148. Press **Tab** on any page: a clear ring follows you from button to field. Click with the mouse: no ring.
149. Move between two pages in Chrome: a short soft fade. Switch animations off in the device settings: no fade.
150. At 1024 and 768 px (a tablet): nothing scrolls sideways, and the labels stay readable.
151. On a wide screen (1200 px or more) the menu is a **dark rail** at the side. Tap *Schedule*: its group opens like a
     drawer and the *Patients* group closes. Open a page of a group, e.g. *Appointments*: the group is open and the
     page is marked. Tap the person at the bottom: the menu opens **upward**. Tap the place name at the top: the
     places open under it.
152. Switch to **العربية**: the rail is on the right. Log in as `amr` or `khadem`: the rail is navy. As `labhead`: teal.
153. On a tablet (1024 px and less) nothing changed: the top bar, the bottom bar and the slide-in menu.
154. **Home page**: a coloured welcome band with the date, the place, your role and (for the owner) *Backup OK*. As
     `owner`, the bookings to approve are a list with their number; the quick buttons are white rows: point at one and
     its icon fills with colour and an arrow shows. As `dentist1`: the band, then the numbers and *My week* (names not
     underlined).
155. On a 1366 px screen the rail shows **icons only**: point at it and it opens over the page; leave it and it
     closes. Tap the small button at its top to keep the names; open another page: it stays as you chose.
156. **Patient file** (`/patients/121/`): the card at the top has a blue round picture (a man), the name, the file
     number, *Under treatment*, *34 years*, the dentist and the opening date. Change the tab: a coloured line moves
     under the open one.
157. **Day planner**: bookings are soft cards with a coloured edge; arrived = yellow, in the room = blue-green, left =
     grey, did not come = red. In English the left arrow goes to the day before.
158. On a tablet (1024 px) the top bar is dark in the place's colour (navy at El Khadem, teal at the lab).

## W. New in this version (13): the ID card read, signatures, prices and returns, the finders
159. **The owner's home** (`owner`): the **four places** side by side, the same size: CIA, El Khadem, CIC and the lab.
     Switch to **El Khadem** (the place at the top of the menu): CIA is still there; the El Khadem card is outlined
     (*you work here now*); *Work at CIC* switches to CIC. At 1024 px they are two by two.
160. **Finders** menu: four pages with tabs between them. *Plans: implant and surgery* offers only implant and surgery
     procedures; *Plans: restorative* only the restorative ones (crowns, fillings, root canals…).
161. **Cases and statistics: implants**: *Group quickly* → **Full arch or not** (a full-arch prosthesis, or 4 implants
     or more in one jaw), **Guided or freehand**, **Crown, bridge or full arch**, **Splitting**, **Expansion**, **Sinus
     lift**, **Immediate or delayed**: each group with its survival, loading, torque and ISQ. Quick searches: *Full-arch
     cases*, *Guided implants*, *Single crowns*, *Bridges*, *Splitting cases*, *Expansion cases*.
162. **Cases and statistics: restorative**: every restorative step of the treatment log by kind of work (tap
     *Fillings* to keep only the fillings), *Group quickly* by step, operator, material, tooth type or month, the
     prostheses on implants (kind, units, delivered, material, retention), and *Export to Excel*.
163. **My signature** (`dentist1`): user menu → *My signature*: sign with the mouse or a finger, save. Print a
     prescription of yours: your signature is on it. A doctor without a login (*Academy → Dentists → Dr. Hala Mostafa*):
     the owner presses *Signature* on his page and he signs on the tablet.
164. **Lab request**: on a patient's file a *Lab request* button with the new icon (a sheet with a tooth) beside *Dental
     chart*; the same icon in the menu and on the lab pages.
165. **Complaints** (`dentist1` or `headcia`): tap a complaint in the list: it opens in place with a comment box; the
     comment shows at once and the reception is told.
166. **Fawry** (`owner`): *Patients → Fawry machine*: at the top the percentage box (change 1.5 to 1.75 and save); a
     *Done by* column and filter. As `secretary`: only her own moves, without the money held at Fawry.
167. **Prices** (`owner` or `stock`): *Stock → Price changes*: the articaine went up **16.7%** (18 → 21, invoice
     INV-1043) and the tea went down; the bell has *Price up 16.7%*. The articaine's page shows *Prices paid*.
168. **Returns** (`owner`): *Purchases → Returns to suppliers*: #1 waits for the refund (step 2), #2 is finished with a
     credit of 36; the supplier's page says *Our credit with him: 36.00*; the balance sheet of this month has *Given
     back by suppliers*.
169. **Problem reports** (`owner`): the secretary's report has a picture of the page; a report with a video plays on
     the page. Report one yourself with *Picture of this page*.
170. **WhatsApp**: *Schedule → WhatsApp* → *Send*: WhatsApp opens with the message (it opened a blank page before).
171. **Registration** (see the secretary's checklist, section X): the ID card read by the camera, the required boxes,
     the city list, the visit preferences.

## X. New in this version (14): one place at a time, the lab's day, photo pages, settings by place, time in the system
172. `owner`: the home page opens on **All places**: a card for CIA, El Khadem, CIC and the lab, and the shared low
     stock; no reception buttons. **Open EK** on its card: only El Khadem shows (its reception, visits, doctors'
     shares); no academy (it is CIA's). The tabs above (*All places*, CIA, EK, CIC, LAB) and the top-bar switch do the
     same; *All places* brings the summary back.
173. `owner`: **Open LAB**: only the lab's home and menus (stock, the lab, reports); patients, reception, academy and
     finders are not in the menu at the lab. *End of the day* there opens the **lab's** day.
174. `dentist1`: the patient with the **ten demo photos** (the first CIA surgery's patient) → *Case report* → **Save as
     PDF**: choose **4 on a page** → the page opens again and the PDF is saved: the dental chart first, then the photos
     4 on each page (a stage with more goes on to a *continued* page). Try **6 on a page** and **Print** too.
175. *Photos → Log book*: *Print* / *Save as PDF* ask 4 or 6 the same way; change a description first: it stays.
176. **Edit a photo on the tablet**: the *Edit* button under a photo → drag a **corner** of the frame (any of the
     four) to crop, drag inside it to move it, turn, lighten → *Save the photo* (it stays at the bottom of the screen).
     The small crop button on the photos of a treatment step and of a surgery opens the same and comes back there.
177. `owner`: *Settings → Access by role*: choose a role on the side; each part has **Normal / Read only / No access**.
     Change two parts for the secretary → *Save* → the role shows how many parts are limited.
178. The dental lab has a new icon (a tooth on a model base with a brush) in the menu and on its pages.
179. `owner`: *Settings*: the main settings as tiles, then a card for **each place** (people, doctors, rooms, the
     services only it gives, name, look and hours; the lab: staff, work types, prices, options), then the lists in
     groups: type "room" in **Find a list**. *Rooms* on the CIC card shows only CIC's rooms.
180. `owner`: *People and logins* → the **LAB** tab: Dr. Sherif Nabil (`dentist2`, a CIA dentist who designs for the
     lab) is there, with the CIA and LAB badges.
181. `owner`: *Settings → Time in the system*: each person this week: times opened, first and last, **open** and
     **worked** time and the part worked; three are *in the system now*. Tap a name: each time, how long, the pages,
     the place, how it ended (logged out, logged out for no use, closed the page). Log in as someone else in another
     browser, open pages, come back: that person is in the list.
182. A tablet held sideways (or a PC 1280 px wide): the *Settings* pages no longer have the person's menu open over
     them.
183. **Up**: at the top of every page *Up* (with the page's name) opens the page above: from a visit or an edit form
     the patient's file, from a receipt the payments, from a lab case the lab cases. The browser's back button still
     goes back one step.
