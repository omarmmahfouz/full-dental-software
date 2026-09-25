# Dentists, supervisors and owner: test checklist

Start the trial with `trial-windows.bat` (see the README). All passwords are **`demo12345`**.
The practice database already has everything below, so every screen has something in it:
- dentists of every type
- dental charts and treatment plans
- 14 implant surgeries, with implants at every stage and one failed implant

| User | Who |
|---|---|
| `dentist1` … `dentist4` | course candidates of batch IMP-2026-A (10 implants required each) |
| `dentist5` | training dentist (helps, does not pay) |
| `dentist6` | full-time dentist |
| `supervisor` | supervisor |
| `owner` | owner |

If you used an earlier trial, delete the `data` folder first so the new sample data is created.

When something is wrong or missing, note three things:
- the **step number**
- **what you did**
- **what you expected to happen**

A screenshot helps a lot.

## A. Language
1. Log in as **dentist1**. Every screen should be in **English**, left to right.
2. Open the user menu and click **العربية**. The screens switch to Arabic. Log out and log in as **secretary**: still Arabic. Log in again as **dentist1**: Arabic, because it remembers the choice. Switch back to English.

## B. Dental chart
3. Open **Patients → My patients** and open a patient. Click **Dental chart**.
   - Missing teeth have an X, fillings are blue and caries are red.
   - Implants show a screw: grey while healing, with a green crown once loaded.
   - Planned treatment shows as blue tooth numbers. The legend is under the chart.
4. Click a tooth, e.g. **17**. Tick *caries* with surface *D*, and save. The chart shows it, and **Chart history** shows *17: … → caries* with your name.
5. Click **Examination & history**.
   - The medical history is already filled in from the last examination or from what the patient told the secretary.
   - Write teeth in *Missed* (e.g. `18, 28`), keep **Write these teeth onto the dental chart** ticked, and save. Those teeth become missing on the chart.

## C. Treatment log: the chart follows the treatment
6. On the chart, click **Record treatment**. Choose *Composite restoration*, teeth `17`, surfaces `D`.
   - Before saving, the box **Dental chart changes** should show *17: caries D → filled composite (D)*.
   - Save with **Update the dental chart** ticked. Tooth 17 is now filled.
7. Record *Extraction* on a sound tooth. It becomes **missing**.
8. Open a patient with an implant (see step 13). Record *Implant failure / removal* on that tooth.
   - The preview says the tooth becomes **missing** and the implant becomes **Failed / removed**.
   - After saving, check both on the chart and on the implant.
9. Record a treatment with **Update the dental chart** unticked. The treatment is saved, but the chart does not change.
10. Try to record a treatment choosing **another dentist** as operator, without yourself as assistant. It should be refused, because you can record only work you did, assisted or supervised.

## D. Treatment plan
11. On the chart, click **Treatment plan**.
    - Add *Composite restoration* on `25` (phase 2) and *Implant placement* on `36, 46` (phase 3). Save.
    - The planned teeth show in blue on the chart.
12. Record *Implant placement* in a surgery chart for **36 only** (see E).
    - The plan item for 36 is ticked **done** automatically, and 46 stays planned.
    - Log in as **supervisor** and click **Approve plan**.

## E. Implant surgery chart
13. Open **Clinical → New surgery chart**. It follows the CIA paper chart.
    - The team: instructor, operator 1, operator 2 and assistant. A candidate appears as *name — batch*.
    - For each tooth, tick the procedures (extraction, flap, simple / immediate / guided implant, expansion, splitting, closed / open sinus, GBR).
    - Fill in the implant type, diameter, length, lot, sticker photo, torque and ISQ.
    - Use **Add tooth** for more teeth.
    - Open the GBR, sinus, membrane, soft tissue and suture sections.
14. Try these mistakes. Each should be refused with a clear message:
    - an implant ticked without its size
    - the same tooth twice
    - the same dentist twice in the team
    - a bone *mix* without the % autogenous
15. Save.
    - The surgery gets a number (SUR-…).
    - The chart shows the implants, and extracted teeth become missing.
    - The surgery page looks like the paper chart, and **Print surgery chart** prints it.
16. Open an implant from the surgery page, the implant list or the chart.
    - It shows its stage: *Placed – healing → Uncovered → Impression / scan taken → Loaded*, or *Failed*, with the dates.
    - Record *Second stage / healing abutment*, then *Digital scan*, then *Final prosthesis delivery* on that tooth in the treatment log. The stage moves forward by itself each time.

## F. Photos and case report
17. On the chart, click **Photos**. You should see the 8 stages of the CIA photo checklist, e.g. *1st visit (diagnostic)*. Upload a photo and a short video for one item. Items with a photo get a green tick.
18. Click **Case report**. It shows the whole case: chart, plans, surgeries with the team and implants, and treatments.
    - Click **Hide patient identity** and check that the name and mobile disappear.
    - Print it or save it as a PDF.

## G. Dentist file
19. As **dentist1**, open **Clinical → My cases and implants**. You should see:
    - the batch
    - implants placed as operator 1 against the 10 required, with a progress bar and **implants remaining**
    - surgeries in each role
    - every case, with a case report link
20. As **dentist1**, try to open another dentist's file, e.g. change the number in the address bar. It should be refused.
21. As **secretary**, open **Academy → Dentists**. All types are listed with their surgeries and implants.
    - Add a *training dentist*.
    - Open a candidate from **Academy → Candidates**. The **Cases and implants** button opens the same dentist file.
22. As **owner**, open the new training dentist and click **Create login**. The username and first password are shown once.

## H. Supervisor
23. As **supervisor**, open **Clinical → Treatment log** and tick *Not checked yet*. Open a treatment, grade it and add a comment.
24. Open **Reports → Dentist follow-up**. Filter by type *Course candidate* and by batch. For each dentist, check:
    - surgeries and implants
    - the **remaining** implants for the course
    - failures, treatments, the share checked and the grade

## I. Case finder & statistics (owner and supervisors)
25. Open **Clinical → Case finder & statistics**. The top cards show the implants, the survival %, the loaded implants and those waiting, the mean days to loading and the mean torque.
26. Click the quick searches:
    - *Healing – waiting 2nd stage*
    - *Uncovered – waiting impression / scan*
    - *Impression taken – waiting delivery*

    Each gives the list of patients waiting for that step.
27. Combine filters: gender *Female*, company *Dentium*, procedure *GBR*, diameter from 4, jaw *Lower*.
    - Set **statistics by** *Implant company*, then by *Implant status*.
    - The table shows the survival % and the days to loading for each group.
28. Click **Export to Excel (CSV)** and open the file in Excel. There is one row per implant, with every detail, and the Arabic names are readable.
29. Save the search under a name. It appears under **Saved searches** for the other managers too.
30. As **dentist1**, the Case finder should not be available.
