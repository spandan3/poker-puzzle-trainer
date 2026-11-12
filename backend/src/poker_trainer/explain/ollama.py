"""The Ollama client (stdlib ``urllib``, no dependency): the rewording call, the status probe,
the prompt and the reply parsing.

The model only rewords the template; ``service.Explainer`` checks its output with the guardrail.
Every failure is one of the ``LlmFailure`` subclasses, whose ``reason`` is the explanation's
``fallback``:

- ``LlmUnavailable``: connection refused, an unknown host, HTTP 404 (the model isn't pulled);
- ``LlmTimeout``: no answer within the timeout, on connect or on read;
- ``LlmError``: any other HTTP error (a 400 from an Ollama older than 0.5, which has no JSON
  schema ``format``), a dropped connection, a reply that isn't Ollama's JSON;
- ``LlmInvalid``: the model's text isn't the JSON object asked for.

The opener never uses a proxy (environment or system): the model is local.
"""

from __future__ import annotations

import http.client
import json
import urllib.request
from typing import Any, Literal
from urllib.error import HTTPError, URLError

from poker_trainer.explain.facts import Facts

FIELDS = ("headline", "hand", "verdict")
MAX_FIELD_CHARS = 1200
PROBE_TIMEOUT = 1.5  # seconds
KEEP_ALIVE = "10m"  # keep the model loaded between results
TEMPERATURE = 0.2

ProbeStatus = Literal["ready", "unavailable"]


class LlmFailure(Exception):
    reason = "error"


class LlmUnavailable(LlmFailure):
    reason = "unavailable"


class LlmTimeout(LlmFailure):
    reason = "timeout"


class LlmError(LlmFailure):
    reason = "error"


class LlmInvalid(LlmFailure):
    reason = "invalid"


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

# The structured output the model must give (Ollama's ``format``, Ollama 0.5 or newer).
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {name: {"type": "string"} for name in FIELDS},
    "required": list(FIELDS),
}

# No number token and no number word in here (a test checks it): the guardrail only allows the
# numbers of the facts, so the instructions must not give the model any other number to copy.
INSTRUCTIONS = (
    "You reword poker explanations for a recreational player. The user message holds FACTS, "
    "which are every number you may use, and an EXPLANATION written by the trainer as a JSON "
    "object with the fields headline, hand and verdict.\n"
    "Rewrite the explanation in plain, friendly English and keep it short. Shorten by dropping "
    "sentences, never by rounding numbers.\n"
    "Rules:\n"
    "- Use only numbers that appear in the facts, written exactly as they appear there, with "
    "the same unit (% or bb). Never compute, round, estimate or invent a number, and never "
    "write a number as a word. Never count things in words. Never write odds as a ratio or a "
    "fraction.\n"
    "- Keep card names exactly as written, with their suit symbols.\n"
    "- Talk about Villain's range. Mention only the expected values the explanation already "
    "mentions. Never mention cards dealt after the decision, Villain's actual cards, or who won "
    "the hand.\n"
    "- Add no advice that is not in the explanation.\n"
    "Reply with a JSON object only: headline is a single sentence, hand tells the hand up to "
    "the decision, verdict says why the decision was good or bad. In hand and verdict, "
    "separate paragraphs with a blank line."
)

_EXPLANATION_MARKER = "EXPLANATION:\n"


def fields_of(template: dict[str, Any]) -> dict[str, str]:
    """The template's headline, hand and verdict as the model's fields (paragraphs separated by
    blank lines)."""
    sections = {s["id"]: s["paragraphs"] for s in template["sections"]}
    return {
        "headline": template["headline"],
        "hand": "\n\n".join(sections["hand"]),
        "verdict": "\n\n".join(sections["verdict"]),
    }


def user_message(template: dict[str, Any], facts: Facts) -> str:
    """The facts block, then the template's text to reword (the Villain section is not
    reworded)."""
    return (
        "FACTS:\n"
        + "\n".join(facts.as_lines())
        + "\n\n"
        + _EXPLANATION_MARKER
        + json.dumps(fields_of(template), ensure_ascii=False, indent=2)
    )


def template_fields(prompt: str) -> dict[str, str]:
    """The template fields of a ``user_message`` (for fake models in tests and fixtures)."""
    return json.loads(prompt.split(_EXPLANATION_MARKER, 1)[1])


def parse_reply(content: str) -> dict[str, str]:
    """The model's fields, stripped; ``LlmInvalid`` unless it is a JSON object with every field
    a non-empty string of at most ``MAX_FIELD_CHARS`` characters."""
    try:
        data = json.loads(content)
    except ValueError as e:
        raise LlmInvalid("the reply is not JSON") from e
    if not isinstance(data, dict):
        raise LlmInvalid("the reply is not a JSON object")
    out: dict[str, str] = {}
    for name in FIELDS:
        value = data.get(name)
        if not isinstance(value, str) or not value.strip():
            raise LlmInvalid(f"{name} is missing or empty")
        value = value.strip()
        if len(value) > MAX_FIELD_CHARS:
            raise LlmInvalid(f"{name} is too long")
        out[name] = value
    return out


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def _opener() -> urllib.request.OpenerDirector:
    """An opener without proxies: ``ProxyHandler({})`` overrides the environment's and the
    system's proxy settings."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _endpoint(url: str, path: str) -> str:
    return url.rstrip("/") + path


def _request_json(req: urllib.request.Request, timeout: float) -> Any:
    """Send ``req`` and decode the JSON reply, mapping every failure to an ``LlmFailure``."""
    try:
        with _opener().open(req, timeout=timeout) as resp:
            raw = resp.read()
    except HTTPError as e:  # before URLError: HTTPError is a subclass
        if e.code == 404:
            raise LlmUnavailable(f"HTTP 404 from {req.full_url}") from e
        hint = " (Ollama 0.5 or newer is needed for structured output)" if e.code == 400 else ""
        raise LlmError(f"HTTP {e.code} from {req.full_url}{hint}") from e
    except URLError as e:
        if isinstance(e.reason, TimeoutError):  # on connect
            raise LlmTimeout(f"no answer from {req.full_url} within {timeout} s") from e
        if isinstance(e.reason, ConnectionResetError):
            raise LlmError(f"connection reset by {req.full_url}") from e
        raise LlmUnavailable(f"cannot reach {req.full_url}: {e.reason}") from e
    except TimeoutError as e:  # on read
        raise LlmTimeout(f"no answer from {req.full_url} within {timeout} s") from e
    except (ConnectionResetError, http.client.HTTPException, OSError) as e:
        # RemoteDisconnected is both a ConnectionResetError and an HTTPException
        raise LlmError(f"connection to {req.full_url} failed: {e!r}") from e
    try:
        return json.loads(raw)
    except ValueError as e:
        raise LlmError(f"the reply from {req.full_url} is not JSON") from e


def generate(
    url: str, model: str, system: str, prompt: str, schema: dict[str, Any], timeout: float
) -> str:
    """``POST {url}/api/chat`` (no streaming, structured output) and return the model's text."""
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "format": schema,
        "options": {"temperature": TEMPERATURE},
        "keep_alive": KEEP_ALIVE,
    }
    req = urllib.request.Request(
        _endpoint(url, "/api/chat"),
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    data = _request_json(req, timeout)
    message = data.get("message") if isinstance(data, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise LlmError("the reply has no message content")
    return content


def _model_names(data: Any) -> set[str]:
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        raise LlmError("not Ollama's model list")
    names = set()
    for m in data["models"]:
        if isinstance(m, dict):
            names |= {m[k] for k in ("name", "model") if isinstance(m.get(k), str)}
    return names


def probe(url: str, model: str, timeout: float = PROBE_TIMEOUT) -> tuple[ProbeStatus, str | None]:
    """``("ready", None)`` when Ollama at ``url`` lists ``model`` (a name without a tag means
    ``name:latest``), else ``("unavailable", <what to do>)``."""
    req = urllib.request.Request(_endpoint(url, "/api/tags"), method="GET")
    try:
        names = _model_names(_request_json(req, timeout))
    except LlmFailure as e:
        # an LlmError, or an HTTP error (a 404 is an LlmUnavailable): something answered, badly
        answered = isinstance(e, LlmError) or isinstance(e.__cause__, HTTPError)
        if answered:
            return (
                "unavailable",
                f"Something answered at {url}, but not like Ollama 0.5 or newer does.",
            )
        return "unavailable", f"Ollama isn't answering at {url}."
    wanted = {model} if ":" in model else {model, f"{model}:latest"}
    if names & wanted:
        return "ready", None
    return (
        "unavailable",
        f"Ollama is running but the model {model} isn't pulled: run `ollama pull {model}`.",
    )
