"""Old paper files (round 13), the dental system's side. The files are read by the separate Paper Reader program on a
PC with the internet; here the reception and the heads:
- download the **lists for the reader** (the values to read, the lists, the place's patients);
- print the **cover sheets** with the file numbers;
- **import a package** from the reader: every value is checked again with the system's own forms, then saved."""

import json
from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.mixins import role_required
from apps.core.models import branch_for_user
from apps.core.roles import FRONT_DESK
from apps.patients.models import Patient

from . import importer
from .fields import lists_file
from .forms import CoversForm, PackageForm
from .models import ImportedFile, PaperImport


def _import(request, pk):
    """A package of the place worked in now."""
    found = PaperImport.objects.filter(pk=pk).first()
    if found is None:
        raise Http404
    if found.branch_id != branch_for_user(request.user).pk:
        raise PermissionDenied
    return found


@role_required(*FRONT_DESK)
def home(request):
    place = branch_for_user(request.user)
    form = PackageForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["package"]
        try:
            manifest = importer.read_manifest(upload)
        except importer.PackageProblem as problem:
            form.add_error("package", str(problem))
        else:
            if manifest.get("place") != place.code:
                form.add_error("package", _("This package was made for %(place)s: open the system at %(place)s to "
                                            "import it.") % {"place": manifest.get("place") or "?"})
            else:
                # Packages looked at days ago and never imported are not kept.
                for stale in PaperImport.objects.filter(branch=place, status=PaperImport.Status.CHECKED,
                                                        created_at__lt=timezone.now() - timedelta(days=2)):
                    stale.drop_package()
                upload.seek(0)
                paper_import = PaperImport(branch=place, name=upload.name[:255], manifest=manifest,
                                           created_by=request.user)
                paper_import.package.save("package.zip", upload, save=False)
                paper_import.save()
                return redirect(paper_import)
    imports = PaperImport.objects.filter(branch=place).select_related("created_by", "imported_by")[:20]
    return render(request, "papers/home.html", {"form": form, "imports": imports, "place": place,
                                                "patients": Patient.objects.filter(branch=place).count()})


@role_required(*FRONT_DESK)
def lists_download(request):
    """The lists for the Paper Reader, as a file to bring to the reader's PC."""
    place = branch_for_user(request.user)
    data = json.dumps(lists_file(place), ensure_ascii=False, indent=1)
    response = HttpResponse(data, content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = (f'attachment; filename="paper-reader-lists-{place.code}-'
                                       f'{timezone.localdate():%Y-%m-%d}.json"')
    return response


@role_required(*FRONT_DESK)
def import_detail(request, pk):
    paper_import = _import(request, pk)
    place = branch_for_user(request.user)
    if request.method == "POST" and paper_import.status == PaperImport.Status.CHECKED:
        if not paper_import.package:
            messages.error(request, _("This package is no longer here: import it again from the reader's file."))
            return redirect("papers:list")
        results = importer.run(paper_import, place, request.user)
        done = sum(1 for result in results if result.status == ImportedFile.Status.IMPORTED)
        failed = sum(1 for result in results if result.status == ImportedFile.Status.FAILED)
        messages.success(request, _("%(done)s files saved into the patients' files.") % {"done": done})
        if failed:
            messages.warning(request, _("%(n)s files were not imported: the reasons are below. Correct them in the "
                                        "Paper Reader (Open it again), then send them again.") % {"n": failed})
        return redirect(paper_import)
    context = {"paper_import": paper_import}
    if paper_import.status == PaperImport.Status.CHECKED:
        context["rows"] = importer.plan(paper_import, place)
    else:
        context["results"] = paper_import.results.select_related("patient", "change")
    return render(request, "papers/import_detail.html", context)


@role_required(*FRONT_DESK)
@require_POST
def import_cancel(request, pk):
    paper_import = _import(request, pk)
    if paper_import.status == PaperImport.Status.CHECKED:
        paper_import.drop_package()
        paper_import.delete()
        messages.info(request, _("The package was not imported."))
    return redirect("papers:list")


@role_required(*FRONT_DESK)
def covers(request):
    """Cover sheets with the file number in large print: put on top of each paper file before scanning, so the
    reader knows whose file it is."""
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
