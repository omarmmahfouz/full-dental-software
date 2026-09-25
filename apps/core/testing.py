"""Helpers shared by the test suites."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command

from apps.core.models import Branch

PASSWORD = "test-pass-123"


def setup_clinic():
    call_command("setup_clinic", stdout=open("/dev/null", "w"))
    return Branch.objects.get(code="CIA")


def make_user(username, *roles, first_name=""):
    user = get_user_model().objects.create_user(username, password=PASSWORD, first_name=first_name or username)
    for role in roles:
        user.groups.add(Group.objects.get(name=role))
    return user


def make_patient(branch, name="مريض تجربة", nid="29001011234567", phone="01001234567", **extra):
    from apps.patients.models import Patient

    return Patient.objects.create(branch=branch, full_name=name, national_id=nid, phone_primary=phone, **extra)
