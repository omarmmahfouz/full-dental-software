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
