"""Create in-app notifications (shown on the bell icon in the top bar)."""

from django.conf import settings
from django.utils import translation

from .models import Notification
from .roles import users_with_role


def notify_users(users, title, message="", url="", level=Notification.Level.INFO, exclude=None, params=None):
    """Notify each user once.

    ``title``/``message`` should be lazy strings (``gettext_lazy``) with optional
    ``%(name)s`` placeholders filled from ``params``. Each notification is written in
    the recipient's own interface language (Arabic for secretaries, English for dentists).
    """
    from .middleware import default_language_for

    params = params or {}
    seen = set()
    rows = []
    for user in users:
        if user is None or user.pk in seen or (exclude is not None and user.pk == exclude.pk):
            continue
        seen.add(user.pk)
        language = default_language_for(user)
        if language not in dict(settings.LANGUAGES):
            language = settings.LANGUAGE_CODE
        with translation.override(language):
            text = str(title) % params if params else str(title)
            body = str(message) % params if params and message else str(message)
        rows.append(Notification(recipient=user, title=text[:200], message=body, url=url, level=level))
    Notification.objects.bulk_create(rows)
    return len(rows)


def notify_roles(roles, title, message="", url="", level=Notification.Level.INFO, exclude=None, params=None):
    return notify_users(users_with_role(*roles), title, message, url, level, exclude, params)
