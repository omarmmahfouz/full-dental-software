"""Uploaded files are checked by what they hold, not only by their name: a program or a web page renamed to
"photo.jpg" is refused (round 11). Files of other kinds (e.g. the lab's 3D scans) may be uploaded where allowed, but
never programs or web pages."""

import os

# The first bytes of each kind of file allowed as a photo, a video or a PDF.
SIGNATURES = {
    ".jpg": (lambda h: h.startswith(b"\xff\xd8\xff")),
    ".jpeg": (lambda h: h.startswith(b"\xff\xd8\xff")),
    ".png": (lambda h: h.startswith(b"\x89PNG\r\n\x1a\n")),
    ".webp": (lambda h: h[:4] == b"RIFF" and h[8:12] == b"WEBP"),
    ".gif": (lambda h: h[:6] in (b"GIF87a", b"GIF89a")),
    ".bmp": (lambda h: h[:2] == b"BM"),
    ".tif": (lambda h: h[:4] in (b"II*\x00", b"MM\x00*")),
    ".tiff": (lambda h: h[:4] in (b"II*\x00", b"MM\x00*")),
    ".heic": (lambda h: h[4:8] == b"ftyp"),
    ".heif": (lambda h: h[4:8] == b"ftyp"),
    ".pdf": (lambda h: b"%PDF" in h[:1024]),
    ".mp4": (lambda h: h[4:8] in (b"ftyp", b"moov", b"mdat", b"wide", b"free")),
    ".m4v": (lambda h: h[4:8] in (b"ftyp", b"moov", b"mdat", b"wide", b"free")),
    ".mov": (lambda h: h[4:8] in (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip")),
    ".webm": (lambda h: h[:4] == b"\x1a\x45\xdf\xa3"),
    ".avi": (lambda h: h[:4] == b"RIFF" and h[8:11] == b"AVI"),
}
# Never accepted anywhere: programs, scripts and web pages.
BLOCKED = {".exe", ".bat", ".cmd", ".com", ".msi", ".scr", ".dll", ".lnk", ".ps1", ".vbs", ".vbe", ".js", ".jse",
           ".wsf", ".jar", ".sh", ".php", ".py", ".pl", ".html", ".htm", ".xhtml", ".svg", ".hta", ".reg", ".cpl",
           ".msp", ".apk", ".app", ".dmg", ".iso"}


def extension(upload):
    return os.path.splitext(getattr(upload, "name", "") or "")[1].lower()


def head(upload, size=1024):
    """The first bytes of an upload (the file is left where it was)."""
    position = upload.tell() if hasattr(upload, "tell") else 0
    try:
        upload.seek(0)
        return upload.read(size) or b""
    finally:
        upload.seek(position)


def looks_right(upload):
    """True when a photo, video or PDF holds what its name says."""
    check = SIGNATURES.get(extension(upload))
    return bool(check and check(head(upload)))


def is_blocked(upload):
    return extension(upload) in BLOCKED or head(upload, 2) == b"MZ"  # a Windows program, whatever its name
