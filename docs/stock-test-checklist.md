# Stock manager: test checklist

Start the trial with `trial-windows.bat` (see the README). Log in as **`stock`**, password **`demo12345`**.
The screens are in Arabic. The practice copy already has:
- the academy's *Dental_Material_and_Instrument* list, with its quantities
- tea, coffee, sugar, water and biscuits
- a purchase of articaine carpules that went into stock, with an expiry date

The steps give the Arabic button names in quotes, so you can match them to the screen.

When something is wrong or missing, note three things:
- the **step number**
- **what you did**
- **what you expected to happen**

## A. What the stock manager sees
1. The menu has only "المخزن والمشتريات". Patients, clinical pages and reports are not there.
2. The home page shows "نواقص المخزن": items at or under their reorder level, and batches expiring soon.

## B. Stock list
3. Open "المخزن" → "أصناف المخزن". Every item is under its category: dental materials, instruments, anaesthesia, consumables, equipment, food and beverage.
4. Rows in yellow are low. Click "نواقص المخزن" at the top to list only them.
5. Filter by category "طعام ومشروبات". Only tea, coffee, sugar, water and biscuits show.

## C. Receiving and using
6. Click **+** next to *Tea*. Record "وارد للمخزن" 3 boxes. The quantity goes up by 3, and the movement shows with your name.
7. Click **−** next to *Coffee*. Try to take out more than there is. It should be refused.
8. Open "صرف من المخزن". Write "لـ / استلمه" = *Room 2* and take out 2 carpules, 5 etchant tips and 1 floss in one go. All three quantities go down.
9. Open an item and record a "جرد (تصحيح الكمية)" with the quantity you counted. The quantity becomes exactly that number.
10. Record "تالف / منتهي الصلاحية" for one item.
11. When an item falls to its reorder level, a notification arrives.

## D. Expiry
12. Open *Carpule articaine (Spain)*. The received batch shows its lot and an expiry date within 60 days, and the home page lists it.

## E. Purchases fill the stock
13. Open "مشتريات جديدة". Add a line and choose the stock item in "إضافة لصنف المخزن". Save. The item's quantity goes up, and the movement links back to the purchase.
14. Edit the purchase and change the quantity. The stock is corrected, not counted twice.
15. Delete that purchase line. The stock goes back down.

## F. Import a list from Excel
16. Open "استيراد قائمة". Upload an Excel file with one item per row, the quantity and the name, like *Dental_Material_and_Instrument.xlsx*.
    - Choose the category for items without one.
    - Leave "الكميات هي جرد للمخزن" ticked to set the quantities, or untick it to add them as a delivery.
17. New items are created, and items already in stock are updated. The message says how many.

## G. Movements
18. Open "حركات المخزن". Filter by date, type of movement, category, or by item or destination (e.g. *Kitchen*). Print it.

## H. Implants by lot (new)
19. Open an implant item, e.g. "Osstem TS III 4.0 x 10": "اللوطات في المخزن" shows each lot with its expiry and how many are left.
20. Receive more with a new lot ("وارد للمخزن", write the lot and the expiry): a new line appears.
21. Add a new implant item: fill "شركة / نوع الزرعة", the diameter and the length. The dentists then find it on the surgery chart, and each implant placed is taken out of its lot by itself.
