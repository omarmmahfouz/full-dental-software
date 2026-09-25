"""Who can see which patient."""

from django.core.exceptions import PermissionDenied
from django.db.models import Q

from apps.core.roles import FRONT_DESK, INTERN, has_role

from .models import Patient


def visible_patients(user):
    """Front desk and management see everyone; an intern sees the patients assigned
    to them plus the ones booked with them."""
    qs = Patient.objects.all()
    if has_role(user, *FRONT_DESK):
        return qs
    if has_role(user, INTERN):
        return qs.filter(Q(assigned_intern=user) | Q(appointments__intern=user)).distinct()
    return qs.none()


def get_visible_patient_or_403(user, pk):
    patient = visible_patients(user).filter(pk=pk).first()
    if patient is None:
        if Patient.objects.filter(pk=pk).exists():
            raise PermissionDenied
        from django.http import Http404

        raise Http404
    return patient
