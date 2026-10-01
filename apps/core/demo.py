"""Round 11 sample data: the security log (logins, wrong passwords, a login closed after wrong passwords, a visit
from outside the clinic's network, files taken out, a page refused) and a record deleted by mistake."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import DeletedRecord, SecurityEvent
from .security import working_as

DEVICES = {
    "pc": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36",
    "ipad": "Mozilla/5.0 (iPad; CPU OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 "
            "Mobile/15E148 Safari/604.1",
    "phone": "Mozilla/5.0 (Linux; Android 14; SM-A546E) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Mobile "
             "Safari/537.36",
    "bot": "python-requests/2.31",
}


def load_round_eleven(patients, secretary):
    users = get_user_model().objects.in_bulk(field_name="username")
    now = timezone.now()

    def event(kind, minutes_ago, username="", ip="192.168.1.10", device="pc", **extra):
        user = users.get(username)
        SecurityEvent.objects.create(kind=kind, at=now - timedelta(minutes=minutes_ago), user=user,
                                     username=username, ip=ip, device=DEVICES[device], **extra)

    day = 24 * 60
    K = SecurityEvent.Kind
    # An ordinary day: the reception, the doctors on the tablets, the lab.
    for username, ip, device, minutes in [("owner", "192.168.1.10", "pc", 2 * day + 300),
                                          ("secretary", "192.168.1.21", "pc", 2 * day + 200),
                                          ("dentist1", "192.168.1.35", "ipad", 2 * day + 150),
                                          ("labsec", "192.168.1.60", "pc", 2 * day + 120),
                                          ("khadem", "192.168.2.15", "pc", day + 400),
                                          ("dentist2", "192.168.1.36", "ipad", day + 250),
                                          ("owner", "192.168.1.10", "pc", day + 90)]:
        event(K.LOGIN, minutes, username, ip, device, path="/login/")
    # The secretary mistyped her password twice, then got in.
    event(K.LOGIN_FAILED, day + 182, "secretary", "192.168.1.21", path="/login/")
    event(K.LOGIN_FAILED, day + 181, "secretary", "192.168.1.21", path="/login/")
    event(K.LOGIN, day + 180, "secretary", "192.168.1.21", path="/login/")
    event(K.IDLE_LOGOUT, day + 30, "secretary", "192.168.1.21")
    # Someone on the guest Wi-Fi tried "admin" with guessed passwords at night: closed after five.
    for n in range(5):
        event(K.LOGIN_FAILED, 3 * day + 60 - n, "admin", "192.168.1.77", "phone", path="/login/")
    event(K.LOCKED, 3 * day + 55, "admin", "192.168.1.77", "phone", details="5 wrong passwords")
    # A program on the internet knocked on the server: refused, it is not the clinic's network.
    event(K.OUTSIDE, 4 * day + 700, "", "41.33.12.5", "bot", path="/admin/login/")
    # Pages refused and files taken out.
    event(K.DENIED, day + 120, "secretary2", "192.168.1.22", path="/reports/money/")
    first = patients[4]
    event(K.EXPORT, day + 85, "owner", details=f"{first.file_number} {first.full_name}.xlsx",
          path=f"/patients/{first.pk}/excel/")
    event(K.EXPORT, 2 * day + 290, "owner", details="all-data.xlsx", path="/settings/backup/excel/")
    event(K.PASSWORD_CHANGED, 2 * day + 140, "dentist1", "192.168.1.35", "ipad", path="/password/")

    # A paper deleted by mistake at the reception: kept with what it held, who and when. (The rows the earlier
    # sample data replaced while it was being made are not shown.)
    DeletedRecord.objects.filter(deleted_by=None).delete()
    from apps.patients.models import PatientDocument

    patient = patients[2]
    paper = PatientDocument.objects.create(patient=patient, kind=PatientDocument.Kind.OTHER, created_by=secretary,
                                           location="https://lab.example/referral/5512",
                                           notes="Referral letter from Dr. Hesham (implant, lower left)")
    PatientDocument.objects.filter(pk=paper.pk).update(created_at=now - timedelta(days=3))
    paper.refresh_from_db()
    with working_as(secretary, f"/patients/{patient.pk}/documents/{paper.pk}/delete/"):
        paper.delete()
    DeletedRecord.objects.filter(deleted_by=secretary).update(deleted_at=now - timedelta(hours=20))
