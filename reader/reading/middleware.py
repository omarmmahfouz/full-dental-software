"""Only the clinic's network may open the Paper Reader (it runs on a PC that has the internet), and the pages are
sent with headers that stop other sites from running scripts in them or framing them."""

import ipaddress

from django.conf import settings
from django.http import HttpResponse

CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; "
       "form-action 'self'; frame-ancestors 'self'")


def _networks(values):
    out = []
    for value in values:
        try:
            out.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    return out


class NetworkFenceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.allowed = getattr(settings, "ALLOWED_NETWORKS", ["*"])
        self.networks = _networks(self.allowed)

    def __call__(self, request):
        if "*" not in self.allowed:
            try:
                ip = ipaddress.ip_address(request.META.get("REMOTE_ADDR", ""))
            except ValueError:
                ip = None
            if ip is None or not any(ip in network for network in self.networks):
                return HttpResponse("The Paper Reader is open on the clinic's network only.\n"
                                    "قارئ الملفات يعمل على شبكة العيادة فقط.", status=403,
                                    content_type="text/plain; charset=utf-8")
        return self.get_response(request)


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
        if getattr(request, "user", None) is not None and request.user.is_authenticated:
            response.headers.setdefault("Cache-Control", "private")
        return response
