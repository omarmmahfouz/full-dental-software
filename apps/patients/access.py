"""Who can see which patient."""

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404

from apps.core.roles import CLINICAL, PATIENT_VIEWERS, has_role

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
    """The front desk, management and the CIA dentists see every patient: the dentists
    record the work of the course candidates, who do not log in. Others see none."""
    if has_role(user, *PATIENT_VIEWERS):
        return Patient.objects.all()
    return Patient.objects.none()


def my_patients(user):
    """Patients the logged-in dentist is responsible for, booked with, or has worked on."""
    from apps.dentists.models import Dentist

    dentist = Dentist.for_user(user)
    if dentist is None:
        return Patient.objects.none()
    return Patient.objects.filter(pk__in=Patient.objects.filter(dentist_patients_q(dentist)).values("pk"))


def get_visible_patient_or_403(user, pk):
    patient = visible_patients(user).filter(pk=pk).first()
    if patient is None:
        if Patient.objects.filter(pk=pk).exists():
            raise PermissionDenied
        raise Http404
    return patient


def get_clinical_patient_or_403(user, pk):
    """For the dental chart, the treatment log and surgeries: the clinical team only. The reception
    reads the plan and the treatments done, in plain Arabic, on the patient file."""
    if not has_role(user, *CLINICAL):
        raise PermissionDenied
    return get_visible_patient_or_403(user, pk)
