"""Who can open a dentist's file."""

from apps.core.access import area_levels
from apps.core.models import AreaAccess
from apps.core.roles import FRONT_DESK, TEAM_HEAD, has_role

from .models import Dentist


def can_open_dentist_file(user, dentist):
    """The dentist himself, the front desk and management (every dentist), and the head of the
    CIA dentists team (the CIA dentists, not the course candidates). Used by the page itself and by
    the templates, so a name is a link only for the people who can open it."""
    if dentist is None or not user.is_authenticated:
        return False
    if area_levels(user).get("dentists") == AreaAccess.Level.HIDDEN:
        return False
    if dentist.user_id == user.pk or has_role(user, *FRONT_DESK):
        return True
    return has_role(user, TEAM_HEAD) and dentist.kind != Dentist.Kind.CANDIDATE
