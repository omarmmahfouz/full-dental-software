"""The reading of the paper files, done in the background so nobody waits on a page: new files are cut into pages,
the pages are sent to Claude (now, or in a batch at half price), the answers are collected and checked, and the
person who sent the file is told when it is ready to check.

It runs in a thread of the server, started when a file is sent and when the list of paper files is opened (so it
goes on after the server restarts), or by ``python manage.py read_paper_files`` (e.g. from the nightly task). Each
page is taken by one worker only, so two servers or two threads never send it twice."""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections, connection
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from . import claude
from .checks import build_fields, settle_pages
from .models import PaperFile, PaperReading, PaperSettings, month_cost, reading_estimate
from .pages import PagesProblem, make_pages

log = logging.getLogger("clinic.papers")
POLL_SECONDS = 60
MAX_TRIES = 3
AT_ONCE = 4  # pages read at the same time when sent now
IDLE, WORKING, WAITING = "idle", "working", "waiting"
STALE = timedelta(minutes=15)  # a file taken by a reader that stopped half way is taken again after this
_lock = threading.Lock()
_polled = {}


def kick():
    """Start the reader in this server when it is not running yet (never while the tests run)."""
    if not getattr(settings, "PAPERS_IN_BACKGROUND", True) or not _lock.acquire(blocking=False):
        return False
    threading.Thread(target=_run, name="paper-reader", daemon=True).start()
    return True


def _run():
    try:
        while True:
            close_old_connections()
            state = run_once()
            if state == IDLE:
                break
            time.sleep(POLL_SECONDS if state == WAITING else 1)
    except Exception:  # noqa: BLE001 - the reason is in the log; the next kick starts again
        log.exception("The paper files reader stopped")
    finally:
        connection.close()
        _lock.release()


def run_once(poll_gap=POLL_SECONDS):
    """One round of work. Returns "working" (more to do now), "waiting" (batches being read) or "idle". A batch is
    asked about at most every ``poll_gap`` seconds."""
    worked = _prepare()
    options = PaperSettings.get()
    try:
        if options.enabled and options.key_is_set:
            waiting = PaperReading.objects.filter(status=PaperReading.Status.WAITING)
            if waiting.exists() and not _can_spend(options):
                _limit_reached(options)
            else:
                worked |= _send_batches(options)
                worked |= _read_now(options)
        else:
            problem = "off" if not options.enabled else "no_key"
            PaperFile.objects.filter(status=PaperFile.Status.WAITING, page_count__gt=0).exclude(error=problem) \
                .update(error=problem)
        if options.key_is_set:
            worked |= _collect(poll_gap)
    except claude.KeyProblem as error:
        _key_problem(str(error))
        return IDLE
    except claude.TryLater:
        return WAITING
    worked |= _finish()
    if worked:
        return WORKING
    sending = options.enabled and options.key_is_set
    if options.key_is_set and PaperReading.objects.filter(status=PaperReading.Status.SENT).exists() or (
            sending and PaperReading.objects.filter(status=PaperReading.Status.WAITING).exists()
            and _can_spend(options)):
        return WAITING
    return IDLE


def run_until_done(sleep=time.sleep):
    """Work until nothing is left (the command); batches are asked about every minute."""
    while True:
        state = run_once(poll_gap=0)  # it waits a minute itself between the rounds
        if state == IDLE:
            return
        sleep(POLL_SECONDS if state == WAITING else 0)


# ------------------------------------------------------------------------------------------- the steps
def _take(paper):
    """Take a file for this reader (False when another reader has it)."""
    now = timezone.now()
    taken = PaperFile.objects.filter(pk=paper.pk, status=paper.status).filter(
        Q(claimed_at=None) | Q(claimed_at__lt=now - STALE)).update(claimed_at=now)
    return taken == 1


def _let_go(paper):
    PaperFile.objects.filter(pk=paper.pk).update(claimed_at=None)


def _prepare():
    """Cut the new files into pages (no internet needed) and plan their readings."""
    worked = False
    options = PaperSettings.get()
    for paper in PaperFile.objects.filter(status=PaperFile.Status.WAITING, page_count=0).select_related("branch")[:10]:
        if not _take(paper):
            continue
        paper.pages.all().delete()  # what a reader that stopped half way left
        try:
            pages = make_pages(paper)
        except (PagesProblem, OSError, ValueError) as error:
            paper.mark(PaperFile.Status.FAILED, f"bad_pdf:{error}")
            _let_go(paper)
            worked = True
            continue
        readings = 2 if options.two_readings else 1
        PaperReading.objects.bulk_create(
            PaperReading(page=page, number=number) for page in pages for number in range(1, readings + 1))
        _let_go(paper)
        worked = True
    return worked


def _spendable(options):
    """The dollars that may still be spent this month (None = no limit): the limit, less what was spent and what the
    readings sent and not back yet will about cost."""
    if not options.monthly_limit:
        return None
    pending = sum(reading_estimate(model, batched) for model, batched in PaperReading.objects.filter(
        status__in=(PaperReading.Status.SENDING, PaperReading.Status.SENT)).values_list("model", "batched"))
    return options.monthly_limit - month_cost() - pending


def _can_spend(options):
    left = _spendable(options)
    return left is None or left >= reading_estimate(options.model, batched=True)


def _within_limit(readings, options, batched):
    """As many of ``readings`` as the month's limit still allows."""
    left = _spendable(options)
    if left is None:
        return readings
    return readings[:max(0, int(left / reading_estimate(options.model, batched)))]


def _claim(readings):
    """Take readings for this worker; only those still waiting (another worker may have taken some)."""
    ids = [reading.pk for reading in readings]
    PaperReading.objects.filter(pk__in=ids, status=PaperReading.Status.WAITING).update(
        status=PaperReading.Status.SENDING, sent_at=timezone.now())
    return [reading for reading in PaperReading.objects.filter(pk__in=ids, status=PaperReading.Status.SENDING)
            .select_related("page__file__branch").order_by("pk")]


def _release(readings):
    PaperReading.objects.filter(pk__in=[r.pk for r in readings], status=PaperReading.Status.SENDING).update(
        status=PaperReading.Status.WAITING)


def _started(readings):
    """The files whose pages are now with Claude: being read, and noted in the security log (data sent out)."""
    from apps.core.models import SecurityEvent
    from apps.core.security import log_event

    papers = {reading.page.file for reading in readings}
    for paper in papers:
        PaperFile.objects.filter(pk=paper.pk).update(status=PaperFile.Status.READING, error="")
        if paper.status == PaperFile.Status.WAITING:
            log_event(SecurityEvent.Kind.EXPORT, user=paper.created_by,
                      details=f"Paper file sent to Claude to be read: {paper.original_name} ({paper.page_count} pages)",
                      path=reverse("papers:review", args=[paper.pk]))


def _send_batches(options):
    readings = list(PaperReading.objects.filter(status=PaperReading.Status.WAITING,
                                                page__file__mode=PaperSettings.Mode.BATCH)
                    .exclude(error="declined").order_by("pk")[:2000])
    readings = _within_limit(readings, options, batched=True)
    if not readings:
        return False
    readings = _claim(readings)
    chunks, chunk, size = [], [], 0
    for reading in readings:  # a batch holds the pictures: at most BATCH_BYTES each
        weight = reading.page.image.size * 4 // 3 + 8000
        if chunk and size + weight > claude.BATCH_BYTES:
            chunks.append(chunk)
            chunk, size = [], 0
        chunk.append(reading)
        size += weight
    if chunk:
        chunks.append(chunk)
    system = claude.instructions()
    for index, chunk in enumerate(chunks):
        try:
            batch_id = claude.send_batch([(f"r{r.pk}", r.page) for r in chunk], options, system)
        except ValueError as error:
            PaperReading.objects.filter(pk__in=[r.pk for r in chunk]).update(
                status=PaperReading.Status.FAILED, error=str(error)[:300], done_at=timezone.now())
        except (claude.KeyProblem, claude.TryLater):
            _release([reading for rest in chunks[index:] for reading in rest])
            raise
        else:
            PaperReading.objects.filter(pk__in=[r.pk for r in chunk]).update(
                status=PaperReading.Status.SENT, batch_id=batch_id, batched=True, model=options.model,
                error="", sent_at=timezone.now())
        _started(chunk)
    return True


def _read_now(options):
    readings = list(PaperReading.objects.filter(status=PaperReading.Status.WAITING).filter(
        Q(page__file__mode=PaperSettings.Mode.NOW) | Q(error="declined")).order_by("pk")[:AT_ONCE * 2])
    readings = _within_limit(readings, options, batched=False)
    if not readings:
        return False
    readings = _claim(readings)
    system = claude.instructions()
    _started(readings)

    def read(reading):
        try:
            return reading, claude.read_now(reading.page, options, system), None
        except Exception as error:  # noqa: BLE001 - kept with the reading
            return reading, None, error

    stop = None
    with ThreadPoolExecutor(max_workers=AT_ONCE) as pool:
        for reading, outcome, error in pool.map(read, readings):
            if outcome is not None:
                answer, problem, usage, model = outcome
                _save(reading, answer, problem, usage, model, batched=False)
            elif isinstance(error, (claude.KeyProblem, claude.TryLater)):
                _release([reading])
                stop = stop or error
            else:
                _save(reading, None, str(error), None, options.model, batched=False)
    if stop is not None:
        raise stop
    return True


def _save(reading, answer, problem, usage, model, batched):
    reading.tries += 1
    if answer is None and problem in ("errored", "expired", "canceled") and reading.tries < MAX_TRIES:
        reading.status = PaperReading.Status.WAITING  # sent again with the next batch
    elif answer is None and problem == "declined" and batched and reading.tries < MAX_TRIES:
        reading.status = PaperReading.Status.WAITING  # read again now, with the fallback model
    else:
        reading.status = PaperReading.Status.DONE if answer is not None else PaperReading.Status.FAILED
        reading.done_at = timezone.now()
    reading.result, reading.error, reading.batched = answer, (problem or "")[:300], batched
    reading.model = model or reading.model
    for key, value in (usage or {}).items():
        setattr(reading, key, getattr(reading, key) + value)
    reading.save()


def _collect(poll_gap=POLL_SECONDS):
    """Ask about the batches being read; save the answers of those that ended."""
    worked = False
    now = time.monotonic()
    for batch_id in set(PaperReading.objects.filter(status=PaperReading.Status.SENT).values_list("batch_id", flat=True)):
        if batch_id in _polled and now - _polled[batch_id] < poll_gap:
            continue
        _polled[batch_id] = now
        rows = claude.batch_results(batch_id)
        if rows is None:
            continue
        readings = {f"r{r.pk}": r for r in PaperReading.objects.filter(batch_id=batch_id,
                                                                       status=PaperReading.Status.SENT)}
        for custom_id, answer, problem, usage, model in rows:
            reading = readings.pop(custom_id, None)
            if reading is not None:
                _save(reading, answer, problem, usage, model, batched=True)
        for reading in readings.values():  # not in the results: sent again
            _save(reading, None, "expired", None, "", batched=True)
        _polled.pop(batch_id, None)
        worked = True
    return worked


def _finish():
    """The files whose pages are all read: their pages settled, their values checked, the sender told."""
    worked = False
    busy = (PaperReading.Status.WAITING, PaperReading.Status.SENDING, PaperReading.Status.SENT)
    for paper in PaperFile.objects.filter(status=PaperFile.Status.READING).exclude(
            pages__readings__status__in=busy).select_related("branch", "created_by").distinct()[:20]:
        if _take(paper):  # one reader only: a page must not be turned twice
            finish(paper)
            _let_go(paper)
            worked = True
    return worked


def finish(paper):
    readings = PaperReading.objects.filter(page__file=paper)
    if not readings.filter(status=PaperReading.Status.DONE).exists():
        paper.mark(PaperFile.Status.FAILED, "unread")
    else:
        turns = settle_pages(paper)
        build_fields(paper, turns)
        PaperFile.objects.filter(pk=paper.pk).update(status=PaperFile.Status.REVIEW, read_at=timezone.now(), error="")
        paper.status = PaperFile.Status.REVIEW
    _tell(paper)


def _tell(paper):
    """Tell the sender once all the files sent together are read."""
    from apps.core.models import Notification
    from apps.core.notify import notify_users

    if paper.created_by is None:
        return
    group = PaperFile.objects.filter(upload=paper.upload) if paper.upload else PaperFile.objects.filter(pk=paper.pk)
    if group.filter(status__in=(PaperFile.Status.WAITING, PaperFile.Status.READING)).exists():
        return
    files = list(group)
    if len(files) == 1:
        flagged = paper.fields.exclude(certainty="sure").count()
        notify_users([paper.created_by], _("Paper file read: %(name)s"),
                     _("%(n)s values to check, the rest are sure.") if paper.status == PaperFile.Status.REVIEW
                     else _("It could not be read."), reverse("papers:review", args=[paper.pk]),
                     Notification.Level.INFO if paper.status == PaperFile.Status.REVIEW else Notification.Level.WARNING,
                     params={"name": paper.original_name, "n": flagged})
    else:
        notify_users([paper.created_by], _("%(n)s paper files are read"), _("They wait for checking."),
                     reverse("papers:list") + "?status=review", Notification.Level.INFO, params={"n": len(files)})


def _limit_reached(options):
    from apps.core.models import Notification
    from apps.core.notify import notify_roles
    from apps.core.roles import OWNER

    problem = "limit"
    waiting = PaperReading.objects.filter(status=PaperReading.Status.WAITING).values_list("page__file", flat=True)
    PaperFile.objects.filter(pk__in=set(waiting), status__in=(PaperFile.Status.WAITING, PaperFile.Status.READING)) \
        .update(error=problem)
    key = f"papers-limit-{timezone.localdate():%Y-%m}"
    if cache.add(key, True, 31 * 24 * 3600):
        notify_roles([OWNER], _("Paper files: the monthly limit is reached"),
                     _("Nothing more is sent to Claude this month. Raise the limit in Settings → Old paper files to "
                       "go on."), reverse("papers:settings"), Notification.Level.WARNING)


def _key_problem(error):
    from apps.core.models import Notification
    from apps.core.notify import notify_roles
    from apps.core.roles import OWNER

    PaperFile.objects.filter(status__in=(PaperFile.Status.WAITING, PaperFile.Status.READING)).update(
        error="key_refused")
    log.warning("Claude refused the key: %s", error)
    if cache.add("papers-key-problem", True, 3600):
        notify_roles([OWNER], _("Paper files: the key to Claude was refused"),
                     _("Nothing can be read until the key is fixed."), reverse("papers:settings"),
                     Notification.Level.WARNING)
