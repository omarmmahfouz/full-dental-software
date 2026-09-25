from django.conf import settings
from django.middleware.locale import LocaleMiddleware
from django.utils import translation


class ArabicFirstLocaleMiddleware(LocaleMiddleware):
    """Arabic by default, whatever language the browser asks for.

    English is used only when a user picks it from the menu (stored in the
    language cookie by Django's set_language view).
    """

    def process_request(self, request):
        language = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME)
        if language not in dict(settings.LANGUAGES):
            language = settings.LANGUAGE_CODE
        translation.activate(language)
        request.LANGUAGE_CODE = translation.get_language()
