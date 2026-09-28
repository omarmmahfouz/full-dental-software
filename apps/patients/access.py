"""Who can see which patient."""

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404
from django.utils.translation import gettext_lazy as _

from apps.core.roles import CLINICAL, FRONT_DESK, PATIENT_VIEWERS, has_role

from .models import Patient


def dentist_patients_q(dentist):
    """Patients a dentist is responsible for, is booked with, or has treated."""
    return (
        Q(assigned_dentist=dentist)
        | Q(appointments__dentist=dentist)
        | Q(treatment_steps__operator=dentist)
        | Q(treatment_steps__assistant=dentist)
        | Q(surgeries__operator_1=dentist)
        | Q(surgeries__operator_2=dentist)
        | Q(surgeries__assistant=dentist)
        | Q(surgeries__instructor=dentist)
        | Q(treatment_steps__supervisor=dentist)
    )


def visible_patients(user):
    """The front desk, management and the dentists see the patients of the place they work in now (the
    switch in the top bar); a place never sees another place's patients. The CIA dentists see every CIA
    patient: they record the work of the course candidates, who do not log in. Others see none."""
    if has_role(user, *PATIENT_VIEWERS):
        from apps.core.models import branch_for_user

        return Patient.objects.filter(branch=branch_for_user(user))
    return Patient.objects.none()


def my_patients(user):
    """Patients the logged-in dentist is responsible for, booked with, or has worked on."""
    from apps.dentists.models import Dentist

    dentist = Dentist.for_user(user)
    if dentist is None:
        return Patient.objects.none()
    return visible_patients(user).filter(pk__in=Patient.objects.filter(dentist_patients_q(dentist)).values("pk"))


def get_visible_patient_or_403(user, pk):
    patient = visible_patients(user).filter(pk=pk).first()
    if patient is None:
        if Patient.objects.filter(pk=pk).exists():
            raise PermissionDenied
        raise Http404
    return patient


def other_place_page(request, branch_id):
    """A page of another of this person's places (e.g. opened from a notification): the page that offers to switch
    to that place first, instead of "not allowed". None when the page is of the place worked in now."""
    from django.shortcuts import render

    from apps.core.models import Branch, branch_for_user, working_places

    here = branch_for_user(request.user)
    if not branch_id or (here is not None and branch_id == here.pk) or not has_role(request.user, *PATIENT_VIEWERS):
        return None
    if not working_places(request.user).filter(pk=branch_id).exists():
        return None
    return render(request, "patients/other_place.html", {"place": Branch.objects.get(pk=branch_id),
                                                         "next": request.get_full_path()})


def get_clinical_patient_or_403(user, pk):
    """For the dental chart, the treatment log and surgeries: the clinical team only. The reception
    reads the plan and the treatments done, in plain Arabic, on the patient file."""
    if not has_role(user, *CLINICAL):
        raise PermissionDenied
    return get_visible_patient_or_403(user, pk)


# The parts of a patient's file the owner can show to or hide from the reception (Settings → Access). The
# dentists, the heads and the owner see them all; the reception always sees the patient's data, the bookings, the
# payments and a short medical summary.
FILE_PARTS = [
    ("medical", _("The whole medical and dental history (otherwise only a short summary), and filling it")),
    ("plan", _("Treatment plans")),
    ("steps", _("Treatment steps (what was done)")),
    ("lab", _("Lab requests")),
    ("xrays", _("X-rays & CBCT")),
    ("tests", _("CBCT and medical test requests")),
    ("instructions", _("Post-op instructions to print")),
]
ALL_PARTS = frozenset(code for code, _label in FILE_PARTS)


def file_parts(user):
    """The parts of a patient's file this person sees."""
    if has_role(user, *CLINICAL) or not has_role(user, *FRONT_DESK):
        return ALL_PARTS
    from apps.core.models import ClinicSettings

    return ALL_PARTS & set(ClinicSettings.get().reception_sees or ())
