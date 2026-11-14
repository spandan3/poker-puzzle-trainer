"""Explanation check: how often does a real model's explanation get through the guardrail?

``explain-check --url http://127.0.0.1:8000 --n 12`` talks to a running app over HTTP (stdlib
``urllib``, no proxy, like the Ollama client). For each of ``n`` puzzles it picks a street (the
four streets in turn), answers (the first, the last and the middle option in turn; equity guess
50%; intent ``value`` for a bet or raise), fetches the explanation and tallies its ``source`` and
``fallback``. It prints a table and totals and always exits 0: it measures, it doesn't gate. A request that fails is a row with source
``error`` (the error in ``fallback``). ``seconds`` is the explanation request only.

Start the app with the LLM provider on (see the settings) and ``PPT_LLM_TIMEOUT=120`` or more:
the server's own timeout (60 s) would turn a slow answer into a ``timeout`` fallback.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

STREETS = ("preflop", "flop", "turn", "river")
EXPLANATION_TIMEOUT = 300.0  # seconds, per request
REQUEST_TIMEOUT = 60.0

Fetch = Callable[[str, str, dict | None, float], Any]


@dataclass(frozen=True)
class Row:
    street: str
    verdict: str
    source: str
    fallback: str | None
    seconds: float


def _fetch(method: str, url: str, body: dict | None, timeout: float) -> Any:
    """One JSON request; no proxy (the app is local). Raises on an HTTP error."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method=method
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def run(url: str, n: int, fetch: Fetch = _fetch) -> list[Row]:
    base = url.rstrip("/")
    rows: list[Row] = []
    for i in range(n):
        street = STREETS[i % 4]
        verdict = "-"
        try:
            puzzle = fetch("POST", f"{base}/api/puzzles", {"street": street}, REQUEST_TIMEOUT)
            options = puzzle["options"]
            option = options[(0, len(options) - 1, len(options) // 2)[(i // 4) % 3]]
            intent = "value" if option["kind"] in ("bet", "raise") else None
            attempt = fetch(
                "POST",
                f"{base}/api/puzzles/{puzzle['id']}/attempts",
                {"option": option["index"], "equity_guess": 0.5, "intent": intent},
                REQUEST_TIMEOUT,
            )
            verdict = attempt["grade"]["verdict"]
            started = time.monotonic()  # only the explanation (the model's time) is timed
            explanation = fetch(
                "GET",
                f"{base}/api/attempts/{attempt['attempt']['id']}/explanation",
                None,
                EXPLANATION_TIMEOUT,
            )
            row = Row(
                street,
                verdict,
                explanation["source"],
                explanation.get("fallback"),
                time.monotonic() - started,
            )
        except Exception as e:  # noqa: BLE001  one failed request must not lose the rest of a long run
            row = Row(street, verdict, "error", f"{type(e).__name__}: {e}"[:40], 0.0)
        rows.append(row)
    return rows


def format_rows(rows: list[Row]) -> str:
    lines = [f"{'street':<8} {'verdict':<8} {'source':<9} {'fallback':<12} {'expl. s':>8}"]
    for r in rows:
        lines.append(
            f"{r.street:<8} {r.verdict:<8} {r.source:<9} {r.fallback or '-':<12} {r.seconds:>8.1f}"
        )
    sources = Counter(r.source for r in rows)
    fallbacks = Counter(r.fallback for r in rows if r.fallback and r.source != "error")
    lines.append("")
    lines.append(f"total: {len(rows)}")
    lines.append(f"llm: {sources.get('llm', 0)}")
    lines.append(f"error: {sources.get('error', 0)}")
    for name, count in sorted(fallbacks.items()):
        lines.append(f"{name}: {count}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check explanations against a running app.")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--n", type=int, default=12)
    args = parser.parse_args(argv)
    print(format_rows(run(args.url, args.n)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
