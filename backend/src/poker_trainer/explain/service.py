"""``Explainer``: which explanation a result gets, and the LLM provider's status.

- Provider ``none``: the template, with ``fallback="off"``; nothing calls a network.
- Provider ``ollama``: the model rewords the template's headline, hand and verdict. Its output
  is used only when every field passes the guardrail against the facts' values; otherwise, or
  when the model is unavailable, slow, broken or gives invalid output, the template is shown
  with the reason in ``fallback``. The Villain section is always the template's.

Successes and guardrail rejections are cached per ``(attempt_id, model)`` (LRU, ``CACHE_SIZE``
entries); failures are not, so the next request retries. A request for a key whose generation is
running waits for it instead of queueing a second generation in Ollama. Route handlers run in a
thread pool, so the cache and the in-flight table are guarded by a lock.

A waiter waits ``llm_timeout + WAIT_MARGIN`` seconds, but the owner's call may take up to about
twice ``llm_timeout`` (the timeout applies to the connect and again to the read). A waiter that
gives up first gets the template with ``fallback="timeout"``, even if the owner then succeeds
(its result is cached for the next request).
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from poker_trainer.explain import guardrail, ollama
from poker_trainer.explain.facts import Facts
from poker_trainer.settings import AppSettings

log = logging.getLogger(__name__)

CACHE_SIZE = 256
PROBE_TTL = 30.0  # seconds a probe result is reused
NOT_CHECKED = "Not checked yet."
WAIT_MARGIN = 5.0  # seconds a duplicate request waits beyond the model's timeout

LlmStatus = Literal["off", "ready", "unavailable"]
Generate = Callable[[str, str, str, str, dict[str, Any], float], str]
Probe = Callable[..., tuple[str, str | None]]

_BLANK_LINES = re.compile(r"\n\s*\n")
_SPACES = re.compile(r"\s+")


def _generate(*args: Any) -> str:
    # looked up at call time, so a patched ``ollama.generate`` applies
    return ollama.generate(*args)


def _probe(url: str, model: str) -> tuple[str, str | None]:
    return ollama.probe(url, model)


def paragraphs(text: str) -> list[str]:
    """Paragraphs split on blank lines, stripped, empty ones dropped."""
    return [p.strip() for p in _BLANK_LINES.split(text) if p.strip()]


def _fallback(template: dict[str, Any], reason: str) -> dict[str, Any]:
    return {**template, "source": "template", "model": None, "fallback": reason}


@dataclass
class _InFlight:
    done: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] | None = None


class Explainer:
    """Lives on ``app.state.explainer``; ``generate``, ``probe`` and ``clock`` are injectable for
    tests."""

    def __init__(
        self,
        settings: AppSettings,
        *,
        generate: Generate | None = None,
        probe: Probe | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self._generate = generate if generate is not None else _generate
        self._probe = probe if probe is not None else _probe
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: OrderedDict[tuple[int, str], dict[str, Any]] = OrderedDict()
        self._in_flight: dict[tuple[int, str], _InFlight] = {}
        self._probed: tuple[float, LlmStatus, str | None] | None = None

    @property
    def enabled(self) -> bool:
        return self.settings.llm_provider != "none"

    @property
    def model(self) -> str | None:
        """The model name, or ``None`` with provider ``none``."""
        return self.settings.ollama_model if self.enabled else None

    # -- explanations ----------------------------------------------------------------------

    def explanation_for(
        self, attempt_id: int, template: dict[str, Any], facts: Facts
    ) -> dict[str, Any]:
        """The explanation to show for an attempt (JSON-safe ``Explanation``); never raises
        because of the model."""
        if not self.enabled:
            return _fallback(template, "off")
        key = (attempt_id, self.settings.ollama_model)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached
            running = self._in_flight.get(key)
            if running is None:
                running = self._in_flight[key] = _InFlight()
                owner = True
            else:
                owner = False
        if not owner:
            if running.done.wait(self.settings.llm_timeout + WAIT_MARGIN) and running.result:
                return running.result
            return _fallback(template, "timeout")
        out: dict[str, Any] | None = None
        cache = False
        try:
            out, cache = self._run(attempt_id, template, facts)
        finally:
            with self._lock:
                if cache and out is not None:
                    self._cache[key] = out
                    while len(self._cache) > CACHE_SIZE:
                        self._cache.popitem(last=False)
                running.result = out if out is not None else _fallback(template, "error")
                del self._in_flight[key]
            running.done.set()
        return running.result

    def _run(
        self, attempt_id: int, template: dict[str, Any], facts: Facts
    ) -> tuple[dict[str, Any], bool]:
        """``(explanation, cache it?)``."""
        s = self.settings
        try:
            content = self._generate(
                s.ollama_url,
                s.ollama_model,
                ollama.INSTRUCTIONS,
                ollama.user_message(template, facts),
                ollama.SCHEMA,
                s.llm_timeout,
            )
            fields = ollama.parse_reply(content)
        except ollama.LlmFailure as e:
            log.info("explanation %d: %s (%s)", attempt_id, e.reason, e)
            return _fallback(template, e.reason), False
        except Exception:  # never a 5xx because of the model
            log.exception("explanation %d: unexpected error", attempt_id)
            return _fallback(template, "error"), False
        bad = guardrail.check_fields(fields, facts.values_text())
        if bad:
            numbers = {name: sorted(tokens) for name, tokens in bad.items()}
            log.info("explanation %d: guardrail rejected numbers %s", attempt_id, numbers)
            return _fallback(template, "guardrail"), True
        sections = {sec["id"]: sec for sec in template["sections"]}
        return {
            "source": "llm",
            "headline": _SPACES.sub(" ", fields["headline"]),
            "sections": [
                {**sections["hand"], "paragraphs": paragraphs(fields["hand"])},
                {**sections["verdict"], "paragraphs": paragraphs(fields["verdict"])},
                sections["villain"],
            ],
            "model": s.ollama_model,
            "fallback": None,
        }, True

    # -- status ----------------------------------------------------------------------------

    def status(self, *, probe: bool = True) -> tuple[LlmStatus, str | None]:
        """``(llm_status, detail)`` for the settings view. Provider ``none``: ``("off", None)``.
        Else the probe's answer, reused for ``PROBE_TTL`` seconds; with ``probe=False`` only the
        last answer (``unavailable``, "Not checked yet." before the first probe)."""
        if not self.enabled:
            return "off", None
        now = self._clock()
        with self._lock:
            last = self._probed
        if last is not None and (not probe or now - last[0] < PROBE_TTL):
            return last[1], last[2]
        if not probe:
            return "unavailable", NOT_CHECKED
        try:
            status, detail = self._probe(self.settings.ollama_url, self.settings.ollama_model)
        except Exception:
            log.exception("LLM status probe failed")
            status, detail = "unavailable", f"Couldn't check Ollama at {self.settings.ollama_url}."
        result: LlmStatus = "ready" if status == "ready" else "unavailable"
        with self._lock:
            self._probed = (now, result, detail)
        return result, detail
