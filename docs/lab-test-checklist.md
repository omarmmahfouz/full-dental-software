# The dental lab — test checklist

Start the practice copy with fresh sample data: delete the `data` folder, then run `trial-windows.bat`
(or `sh trial-mac-linux.sh`). The password is `demo12345` for every login.

In the sample data:
- **Dr. Hossam** (`labhead`) is the head of the lab: everything, the prices, the receipts, the costs and the report.
  He also does the quality check.
- **Eng. Karim** (`labmanager`) gives out the work: who designs, who mills… and follows the cases.
- **نورا** (`labsec`) is the lab's secretary (Arabic): she receives the cases, prints the labels, answers on WhatsApp,
  delivers and writes the receipts.
- **Dr. Sherif** (`dentist2`, a CIA dentist) also **designs** for the lab. **Dr. Nada** designs too, without a login.
  **Mahmoud** (milling, sintering, printing), **Ayman** (casting, ceramic, stain and glaze), **Samir** (models, set-up,
  processing) and **Reda** (finishing) have no login: the manager records their steps.
- **Clients**: CIA, CIC and El Khadem, each with **its own price list**, and three outside clinics (Dr. Moustafa Kamel,
  Smile Dental Center, Dr. Ramy Saad) on the **outside clinics** list.
- Six weeks of cases: most delivered, the last ones in every step, two remakes, one case at **another lab** (Alpha
  Titanium Lab), one **on hold**, one denture **at the clinic for a try-in**, and the lab's own stock and blocks.

## A. The login page with the places
1. Open `http://localhost:8000/login/`: under *Welcome* there are **four places**: CIA, El Khadem (EK), CIC and the
   lab (LAB). Tap **LAB**: the page turns teal-blue with the GDIL logo; this PC remembers it next time.
2. Log in as **labsec**: the lab opens (LAB in the top bar, Arabic). Log out, tap **CIA** and log in as **labsec**
   again: a message says she does not work at CIA, and the lab opens.
3. As **owner**, the place button in the top bar now has **LAB — the dental lab** too.

## B. The lab's secretary (`labsec`, Arabic)
4. The home page: search a case, big buttons (*Lab board*, *Receive a case*, *On the way from our clinics*, *Lab
   WhatsApp*, *New receipt*, *Blocks*), the numbers of the day, and the **late cases**.
5. **استلام حالة** (receive a case): choose *Smile Dental Center*, the doctor's mobile, the patient, *Digital* or
   *Conventional impression*, what came with the work, then the work: *Zirconia crown*, teeth 11 21, 2 units, no
   price. Save: the price is **3,600** (2 × 1,800 of the outside list), the date promised is 7 days later, and the
   case has its steps (received → design → milling → sintering → stain and glaze → quality check → ready).
   A *conventional impression* adds *models and scanning* before the design.
6. The green box says: write the number on the box or **print the label** (80 mm), then **tell the doctor**: WhatsApp
   opens with the message ready ("استلمنا شغل المريض… رقم الحالة… الميعاد المتوقع…").
7. **في الطريق من عياداتنا** (on the way from our clinics): the work CIA, CIC or El Khadem sent to the lab. Tick
   what came with one, tick *I checked the work against the request* and press **استلمناها في المعمل**.
8. **واتساب المعمل**: a doctor asks where his case is. Type the case number (e.g. **5** or **LAB-00005**) or the
   doctor's mobile: the answer is written with the **real step**, since when, and the date promised (or *late*).
   Press **ابعت الرد ده**: WhatsApp opens with it. Below: the messages still to send (cases received, ready, sent back).
9. A case **ready** on the board: press **اتسلّمت للعيادة** (or on the case page). A case of our places: its
   reception is told the work is on its way back.
10. **إيصال جديد** for *Dr. Moustafa Kamel*: the amount still owed is written for you. Save: the 80 mm receipt.

## C. The manager (`labmanager`, English)
11. **Lab board**: one column per step (on the way, to give out, design, milling / printing / casting, finishing,
    quality check, ready, away). Each card: the number, the client and doctor, the patient, the work, the step and for
    how long, **who has it**, and the date promised (red when late; a flame when urgent). Filter by person or client,
    or *Late only*. On a tablet the columns go under each other (no sideways scrolling).
12. Open a case in *To give out*: press **Done: go on to CAD design** and choose *Dr. Sherif*: he is told. A step
    with only one person (milling → Mahmoud, quality check → Dr. Hossam) goes to him by himself.
13. **Move to another step** (e.g. back to milling after a failed check), **On hold** with the reason (going on
    resumes the same step), **Send to another lab** (the lab, what, the cost, back by) and *It came back*.
14. The case page: the **steps of this case** at the top, and **Step by step: who and how long**: each step with its
    person, from–to and a bar of its length.
15. **Remake** (on a delivered case): the reason (fit, shade, contacts…) and **whose fault**: the lab's own mistake is
    remade **free**; the remake is linked to the first case both ways.
16. **Lab report**: cases received and delivered, **on time %**, late now, remakes and their rate; the **time in each
    step** (average, middle, longest); **from received to delivered by kind of work**; each person's steps, average
    time, **units designed** and remakes of their designs; the remakes by reason and fault; the **units made from each
    block**; the clients. The manager does not see the money; the head does.
17. **Lab staff**: tick the steps each person does, link a login, and (head) the fee per unit designed.

## D. The designer (`dentist2`, Dr. Sherif)
18. He keeps his CIA menus and has **Dental lab** too. **My lab work**: the cases with him, the units he designed this
    month and his design fees. Press the button on a case when the design is done: it goes on to milling (Mahmoud).
19. He cannot move a case that is not his, nor open the prices, receipts or report.

## E. The head of the lab (`labhead`)
20. **Lab prices**: one column per list (CIA, CIC, EK, outside clinics). Change a price and save. *Who uses which list*.
21. **Clients and accounts**: each client with the work delivered, paid, **still owed**, and the work still in the lab.
    Open *Cairo Implant Academy* → **Statement** for this month: the balance before, the cases, the payments, the
    balance owed; print it or **send the total on WhatsApp**.
22. **Lab receipts**: open one → **Cancel the receipt** with the reason: it stays, crossed out, and the balance
    comes back. The secretary cannot cancel.
23. **Blocks and lab stock**: the zirconia disc in use and the units made from it; *finished blocks* (e.g. 18 crowns
    from one disc, the cost per crown). **Open a new block**: one disc is taken out of the lab's stock. Take out
    liquids, stains or bond, or receive them.
24. On a case in milling: **Blocks used** → choose the block and the units: the block counts them.
25. **Lab report** with the **money**: work delivered, money received, materials used (the lab's stock), other labs,
    designers' fees and **left for the lab**.
26. **Lab options**: the three WhatsApp texts, and the **automatic answer** (see the limits in the report).
27. **Blank lab request (print)**: the universal request for outside clinics: every kind of work to tick, the teeth,
    the stage, the impression, the shade, the finish line, the pontic, implants and what is sent with the work.

## F. The clinics and the lab together
28. As **dentist1**, make a lab request to **Our dental lab**; as **secretary**, send it: at the lab it is **on the
    way** (section B7) with the CIA price, and the request's **lab cost** is filled in.
29. On the request (clinic side), a line shows **where the work is at our lab**: the step, since when and the date
    promised.
30. When the clinic's reception marks the work **received from the lab**, the lab's case is closed as delivered if
    the lab forgot; **Return to lab for remake** opens a remake at the lab, on its way.

## G. New in this version (9)
1. The dental lab opens: clients with their own prices, cases step by step with their people and times (sections B, C).
2. Designers, the manager giving out the work, the head of the lab (sections C, D, E).
3. Remakes with their reason and fault, and work sent to another lab (section C).
4. Blocks and what was made from each, and the lab's stock (section E23–24).
5. Receipts, accounts and statements of the clients (section E).
6. The lab report: times between the steps, people, remakes, money (sections C16, E25).
7. WhatsApp from the lab and the answer with the real status (section B8, E26).
8. The universal lab request to print (section E27).
9. The clinics' lab requests go to our lab and show its steps (section F).
10. The login page with the four places (section A).

## H. New in this version (10)
1. **GDIL**: the lab is now **GDIL Dental Lab — The art of dentistry**, with its logo on the login page (tap **LAB**:
   the page turns teal-blue), the top bar, the case sheet, the label, the receipts, the statements and the blank lab
   request. An older system gets the new name when `setup_clinic` runs (the update does it).
