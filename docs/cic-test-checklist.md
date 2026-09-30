# CIC (Cairo Implant Center) — test checklist

Start the practice copy with fresh sample data: delete the `data` folder, then run `trial-windows.bat`
(or `sh trial-mac-linux.sh`). The password is `demo12345` for every login.

In the sample data:
- the **secretary** works at CIA and CIC;
- **Dr. Sherif** (`dentist2`) works at both places and gets 30% at CIC;
- **Dr. Walid** (`cicdoctor`) works at CIC only and gets 1,500 per CIC implant and 25% of the rest;
- **Dr. Hala** has no login and gets 400 per visit;
- **Hany** (`moderator`) manages CIC.

## A. The secretary at two places
1. Log in as **secretary**. Next to the logo there is a green **CIA** button. Click it and choose **CIC — مركز القاهرة لزراعة الأسنان**.
   - The button turns blue and the line under the top bar turns blue. A message says you are working at CIC now.
2. **Reception today** ("الاستقبال اليوم") now shows CIC's day. Dr. Walid's 12:00 patient has left, Dr. Hala's 1:00 patient is waiting, and Dr. Sherif's 6:00 patient is still to come. The rooms at the bottom are the 3 CIC rooms.
3. **Book** ("حجز موعد"):
   - The rooms list has the CIC rooms only.
   - The dentists list has the CIC doctors only (Walid, Hala, Sherif). Dr. Mona works at CIA only, so she is not in it.
   - Choose Dr. Walid and today: the green line says he works in "CIC غرفة 1" from 12 to 8.
4. Switch back to **CIA**: the board, the rooms and the dentists are CIA's again.
5. Open a CIA patient's file. Next to "حجز موعد (CIA)" there is a blue **"احجز في CIC"** button: it switches you to CIC and opens the booking with the patient filled in. Save the booking.
   - Back on the patient's file, the visits list shows a blue **CIC** badge next to that visit.
6. Log in as **secretary2** (CIA only): there is no place button, as she works at CIA only.

## B. Bills, prices and the two Fawry machines
7. As **secretary** working at **CIC**:
   - Open "المرضى" → "فاتورة جديدة". The quick buttons include **"كشف CIC"**, and the services list includes **"زرعة CIC"** and **"تركيبة على زرعة CIC"** (CIC's price list).
   - At CIA these three services are not offered.
8. Make a bill with "زرعة CIC" on tooth 36 and pay part of it by **ماكينة فوري**, without choosing a machine: a message asks which Fawry machine took it. Choose **Fawry 2** and save. The printed bill has CIC's name, phone and address at the top instead of the CIA logo.
9. "المرضى" → "مدفوعات المرضى": the title has a **CIC** badge and shows only CIC's payments today. In "المكان" choose "كل الأماكن": both places show, with a badge on each payment. The Fawry payments say which machine took them.
10. "المرضى" → "ماكينة فوري": at the top, one box per machine (**Fawry 1**, **Fawry 2**) shows what each machine still holds at Fawry. Click **Fawry 2**: only its moves are listed, with its own running balance.
    - A new move (e.g. "فاتورة مدفوعة من الماكينة") asks for the machine.

## C. The clinic manager (moderator)
11. Log in as **moderator** (Hany). His home page has a **CIC — This month** card: visits, time in the chair, what the patients paid, the doctors' shares and what is owed to them.
12. **Clinics → Doctors' shares** (place CIC, this month). One row per doctor:
    - visits, time in the chair, patients, billed, paid;
    - their **share**, what was **paid to the doctor** and what is **still owed**.

    Check the numbers:
    - Dr. Hala: 400 × her finished visits.
    - Dr. Sherif: 30% of what his patients paid, less the 500 he was paid.
    - Dr. Walid: 1,500 per implant tooth plus 25% of the consultations paid.
13. Click **Dr. Walid**: his statement lists every service with the rule used and the share, every visit with the time in the chair, and the payments to him.
    - Under **Record a payment to the doctor**, write 1,000 and save: "Still owed" goes down by 1,000.
    - Delete it with the bin button.
14. **Clinics → Doctors' fee rules**: one card per doctor.
    - **New rule**: choose Dr. Hala, *Percentage of what the patient paid*, 20, from the 1st of next month. Her old visits keep 400 per visit.
    - Try a percentage of 130: refused.
    - Try *Fixed amount for each visit* with a service: refused.
15. **Clinics → Clinic report**:
    - what the patients paid, by payment method and **by Fawry machine**;
    - visits, patients seen, new files, time in the chair;
    - the doctors' shares, the **materials used** from stock and **Left for the clinic**;
    - a day-by-day view with bars.

    Change the dates to last month and back.
16. On a tablet or a narrow window, the moderator's bottom bar has *Home*, *Doctors*, *Report*, *Fee rules* and *Menu*.

## D. A CIC doctor
17. Log in as **cicdoctor** (Dr. Walid). *Clinical* → **My shares** opens his own statement at CIC, without the payment form.
    - Opening another doctor's statement (change the number in the address) is refused.
18. As **dentist2** (Dr. Sherif, CIA and CIC): the place button lets him switch. His *My shares* shows his CIC statement.

## E. Stock of each place
19. Log in as **stock**. In "المخزن", filter **"يخص" → CIC**: the Osstem implants and the sterile drapes bought for CIC. Filter **"مشترك بين كل الأماكن"**: the shared items.
20. "صرف من المخزن":
    - "للمكان" is the place you work in. Take out 2 gloves for **CIC**.
    - Then try to take out the CIC drapes for **CIA**: refused, because they belong to CIC.
21. "حركات المخزن": the box **"استهلاك كل مكان في هذه الفترة"** shows what CIA and CIC used and its value, and each movement has its place badge.
22. As **dentist2** working at **CIC**, open a new surgery chart and choose *Osstem* on a tooth: the CIC implants are offered. At CIA they are not.

## F. The owner
23. As **owner**, the place button lists every place. *Settings*:
    - **Places**: CIC's phone and address, used in WhatsApp messages and printouts.
    - **Fawry machines**: the two machines with their terminal numbers.
    - **Paid services**: the "only at" column.
    - **People and logins**: the secretary's "works at".
    - *Academy → Dentists*: each dentist's "works at".
24. *Reports → Balance sheet*: CIC's column has its patient payments (where they were paid) and **Paid to the doctors (their shares)** as a cost.

## G. New in this version (6): quick with years of data
25. As **moderator**, *Clinics → Doctors' shares* for a whole year, and the *Clinic report* for a year: they open in about a second (before, with thousands of patients, they took 15 seconds). The numbers are the same as each doctor's statement: open Dr. Walid Hamdy's statement for the same period and compare *Share* and *Still owed*.
26. As **secretary** at CIC: "الفواتير" and "مدفوعات المرضى" for a long period show 200 rows a page, with the totals for the whole period.

## H. New in this version (7): each place apart
27. As **secretary**, switch to **CIC** in the top bar: the patient list, the complaints, the waiting list and the patients to call are **CIC's only**; CIA's patients do not show, even their names. New CIC files are numbered `CIC-…`.
28. The patient moved from CIA has a new CIC file; the old CIA file is *out*, with a link to the new one. A patient cannot be booked at CIC with a CIA file: move it first ("نقل لمكان آخر").
29. CIC has its own 4 numbered **extra rooms**, closed until booked or given a shift.
30. **End of the day at CIC**: "نهاية اليوم" shows CIC's receipts only; the day is closed for each place apart.
31. A CIC doctor who writes a bill sends it to the CIC reception, which takes the payment.

## I. New in this version (8): El Khadem, and what it adds for CIC
The steps of El Khadem are in **[khadem-test-checklist.md](khadem-test-checklist.md)**. For CIC:
32. As **moderator**, *Clinics → Doctors' fee rules → Add*: a rule can now be **for his own patients** or **for the
    patients of the clinic** (e.g. 40% / 30%), and can **take off the lab and implant cost first**. CIC's rules stay as
    they were (every patient, nothing taken off), so CIC's shares do not change.
33. *Clinics → Doctors' prices*: a CIC doctor can have **his own price** for a service; a bill with this doctor takes it
    by itself. Each service can have a **usual lab / implant cost** (*Settings → Paid services*).
34. Dr. Walid Hamdy's **statement** has a *lab / implant cost* column and says, for each service, *his own patient* or
    *clinic's patient*.
35. **Changes to approve**: when the CIC reception edits a patient's data or a visit's times, the **moderator** (who
    works at CIC) can approve it too, besides the head of CIA and the owner. The changes list shows the place of each.
36. As **secretary** (CIA and CIC): El Khadem's patients never show, and the place switch offers CIA and CIC only.
37. Printed bills and papers of CIC keep CIC's name, phone and address; the place's look is set in *Settings → Places*
    (CIC stays *standard*; a logo can be uploaded there).

## J. New in this version (9): the lab and the dashboard
38. **Login page**: tap **CIC**: the page turns blue, and the secretary starts at CIC after logging in.
39. As **moderator**, **Dashboard** (menu or the button on the home page): CIC side by side with the places he manages,
    for today, 7 days or this month, with the money paid and a column for each day.
40. The lab has **CIC's own price list** (*Lab prices*, as `labhead`): CIC's lab requests sent to our lab take it, and
    it becomes the request's **lab cost**. See [lab-test-checklist.md](lab-test-checklist.md), section F.
