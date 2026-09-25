from django.conf import settings
from django.middleware.locale import LocaleMiddleware
from django.utils import translation

from .roles import SECRETARY, user_roles


def default_language_for(user):
    """Secretaries work in Arabic; dentists, supervisors and the owner in English.
    A language picked from the user menu (saved on the profile) always wins."""
    profile = getattr(user, "profile", None)
    if profile is not None and profile.language:
        return profile.language
    roles = user_roles(user)
    if roles == {SECRETARY}:
        return "ar"
    if roles:
        return "en"
    return settings.LANGUAGE_CODE


class UserLanguageMiddleware(LocaleMiddleware):
    """Chooses the interface language per user, not per browser, so a dentist
    switching language on a shared PC does not change it for the secretary.
    Before login (the login page) the language cookie is used, Arabic by default.
    Must come after AuthenticationMiddleware."""

    def process_request(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            language = default_language_for(user)
        else:
            language = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME)
        if language not in dict(settings.LANGUAGES):
            language = settings.LANGUAGE_CODE
        translation.activate(language)
        request.LANGUAGE_CODE = translation.get_language()
