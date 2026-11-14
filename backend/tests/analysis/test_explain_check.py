"""The explanation check script, with a fake ``fetch`` (no app, no Ollama)."""

from __future__ import annotations

from typing import Any

from poker_trainer.analysis import explain_check

OPTIONS = [
    {"index": 0, "label": "Fold", "kind": "fold", "to": 0},
    {"index": 1, "label": "Call", "kind": "call", "to": 4},
    {"index": 2, "label": "Raise 2.5x", "kind": "raise", "to": 10},
    {"index": 3, "label": "Bet 75%", "kind": "bet", "to": 6},
]

# the sources and fallbacks the fake app answers with, in request order
ANSWERS = [("llm", None), ("template", "guardrail"), ("template", "timeout"), ("llm", None)]


def make_fetch() -> tuple[Any, list[tuple[str, str, Any, float]]]:
    calls: list[tuple[str, str, Any, float]] = []
    state = {"puzzles": 0}

    def fetch(method: str, url: str, body: dict | None, timeout: float) -> Any:
        calls.append((method, url, body, timeout))
        if method == "POST" and url.endswith("/api/puzzles"):
            state["puzzles"] += 1
            return {"id": state["puzzles"], "street": body["street"], "options": OPTIONS}
        if method == "POST" and url.endswith("/attempts"):
            pid = int(url.split("/")[-2])
            return {"attempt": {"id": pid + 100}, "grade": {"verdict": "mistake"}}
        if method == "GET" and url.endswith("/explanation"):
            aid = int(url.split("/")[-2])
            source, fallback = ANSWERS[(aid - 101) % 4]
            return {"source": source, "fallback": fallback}
        raise AssertionError(url)

    return fetch, calls


def test_explain_check_run():
    fetch, calls = make_fetch()
    rows = explain_check.run("http://app/", 4, fetch)
    assert [r.street for r in rows] == ["preflop", "flop", "turn", "river"]
    assert [r.source for r in rows] == ["llm", "template", "template", "llm"]
    assert [r.fallback for r in rows] == [None, "guardrail", "timeout", None]
    assert all(r.verdict == "mistake" for r in rows)
    posts = [c for c in calls if c[1].endswith("/attempts")]
    # first four puzzles all answer option 0 (the first); bets and raises carry an intent
    assert [c[2]["option"] for c in posts] == [0, 0, 0, 0]
    assert all(c[2]["equity_guess"] == 0.5 for c in posts)
    assert all(c[2]["intent"] is None for c in posts)  # a fold has no intent
    assert calls[0][1] == "http://app/api/puzzles"  # trailing slash tolerated
    expl = [c for c in calls if c[1].endswith("/explanation")]
    assert all(c[3] == explain_check.EXPLANATION_TIMEOUT for c in expl)

    text = explain_check.format_rows(rows)
    assert "llm: 2" in text and "guardrail: 1" in text and "timeout: 1" in text


def test_option_cycle_and_intent():
    fetch, calls = make_fetch()
    explain_check.run("http://app", 12, fetch)
    posts = [c[2] for c in calls if c[1].endswith("/attempts")]
    # first, last, middle by blocks of four
    assert [p["option"] for p in posts] == [0] * 4 + [3] * 4 + [2] * 4
    assert posts[4]["intent"] == "value"  # option 3 is a bet
    assert posts[8]["intent"] == "value"  # option 2 is a raise
