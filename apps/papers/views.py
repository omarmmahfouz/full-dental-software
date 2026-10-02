"""Old paper files (round 13): send the scans, follow their reading, check what Claude read next to a cut-out of the
paper, and save it into the patient's file. The reception and the heads of the place use it; the owner sets it up."""

from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.mixins import role_required
from apps.core.models import branch_for_user
from apps.core.roles import FRONT_DESK, HEAD_CIA, OWNER, has_role
from apps.patients.forms import lookup_value
from apps.patients.models import Patient

from . import approve as approving
from . import worker
from .checks import SUGGESTED_BECAUSE
from .fields import BY_NAME, PATIENT_FIELDS
from .forms import CoversForm, PageForm, PaperHistoryForm, PaperPatientForm, PaperSettingsForm, TargetForm, UploadForm
from .models import PaperField, PaperFile, PaperPage, PaperReading, PaperSettings, month_cost, new_token
from .pages import PagesProblem, cut_out, pdf_from_pictures, turn_box, turn_page

def _papers(request):
    """The paper files of the place worked in now."""
    return PaperFile.objects.filter(branch=branch_for_user(request.user))


def _paper(request, pk):
    paper = _papers(request).filter(pk=pk).first()
    if paper is None:
        if PaperFile.objects.filter(pk=pk).exists():
            raise PermissionDenied
        raise Http404
    return paper


def page_price(options):
    """About what a page costs when sent now (all its readings)."""
    from .models import reading_estimate

    return reading_estimate(options.model, batched=False) * (2 if options.two_readings else 1)


@role_required(*FRONT_DESK)
def paper_list(request):
    worker.kick()  # goes on with the work left after a restart
    papers = _papers(request)
    counts = dict(papers.values_list("status").annotate(n=Count("pk")).values_list("status", "n"))
    status = request.GET.get("status") or ("review" if counts.get("review") else "all")
    shown = papers.filter(status=status) if status in PaperFile.Status.values else papers
    shown = shown.select_related("patient", "suggested", "created_by").annotate(
        to_check=Count("fields", filter=Q(fields__certainty__in=("check", "unclear"), fields__checked=False)))
    page_obj = Paginator(shown, 30).get_page(request.GET.get("page"))
    options = PaperSettings.get()
    busy = papers.filter(Q(status=PaperFile.Status.READING) | Q(status=PaperFile.Status.WAITING, error="")).exists()
    return render(request, "papers/list.html", {
        "page_obj": page_obj, "papers": page_obj.object_list, "status": status, "counts": counts,
        "statuses": PaperFile.Status.choices, "total": sum(counts.values()), "options": options, "busy": busy,
        "month_cost": month_cost() if has_role(request.user, OWNER) else None,
    })


@role_required(*FRONT_DESK)
def upload(request):
    options = PaperSettings.get()
    patient = None
    if request.GET.get("patient", "").isdigit():
        from apps.patients.access import get_visible_patient_or_403

        patient = get_visible_patient_or_403(request.user, int(request.GET["patient"]))
    form = UploadForm(request.POST or None, request.FILES or None, initial={"mode": options.default_mode})
    if request.method == "POST" and form.is_valid():
        place, token = branch_for_user(request.user), new_token()
        files = form.cleaned_data["files"]
        pdfs = [f for f in files if f.name.lower().endswith(".pdf")]
        pictures = [f for f in files if not f.name.lower().endswith(".pdf")]
        made = []
        try:
            if pictures:  # the photos of the pages of one file
                data, _pictures = pdf_from_pictures(pictures)
                made.append((ContentFile(data, name="photos.pdf"), pictures[0].name))
        except PagesProblem:
            messages.error(request, _("The photos could not be opened: take them again."))
            return redirect(request.get_full_path())
        made += [(f, f.name) for f in pdfs]
        for content, name in made:
            paper = PaperFile(branch=place, patient=patient, upload=token, original_name=name[:255],
                              mode=form.cleaned_data["mode"], created_by=request.user)
            paper.original.save(content.name if hasattr(content, "name") else "scan.pdf", content, save=False)
            paper.save()
        worker.kick()
        if len(made) == 1 and patient is not None:
            messages.success(request, _("The file is being read: it opens here when it is ready."))
        else:
            messages.success(request, _("%(n)s files are being read. You are told when they are ready to check.")
                             % {"n": len(made)})
        if not options.enabled:
            messages.warning(request, _("Reading is switched off: the files wait until the owner switches it on "
                                        "(Settings → Old paper files)."))
        return redirect("papers:list")
    return render(request, "papers/upload.html", {
        "form": form, "options": options, "patient": patient, "page_price": page_price(options),
        "page_price_batch": page_price(options) / 2,
    })


def _forms(request, paper):
    """The three forms of the review page: whose file, the patient's data, the history."""
    patient_values, history_values = approving.initial_values(paper)
    data = request.POST if request.method == "POST" else None
    chosen = paper.patient or paper.suggested
    target_initial = {"target": TargetForm.EXISTING if chosen else TargetForm.NEW,
                      "patient": lookup_value(chosen) if chosen else ""}
    target = TargetForm(data, prefix="t", initial=target_initial)
    existing = None
    if data is not None and target.is_valid() and target.cleaned_data["target"] == TargetForm.EXISTING:
        existing = target.cleaned_data["patient"]
    elif data is None and chosen is not None:
        existing = chosen
    if paper.patient is not None:
        existing = paper.patient  # sent from the patient's own page
    patient_form = PaperPatientForm(data, prefix="p", initial=patient_values,
                                    instance=existing or Patient(branch=paper.branch))
    history_form = PaperHistoryForm(data, prefix="h", initial=history_values)
    return target, patient_form, history_form, existing


def _save_values(paper, patient_form, history_form):
    """Keep what the person typed (Save for later): the values become checked."""
    rows = {row.name: row for row in paper.fields.all()}
    for form in (patient_form, history_form):
        for name in form.fields:
            if name not in BY_NAME:
                continue
            raw = form.data.getlist(form.add_prefix(name)) if hasattr(form.data, "getlist") else []
            value = ",".join(v for v in raw if v) if BY_NAME[name].kind == "conditions" else (raw[-1] if raw else "")
            if BY_NAME[name].kind == "yes_no":
                value = "yes" if value in ("on", "true", "True", "1") else ""
            row = rows.get(name)
            if BY_NAME[name].kind == "conditions" and row is not None:
                same = sorted(value.split(",")) == sorted(row.value.split(","))
            else:
                same = row is not None and row.value == value
            if row is None:
                if value:
                    PaperField.objects.create(file=paper, name=name, value=value, checked=True)
            elif not same:  # changed by the person: it counts as checked
                row.value, row.checked = value, True
                row.save(update_fields=["value", "checked"])


def _current(patient, name):
    """(the patient's value as the paper's values are written, as shown) for one field; ("", "") when empty."""
    value = getattr(patient, name, None)
    if value in (None, "", "unknown"):
        return "", ""
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y"), value.strftime("%d/%m/%Y")
    if hasattr(value, "pk"):
        return str(value.pk), str(value)
    display = getattr(patient, f"get_{name}_display", None)
    return str(value), str(display() if display else value)


@role_required(*FRONT_DESK)
def review(request, pk):
    paper = _paper(request, pk)
    if paper.status in (PaperFile.Status.WAITING, PaperFile.Status.READING):
        worker.kick()
    target, patient_form, history_form, existing = _forms(request, paper)
    if request.method == "POST":
        if not paper.is_open:
            messages.info(request, _("This file is already done."))
            return redirect(paper)
        action = request.POST.get("action")
        if action == "save":
            _save_values(paper, patient_form, history_form)
            messages.success(request, _("Saved. You can go on later."))
            return redirect(paper)
        if action == "set_aside":
            approving.set_aside(paper, request.user)
            messages.info(request, _("Set aside: the scan stays here, to type by hand."))
            return redirect("papers:list")
        if action == "pages_only":
            if existing is None:
                messages.error(request, _("Choose the patient first."))
            else:
                approving.approve(paper, request.user, patient=existing, pages_only=True)
                messages.success(request, _("The pages are kept in the patient's documents."))
                return redirect(reverse("patients:detail", args=[existing.pk]) + "#documents")
        elif action == "approve":
            forms_ok = target.is_valid() and patient_form.is_valid() and history_form.is_valid()
            if forms_ok:
                replace = set(request.POST.getlist("replace"))
                patient, waiting = approving.approve(paper, request.user, patient_form, history_form,
                                                     patient=existing, replace=replace)
                messages.success(request, _("Saved into the file of %(name)s (%(file)s).") % {
                    "name": patient.full_name, "file": patient.file_number})
                if waiting is not None:
                    messages.warning(request, _("The values that replace the old ones were sent to the head for "
                                                "approval."))
                return redirect(patient)
            messages.error(request, _("Not saved yet: please correct the values marked in red."))
    rows = {row.name: row for row in paper.fields.select_related("page")}
    for form in (patient_form, history_form):  # a value to check gets room for its reasons and its cut-out
        for name, row in rows.items():
            if name in form.fields and row.needs_look and getattr(form.fields[name].widget, "input_type", "") != "checkbox":
                form.fields[name].col = "col-12 col-md-6"
    pages = list(paper.pages.prefetch_related("readings"))
    differs = {}
    if existing is not None:  # the values of the file that the paper would change: kept unless ticked
        for name in PATIENT_FIELDS:
            row, (code, shown) = rows.get(name), _current(existing, name)
            if row is not None and row.value and code and code != row.value:
                differs[name] = shown
    counts = {key: sum(1 for row in rows.values() if row.certainty == key and not row.checked)
              for key in ("check", "unclear")}
    readings = [reading for page in pages for reading in page.readings.all()]
    return render(request, "papers/review.html", {
        "paper": paper, "target_form": target, "patient_form": patient_form, "history_form": history_form,
        "rows": rows, "pages": pages, "existing": existing, "differs": differs, "counts": counts,
        "replace": set(request.POST.getlist("replace")) if request.method == "POST" else set(),
        "suggested_because": SUGGESTED_BECAUSE.get(paper.suggested_reason, ""),
        "kinds": PaperPage.Kind.choices,
        "failed_pages": [page for page in pages if page.readings.all() and not any(
            r.status == PaperReading.Status.DONE for r in page.readings.all())],
        "cost": sum((r.cost for r in readings), Decimal("0")) if has_role(request.user, OWNER) else None,
        "sure": sum(1 for row in rows.values() if row.certainty == "sure"),
        "read_rows": [(BY_NAME[name].label, row) for name, row in rows.items() if name in BY_NAME],
    })


@role_required(*FRONT_DESK)
@require_POST
def page_edit(request, pk, page_pk):
    """Change what a page is, or turn it (its values' places turn with it)."""
    paper = _paper(request, pk)
    page = get_object_or_404(PaperPage, pk=page_pk, file=paper)
    form = PageForm(request.POST)
    if paper.is_open and form.is_valid():
        if form.cleaned_data["kind"]:
            page.kind = form.cleaned_data["kind"]
            page.save(update_fields=["kind"])
        degrees = {"left": 270, "right": 90}.get(form.cleaned_data["turn"])
        if degrees:
            width, height = page.width, page.height
            turn_page(page, degrees)
            for row in PaperField.objects.filter(page=page).exclude(box=None):
                row.box = turn_box(row.box, degrees, width, height)
                row.save(update_fields=["box"])
    return redirect(reverse("papers:review", args=[paper.pk]) + "#pages")


@role_required(*FRONT_DESK)
@require_POST
def read_again(request, pk):
    paper = _paper(request, pk)
    if paper.status in (PaperFile.Status.REVIEW, PaperFile.Status.FAILED):
        approving.read_again(paper)
        worker.kick()
        messages.info(request, _("The file is read again."))
    return redirect(paper)


@role_required(OWNER, HEAD_CIA)
@require_POST
def delete(request, pk):
    paper = _paper(request, pk)
    if paper.status == PaperFile.Status.APPROVED:
        messages.error(request, _("A file saved into a patient's file is kept."))
        return redirect(paper)
    paper.delete()  # kept in the deleted records (Settings → Security)
    messages.success(request, _("Deleted."))
    return redirect("papers:list")


@role_required(*FRONT_DESK)
def spot(request, pk):
    """The cut-out of the paper around one value (made when asked; the browser keeps it)."""
    row = get_object_or_404(PaperField.objects.select_related("page", "file"), pk=pk)
    if row.file.branch_id != branch_for_user(request.user).pk:
        raise PermissionDenied
    if row.page is None or not row.box:
        raise Http404
    etag = f'"{row.page.image.name}-{"-".join(str(v) for v in row.box)}"'
    if etag in request.headers.get("If-None-Match", ""):
        return HttpResponse(status=304)
    response = HttpResponse(cut_out(row.page, row.box), content_type="image/jpeg")
    response["ETag"], response["Cache-Control"] = etag, "private, no-cache"
    return response


@role_required(*FRONT_DESK)
def covers(request):
    """Cover sheets with the file number in large print: put on top of each paper file before scanning, so the
    system knows whose file it is."""
    form = CoversForm(request.GET or None)
    sheets, blank = [], 0
    if request.GET and form.is_valid():
        data = form.cleaned_data
        patients = Patient.objects.filter(branch=branch_for_user(request.user))
        if data.get("patient"):
            sheets.append(data["patient"])
        if data.get("registered_from") or data.get("registered_to"):
            chosen = patients
            if data.get("registered_from"):
                chosen = chosen.filter(registered_on__gte=data["registered_from"])
            if data.get("registered_to"):
                chosen = chosen.filter(registered_on__lte=data["registered_to"])
            sheets += list(chosen.order_by("file_number")[:300])
        blank = data.get("blank") or 0
        if sheets or blank:
            return render(request, "papers/covers_print.html", {
                "sheets": sheets, "blank": range(blank), "place": branch_for_user(request.user),
                "today": timezone.localdate()})
        messages.info(request, _("Choose a patient, the dates, or a number of blank sheets."))
    return render(request, "papers/covers.html", {"form": form})


@role_required(OWNER)
def settings_page(request):
    options = PaperSettings.get()
    form = PaperSettingsForm(request.POST or None, instance=options)
    if request.method == "POST" and form.is_valid():
        options = form.save(commit=False)
        options.updated_by = request.user
        options.save()
        messages.success(request, _("Saved."))
        if options.enabled:
            worker.kick()
        return redirect("papers:settings")
    readings = PaperReading.objects.exclude(done_at=None)
    return render(request, "papers/settings.html", {
        "form": form, "options": options, "month_cost": month_cost(), "page_price": page_price(options),
        "pages_read": readings.filter(status=PaperReading.Status.DONE).values("page").distinct().count(),
        "files": PaperFile.objects.count(),
    })


@role_required(OWNER)
@require_POST
def check_key(request):
    from . import claude

    options = PaperSettings.get()
    if not options.key_is_set:
        messages.error(request, _("The key is not set: write ANTHROPIC_API_KEY=… in the server's .env file and "
                                  "start the server again."))
        return redirect("papers:settings")
    try:
        claude.check_key(options)
    except claude.KeyProblem:
        messages.error(request, _("Anthropic refused the key: check it in the .env file."))
    except claude.TryLater:
        messages.error(request, _("Anthropic cannot be reached now: check the server's internet."))
    except ValueError as error:
        messages.error(request, _("Anthropic answered: %(error)s") % {"error": error})
    else:
        messages.success(request, _("The key works and the model is open to it."))
    return redirect("papers:settings")
