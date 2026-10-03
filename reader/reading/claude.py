"""Asking Claude (Anthropic's API) to read one page: the instructions, the form of the answer, and the two ways of
sending (now, or in a batch at half price). The key is ANTHROPIC_API_KEY in the reader's .env file, never in the
code. Nothing is sent unless reading is switched on (Settings)."""

import base64
import json

from .catalogue import CONDITIONS, DATE, DECIMAL, DENTIST, LISTED, NUMBER, PHONE, YES_NO, by_name, specs
from .models import PaperPage

MAX_TOKENS = 16000
# A page that Claude's safety checks decline is read again by the model Anthropic recommends (only when sent now:
# the batches do not take this option).
FALLBACK_BETA = "server-side-fallback-2026-07-01"
BATCH_BYTES = 150 * 1024 * 1024  # a batch may hold 256 MB: the pictures are sent inside it


class KeyProblem(Exception):
    """The key is missing or refused: nothing can be read until the owner fixes it."""


class TryLater(Exception):
    """No internet, or Anthropic is busy: the page is sent again later."""


INSTRUCTIONS = """You read scanned pages of old patient files of a dental clinic in Egypt (the Cairo Implant Academy \
and its clinics), so the reception does not have to type them again. A person checks every answer before it is \
saved, so say clearly what you are not sure of.

Each request is one page of one patient's paper file, as a picture. A file can hold: a cover sheet printed by the \
clinic with the file number in large print; the national ID card (front and back); a registration form with the \
patient's data (in Arabic or English); the medical and dental history of the CIA paper chart (questions with ticks, \
yes/no and short answers, readings such as blood pressure and blood sugar); the examination; a drawing of the teeth; \
the treatment plan; the surgery chart; the treatment log of the visits; prescriptions; lab papers; signed consents; \
receipts; X-rays and photos.

Answer with:
- page_kind: what the page is.
- turn: the degrees to turn the picture clockwise so that the writing reads upright (0 when it already does).
- cover_file_number: on a cover sheet, the file number printed on it, exactly (e.g. CIA-00123); else "".
- page_notes: a short note in plain English when the page is hard to read (faded, cut, crossed out), else "".
- fields: the values from the list below that are written on this page.

For each value:
- name: one of the names in the list below.
- written: exactly what is written, letter by letter, in the language and the digits used on the paper.
- value: the same value made clean: Western digits (0-9) instead of Arabic-Indic digits; dates as dd/mm/yyyy; for a \
value with allowed answers, the code of the answer; for a tick box, "yes" or "no"; else the text as written.
- certainty: "sure" when the writing is clear and you are certain; "check" when it could be read another way (a digit \
or a letter that could be another one, a word partly hidden); "unclear" when you cannot read it (then value is "").
- box: [left, top, right, bottom]: where the written value is on this picture, in pixels, counted from the top left \
corner of the picture exactly as it is sent (before any turn). Cover the handwriting itself, not the printed question.
- note: a short note in plain English when something is odd (two values written, a correction, a value written \
outside its place), else "".

Rules:
- Never guess. A value that is not written is left out. A value that is written but cannot be read is listed with \
certainty "unclear".
- Copy numbers digit by digit. The national ID has 14 digits; Egyptian mobiles have 11 digits and start with 010, 011, \
012 or 015. When the number of digits written is different, copy what is written and use "check".
- full_name is the patient's full name as on the ID card (at least three names, in Arabic). A short name in the \
heading of a page is not the full name: leave it out.
- On the ID card, read the name, the address and the national ID (front), and the job, the gender and the marital \
status (back). Leave out the card's printed headings and its dates of issue and expiry.
- A value with allowed answers: give the code. When the paper says something that is not in the list, give the \
paper's words as value and use "check".
- conditions: the diseases ticked or written under "did you ever have", as the codes from its list, separated by \
commas. A disease that is not in the list goes to other_condition.
- Tick boxes: a tick, a circle or a cross on yes is "yes", on no is "no". An empty tick box is left out.
- Readings: blood pressure is two values (systolic and diastolic); write each in its own field.
- Only the values in the list are read now. The teeth, the plan, the visits, the prescriptions and the receipts are \
kept as pages: do not list them.

The values (name (kind): label in English / label in Arabic; allowed answers as code = meaning):
"""

KIND_HINTS = {DATE: "date", NUMBER: "number", DECIMAL: "number with a decimal point", PHONE: "mobile",
              YES_NO: "yes / no", CONDITIONS: "codes separated by commas"}


def instructions():
    """The fixed part of every request (the same for every page, so Anthropic keeps it ready and charges a tenth)."""
    lines = []
    for spec in specs():
        kind = KIND_HINTS.get(spec.kind, "text")
        line = f"- {spec.name} ({kind}): {spec.label_en} / {spec.label_ar}"
        if spec.kind in LISTED and spec.choices:
            line += "; answers: " + "; ".join(f"{code} = {' / '.join(word for word in (english, arabic) if word)}"
                                             for code, english, arabic in spec.choices)
        if spec.kind == DENTIST:
            line += " (when the name is not in the list, give the name as written and use \"check\")"
        lines.append(line)
    return INSTRUCTIONS + "\n".join(lines)


def schema():
    """The form of every answer (Claude's answer always follows it)."""
    return {
        "type": "object",
        "properties": {
            "page_kind": {"type": "string", "enum": [str(kind) for kind in PaperPage.Kind.values]},
            "turn": {"type": "integer", "enum": [0, 90, 180, 270]},
            "cover_file_number": {"type": "string"},
            "page_notes": {"type": "string"},
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": [spec.name for spec in specs()]},
                        "written": {"type": "string"},
                        "value": {"type": "string"},
                        "certainty": {"type": "string", "enum": ["sure", "check", "unclear"]},
                        "box": {"type": "array", "items": {"type": "integer"}},
                        "note": {"type": "string"},
                    },
                    "required": ["name", "written", "value", "certainty", "box", "note"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["page_kind", "turn", "cover_file_number", "page_notes", "fields"],
        "additionalProperties": False,
    }


def request_params(page, options, system=None, form=None):
    """What is sent for one page (``system`` and ``form`` are made once for many pages)."""
    page.image.open("rb")
    try:
        picture = base64.standard_b64encode(page.image.read()).decode("ascii")
    finally:
        page.image.close()
    return {
        "model": options.model,
        "max_tokens": MAX_TOKENS,
        "system": [{"type": "text", "text": system or instructions(), "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": picture}},
            {"type": "text", "text": f"Page {page.number} of {page.file.page_count}. The picture is {page.width} x "
                                     f"{page.height} pixels."},
        ]}],
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": options.effort, "format": {"type": "json_schema", "schema": form or schema()}},
    }


def client():
    import anthropic

    return anthropic.Anthropic(max_retries=3, timeout=600)


def _errors(error):
    """Turn the library's errors into: a key problem, try later, or a problem with this page (ValueError)."""
    import anthropic

    if isinstance(error, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return KeyProblem(str(getattr(error, "message", error))[:300])
    if isinstance(error, (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError)):
        return TryLater(str(error)[:300])
    if isinstance(error, anthropic.APIStatusError) and error.status_code in (408, 409, 429, 529) \
            or isinstance(error, anthropic.APIStatusError) and error.status_code >= 500:
        return TryLater(str(error)[:300])
    return ValueError(str(getattr(error, "message", error))[:300])


def usage_of(message):
    usage = message.usage
    return {"input_tokens": usage.input_tokens or 0, "output_tokens": usage.output_tokens or 0,
            "cache_read_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
            "cache_write_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0}


def answer_of(message, known=None):
    """(the answer as a dict, or None; the problem when there is no answer)."""
    if message.stop_reason == "refusal":
        return None, "declined"
    if message.stop_reason == "max_tokens":
        return None, "too long"
    text = next((block.text for block in message.content if getattr(block, "type", "") == "text"), "")
    try:
        answer = json.loads(text)
    except ValueError:
        return None, "not understood"
    if not isinstance(answer, dict) or not isinstance(answer.get("fields"), list):
        return None, "not understood"
    known = known or by_name()
    answer["fields"] = [entry for entry in answer["fields"] if isinstance(entry, dict) and entry.get("name") in known]
    return answer, ""


def read_now(page, options, system=None, form=None, known=None):
    """Read one page now: (answer or None, problem, usage, model). It runs in a thread of its own: everything read
    from the database (the instructions, the answer form, the values known) is given to it."""
    import anthropic

    params = request_params(page, options, system, form)
    try:
        message = client().beta.messages.create(**params, betas=[FALLBACK_BETA], fallbacks="default")
    except anthropic.APIError as error:
        raise _errors(error) from error
    answer, problem = answer_of(message, known)
    return answer, problem, usage_of(message), message.model


def send_batch(items, options, system=None):
    """Send [(custom id, page)] as one batch; returns the batch's id."""
    import anthropic

    form = schema()
    requests = [{"custom_id": custom_id, "params": request_params(page, options, system, form)}
                for custom_id, page in items]
    try:
        batch = client().messages.batches.create(requests=requests)
    except anthropic.APIError as error:
        raise _errors(error) from error
    return batch.id


def batch_results(batch_id):
    """None while the batch is being read; else [(custom id, answer or None, problem, usage or None, model)]."""
    import anthropic

    try:
        batch = client().messages.batches.retrieve(batch_id)
        if batch.processing_status != "ended":
            return None
        rows = []
        for item in client().messages.batches.results(batch_id):
            result = item.result
            if result.type == "succeeded":
                answer, problem = answer_of(result.message)
                rows.append((item.custom_id, answer, problem, usage_of(result.message), result.message.model))
            else:
                rows.append((item.custom_id, None, result.type, None, ""))
        return rows
    except anthropic.APIError as error:
        raise _errors(error) from error


def check_key(options):
    """Ask Anthropic whether the key works and the model is open to it (free: nothing is read)."""
    import anthropic

    try:
        client().models.retrieve(options.model)
    except anthropic.APIError as error:
        raise _errors(error) from error
