"""Progress stats over stored attempt rows: pure functions, no DB, nothing regraded.

Only first attempts (``is_first``) count toward every number here; retries are only counted.
EV is reported in bb (``ev_loss_chips / 2``); equity and range-read errors stay fractions (0-1).
Nothing is rounded: the UI formats.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo, available_timezones

from poker_trainer.stats import leaks
from poker_trainer.villain.profiles import profile_meta

ROLLING_WINDOW = 50  # trend averages and the headline's "last 50"
TREND_MAX_POINTS = 500  # newest first attempts returned in the trend
RECENT_DAYS = 14  # days in ``days.recent``, ending today
CHIPS_PER_BB = 2

STREETS: tuple[tuple[str, str], ...] = (
    ("preflop", "Pre-flop"),
    ("flop", "Flop"),
    ("turn", "Turn"),
    ("river", "River"),
)
ACTIONS: tuple[tuple[str, str], ...] = (
    ("fold", "Fold"),
    ("check", "Check"),
    ("call", "Call"),
    ("bet", "Bet"),
    ("raise", "Raise"),
)
VERDICTS = ("best", "fine", "mistake", "blunder")
GOOD_VERDICTS = frozenset({"best", "fine"})


@dataclass(frozen=True)
class StatRow:
    """One attempt (first or retry), stored columns only: never the puzzle blob or ``chosen``."""

    id: int
    created_at: datetime  # aware, UTC
    is_first: bool
    street: str
    profile: str
    action_kind: str
    best_kind: str
    verdict: str
    ev_loss_chips: float
    equity_guess: float
    equity_error: float
    true_equity: float | None
    range_read_guess: float | None
    range_read_error: float | None
    ahead_now: float | None
    hero_category: str | None
    intent: str | None
    intent_truth: str | None
    intent_flag: str | None
    bluff_required: float | None
    bluff_actual: float | None

    @property
    def ev_lost_bb(self) -> float:
        return self.ev_loss_chips / CHIPS_PER_BB

    @property
    def good(self) -> bool:
        return self.verdict in GOOD_VERDICTS


# Files that sit in a system tz directory (Linux, macOS) but are not zones: the machine's own
# zone and the placeholder. Windows has neither, so both are refused everywhere.
_NOT_ZONES = frozenset({"localtime", "Factory", "posixrules"})


@lru_cache(maxsize=1)
def _known_zones() -> frozenset[str]:
    return frozenset(available_timezones()) - _NOT_ZONES


def parse_tz(name: str) -> ZoneInfo:
    """The IANA zone ``name``; ``ValueError`` for an unknown or malformed name (a path, a
    directory such as ``Europe``, an empty string). Only names in ``available_timezones()`` (less
    the non-zone files above) are accepted, so the answer is the same on Linux, macOS and Windows
    (``ZoneInfo`` alone would also load ``localtime`` or ``Factory`` from a system tz directory).
    ``UTC`` is always valid."""
    if name != "UTC" and name not in _known_zones():
        raise ValueError(f"unknown time zone {name!r}")
    try:
        return ZoneInfo(name)
    except (ValueError, KeyError, OSError) as e:  # KeyError covers ZoneInfoNotFoundError
        raise ValueError(f"unknown time zone {name!r}") from e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mean(xs: Sequence[float]) -> float | None:
    return math.fsum(xs) / len(xs) if xs else None


def _mean_of(rows: Sequence[StatRow], f: Callable[[StatRow], float | None]) -> float | None:
    """Mean of the non-null ``f(row)``; None when there are none."""
    return _mean([v for v in map(f, rows) if v is not None])


def _accuracy(rows: Sequence[StatRow]) -> float | None:
    return sum(1 for r in rows if r.good) / len(rows) if rows else None


def _headline(first: Sequence[StatRow]) -> dict[str, Any]:
    last = first[-ROLLING_WINDOW:]
    # "the 50 before" is always a full 50: null until there are 100 first attempts
    prev = first[-2 * ROLLING_WINDOW : -ROLLING_WINDOW] if len(first) >= 2 * ROLLING_WINDOW else []
    return {
        "ev_lost_bb_last50": _mean_of(last, lambda r: r.ev_lost_bb),
        "ev_lost_bb_prev50": _mean_of(prev, lambda r: r.ev_lost_bb),
        "accuracy_last50": _accuracy(last),
        "equity_error_last50": _mean_of(last, lambda r: r.equity_error),
        "range_read_error_last50": _mean_of(last, lambda r: r.range_read_error),
    }


def _trend(first: Sequence[StatRow]) -> list[dict[str, Any]]:
    """One point per first attempt (the newest ``TREND_MAX_POINTS``), oldest first. Each average
    is over the window of the last ``ROLLING_WINDOW`` first attempts ending at the point, taken
    over all first attempts (so a capped series' first point still has a full window)."""
    start = max(0, len(first) - TREND_MAX_POINTS)
    points = []
    for i in range(start, len(first)):
        r = first[i]
        window = first[max(0, i - ROLLING_WINDOW + 1) : i + 1]
        ev_avg = _mean_of(window, lambda w: w.ev_lost_bb)
        eq_avg = _mean_of(window, lambda w: w.equity_error)
        assert ev_avg is not None and eq_avg is not None  # the window holds ``r`` itself
        points.append(
            {
                "n": i + 1,
                "attempt_id": r.id,
                "created_at": r.created_at.isoformat(),
                "ev_lost_bb": r.ev_lost_bb,
                "equity_error": r.equity_error,
                "range_read_error": r.range_read_error,
                "ev_lost_bb_avg": ev_avg,
                "equity_error_avg": eq_avg,
                "range_read_error_avg": _mean_of(window, lambda w: w.range_read_error),
            }
        )
    return points


def _breakdown_row(key: str, label: str, rows: Sequence[StatRow]) -> dict[str, Any]:
    verdicts = Counter(r.verdict for r in rows)
    return {
        "key": key,
        "label": label,
        "count": len(rows),
        "accuracy": _accuracy(rows),
        "ev_lost_bb_avg": _mean_of(rows, lambda r: r.ev_lost_bb),
        "equity_error_avg": _mean_of(rows, lambda r: r.equity_error),
        "verdicts": {v: verdicts.get(v, 0) for v in VERDICTS},
    }


def _breakdown(
    first: Sequence[StatRow],
    key: Callable[[StatRow], str],
    known: Sequence[tuple[str, str]],
    other_label: Callable[[str], str] = lambda k: k,
) -> list[dict[str, Any]]:
    """Rows in ``known`` order (key, label), then any other stored key alphabetically (labelled
    by ``other_label``, by default the key). Keys without attempts are omitted."""
    groups: dict[str, list[StatRow]] = {}
    for r in first:
        groups.setdefault(key(r), []).append(r)
    labels = dict(known)
    order = [k for k, _ in known if k in groups] + sorted(k for k in groups if k not in labels)
    return [
        _breakdown_row(k, labels[k] if k in labels else other_label(k), groups[k]) for k in order
    ]


def _streak(first: Sequence[StatRow]) -> dict[str, int]:
    best = run = 0
    for r in first:
        run = run + 1 if r.good else 0
        best = max(best, run)
    return {"current": run, "best": best}


def _days(first: Sequence[StatRow], tz: ZoneInfo, now: datetime, goal: int) -> dict[str, Any]:
    counts = Counter(r.created_at.astimezone(tz).date() for r in first)
    today = now.astimezone(tz).date()
    # a day after today (a clock change, a row from another machine) is never part of a streak
    met = {d for d, c in counts.items() if c >= goal and d <= today}

    # today doesn't break the run until it's over: start from yesterday if it hasn't met the goal
    day = today if today in met else today - timedelta(days=1)
    current = 0
    while day in met:
        current += 1
        day -= timedelta(days=1)

    best = 0
    run = 0
    prev: date | None = None
    for d in sorted(met):
        run = run + 1 if prev is not None and d - prev == timedelta(days=1) else 1
        best = max(best, run)
        prev = d

    recent = [today - timedelta(days=k) for k in range(RECENT_DAYS - 1, -1, -1)]
    return {
        "goal": goal,
        "today": counts.get(today, 0),
        "current_streak": current,
        "best_streak": best,
        "recent": [{"date": d.isoformat(), "count": counts.get(d, 0)} for d in recent],
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def compute(
    rows: Sequence[StatRow],
    *,
    tz: ZoneInfo,
    now: datetime,
    goal: int,
    profile_labels: Mapping[str, str],
) -> dict[str, Any]:
    """The ``StatsView`` dict for ``rows`` (every attempt of one user, any order).

    ``now`` (aware) fixes "today" in ``tz``; ``goal`` is the daily goal, applied to past days too.
    ``profile_labels`` maps current profile names to labels, in display order; a stored profile
    not in it sorts after them by name, labelled by ``profile_meta``.
    """
    ordered = sorted(rows, key=lambda r: r.id)  # insert order
    first = [r for r in ordered if r.is_first]
    return {
        "tz": tz.key,
        "totals": {"first_attempts": len(first), "retries": len(ordered) - len(first)},
        "headline": _headline(first),
        "trend": _trend(first),
        "breakdowns": {
            "street": _breakdown(first, lambda r: r.street, STREETS),
            "action": _breakdown(first, lambda r: r.action_kind, ACTIONS),
            "profile": _breakdown(
                first,
                lambda r: r.profile,
                list(profile_labels.items()),
                lambda k: profile_meta(k)[0],
            ),
        },
        "streak": _streak(first),
        "days": _days(first, tz, now, goal),
        "leaks": leaks.detect(ordered),
    }
