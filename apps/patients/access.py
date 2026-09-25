"""Who can see which patient."""

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404

from apps.core.roles import DENTIST, FRONT_DESK, has_role
from apps.dentists.models import Dentist

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
    """Front desk and management see everyone; a dentist sees only their own patients."""
    qs = Patient.objects.all()
    if has_role(user, *FRONT_DESK):
        return qs
    if has_role(user, DENTIST):
        dentist = Dentist.for_user(user)
        if dentist is None:
            return qs.none()
        ids = Patient.objects.filter(dentist_patients_q(dentist)).values("pk")
        return qs.filter(pk__in=ids)
    return qs.none()


def get_visible_patient_or_403(user, pk):
    patient = visible_patients(user).filter(pk=pk).first()
    if patient is None:
        if Patient.objects.filter(pk=pk).exists():
            raise PermissionDenied
        raise Http404
    return patient
