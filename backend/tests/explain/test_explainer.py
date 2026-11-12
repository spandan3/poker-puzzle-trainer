"""``Explainer``: provider selection, fallback reasons, the guardrail, the cache and the probe."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import pytest
from explain_cases import facts, puzzle, result
from test_ollama import FakeOllama

from poker_trainer.explain import ollama, service
from poker_trainer.explain.service import CACHE_SIZE, PROBE_TTL, Explainer
from poker_trainer.explain.template import render
from poker_trainer.settings import AppSettings


def _settings(provider: str = "ollama", **kw: Any) -> AppSettings:
    base = {
        "llm_provider": provider,
        "ollama_url": "http://127.0.0.1:1",
        "ollama_model": "llama3.2:3b",
        "llm_timeout": 5.0,
    }
    return AppSettings(_env_file=None, **{**base, **kw})


@pytest.fixture(scope="module")
def case():
    p = puzzle(1, "river")
    res = result(p, option=0)
    res.pop("explanation")
    f = facts(res, p)
    return render(f), f


def _reword(prompt: str) -> str:
    """A well-behaved model: the template's own text, reworded without new numbers."""
    fields = ollama.template_fields(prompt)
    return json.dumps(
        {
            "headline": "In short: " + fields["headline"],
            "hand": fields["hand"].replace("\n\n", " "),
            "verdict": fields["verdict"],
        }
    )


class FakeGenerate:
    def __init__(self, reply: Any = None) -> None:
        self.reply = reply
        self.calls: list[tuple[Any, ...]] = []

    def __call__(self, url, model, system, prompt, schema, timeout):
        self.calls.append((url, model, system, prompt, schema, timeout))
        if isinstance(self.reply, BaseException):
            raise self.reply
        if callable(self.reply):
            return self.reply(prompt)
        return _reword(prompt) if self.reply is None else self.reply


def _no_network(*_a: Any, **_k: Any) -> Any:
    raise AssertionError("no network with provider none")


# ---------------------------------------------------------------------------
# explanation_for
# ---------------------------------------------------------------------------


def test_provider_none_is_the_template_without_a_call(case):
    template, f = case
    ex = Explainer(_settings("none"), generate=_no_network, probe=_no_network)
    out = ex.explanation_for(1, template, f)
    assert out == {**template, "fallback": "off"}
    assert ex.status() == ("off", None)


def test_llm_success(case):
    template, f = case
    gen = FakeGenerate()
    ex = Explainer(_settings(), generate=gen)
    out = ex.explanation_for(7, template, f)
    assert out["source"] == "llm" and out["model"] == "llama3.2:3b" and out["fallback"] is None
    assert out["headline"] == "In short: " + template["headline"]
    assert [s["id"] for s in out["sections"]] == ["hand", "verdict", "villain"]
    hand, verdict, villain = out["sections"]
    assert hand["paragraphs"] == [" ".join(template["sections"][0]["paragraphs"])]
    assert verdict["paragraphs"] == template["sections"][1]["paragraphs"]  # split on blank lines
    assert villain == template["sections"][2]  # always the template's
    assert [s["title"] for s in out["sections"]] == [s["title"] for s in template["sections"]]
    url, model, system, prompt, schema, timeout = gen.calls[0]
    assert (url, model, system, schema, timeout) == (
        "http://127.0.0.1:1",
        "llama3.2:3b",
        ollama.INSTRUCTIONS,
        ollama.SCHEMA,
        5.0,
    )
    assert all(line in prompt for line in f.as_lines())
    # cached: a second request does not call the model again
    assert ex.explanation_for(7, template, f) == out
    assert len(gen.calls) == 1


def test_paragraphs_split_on_blank_lines(case):
    template, f = case
    headline = template["headline"]
    reply = json.dumps({"headline": headline, "hand": "A.\n\n\nB.\n  \nC.", "verdict": "D.\n\n"})
    out = Explainer(_settings(), generate=FakeGenerate(reply)).explanation_for(1, template, f)
    assert out["sections"][0]["paragraphs"] == ["A.", "B.", "C."]
    assert out["sections"][1]["paragraphs"] == ["D."]


def test_guardrail_rejection_falls_back_and_is_cached(case, caplog):
    template, f = case
    reply = json.dumps({"headline": "Fine.", "hand": "You had 99.9% equity.", "verdict": "Good."})
    gen = FakeGenerate(reply)
    ex = Explainer(_settings(), generate=gen)
    with caplog.at_level(logging.INFO, logger="poker_trainer.explain.service"):
        out = ex.explanation_for(3, template, f)
    assert out == {**template, "fallback": "guardrail"}
    assert "99.9%" in caplog.text and "You had" not in caplog.text  # the numbers, not the text
    assert ex.explanation_for(3, template, f) == out
    assert len(gen.calls) == 1


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        (lambda fl: {**fl, "verdict": fl["verdict"] + " A Blunder, really."}, "verdict"),
        (lambda fl: {**fl, "headline": "Checking was a Mistake."}, "headline"),
        (lambda fl: {**fl, "hand": fl["hand"] + " Villain had a flush."}, "result"),
        (lambda fl: {**fl, "verdict": fl["verdict"] + " You would win more often."}, "result"),
    ],
)
def test_claim_rejection_falls_back_and_is_cached(case, caplog, change, rule):
    template, f = case  # verdict Mistake, top play Bet 33%, chosen Check

    def reply(prompt: str) -> str:
        return json.dumps(change(json.loads(_reword(prompt))))

    gen = FakeGenerate(reply)
    ex = Explainer(_settings(), generate=gen)
    with caplog.at_level(logging.INFO, logger="poker_trainer.explain.service"):
        out = ex.explanation_for(4, template, f)
    assert out == {**template, "fallback": "guardrail"}
    assert "rejected claims" in caplog.text and f"'{rule}'" in caplog.text
    assert ex.explanation_for(4, template, f) == out
    assert len(gen.calls) == 1


@pytest.mark.parametrize("field", ["headline", "hand", "verdict"])
def test_one_bad_field_discards_everything(case, field):
    template, f = case

    def reply(prompt: str) -> str:
        fields = json.loads(_reword(prompt))
        fields[field] += " That happens twice."
        return json.dumps(fields)

    out = Explainer(_settings(), generate=FakeGenerate(reply)).explanation_for(1, template, f)
    assert out["fallback"] == "guardrail" and out["source"] == "template"


def test_number_word_and_normalisation(case):
    template, f = case
    eq = f.equity  # e.g. "42.5%"

    def padded(prompt: str) -> str:
        fields = json.loads(_reword(prompt))
        value = eq[:-1]
        fields["verdict"] += f" Your equity was {value}0%." if "." in value else ""
        return json.dumps(fields)

    out = Explainer(_settings(), generate=FakeGenerate(padded)).explanation_for(1, template, f)
    assert out["source"] == "llm"  # "42.50%" is "42.5%"

    def worded(prompt: str) -> str:
        fields = json.loads(_reword(prompt))
        fields["verdict"] += " Villain folds about half the time."
        return json.dumps(fields)

    out = Explainer(_settings(), generate=FakeGenerate(worded)).explanation_for(1, template, f)
    assert out["fallback"] == "guardrail"


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (ollama.LlmUnavailable("down"), "unavailable"),
        (ollama.LlmTimeout("slow"), "timeout"),
        (ollama.LlmError("HTTP 500"), "error"),
        (RuntimeError("a bug"), "error"),  # never a 5xx because of the model
    ],
)
def test_failures_fall_back_and_are_not_cached(case, exc, reason):
    template, f = case
    gen = FakeGenerate(exc)
    ex = Explainer(_settings(), generate=gen)
    assert ex.explanation_for(1, template, f) == {**template, "fallback": reason}
    ex.explanation_for(1, template, f)
    assert len(gen.calls) == 2  # retried


@pytest.mark.parametrize("reply", ["not json", "{}", json.dumps({"headline": "", "hand": "x"})])
def test_invalid_output_falls_back(case, reply):
    template, f = case
    gen = FakeGenerate(reply)
    ex = Explainer(_settings(), generate=gen)
    assert ex.explanation_for(1, template, f) == {**template, "fallback": "invalid"}
    ex.explanation_for(1, template, f)
    assert len(gen.calls) == 2


def test_cache_is_bounded_lru(case):
    template, f = case
    gen = FakeGenerate()
    ex = Explainer(_settings(), generate=gen)
    for i in range(CACHE_SIZE + 1):
        ex.explanation_for(i, template, f)
    assert len(gen.calls) == CACHE_SIZE + 1
    ex.explanation_for(CACHE_SIZE, template, f)  # newest: cached
    assert len(gen.calls) == CACHE_SIZE + 1
    ex.explanation_for(0, template, f)  # oldest: evicted
    assert len(gen.calls) == CACHE_SIZE + 2


def test_cache_key_includes_the_model(case):
    template, f = case
    gen = FakeGenerate()
    Explainer(_settings(), generate=gen).explanation_for(1, template, f)
    ex = Explainer(_settings(ollama_model="mistral"), generate=gen)
    assert ex.explanation_for(1, template, f)["model"] == "mistral"


class _CountingEvent(threading.Event):
    """An event that counts the threads that called ``wait`` on it."""

    def __init__(self) -> None:
        super().__init__()
        self._count_lock = threading.Lock()
        self.waiters = 0

    def wait(self, timeout: float | None = None) -> bool:
        with self._count_lock:
            self.waiters += 1
        return super().wait(timeout)


def test_concurrent_duplicates_wait_for_the_running_call(case, monkeypatch):
    template, f = case
    started, release = threading.Event(), threading.Event()
    events: list[_CountingEvent] = []

    def counting_event() -> _CountingEvent:
        events.append(_CountingEvent())
        return events[-1]

    @dataclass
    class CountingInFlight(service._InFlight):
        done: threading.Event = field(default_factory=counting_event)

    monkeypatch.setattr(service, "_InFlight", CountingInFlight)

    def slow(prompt: str) -> str:
        started.set()
        release.wait(5)
        return _reword(prompt)

    def failing_slow(prompt: str) -> str:
        slow(prompt)
        raise ollama.LlmTimeout("slow")

    for reply, source in ((slow, "llm"), (failing_slow, "template")):
        started.clear()
        release.clear()
        events.clear()
        gen = FakeGenerate(reply)
        ex = Explainer(_settings(), generate=gen)
        outs: list[dict[str, Any]] = []

        def ask(ex: Explainer = ex, outs: list[dict[str, Any]] = outs) -> None:
            outs.append(ex.explanation_for(5, template, f))

        threads = [threading.Thread(target=ask) for _ in range(3)]
        threads[0].start()
        assert started.wait(5)
        for t in threads[1:]:
            t.start()
        # both duplicates found the running call and wait on it before it finishes
        deadline = time.monotonic() + 5
        while events[-1].waiters < 2:
            assert time.monotonic() < deadline, "the duplicates never waited on the running call"
            time.sleep(0.001)
        assert len(events) == 1  # one in-flight entry: the duplicates joined it
        release.set()
        for t in threads:
            t.join(5)
        assert not any(t.is_alive() for t in threads)
        assert len(gen.calls) == 1  # one generation, three answers
        assert len(outs) == 3 and all(o == outs[0] for o in outs)
        assert outs[0]["source"] == source


def test_end_to_end_with_a_fake_server(case):
    """The real client: each failure of the server gives the template with its reason."""
    template, f = case
    fake = FakeOllama()
    fake.thread.start()
    try:
        # a timeout a slow CI runner meets on the success call, and a slow route well past it
        ex = Explainer(_settings(ollama_url=fake.url, llm_timeout=2.0))
        fake.routes[("POST", "/api/chat")] = lambda b: (
            200,
            json.dumps({"message": {"content": _reword(b["messages"][1]["content"])}}).encode(),
            0.0,
        )
        assert ex.explanation_for(1, template, f)["source"] == "llm"
        for i, (setup, reason) in enumerate(
            [
                (lambda: fake.chat("x", status=404), "unavailable"),
                (lambda: fake.chat("x", status=500), "error"),
                (lambda: fake.chat("not json"), "invalid"),
                (lambda: fake.chat(""), "invalid"),
                (lambda: fake.chat("{}", delay=5.0), "timeout"),
            ],
            start=2,
        ):
            setup()
            assert ex.explanation_for(i, template, f)["fallback"] == reason, reason
    finally:
        fake.server.shutdown()
        fake.server.server_close()


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


class FakeProbe:
    def __init__(self, answer: tuple[str, str | None] = ("ready", None)) -> None:
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    def __call__(self, url: str, model: str, timeout: float = 1.5) -> tuple[str, str | None]:
        self.calls.append((url, model))
        return self.answer


def test_status_probes_and_caches_for_thirty_seconds():
    now = [100.0]
    probe = FakeProbe()
    ex = Explainer(_settings(), probe=probe, clock=lambda: now[0])
    assert ex.status(probe=False) == ("unavailable", "Not checked yet.")
    assert probe.calls == []
    assert ex.status() == ("ready", None)
    assert probe.calls == [("http://127.0.0.1:1", "llama3.2:3b")]
    probe.answer = ("unavailable", "Ollama isn't answering at http://127.0.0.1:1.")
    now[0] += PROBE_TTL - 0.1
    assert ex.status() == ("ready", None)  # cached
    assert ex.status(probe=False) == ("ready", None)
    now[0] += 0.2
    assert ex.status() == probe.answer  # re-probed
    assert len(probe.calls) == 2
    assert PROBE_TTL == 30


def test_status_survives_a_broken_probe():
    def broken(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("bug")

    status, detail = Explainer(_settings(), probe=broken).status()
    assert status == "unavailable" and detail


def test_status_with_the_real_probe():
    fake = FakeOllama()
    fake.tags("llama3.2:3b")
    fake.thread.start()
    try:
        assert Explainer(_settings(ollama_url=fake.url)).status() == ("ready", None)
    finally:
        fake.server.shutdown()
        fake.server.server_close()
