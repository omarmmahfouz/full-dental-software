"""Create in-app notifications (shown on the bell icon in the top bar)."""

from django.conf import settings
from django.utils import translation

from .models import Notification, staff_at
from .roles import OWNER, users_with_role


def make_notifications(users, title, message="", url="", level=Notification.Level.INFO, exclude=None, params=None,
                       languages=None):
    """The notifications of ``notify_users``, not saved yet: for a sender that writes many at once and saves them
    together (``Notification.objects.bulk_create``). ``languages`` ({user pk: language}) is filled and used again,
    so each person's language is looked up once."""
    from .middleware import default_language_for

    params = params or {}
    languages = {} if languages is None else languages
    seen = set()
    rows = []
    for user in users:
        if user is None or user.pk in seen or (exclude is not None and user.pk == exclude.pk):
            continue
        seen.add(user.pk)
        language = languages.get(user.pk)
        if language is None:
            language = default_language_for(user)
            if language not in dict(settings.LANGUAGES):
                language = settings.LANGUAGE_CODE
            languages[user.pk] = language
        with translation.override(language):
            text = str(title) % params if params else str(title)
            body = str(message) % params if params and message else str(message)
        rows.append(Notification(recipient=user, title=text[:200], message=body, url=url, level=level))
    return rows


def notify_users(users, title, message="", url="", level=Notification.Level.INFO, exclude=None, params=None):
    """Notify each user once.

    ``title``/``message`` should be lazy strings (``gettext_lazy``) with optional
    ``%(name)s`` placeholders filled from ``params``. Each notification is written in
    the recipient's own interface language (Arabic for secretaries, English for dentists).
    """
    rows = make_notifications(users, title, message, url, level, exclude, params)
    Notification.objects.bulk_create(rows)
    return len(rows)


def notify_roles(roles, title, message="", url="", level=Notification.Level.INFO, exclude=None, params=None):
    return notify_users(users_with_role(*roles), title, message, url, level, exclude, params)


def notify_place(place, roles, title, message="", url="", level=Notification.Level.INFO, exclude=None, params=None):
    """Notify the people holding ``roles`` who work at ``place``. For news about a patient: each place has its own
    patients, and the reception of another place cannot open the page (El Khadem's reception was told to send CIA's
    lab requests). The owner works everywhere. When nobody at the place holds the roles, everyone who holds them is
    told, so the news is never lost."""
    people = []
    if place is not None:
        local = [role for role in roles if role != OWNER]
        people = list(staff_at(place, *local)) if local else []
        if OWNER in roles:
            people += list(users_with_role(OWNER))
    return notify_users(people or users_with_role(*roles), title, message, url, level, exclude, params)
