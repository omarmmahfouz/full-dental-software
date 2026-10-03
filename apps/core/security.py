"""Protection of the system (round 11).

- **Wrong passwords**: after LOGIN_LOCK_AFTER wrong passwords in a row for a username, that login is closed for
  LOGIN_LOCK_MINUTES; after LOGIN_IP_LOCK_AFTER wrong passwords from one device (any usernames), that device is
  closed too. The owner is told and can open them again (Settings → Security). It works for the admin pages too
  (``LockoutBackend``).
- **The security log** (``SecurityEvent``): logins, wrong passwords, closed logins, log outs, passwords changed or
  set by the owner, data taken out (exports, backups), pages refused, visits from outside the clinic's network.
- **Easy passwords**: seen at login (short, common, like the username or a sample password); the person is asked to
  change it, or must change it when the owner chooses so.
- **A PC left open** logs out by itself after ``ClinicSettings.idle_logout_minutes`` without use.
- **The clinic's network only**: requests from addresses outside ALLOWED_NETWORKS (the private networks by default)
  are refused, so a server opened to the internet by mistake still shows nothing.
- **Headers** that stop other sites from running scripts in the pages or framing them (Content-Security-Policy).
- **Deleted records** are kept with what they held, who deleted them and when (``DeletedRecord``).
"""

import ipaddress
import json
import math
import time
from contextvars import ContextVar
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout, user_logged_in, user_logged_out, user_login_failed
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

LOCK_AFTER = getattr(settings, "LOGIN_LOCK_AFTER", 5)
IP_LOCK_AFTER = getattr(settings, "LOGIN_IP_LOCK_AFTER", 20)
LOCK_MINUTES = getattr(settings, "LOGIN_LOCK_MINUTES", 15)
KEEP_DAYS = 365
# Passwords of the sample data and the ones people pick first: never good enough on the real system.
EASY_PASSWORDS = {"demo12345", "12345678", "123456789", "1234567890", "password", "password1", "qwerty123",
                  "admin123", "cia12345", "cic12345", "clinic123", "dental123", "11111111", "00000000"}
# Pages a page asks for by itself (the bell every 30 s): they do not count as using the system.
BACKGROUND_PATHS = ("/notifications/poll/",)
# Pages that must be reachable from outside the clinic's network when used (Meta's WhatsApp messages to the lab).
OUTSIDE_ALLOWED_PATHS = ("/lab/whatsapp/hook/",)

_current_user = ContextVar("current_user", default=None)
_current_path = ContextVar("current_path", default="")


# ------------------------------------------------------------------ the device's address
def _networks(values):
    networks = []
    for value in values:
        try:
            networks.append(ipaddress.ip_network(value.strip(), strict=False))
        except ValueError:
            continue
    return networks


def _in(address, networks):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in network for network in networks)


def client_ip(request):
    """The device's address. Behind our own nginx (TRUSTED_PROXIES) it is the address nginx saw; a device on the
    network cannot pretend to be another by sending the header itself."""
    remote = request.META.get("REMOTE_ADDR", "") or ""
    if remote and _in(remote, _networks(getattr(settings, "TRUSTED_PROXIES", []))):
        real = request.META.get("HTTP_X_REAL_IP", "").strip()
        forwarded = [part.strip() for part in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if part.strip()]
        candidate = real or (forwarded[-1] if forwarded else "")
        try:
            ipaddress.ip_address(candidate)
            return candidate
        except ValueError:
            pass
    try:
        ipaddress.ip_address(remote)
        return remote
    except ValueError:
        return None


def device(request):
    return request.META.get("HTTP_USER_AGENT", "")[:200]


# ------------------------------------------------------------------ the security log
def log_event(kind, request=None, user=None, username="", details="", path=None):
    from .models import SecurityEvent

    if user is None and request is not None and getattr(request, "user", None) is not None \
            and request.user.is_authenticated:
        user = request.user
    if user is not None and not username:
        username = user.get_username()
    return SecurityEvent.objects.create(
        kind=kind, user=user, username=(username or "")[:150], ip=client_ip(request) if request is not None else None,
        device=device(request) if request is not None else "", details=str(details)[:300],
        path=(path if path is not None else (request.get_full_path() if request is not None else ""))[:300])


# ------------------------------------------------------------------ wrong passwords
def _window():
    return timezone.now() - timedelta(minutes=LOCK_MINUTES)


def _last_reset(username):
    from .models import SecurityEvent

    return SecurityEvent.objects.filter(
        username__iexact=username, kind__in=(SecurityEvent.Kind.LOGIN, SecurityEvent.Kind.UNLOCKED),
        at__gte=_window()).order_by("-at").values_list("at", flat=True).first()


def failures(username):
    """Wrong passwords for this username since the last good login (or opening), within the lock time."""
    from .models import SecurityEvent

    since = _last_reset(username) or _window()
    return SecurityEvent.objects.filter(username__iexact=username, kind=SecurityEvent.Kind.LOGIN_FAILED,
                                        at__gt=since).count()


def ip_failures(ip):
    from .models import SecurityEvent

    events = SecurityEvent.objects.filter(ip=ip, at__gte=_window())
    since = events.filter(kind=SecurityEvent.Kind.UNLOCKED, username="").order_by("-at").values_list(
        "at", flat=True).first()
    failed = events.filter(kind=SecurityEvent.Kind.LOGIN_FAILED)
    return (failed.filter(at__gt=since) if since else failed).count()


def _lock_event(username=None, ip=None):
    """The closing still in force for this username (or this device), or None."""
    from .models import SecurityEvent

    events = SecurityEvent.objects.filter(at__gte=_window())
    if username is not None:
        lock = events.filter(kind=SecurityEvent.Kind.LOCKED, username__iexact=username).order_by("-at").first()
        if lock is None:
            return None
        opened = events.filter(username__iexact=username, kind__in=(SecurityEvent.Kind.LOGIN,
                                                                    SecurityEvent.Kind.UNLOCKED), at__gt=lock.at)
    else:
        lock = events.filter(kind=SecurityEvent.Kind.LOCKED, username="", ip=ip).order_by("-at").first()
        if lock is None:
            return None
        opened = events.filter(kind=SecurityEvent.Kind.UNLOCKED, username="", ip=ip, at__gt=lock.at)
    return None if opened.exists() else lock


def minutes_locked(username, ip=None):
    """Minutes left before this username (or this device) may try again; 0 when it may."""
    locks = [lock for lock in (_lock_event(username=username) if username else None,
                               _lock_event(ip=ip) if ip else None) if lock is not None]
    if not locks:
        return 0
    until = max(lock.at for lock in locks) + timedelta(minutes=LOCK_MINUTES)
    return max(1, math.ceil((until - timezone.now()).total_seconds() / 60))


def locked_logins():
    """The usernames and devices closed now: [{"username", "ip", "at", "until"}] (for Settings → Security)."""
    from .models import SecurityEvent

    rows, seen = [], set()
    for lock in SecurityEvent.objects.filter(kind=SecurityEvent.Kind.LOCKED, at__gte=_window()):
        key = (lock.username.lower(), lock.ip if not lock.username else None)
        if key in seen:
            continue
        seen.add(key)
        current = _lock_event(username=lock.username) if lock.username else _lock_event(ip=lock.ip)
        if current is not None and current.pk == lock.pk:
            rows.append({"event": lock, "username": lock.username, "ip": lock.ip,
                         "until": lock.at + timedelta(minutes=LOCK_MINUTES)})
    return rows


def unlock(request, username="", ip=None):
    """The owner opens a closed login (``username``) or device (``ip``) again."""
    from .models import SecurityEvent

    return SecurityEvent.objects.create(
        kind=SecurityEvent.Kind.UNLOCKED, username=(username or "")[:150], ip=None if username else ip,
        details=_("by %(owner)s") % {"owner": request.user.get_username()})


def _tell_owner(text, params, url):
    from .models import Notification
    from .notify import notify_roles
    from .roles import OWNER

    notify_roles((OWNER,), text, url=url, level=Notification.Level.DANGER, params=params)


@receiver(user_login_failed)
def _login_failed(sender, credentials, request=None, **kwargs):
    from .models import SecurityEvent

    if request is None or getattr(request, "_refused_while_locked", False):
        return
    username = str(credentials.get("username") or "")[:150]
    ip = client_ip(request)
    SecurityEvent.objects.create(kind=SecurityEvent.Kind.LOGIN_FAILED, username=username, ip=ip,
                                 device=device(request), path=request.path[:300])
    if username and failures(username) >= LOCK_AFTER and _lock_event(username=username) is None:
        SecurityEvent.objects.create(kind=SecurityEvent.Kind.LOCKED, username=username, ip=ip, device=device(request),
                                     details=_("%(n)s wrong passwords") % {"n": LOCK_AFTER})
        _tell_owner(gettext_lazy("Login closed after wrong passwords: %(name)s (device %(ip)s)"),
                    {"name": username, "ip": ip or "?"}, reverse("settings:security"))
    if ip and ip_failures(ip) >= IP_LOCK_AFTER and _lock_event(ip=ip) is None:
        SecurityEvent.objects.create(kind=SecurityEvent.Kind.LOCKED, username="", ip=ip, device=device(request),
                                     details=_("%(n)s wrong passwords from this device") % {"n": IP_LOCK_AFTER})
        _tell_owner(gettext_lazy("A device was closed after many wrong passwords: %(ip)s"), {"ip": ip},
                    reverse("settings:security"))


class LockoutBackend(ModelBackend):
    """The normal login, refused while the username or the device is closed after wrong passwords."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if request is not None and username and minutes_locked(username, client_ip(request)):
            request._refused_while_locked = True  # not counted again: the closing does not grow
            return None
        return super().authenticate(request, username=username, password=password, **kwargs)


# ------------------------------------------------------------------ easy passwords
def is_easy(password, user=None):
    if not password:
        return True
    lowered = password.lower()
    if lowered in EASY_PASSWORDS or (user is not None and user.get_username().lower() in lowered):
        return True
    try:
        validate_password(password, user)
    except ValidationError:
        return True
    return False


def note_password(user, password):
    """At each good login: is the password easy to guess? (Kept on the profile; the password itself is not.)"""
    from .models import ClinicSettings, UserProfile

    easy = is_easy(password, user)
    profile, _created = UserProfile.objects.get_or_create(user=user)
    fields = []
    if profile.weak_password != easy:
        profile.weak_password = easy
        fields.append("weak_password")
    if easy and ClinicSettings.get().force_strong_passwords and not profile.must_change_password:
        profile.must_change_password = True
        fields.append("must_change_password")
    if fields:
        profile.save(update_fields=fields)
    return easy


@receiver(user_logged_in)
def _logged_in(sender, request, user, **kwargs):
    from .models import SecurityEvent

    if request is None:
        return
    log_event(SecurityEvent.Kind.LOGIN, request, user=user)
    if hasattr(request, "session"):
        from .worktime import KEY, finish

        if request.session.get(KEY):  # logged in again without logging out: the earlier stretch ends here
            finish(request, "closed")
        request.session["seen"] = int(time.time())
        request.session["ip"] = client_ip(request) or ""
        request.session["device"] = device(request)
        request.session["since"] = int(time.time())


@receiver(user_logged_out)
def _logged_out(sender, request, user, **kwargs):
    from .models import SecurityEvent

    if request is None or user is None:
        return
    kind = getattr(request, "_logout_kind", SecurityEvent.Kind.LOGOUT)
    log_event(kind, request, user=user, path="")
    from .worktime import finish

    finish(request, "idle" if kind == SecurityEvent.Kind.IDLE_LOGOUT else "logout")  # time in the system (round 14)


# ------------------------------------------------------------------ who is logged in now
def open_sessions():
    """The sessions open now: [{"key", "user", "ip", "device", "since", "seen"}], newest first. A session left
    longer than the minutes of the automatic log out is not counted: its next click logs out."""
    from django.contrib.auth import get_user_model
    from django.contrib.sessions.models import Session

    from .models import ClinicSettings

    minutes = ClinicSettings.get().idle_logout_minutes
    oldest = time.time() - minutes * 60 if minutes else 0
    rows = []
    for session in Session.objects.filter(expire_date__gt=timezone.now()):
        data = session.get_decoded()
        user_id = data.get("_auth_user_id")
        if user_id and (not oldest or (data.get("seen") or 0) >= oldest):
            rows.append({"key": session.session_key, "user_id": int(user_id), "ip": data.get("ip", ""),
                         "device": data.get("device", ""), "since": data.get("since"), "seen": data.get("seen")})
    users = get_user_model().objects.in_bulk([row["user_id"] for row in rows])
    for row in rows:
        row["user"] = users.get(row["user_id"])
        for key in ("since", "seen"):
            row[key] = datetime.fromtimestamp(row[key], tz=timezone.get_current_timezone()) if row[key] else None
    rows = [row for row in rows if row["user"] is not None]
    rows.sort(key=lambda row: row["seen"] or row["since"] or timezone.now() - timedelta(days=365), reverse=True)
    return rows


def end_sessions(request, user=None, keep=None):
    """Log out a person (every device), or everyone but ``keep`` (a session key). Returns how many."""
    from django.contrib.sessions.models import Session

    from .models import SecurityEvent

    ended = 0
    for row in open_sessions():
        if row["key"] == keep or (user is not None and row["user_id"] != user.pk):
            continue
        Session.objects.filter(session_key=row["key"]).delete()
        log_event(SecurityEvent.Kind.FORCED_LOGOUT, request, user=row["user"],
                  details=_("by %(owner)s") % {"owner": request.user.get_username()}, path="")
        ended += 1
    return ended


# ------------------------------------------------------------------ middlewares
class NetworkFenceMiddleware:
    """Only the clinic's own network (ALLOWED_NETWORKS) may open the system; others get a short refusal."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        allowed = getattr(settings, "ALLOWED_NETWORKS", ["*"])
        if "*" not in allowed and not request.path.startswith(OUTSIDE_ALLOWED_PATHS):
            ip = client_ip(request)
            if ip is None or not _in(ip, _networks(allowed)):
                from .models import SecurityEvent

                recent = SecurityEvent.objects.filter(kind=SecurityEvent.Kind.OUTSIDE, ip=ip,
                                                      at__gte=timezone.now() - timedelta(hours=1))
                if not recent.exists():  # once an hour per address: the log is not flooded
                    SecurityEvent.objects.create(kind=SecurityEvent.Kind.OUTSIDE, ip=ip, device=device(request),
                                                 path=request.path[:300])
                return HttpResponse("This system is open on the clinic's network only.\n"
                                    "هذا النظام يعمل على شبكة العيادة فقط.", status=403,
                                    content_type="text/plain; charset=utf-8")
        return self.get_response(request)


# 'wasm-unsafe-eval': the ID card reader (static/vendor/tesseract) runs WebAssembly; it does not allow eval().
# form-action: a WhatsApp "Send" button is a form that records the message and then opens WhatsApp; Chrome applies
# form-action to that last step too, so WhatsApp's addresses are allowed (round 13: it opened a blank page).
WHATSAPP = "https://wa.me https://api.whatsapp.com https://web.whatsapp.com whatsapp:"
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; media-src 'self' blob:; "
       "worker-src 'self' blob:; frame-src 'self' blob:; object-src 'none'; base-uri 'self'; "
       f"form-action 'self' {WHATSAPP}; "
       "frame-ancestors 'self'")
PERMISSIONS = "camera=(self), microphone=(), geolocation=(), payment=(), usb=()"


class SecurityHeadersMiddleware:
    """Pages may load scripts, styles and pictures from this server only, and only this server may frame them:
    a script slipped into a name or a note cannot call another site."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("Permissions-Policy", PERMISSIONS)
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            # Patient data is not kept in shared caches; the browser's own back button still works.
            response.headers.setdefault("Cache-Control", "private")
            disposition = response.get("Content-Disposition", "")
            if disposition.startswith("attachment") and response.status_code == 200 \
                    and not request.path.startswith("/media/"):
                # Data taken out of the system (an export, a Word or Excel file, a backup): written in the log.
                from .models import SecurityEvent

                log_event(SecurityEvent.Kind.EXPORT, request, details=file_name(disposition))
        return response


def file_name(disposition):
    """The file's name in a Content-Disposition header (plain, or in UTF-8 for Arabic names)."""
    from urllib.parse import unquote

    for part in disposition.split(";"):
        key, _sep, value = part.strip().partition("=")
        if key.lower() == "filename*" and "''" in value:
            return unquote(value.split("''", 1)[1])
    for part in disposition.split(";"):
        key, _sep, value = part.strip().partition("=")
        if key.lower() == "filename":
            return value.strip('"')
    return ""


class IdleLogoutMiddleware:
    """A PC left open (the reception's, a tablet) logs out by itself after the minutes of Settings → Clinic
    options without use. The bell's own checks do not count as use. Also keeps who is working now (the request's
    user and page) for the deleted records. Must come after AuthenticationMiddleware."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        user_token = _current_user.set(user if user is not None and user.is_authenticated else None)
        path_token = _current_path.set(request.path[:300])
        try:
            if user is not None and user.is_authenticated:
                expired = self._check(request)
                if expired is not None:
                    return expired
            return self.get_response(request)
        finally:
            _current_user.reset(user_token)
            _current_path.reset(path_token)

    def _check(self, request):
        from .models import ClinicSettings, SecurityEvent

        minutes = ClinicSettings.get().idle_logout_minutes
        now = int(time.time())
        seen = request.session.get("seen")
        background = request.path.startswith(BACKGROUND_PATHS)
        if minutes and seen and now - seen > minutes * 60:
            request._logout_kind = SecurityEvent.Kind.IDLE_LOGOUT
            logout(request)
            messages.info(request, _("You were logged out after %(n)s minutes without use. Log in again.")
                          % {"n": minutes})
            if background or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({"logged_out": True, "login": reverse("login")}, status=401)
            target = reverse("login")
            if request.method == "GET":
                from urllib.parse import urlencode

                target += "?" + urlencode({"next": request.get_full_path()})
            return redirect(target)
        if not background and (not seen or now - seen >= 60):  # written at most once a minute
            request.session["seen"] = now
        return None


# ------------------------------------------------------------------ deleted records
SKIP_DELETED = {"core.securityevent", "core.deletedrecord", "core.notification", "core.backuprun",
                "core.problemreport", "core.areaaccess", "core.personareaaccess", "sessions.session",
                "admin.logentry"}


def _our_model(model):
    module = model.__module__ or ""
    label = model._meta.label_lower
    return module.startswith("apps.") and label not in SKIP_DELETED and not model._meta.auto_created


@receiver(pre_delete)
def _keep_deleted(sender, instance, **kwargs):
    """Every record deleted from the system is kept with what it held, who deleted it and when."""
    if not _our_model(sender) or kwargs.get("raw"):
        return
    from django.core import serializers

    from .models import DeletedRecord

    try:
        fields = serializers.serialize("python", [instance])[0]["fields"]
    except Exception:  # noqa: BLE001 - a record that cannot be written out is still noted
        fields = {}
    data = DjangoJSONEncoder().encode(fields)
    user = _current_user.get()
    DeletedRecord.objects.create(model=sender._meta.label_lower[:100], label=str(instance)[:300],
                                 object_id=str(instance.pk)[:40], data=json.loads(data),
                                 deleted_by=user if user is not None and user.pk else None,
                                 page=_current_path.get())


class working_as:
    """Deletions made outside a page (a command, the sample data) are written in the name of ``user``."""

    def __init__(self, user, page=""):
        self.user, self.page = user, page

    def __enter__(self):
        self.tokens = _current_user.set(self.user), _current_path.set(self.page)
        return self

    def __exit__(self, *exc):
        _current_user.reset(self.tokens[0])
        _current_path.reset(self.tokens[1])
        return False


def clean_old_records():
    """The security log and the deleted records are kept a year (the nightly backup calls this)."""
    from .models import DeletedRecord, SecurityEvent

    limit = timezone.now() - timedelta(days=KEEP_DAYS)
    removed = SecurityEvent.objects.filter(at__lt=limit).delete()[0]
    removed += DeletedRecord.objects.filter(deleted_at__lt=limit).delete()[0]
    from .kept_uploads import clean_old

    removed += clean_old()  # photos kept for a form never sent again (round 13)
    from .models import WorkSession

    removed += WorkSession.objects.filter(started_at__lt=timezone.now() - timedelta(days=2 * KEEP_DAYS)).delete()[0]
    return removed
