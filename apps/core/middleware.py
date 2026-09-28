import logging
import time

from django.conf import settings
from django.middleware.locale import LocaleMiddleware
from django.utils import translation

from .roles import SECRETARY, STOCK, user_roles


def default_language_for(user):
    """Secretaries and the stock manager work in Arabic; dentists and managers in English.
    A language picked from the user menu (saved on the profile) always wins."""
    profile = getattr(user, "profile", None)
    if profile is not None and profile.language:
        return profile.language
    roles = user_roles(user)
    if roles and roles <= {SECRETARY, STOCK}:
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


class ErrorRecorderMiddleware:
    """A page that stops with an error is written down for the owner (Problem reports)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        from .problems import record_error

        record_error(request, exception)
        return None  # the normal error page is still shown


class WorkingPlaceMiddleware:
    """People who work in more than one place (e.g. the secretary at CIA and at CIC) choose the place
    they work in now with the switch in the top bar; it is kept in their session. Every page then
    works for that place: the reception board, bookings, rooms, bills and stock use.
    Must come after AuthenticationMiddleware."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        chosen = request.session.get("place") if user is not None and user.is_authenticated else None
        if chosen:
            from .models import working_places

            place = working_places(user).filter(pk=chosen).first()
            if place is None:
                request.session.pop("place", None)
            else:
                user._working_branch = place
        if user is None or not user.is_authenticated:
            return self.get_response(request)
        from .models import branch_for_user, working_at

        with working_at(branch_for_user(user)):  # patients are looked up in this place only
            return self.get_response(request)


class PageCacheMiddleware:
    """Settings read many times while one page is made are read from the database once (see ``page_cache``)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from .models import page_cache

        with page_cache():
            return self.get_response(request)


slow_log = logging.getLogger("clinic.slow")


class SlowPageMiddleware:
    """Writes down every page that took longer than SLOW_PAGE_SECONDS (data/logs/slow-pages.log), with who
    opened it, so a page that becomes slow as the data grows is seen before the staff complain."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.monotonic()
        response = self.get_response(request)
        seconds = time.monotonic() - started
        if seconds >= settings.SLOW_PAGE_SECONDS:
            user = getattr(request, "user", None)
            slow_log.warning("%.1f s  %s %s  (%s)", seconds, request.method, request.get_full_path()[:300],
                             user.get_username() if user is not None and user.is_authenticated else "-")
        return response
