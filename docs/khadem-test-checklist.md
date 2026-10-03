# El Khadem Dental Clinic — test checklist

Start the practice copy with fresh sample data: delete the `data` folder, then run `trial-windows.bat`
(or `sh trial-mac-linux.sh`). The password is `demo12345` for every login.

In the sample data:
- **Dr. Amr El Khadem** (`amr`) owns and runs the clinic: he is a doctor (prosthodontist) and its manager.
- **هدى** (`khadem`) is El Khadem's own reception. She works at El Khadem only, in Arabic.
- **Dr. Yasser Hamed** (`endo`) is the endodontist, with a login.
- **Dr. Hazem Fathy** (TMJ specialist), **Dr. Dina Sami** (orthodontist), **Dr. Tarek Nour** (oral surgeon, brings his
  own patients) and **Dr. Laila Fouad** (prosthodontist) have no login.
- Every doctor gets **40% of his own patients** and **30% of the patients the clinic refers to him**, after the lab and
  implant cost. Two patients are Dr. Tarek's own: **طارق وليد منصور** and **رنا سمير إبراهيم**.
- El Khadem has **4 shared rooms**, opens from 12:00 to 22:00 and is closed on Fridays.
- The stock and the two Fawry machines are the same for every place.

## A. The look of El Khadem and the login page
1. Open `http://localhost:8000/login/?place=EK`: the login page is navy and gold, with the El Khadem mark, the
   clinic's name and its line. Close the browser and open `http://localhost:8000/`: this PC remembers El Khadem.
2. Log in as **khadem**. The top bar is navy with a thin gold line, the El Khadem mark and its name; the buttons are
   navy. There is no place button: she works at El Khadem only.
3. As **owner**, switch the place button to **EK — عيادة الخادم**: the whole look changes to navy and gold; switch
   back to CIA: green again.
4. As **owner**, *Settings → Places → El Khadem*: the file number prefix (**EK**), the line under the name, the
   e-mail, the **look of the screens** (standard / elite), a **colour**, a **logo** (upload one: it shows on the top bar,
   the login page and every printed paper), the **opening hours**, the **closed days** and **rooms are shared**.

## B. The reception of El Khadem (`khadem`, Arabic)
5. The home page shows El Khadem only: its patients (files `EK-…`), its day, its WhatsApp messages. There is **no
   academy**: no candidates, courses or installments.
6. **Register a new patient**: under "مين رشّحك؟" there is **"مريض الطبيب نفسه (جابه)"**: choose Dr. Tarek for a
   patient he brought. Leave it on "لا: مريض العيادة" for the clinic's patients.
7. **Book** a patient with Dr. Hazem tomorrow at 13:00 **without choosing a room**: a free room is chosen by itself,
   and the booking is confirmed at once (no "not the dentist's day" approval: the rooms are shared). The green line
   under the dentist says the rooms are shared and lists his other patients of that day.
8. Book another patient with Dr. Yasser at the same time: he gets the next free room. Try to put him in the first
   room: refused, the room is taken by Dr. Hazem's patient.
9. **Day planner**: one column per room; every free place in the opening hours is green. Each patient has a small
   **⇄** button: tap it and choose another room, or **swap rooms** with the patient who is there. On a PC, drag a
   patient to another room's column.
10. Press **By doctor**: one column per doctor of the day, and each patient shows his room.
11. **Nearest free times** (on the booking page) for Dr. Hazem: the times when a room is free and he has no patient.
    Fridays are skipped.
12. **Reception today**: the rooms box shows who is **in** each room now and who comes **next**.
13. "العلاج" → **"التحويلات"**: the referrals **to book**. Open Dr. Amr's referral of **هشام فاروق عزت** to the
    orthodontist: press **"احجز مع د. دينا سامي"**: the booking opens with the patient and the doctor filled in. Save:
    the referral becomes *Booked*.
14. **New bill** for a patient with **Dr. Hazem**: the examination costs **1,200** (his own price) instead of 500.
    Choose Dr. Amr: 800.

## C. Dr. Amr, doctor and manager (`amr`, English)
15. The home page has the **El Khadem — This month** card (visits, paid, the doctors' shares, what is owed).
16. **Clinics → Doctors' fee rules**: each doctor has two rules, *40% … after the lab / implant cost — His own patients*
    and *30% … — Patients of the clinic*.
17. **Clinics → Doctors' shares → Dr. Tarek Nour**: each service says **his own patient** or **clinic's patient**, the
    **lab / implant cost** taken off, and the share. Rana's implant: 40% of what she paid less the implant cost. Change
    a cost in its box and press ✓: the share changes.
18. **Clinics → Doctors' prices**: each doctor's own prices (TMJ examination 1,200; Dr. Yasser's root canal 4,000;
    Dr. Laila's zirconia crown 6,500 with a lab cost of 1,700) and the price list of El Khadem with the usual costs.
    Add a price; a second price for the same doctor and service is refused.
19. **Schedule → Day planner**: he sees the whole day of the clinic (by room or by doctor), without booking.
20. **Changes to approve** (the ✓ icon): when the reception edits a patient's data, Dr. Amr approves it, not the head of
    CIA.

## D. Referrals
21. Open the file of **كريم مصطفى عبد الحميد** → **Specialists**. Big buttons: *Refer to a specialist*, *Endodontic
    chart*, *TMJ examination*, *Orthodontic case*, *Take the shade*, and a line with our specialists.
22. His referral **to Dr. Yasser** is answered: open it. The **letter** has El Khadem's letterhead, the reason, the
    teeth, the medical alerts, Dr. Amr's name and title, and **Dr. Yasser's answer** under it. *Print the letter*.
23. Refer a patient to **Dr. Hazem**: log in as **endo** or look at the reception: the specialist and the reception are
    told. Refer one **outside** the clinic (e.g. a radiology centre): no booking, only the letter to print.
24. As **endo**, open a referral to him and write the answer: Dr. Amr is told.

## E. Endodontics (`endo`)
25. **Specialist cases → Endodontics**: Karim's **36** (obturated) and Marwan's **11** (in treatment, calcium hydroxide
    in the canal).
26. Open **36**: the AAE diagnosis (symptomatic irreversible pulpitis, normal apical tissues), the case difficulty and
    why, the tests, the files and irrigation, the **canals drawn as bars** at their working lengths (MB 21.5, ML 21,
    D 22) with the reference points, master files and cones, and the two visits. The case is in the **treatment log**,
    and the dental chart shows the root canal of 36.
27. Open **11**, add a visit (obturation), then press **Obturated: finish the case**: the chart of 11 shows the root
    canal, and it is written in the treatment log.
28. **New endodontic chart** for a patient: choose tooth 26 and press **Add the usual canals of this tooth**: MB, MB2,
    DB and P are added. Write the working lengths and save.
29. *Print the report*: the place's letterhead, the patient, the whole case and the signature.

## F. TMJ, orthodontics and the shade
30. **Noha's TMJ examination** (Dr. Hazem): pain 7/10, opening **28 mm** on a gauge where 40–50 mm is green, clicking on
    the left, the tender muscles, the diagnosis (disc displacement without reduction, with limited opening; myalgia;
    bruxism) and the plan (splint, physiotherapy). The **follow-up** bars show the opening going up (28 → 34 → 38 mm)
    and the pain going down. Add a follow-up.
31. **Yasmin's orthodontic case** (Dr. Dina): Class II on both sides, overjet 7, the cephalometric values next to the
    usual ones (ANB 6), metal MBT brackets, 20 months expected, the time in treatment, and the adjustment visits with
    the wires and elastics. **Add a visit**: the wires of the last visit are filled in.
32. **Salwa's shade** (Dr. Laila) for 11, 21: a tooth drawn in the three shades (A3, A2, A1) and the stump ND2, the
    translucency and the characters. **Take the shade** for another patient: tap the coloured tabs of the VITA classical
    or 3D-Master guide; a 3D-Master tab is refused on a VITA classical record.
33. **Lab request with this shade**: the new lab request has the teeth, the shades of the three thirds and the stump.

## G. The printed papers
34. **Treatment plan** of Karim (*Full rehabilitation*): press **Plan for the patient**: an A4 page with El Khadem's
    letterhead, the diagnosis, the dental chart, the treatment **phase by phase** with the doctor and the fee of each
    step, the **total** (38,300), the expected duration, **Your treatment team** (Dr. Amr, Dr. Yasser, Dr. Tarek,
    Dr. Laila, each with his part), the other options explained, and the consent with the two signatures. Press
    **العربية**: the same plan in Arabic, right to left.
35. Edit a plan: each item has **By the doctor** and **Fee**; tick **comprehensive case** to show the team.
36. **Salwa's lab request**: *Print lab form*: the letterhead, the stage (final work), the date needed back, the lab,
    the doctor and the patient, the **teeth on a small chart**, the **shade tabs in colour**, the design (chamfer, light
    contacts), **what is sent with the work** (ticked boxes) and three signatures.
37. A lab request now asks for the stage (final, framework or bisque try-in…), the shades of the three thirds and the
    stump, the finish line, the pontic, the occlusion, the implant retention and parts, and what is sent with it.

## H. Shared with the other places
38. As **stock**: *Stock movements* show what El Khadem took from the shared stock (its place badge **EK**).
39. As **khadem**, a Fawry payment asks which of the two Fawry machines took it: the machines are shared.
40. As **secretary** (CIA and CIC): El Khadem's patients never show; the El Khadem reception does not see CIA's or CIC's.

## I. New in this version (8)
1. El Khadem Dental Clinic opens (sections A, B).
2. Specialties for every doctor, and the doctor's own patients (sections B6, C16–17).
3. Referrals with a printed letter, booking and the answer (section D).
4. 40% / 30% after the lab and implant cost (section C17).
5. Each doctor's own prices (sections B14, C18).
6. The interchangeable schedule of the four shared rooms (sections B7–B12).
7. The endodontic chart (section E).
8. The TMJ examination (section F30).
9. The orthodontic case (section F31).
10. The shade guide (sections F32–33).
11. The treatment plan printed for the patient (section G34–35).
12. The detailed lab request and its print (sections F33, G36–37).
13. The elite look of a place, and the login page of this PC (section A).
14. The stock and Fawry shared, the reception apart (section H).
15. The reception's changes approved by the clinic's manager (section C20).

## J. New in this version (9)
1. **The login page with the places** (the owner's choice): `http://localhost:8000/login/` shows the four places; tap
   **EK**: navy and gold, and El Khadem opens after logging in. The PC remembers the last place tapped.
2. El Khadem's lab work sent to **our lab** takes **El Khadem's price list** at the lab (*Lab prices* as `labhead`), and
   the request shows where the work is at the lab ([lab-test-checklist.md](lab-test-checklist.md), section F).
3. As **amr**, **Dashboard** (menu *Dashboard*, or the button on his home page): El Khadem this month, with a column for
   each day.
4. **Back** goes up one page (never to a saved form), and *Save* works once even when tapped twice.

## K. New in this version (10)
1. As **amr** or **endo**: *Record → Treatment step*: tap **Endodontics (root canal)**, then the step (access /
   access, cleaning and shaping / obturation / all in a single visit / pulpotomy): the step's page asks for its
   **periapical X-rays**, taken with the tablet's camera.
2. The patient's file shows the **steps of the file** (histories and readings, examination, impression or scan, CBCT,
   plan…) and a yellow **Next** button; the readings above the limits put the patient on **Medical follow-up**, with a
   ready consultation letter on El Khadem's paper.
3. A surgery chart at El Khadem is drawn like a scanner's order form (implants, pontics, extractions), with the
   **delivery checklist** of the teeth on the implants (see the dentists' checklist, section T).

## L. New in this version (11)
1. Five wrong passwords close `khadem`'s (or `amr`'s) login for 15 minutes; the owner is told and can open it.
2. El Khadem's reception PC logs out by itself after the minutes without use; a form typed when the network stopped is
   offered back (**Put it back**).
3. Whatever is deleted at El Khadem (a document, a photo, a room shift) is kept in the owner's *Security → Deleted
   records*, with who deleted it. See the dentists' checklist, section U.

## M. New in this version (13)
1. As `khadem`: *Patients → Old paper files* shows only El Khadem's packages; *Download the lists* gives El Khadem's
   patients only (`EK-…`); the cover sheets carry El Khadem's letterhead and `EK-…` numbers. A package made for CIA is
   refused here.
