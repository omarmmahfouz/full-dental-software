# Secretary role: test checklist

Start the trial with `trial-windows.bat` (see the README). Log in as **`secretary`**, password **`demo12345`**.
The practice database already has sample patients, callers, a room schedule and visits, so every screen has something in it.
The steps give the Arabic button names in quotes, so you can match them to the screen.

When something is wrong or missing, note three things:
- the **step number**
- **what you did**
- **what you expected to happen**

A screenshot helps a lot.

---

## A. Call list: people who call to become patients
1. Open "المرضى" → "قائمة المكالمات". You should see open callers, and the tabs "مكالمات اليوم", "جديد" and so on.
2. Click "مكالمة واردة جديدة" and fill in:
   - the name
   - 2 mobiles, and which one is preferred
   - age
   - missing teeth ("فك كامل")
   - tick two medical conditions
   - the source ("فيسبوك")
   - the next call date

   Save. The caller should appear in the list.
3. Add another caller with **the same mobile**. It should be **refused** with the name of the existing caller.
4. Add a caller with the mobile of a **registered patient**. Copy one from "المرضى" → "كل المرضى". It should be refused with that patient's name and file number.
5. Type the mobile with Arabic digits (٠١٠…) or as +20 100…. It should be accepted and saved as `010…`.
6. Open the caller and click "تسجيل مكالمة" with the result "لم يرد" and a next call date. The call should appear in "سجل المكالمات" and the status should change to "معاودة الاتصال لاحقًا".
7. The home page ("الرئيسية") should show the caller under "مكالمات مطلوبة اليوم" when the call is due.

## B. Registering a new patient
8. Open the caller from step 2 and click "المريض حضر: تسجيل الملف كامل". The name, mobiles, missing teeth, medical history and source should already be filled in.
9. Enter a real-format national ID of 14 digits, e.g. `29001150101234`. Leave the date of birth empty. Save. The birth date should be **15/01/1990** and the gender **ذكر**, and you should get a **file number** (CIA-000xx). Back in the call list, the caller is now "أصبح مريضًا".
10. Register another patient with the **same national ID**. It should be refused, and the message should name the existing file.
11. Register a patient with the **same primary mobile** as another patient. It should be refused.
12. Enter an invalid national ID, such as 13 digits or an impossible date. It should give a clear error.
13. Upload **ID scans**: both the front and the back. Use a phone photo, a scanner file or a PDF. They should show under the "البطاقة والمستندات" tab and open when clicked.
14. Choose the source "مريض عندنا (قريب أو صديق)" **without** filling in the referring patient. It should ask for it. Then enter another patient's file number or mobile, and it should be accepted.
15. Under "أقارب أو أصدقاء من مرضانا", enter another patient's file number and the relation "أخ / أخت". The link should show on **both** patients' files.
16. Choose the responsible dentist ("الطبيب المسؤول"). It should show on the file and in the patients list.
17. Use the search box at the top. Try a name, a mobile, a file number and a national ID. An exact match should open the file directly.

## C. Room schedule
18. Open "الجدول" → "جدول الغرف". You should see 5 rooms × 7 days (Saturday to Friday).
19. Click "إضافة" in a cell. Choose a dentist, a supervisor, the day type (regular or surgery day) and the hours. It should appear in the grid; surgery days show a red "يوم عمليات" badge.
20. Book the **same room** at an overlapping time for another dentist. It should be refused.
21. Book the **same dentist** in another room at the same time. It should be refused.
22. Go to next week and click "نسخ الأسبوع السابق". All shifts should be copied. Clashes are skipped and counted.

## D. Appointments and the reception board (arrival / room / leaving)
23. From a patient file, click "حجز موعد". Leave the dentist and room empty. The patient's responsible dentist and that dentist's room should be filled in automatically.
24. Book the same patient again 30 minutes later. It should be refused as a double booking.
25. Open "الاستقبال اليوم". For the appointment:
    1. Click "وصل". The arrival time is recorded, and "متأخر" shows the minutes late if the patient is more than 10 minutes late.
    2. Choose a room and click "دخل الغرفة". The waiting time is recorded.
    3. Click "انصرف". The time in the chair is recorded.
26. Click the undo button ↺. The last step should be undone. Use it if you clicked by mistake.
27. Mark an appointment "لم يحضر". It should turn red.
28. Use "مريض حضر بدون موعد" with a file number. The patient should appear as arrived, marked "بدون حجز".
29. Use the arrows or "اليوم" to see other days. The previous two weeks have sample visits with times (except Fridays).

## E. Lab work (secretary's part)
30. On the home page, click "تمت المراجعة، في انتظار الإرسال للمعمل". Open a request, try "تسجيل الإرسال للمعمل" **without** ticking "راجعت الشغل على طلب المعمل". It should be refused. Tick it and send, and the status should become "في المعمل".
31. When the work comes back, tick the check again and click "تسجيل الاستلام من المعمل". The doctor should get a notification.
32. Patients with open lab work should show the blue **"شغل معمل"** badge next to their name, in the patients list and on the reception board.
33. "طباعة طلب المعمل" should print the lab prescription with the logo.
34. "السجل" on the request should show who created, reviewed, sent and received it, and when.

## F. Complaints
35. From a patient file, click "تسجيل شكوى". Write the complaint and set "الأهمية" to "عالية - عاجلة". Save. Then log in as **headcia** or **owner**: the bell 🔔 should show the new complaint straight away.
36. Add a follow-up ("إضافة متابعة") with a next date. It should appear in "سجل المتابعة". Set the status to "تم الحل" and the solution is saved.

## G. Course candidates and installments
37. Open "الأكاديمية" → "الدارسون" → "دارس جديد". Save a candidate. Try the same mobile again and it should be refused.
38. Click "تسجيل في كورس" and fill in:
    - the course
    - a discount
    - a down payment of 5000 ("كاش")
    - 3 installments
    - the first installment date

    The installment plan should be created and the down payment recorded.
39. Click "تسجيل دفعة" with "إنستاباي" and **no reference**. It should ask for the transaction number. Add it and save. A printable **receipt with the logo** should open.
40. Try to pay more than the remaining balance. It should be refused.
41. Open "الأقساط المتأخرة". Candidates with overdue installments should be listed with the amount and days late.

## H. Purchases
42. Open "المشتريات" → "مشتريات جديدة". Add a supplier if needed. Then enter:
    - "شاي وسكر" under "شاي وقهوة وسكر"
    - "جوانتي" under "مستهلكات"
    - "أقلام" under "أدوات مكتبية"

    Use "إضافة صنف" for more rows. The total should update as you type. Upload the invoice photo and save.
43. Open "المشتريات". The totals by category should be shown. Filter by "النوع: غير طبية" or by supplier.

## I. Patients to call and printouts
44. The home page shows "مرضى للاتصال بهم" when the head of CIA sent a list. Open it:
    - "ماذا نقول للمرضى" shows what to tell them, and "السبب" shows why each patient is on the list.
    - Call a patient from the number shown, choose the result ("حجز موعد"، "لم يرد"...), write the patient's answer and save.
    - The green calendar button opens "حجز موعد" with the patient filled in.
45. From a patient's dental chart, click "تعليمات بعد العملية". The instructions print in Arabic with the patient's name and the surgery.

## J. WhatsApp messages to patients
For WhatsApp to open on the reception PC, install **WhatsApp Desktop** or open **WhatsApp Web** once with the clinic's WhatsApp number. On a phone or tablet, the WhatsApp app opens.

46. Book an appointment ("حجز موعد"). After saving, the message says "تم حجز الموعد. أرسل التأكيد على واتساب."
47. On the appointment page, the "واتساب" card has the buttons "تأكيد الحجز" and "تذكير بالموعد". For a missed appointment it also has "موعد لم يحضره". Click "تأكيد الحجز":
    - WhatsApp opens with the patient's mobile and the message ready: the name, day, date, time, dentist, and the clinic's address and phone. Press send in WhatsApp.
    - Back in the system, refresh the page. The message is listed on the appointment with the time and your name.
48. Open "الجدول" → "رسائل واتساب". You can also get there from the button on "الاستقبال اليوم" or the green card on the home page. There are three lists:
    - "تأكيد الحجوزات الجديدة": appointments booked in the last 3 days
    - "تذكير لمواعيد": tomorrow's appointments (use the arrows for another day)
    - "مواعيد لم يحضرها المريض (آخر 7 أيام)"
49. Click "إرسال" on a line and send it in WhatsApp. The line then shows ✓ with the time, and the button becomes "إرسال مرة أخرى".
50. Mark an appointment "لم يحضر" on the reception board. It appears in the missed list. Send the message that asks the patient to call and book again.

## K. General
51. Every screen should be in Arabic, right to left, with the CIA logo and colours.
52. Log out, then try to open a page. You should be sent to the login page.
53. Log in as **dentist1**. The screens should be in **English**. They should **not** see the call list, patient registration, the academy or purchases. They see every patient and can read the complaints, but cannot record or edit them.
