"""The pages of the Paper Reader: send the scans, follow their reading, check what Claude read next to a cut-out of
the paper, approve, and make the package for the dental system. The person in charge sets it up (Settings, the
lists from the system, the people)."""

import json
import mimetypes
import os
import posixpath
from decimal import Decimal
from functools import wraps
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.http import require_POST

from . import worker
from .catalogue import CONDITIONS, HISTORY, PATIENT, YES_NO, by_name
from .checks import SUGGESTED_BECAUSE
from .exchange import build_package, import_lists
from .forms import (ListsForm, OwnerForm, PageForm, PersonForm, SettingsForm, TargetForm, UploadForm, ValuesForm,
                    initial_values)
from .models import (Export, KnownPatient, PaperField, PaperFile, PaperPage, PaperReading, ReaderSettings, SystemLists,
                     month_cost, new_token, reading_estimate)
from .pages import PagesProblem, cut_out, pdf_from_pictures, turn_box, turn_page

SHOWN = {"image/jpeg", "image/png", "image/webp", "application/pdf"}


def in_charge(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def page_price(options):
    return reading_estimate(options.model, batched=False) * (2 if options.two_readings else 1)


# ------------------------------------------------------------------------------------------- logging in
class LoginView(auth_views.LoginView):
    template_name = "registration/login.html"

    @method_decorator(login_not_required)
    def dispatch(self, request, *args, **kwargs):
        if not get_user_model().objects.exists():
            return redirect("setup_owner")  # the first run: make the person in charge
        return super().dispatch(request, *args, **kwargs)


@login_not_required
def setup_owner(request):
    """The first run only: the person in charge makes their own login."""
    User = get_user_model()
    if User.objects.exists():
        return redirect("login")
    form = OwnerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = User.objects.create_user(form.cleaned_data["username"], password=form.cleaned_data["password"],
                                        first_name=form.cleaned_data["first_name"], is_staff=True)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, _("Welcome. Bring in the lists from the dental system first."))
        return redirect("reading:lists")
    return render(request, "registration/setup.html", {"form": form})


def protected_media(request, path):
    """The scans, pages and packages: only for the people logged in."""
    if posixpath.normpath(path) != path or path.startswith(("/", "..")) or "\\" in path:
        raise Http404
    if not default_storage.exists(path):
        raise Http404
    full = default_storage.path(path)
    kind = mimetypes.guess_type(full)[0] or "application/octet-stream"
    response = FileResponse(open(full, "rb"), content_type=kind if kind in SHOWN else "application/octet-stream")
    if kind not in SHOWN:
        response["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(os.path.basename(full))}"
    response["X-Content-Type-Options"] = "nosniff"
    return response


# ------------------------------------------------------------------------------------------- the files
def paper_list(request):
    worker.kick()  # goes on with the work left after a restart
    counts = dict(PaperFile.objects.values_list("status").annotate(n=Count("pk")).values_list("status", "n"))
    status = request.GET.get("status") or ("review" if counts.get("review") else "all")
    shown = PaperFile.objects.filter(status=status) if status in PaperFile.Status.values else PaperFile.objects.all()
    shown = shown.select_related("created_by").annotate(
        to_check=Count("fields", filter=Q(fields__certainty__in=("check", "unclear"), fields__checked=False)))
    page_obj = Paginator(shown, 30).get_page(request.GET.get("page"))
    busy = PaperFile.objects.filter(Q(status=PaperFile.Status.READING) | Q(status=PaperFile.Status.WAITING, error="")) \
        .exists()
    names = dict(KnownPatient.objects.filter(file_number__in={p.suggested for p in page_obj if p.suggested} | {
        (p.approved or {}).get("file_number") for p in page_obj if p.approved}).values_list("file_number", "full_name"))
    return render(request, "reading/list.html", {
        "page_obj": page_obj, "papers": page_obj.object_list, "status": status, "counts": counts,
        "statuses": PaperFile.Status.choices, "total": sum(counts.values()), "busy": busy, "names": names,
        "month_cost": month_cost() if request.user.is_staff else None,
    })


def upload(request):
    lists = SystemLists.get()
    if not lists.ready:
        messages.warning(request, _("Bring in the lists from the dental system first (Settings → Lists)."))
        return redirect("reading:lists" if request.user.is_staff else "reading:list")
    options = ReaderSettings.get()
    form = UploadForm(request.POST or None, request.FILES or None, initial={"mode": options.default_mode})
    if request.method == "POST" and form.is_valid():
        token = new_token()
        files = form.cleaned_data["files"]
        pdfs = [f for f in files if f.name.lower().endswith(".pdf")]
        pictures = [f for f in files if not f.name.lower().endswith(".pdf")]
        made = []
        if pictures:  # the photos of the pages of one file
            try:
                data, _pictures = pdf_from_pictures(pictures)
            except PagesProblem:
                messages.error(request, _("The photos could not be opened: take them again."))
                return redirect("reading:upload")
            made.append((ContentFile(data, name="photos.pdf"), pictures[0].name))
        made += [(f, f.name) for f in pdfs]
        for content, name in made:
            paper = PaperFile(upload=token, place_code=lists.place_code, original_name=name[:255],
                              mode=form.cleaned_data["mode"], created_by=request.user)
            paper.original.save("scan.pdf", content, save=False)
            paper.save()
        worker.kick()
        messages.success(request, ngettext(
            "%(n)s file is being read. It appears under “To check” when it is ready.",
            "%(n)s files are being read. They appear under “To check” when they are ready.", len(made))
            % {"n": len(made)})
        if not options.enabled:
            messages.warning(request, _("Reading is switched off: the files wait until it is switched on (Settings)."))
        return redirect("reading:list")
    return render(request, "reading/upload.html", {
        "form": form, "page_price": page_price(options), "page_price_batch": page_price(options) / 2})


def _paper(pk):
    return get_object_or_404(PaperFile, pk=pk)


def _forms(request, paper):
    """The three forms of the review page: whose file, the patient's data, the history."""
    data = request.POST if request.method == "POST" else None
    approved = paper.approved or {}
    chosen = approved.get("file_number") or paper.suggested
    target_initial = {"target": approved.get("target") or (TargetForm.EXISTING if chosen else TargetForm.NEW),
                      "file_number": chosen}
    target = TargetForm(data, prefix="t", initial=target_initial)
    if data is not None:
        new_patient = data.get("t-target") != TargetForm.EXISTING
    else:
        new_patient = target_initial["target"] == TargetForm.NEW
    patient_values = approved.get("patient") if approved else None
    patient_form = ValuesForm(data, prefix="p", part=PATIENT, new_patient=new_patient,
                              initial=_as_initial(patient_values) if patient_values is not None
                              else initial_values(paper, PATIENT))
    history_values = approved.get("history") if approved else None
    history_form = ValuesForm(data, prefix="h", part=HISTORY, new_patient=new_patient,
                              initial=_as_initial(history_values) if history_values is not None
                              else initial_values(paper, HISTORY))
    return target, patient_form, history_form


def _as_initial(values):
    known, out = by_name(), {}
    for name, value in (values or {}).items():
        spec = known.get(name)
        if spec is None:
            continue
        if spec.kind == CONDITIONS:
            out[name] = [code for code in value.split(",") if code]
        elif spec.kind == YES_NO:
            out[name] = value == "yes"
        else:
            out[name] = value
    return out


def _save_values(paper, patient_form, history_form):
    """Keep what the person typed (Save for later): a changed value counts as checked."""
    rows = {row.name: row for row in paper.fields.all()}
    for form in (patient_form, history_form):
        for name, field in form.fields.items():
            raw = form.data.getlist(form.add_prefix(name))
            kind = field.spec.kind
            if kind == CONDITIONS:
                value = ",".join(v for v in raw if v)
            elif kind == YES_NO:
                value = "yes" if raw and raw[-1] in ("on", "true", "True", "1") else ""
            else:
                value = (raw[-1] if raw else "").strip()
            row = rows.get(name)
            if kind == CONDITIONS and row is not None:
                same = sorted(value.split(",")) == sorted(row.value.split(","))
            else:
                same = row is not None and row.value == value
            if row is None:
                if value:
                    PaperField.objects.create(file=paper, name=name, value=value, checked=True)
            elif not same:
                row.value, row.checked = value, True
                row.save(update_fields=["value", "checked"])


def _duplicates(patient_form):
    """A new patient whose national ID or mobile is already registered: choose that patient instead."""
    values = patient_form.cleaned_data
    nid = values.get("national_id")
    if nid:
        known = KnownPatient.objects.filter(national_id=nid).first()
        if known:
            patient_form.add_error("national_id", _("This ID is already registered for %(name)s (file %(file)s): "
                                                    "choose “A patient already registered”.")
                                   % {"name": known.full_name, "file": known.file_number})
    phone = values.get("phone_primary")
    if phone:
        known = KnownPatient.objects.filter(Q(phone_primary=phone) | Q(phone_secondary=phone)).first()
        if known:
            patient_form.add_error("phone_primary", _("This mobile belongs to the registered patient %(name)s (file "
                                                      "%(file)s).") % {"name": known.full_name,
                                                                       "file": known.file_number})


def _current(known, name, spec):
    """(the registered patient's value as text, as shown) for one field; ("", "") when empty."""
    value = (known.values or {}).get(name, "") if known else ""
    if value in (None, "", "unknown"):
        return "", ""
    shown = spec.choice_label(value) if spec.choices else value
    return str(value), str(shown)


def review(request, pk):
    paper = _paper(pk)
    if paper.status in (PaperFile.Status.WAITING, PaperFile.Status.READING):
        worker.kick()
    target, patient_form, history_form = _forms(request, paper)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "reopen" and paper.status == PaperFile.Status.APPROVED:
            PaperFile.objects.filter(pk=paper.pk).update(status=PaperFile.Status.REVIEW)
            messages.info(request, _("Opened again: change it and approve it again."))
            return redirect(paper)
        if not paper.is_open:
            messages.info(request, _("This file is already done."))
            return redirect(paper)
        if action == "save":
            _save_values(paper, patient_form, history_form)
            messages.success(request, _("Saved. You can go on later."))
            return redirect(paper)
        if action == "set_aside":
            PaperFile.objects.filter(pk=paper.pk).update(status=PaperFile.Status.SET_ASIDE)
            messages.info(request, _("Set aside: the scan stays here, to type by hand."))
            return redirect("reading:list")
        if action in ("approve", "pages_only") and target.is_valid():
            pages_only = action == "pages_only"
            existing = target.cleaned_data["target"] == TargetForm.EXISTING
            if pages_only and not existing:
                messages.error(request, _("Choose the patient first."))
            elif pages_only or (patient_form.is_valid() and history_form.is_valid()):
                if not pages_only and not existing:
                    _duplicates(patient_form)
                if pages_only or not patient_form.errors:
                    paper.approved = {
                        "target": TargetForm.EXISTING if existing else TargetForm.NEW,
                        "file_number": target.cleaned_data["file_number"] if existing else "",
                        "patient": {} if pages_only else patient_form.values(),
                        "history": {} if pages_only else history_form.values(),
                        "replace": [] if pages_only else [name for name in request.POST.getlist("replace")
                                                          if name in patient_form.fields],
                        "pages_only": pages_only,
                    }
                    paper.status, paper.approved_by, paper.approved_at = (PaperFile.Status.APPROVED, request.user,
                                                                         timezone.now())
                    paper.save(update_fields=["approved", "status", "approved_by", "approved_at", "updated_at"])
                    messages.success(request, _("Approved: it goes to the dental system with the next package "
                                                "(Send to the system)."))
                    return redirect("reading:list")
            messages.error(request, _("Not approved yet: please correct the values marked in red."))
        elif action in ("approve", "pages_only"):
            messages.error(request, _("Not approved yet: please correct the values marked in red."))
    rows = {row.name: row for row in paper.fields.select_related("page")}
    for form in (patient_form, history_form):  # a value to check gets room for its reasons and its cut-out
        for name, row in rows.items():
            if name in form.fields and row.needs_look and form.fields[name].spec.kind not in (YES_NO, CONDITIONS):
                form.fields[name].col = "col-12 col-md-6"
    pages = list(paper.pages.prefetch_related("readings"))
    chosen = (paper.approved or {}).get("file_number") or paper.suggested
    known = KnownPatient.objects.filter(file_number=chosen).first() if chosen else None
    differs = {}
    if known is not None:  # the values of the file that the paper would change: kept unless ticked
        specs = by_name()
        for name, row in rows.items():
            spec = specs.get(name)
            if spec is None or spec.part != PATIENT or not row.value:
                continue
            code, shown = _current(known, name, spec)
            if code and code != row.value:
                differs[name] = shown
    for form in (patient_form, history_form):  # each box knows its value read and the file's value
        for name, field in form.fields.items():
            field.row, field.differs = rows.get(name), differs.get(name, "")
    counts = {key: sum(1 for row in rows.values() if row.certainty == key and not row.checked)
              for key in ("check", "unclear")}
    readings = [reading for page in pages for reading in page.readings.all()]
    replace = set(request.POST.getlist("replace")) if request.method == "POST" else set(
        (paper.approved or {}).get("replace", []))
    return render(request, "reading/review.html", {
        "paper": paper, "target_form": target, "patient_form": patient_form, "history_form": history_form,
        "rows": rows, "pages": pages, "known": known, "differs": differs, "counts": counts, "replace": replace,
        "suggested_because": SUGGESTED_BECAUSE.get(paper.suggested_reason, ""),
        "suggested_name": KnownPatient.objects.filter(file_number=paper.suggested).values_list(
            "full_name", flat=True).first() if paper.suggested else "",
        "kinds": PaperPage.Kind.choices,
        "failed_pages": [page for page in pages if page.readings.all() and not any(
            r.status == PaperReading.Status.DONE for r in page.readings.all())],
        "cost": sum((r.cost for r in readings), Decimal("0")) if request.user.is_staff else None,
        "sure": sum(1 for row in rows.values() if row.certainty == "sure"),
        "read_rows": [(by_name()[name].label, row) for name, row in rows.items() if name in by_name()],
    })


@require_POST
def page_edit(request, pk, page_pk):
    """Change what a page is, or turn it (its values' places turn with it)."""
    paper = _paper(pk)
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
    return redirect(reverse("reading:review", args=[paper.pk]) + "#pages")


@require_POST
def read_again(request, pk):
    paper = _paper(pk)
    if paper.status in (PaperFile.Status.REVIEW, PaperFile.Status.FAILED):
        readings = 2 if ReaderSettings.get().two_readings else 1
        paper.fields.all().delete()
        PaperReading.objects.filter(page__file=paper).delete()
        PaperReading.objects.bulk_create(PaperReading(page=page, number=number) for page in paper.pages.all()
                                         for number in range(1, readings + 1))
        PaperFile.objects.filter(pk=paper.pk).update(status=PaperFile.Status.WAITING, error="", read_at=None,
                                                     suggested="", suggested_reason="", approved=None)
        worker.kick()
        messages.info(request, _("The file is read again."))
    return redirect(paper)


@in_charge
@require_POST
def delete(request, pk):
    paper = _paper(pk)
    if paper.status == PaperFile.Status.EXPORTED:
        messages.error(request, _("A file sent to the system is kept."))
        return redirect(paper)
    paper.delete()
    messages.success(request, _("Deleted."))
    return redirect("reading:list")


def spot(request, pk):
    """The cut-out of the paper around one value (made when asked; the browser keeps it)."""
    row = get_object_or_404(PaperField.objects.select_related("page"), pk=pk)
    if row.page is None or not row.box:
        raise Http404
    etag = f'"{row.page.image.name}-{"-".join(str(v) for v in row.box)}"'
    if etag in request.headers.get("If-None-Match", ""):
        return HttpResponse(status=304)
    response = HttpResponse(cut_out(row.page, row.box), content_type="image/jpeg")
    response["ETag"], response["Cache-Control"] = etag, "private, no-cache"
    return response


def lookup(request):
    """Registered patients (from the lists file) matching a file number, a name or a mobile: for the "whose file" box."""
    from django.http import JsonResponse

    from .rules import normalize_digits

    text = normalize_digits(request.GET.get("q", "")).strip()
    rows = []
    if len(text) >= 2:
        found = KnownPatient.objects.filter(Q(file_number__icontains=text) | Q(full_name__icontains=text)
                                            | Q(phone_primary__startswith=text) | Q(national_id__startswith=text))
        rows = [{"value": p.file_number, "label": f"{p.file_number} — {p.full_name}"} for p in found[:20]]
    return JsonResponse({"results": rows})


# ------------------------------------------------------------------------------------------- to the dental system
def export(request):
    lists = SystemLists.get()
    ready = PaperFile.objects.filter(status=PaperFile.Status.APPROVED, place_code=lists.place_code)
    other_place = PaperFile.objects.filter(status=PaperFile.Status.APPROVED).exclude(place_code=lists.place_code)
    if request.method == "POST":
        papers = list(ready.select_related("approved_by").prefetch_related("pages"))
        if not papers:
            messages.info(request, _("Nothing approved to send."))
            return redirect("reading:export")
        made = build_package(papers, request.user)
        messages.success(request, _("The package is ready: download it, then import it in the dental system "
                                    "(Old paper files → Import a package)."))
        if made.count < len(papers):
            left = len(papers) - made.count
            messages.info(request, ngettext(
                "%(n)s file did not fit in this package: make another package after this one.",
                "%(n)s files did not fit in this package: make another package after this one.", left) % {"n": left})
        return redirect(reverse("reading:export") + f"?made={made.pk}")
    return render(request, "reading/export.html", {
        "ready": ready.order_by("approved_at"), "other_place": other_place.count(),
        "exports": Export.objects.select_related("made_by")[:30],
        "made": Export.objects.filter(pk=request.GET.get("made")).first() if request.GET.get("made", "").isdigit()
        else None,
    })


def export_download(request, pk):
    made = get_object_or_404(Export, pk=pk)
    return FileResponse(made.package.open("rb"), as_attachment=True, filename=made.name)


# ------------------------------------------------------------------------------------------- set-up
@in_charge
def settings_page(request):
    options = ReaderSettings.get()
    form = SettingsForm(request.POST or None, instance=options)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Saved."))
        if form.instance.enabled:
            worker.kick()
        return redirect("reading:settings")
    return render(request, "reading/settings.html", {
        "form": form, "options": options, "month_cost": month_cost(), "page_price": page_price(options),
        "pages_read": PaperReading.objects.filter(status=PaperReading.Status.DONE).values("page").distinct().count(),
        "files": PaperFile.objects.count(),
    })


@in_charge
@require_POST
def check_key(request):
    from . import claude

    options = ReaderSettings.get()
    if not options.key_is_set:
        messages.error(request, _("The key is not set: write ANTHROPIC_API_KEY=… in the reader's .env file and start "
                                  "the reader again."))
        return redirect("reading:settings")
    try:
        claude.check_key(options)
    except claude.KeyProblem:
        messages.error(request, _("Anthropic refused the key: check it in the .env file."))
    except claude.TryLater:
        messages.error(request, _("Anthropic cannot be reached now: check this PC's internet."))
    except ValueError as error:
        messages.error(request, _("Anthropic answered: %(error)s") % {"error": error})
    else:
        messages.success(request, _("The key works and the model is open to it."))
    return redirect("reading:settings")


@in_charge
def lists_page(request):
    form = ListsForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            data = json.loads(form.cleaned_data["lists"].read().decode("utf-8"))
            place, fields, patients = import_lists(data, request.user)
        except (ValueError, UnicodeDecodeError):
            messages.error(request, _("This is not a lists file of the dental system."))
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, _("The lists of %(place)s are in: %(fields)s values to read, %(patients)s "
                                        "registered patients.") % {"place": place, "fields": fields,
                                                                   "patients": patients})
            return redirect("reading:lists")
    lists = SystemLists.get()
    return render(request, "reading/lists.html", {"form": form, "patients": KnownPatient.objects.count(),
                                                  "values": len(lists.data.get("fields", []))})


@in_charge
def people(request, pk=None):
    User = get_user_model()
    person = get_object_or_404(User, pk=pk) if pk else None
    initial = {"username": person.username, "first_name": person.first_name, "admin": person.is_staff,
               "active": person.is_active} if person else {"active": True}
    form = PersonForm(request.POST or None, person=person, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        person = person or User(username=data["username"])
        person.username, person.first_name = data["username"], data["first_name"]
        if person.pk == request.user.pk:
            data["admin"], data["active"] = True, True  # one cannot lock oneself out
        person.is_staff, person.is_active = data["admin"], data["active"]
        if data.get("password"):
            person.set_password(data["password"])
        person.save()
        messages.success(request, _("Saved."))
        return redirect("reading:people")
    return render(request, "reading/people.html", {"form": form, "person": person,
                                                   "rows": User.objects.order_by("-is_active", "username")})
