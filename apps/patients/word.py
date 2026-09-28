"""A patient's whole file as a Word document (.docx): to print, to send, or to keep outside the
system. Written in English with the data as entered (Arabic names stay Arabic)."""

import io

from django.utils import timezone, translation

from apps.billing.models import account
from apps.charting.forms import HISTORY_FIELDS
from apps.charting.models import ToothState

TABLE_STYLE = "Light Grid Accent 1"


def _text(value):
    if value is None or value == "":
        return ""
    if hasattr(value, "strftime"):
        if hasattr(value, "hour"):
            return timezone.localtime(value).strftime("%d/%m/%Y %I:%M %p") if timezone.is_aware(value) \
                else value.strftime("%d/%m/%Y %I:%M %p")
        return value.strftime("%d/%m/%Y")
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _field_value(obj, name):
    field = obj._meta.get_field(name)
    if field.many_to_many:
        return ", ".join(str(item) for item in getattr(obj, name).all())
    if field.choices:
        return str(getattr(obj, f"get_{name}_display")())
    return _text(getattr(obj, name))


def _table(document, headers, rows):
    table = document.add_table(rows=1, cols=len(headers))
    table.style = TABLE_STYLE
    for cell, header in zip(table.rows[0].cells, headers):
        cell.text = str(header)
    for row in rows:
        cells = table.add_row().cells
        for cell, value in zip(cells, row):
            cell.text = _text(value)
    document.add_paragraph()
    return table


def _facts(document, pairs):
    """Label / value lines, skipping empty values."""
    rows = [(label, value) for label, value in pairs if value not in (None, "", "—")]
    if rows:
        table = document.add_table(rows=0, cols=2)
        table.style = TABLE_STYLE
        for label, value in rows:
            cells = table.add_row().cells
            cells[0].text, cells[1].text = str(label), _text(value)
        document.add_paragraph()


def file_sections(patient):
    """The file as a list of (title, kind, content): kind "facts" gives (label, value) pairs, kind "table" gives
    (headers, rows). The Word and the Excel exports write the same sections. Called with English active."""
    sections = []
    names = ["file_number", "full_name", "id_type", "national_id", "birth_date", "gender", "marital_status",
             "phone_primary", "phone_secondary", "address", "city", "governorate", "occupation", "referral_source",
             "referral_details", "assigned_dentist", "status", "out_reason", "out_notes", "registered_on",
             "missing_teeth", "missing_teeth_notes", "notes"]
    sections.append(("Personal data", "facts", [(patient._meta.get_field(n).verbose_name.capitalize(),
                                                  _field_value(patient, n)) for n in names if _has_field(patient, n)]))

    exam = patient.examinations.prefetch_related("conditions").first()
    if exam is not None:
        sections.append(("Medical and dental history", "facts",
                         [("Date", _text(exam.exam_date))] + [
                             (exam._meta.get_field(n).verbose_name.capitalize(), _field_value(exam, n))
                             for n in HISTORY_FIELDS if _has_field(exam, n)]))

    rows = []
    for state in patient.tooth_states.order_by("tooth"):
        findings = [label for flag, label in ((state.caries, "caries"), (state.filled, "filled"),
                                              (state.rct, "root canal"), (state.crown, "crown"),
                                              (state.hopeless, "hopeless")) if flag]
        if state.status != ToothState.Status.PRESENT or findings:
            rows.append((state.tooth, state.get_status_display(), ", ".join(findings)))
    if rows:
        sections.append(("Dental chart", "table", (["Tooth", "Status", "Findings"], rows)))

    rows = []
    for plan in patient.treatment_plans.select_related("dentist").prefetch_related("items__step_type"):
        for section in plan.sections():
            for item in section["items"]:
                rows.append((plan.title, plan.get_status_display(), plan.created_at, section["label"], item.step_type,
                             item.teeth, item.details, item.get_status_display()))
    if rows:
        sections.append(("Treatment plans", "table", (
            ["Plan", "Plan status", "Planned on", "Part", "Procedure", "Teeth", "Details", "Status"], rows)))

    steps = list(patient.treatment_steps.select_related("step_type", "operator", "supervisor").order_by("performed_at"))
    if steps:
        sections.append(("Treatment log", "table", (
            ["Date", "Treatment", "Teeth", "Operator", "Supervisor", "Notes"],
            [(s.performed_at, s.step_type, s.teeth, s.operator, s.supervisor, s.notes) for s in steps])))

    rows = []
    for surgery in patient.surgeries.select_related("operator_1", "instructor").prefetch_related(
            "sites__implant_system").order_by("date"):
        for site in surgery.sites.all():
            rows.append((surgery.date, surgery.number, site.tooth, ", ".join(site.procedure_labels()),
                         site.implant_label if site.has_implant else "", surgery.operator_1, surgery.instructor))
    if rows:
        sections.append(("Surgeries and implants", "table", (
            ["Date", "Surgery", "Tooth", "Procedures", "Implant", "Operator", "Supervisor"], rows)))

    appointments = list(patient.appointments.select_related("room", "dentist").order_by("scheduled_at"))
    if appointments:
        sections.append(("Appointments", "table", (
            ["Date", "Status", "Room", "Dentist", "Purpose"],
            [(a.scheduled_at, a.get_status_display(), a.room, a.dentist, a.what) for a in appointments])))

    money = account(patient)
    if money["rows"] or money["payments"]:
        sections.append(("Services", "table", (
            ["Date", "Service", "Price", "Discount", "Net", "Paid", "Left"],
            [(r["charge"].charged_on, r["charge"].service, r["charge"].price, r["charge"].discount_amount,
              r["charge"].net, r["paid"], r["left"]) for r in money["rows"]])))
        sections.append(("Payments", "table", (
            ["Paid on", "Receipt", "Amount", "Method", "Notes"],
            [(p.paid_on, p.receipt_number, p.amount, p.get_method_display(), p.notes) for p in money["payments"]])))
        sections.append(("Account", "facts", [("Total", money["net"]), ("Paid", money["paid"]),
                                              ("Balance", money["balance"])]))

    labs = list(patient.lab_requests.select_related("work_type", "lab", "dentist"))
    if labs:
        sections.append(("Lab requests", "table", (
            ["Date", "Work", "Teeth", "Lab", "Dentist", "Status"],
            [(lab.created_at, lab.work_type, lab.teeth, lab.lab, lab.dentist, lab.get_status_display())
             for lab in labs])))
    return sections


def patient_docx(patient):
    from docx import Document
    from docx.shared import Pt

    with translation.override("en"):
        document = Document()
        document.styles["Normal"].font.name = "Calibri"
        document.styles["Normal"].font.size = Pt(10)
        document.add_heading(f"{patient.full_name} — {patient.file_number}", level=0)
        document.add_paragraph(f"Patient file exported on {timezone.localtime():%d/%m/%Y %I:%M %p}")
        for title, kind, content in file_sections(patient):
            document.add_heading(title, level=1)
            if kind == "facts":
                _facts(document, content)
            else:
                _table(document, *content)
        output = io.BytesIO()
        document.save(output)
        output.seek(0)
        return output


def patient_xlsx(patient):
    """The same file as an Excel workbook: one sheet per part, to sort, filter or keep."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    head = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="1F6FB2")
    with translation.override("en"):
        book = Workbook()
        book.remove(book.active)
        for title, kind, content in file_sections(patient):
            sheet = book.create_sheet(title[:31])
            headers, rows = (["", ""], content) if kind == "facts" else content
            if kind == "facts":
                sheet.append([f"{patient.full_name} — {patient.file_number}"])
                sheet["A1"].font = Font(bold=True, size=13)
            else:
                sheet.append(list(map(str, headers)))
                for cell in sheet[1]:
                    cell.font, cell.fill = head, fill
                sheet.freeze_panes = "A2"
            for row in rows:
                sheet.append([_cell(value) for value in row])
            for index in range(1, sheet.max_column + 1):
                width = max((len(str(c.value or "")) for c in sheet[get_column_letter(index)]), default=8)
                sheet.column_dimensions[get_column_letter(index)].width = min(max(width + 2, 10), 60)
            for row in sheet.iter_rows(min_row=2):
                for cell in row:
                    cell.alignment = Alignment(wrap_text=True, vertical="top")
        output = io.BytesIO()
        book.save(output)
        output.seek(0)
        return output


def _cell(value):
    """Numbers and dates stay numbers and dates in Excel; the rest is text."""
    from decimal import Decimal

    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return float(value) if isinstance(value, Decimal) else value
    return _text(value)


def _has_field(obj, name):
    try:
        obj._meta.get_field(name)
    except Exception:
        return False
    return True
