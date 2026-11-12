"""Rule-based leaks over the newest first attempts (main spec §10, M7 plan Task 3).

Each rule looks at some of the last ``window`` first attempts and fires when it has at least
``min_n`` of them and either the share it flags or the mean signed error crosses a threshold.
Share rules report the bb lost on the flagged rows; mean rules report the signed mean error.
Every number in a title or detail is formatted here, from the stored columns.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from poker_trainer.stats.service import StatRow

AGGRESSIVE = frozenset({"bet", "raise"})
PASSIVE = frozenset({"check", "call"})
BAD_VERDICTS = frozenset({"mistake", "blunder"})
DRAW_CATEGORIES = frozenset({"strong_draw", "weak_draw"})


@dataclass(frozen=True)
class LeakThresholds:
    """The window, minimum samples and thresholds of every rule."""

    window: int = 200  # newest first attempts the rules look at

    river_overcall_min_n: int = 5
    river_overcall_share: float = 0.4
    overfold_min_n: int = 8
    overfold_share: float = 0.35
    overbluff_min_n: int = 5
    overbluff_share: float = 0.4
    missed_value_min_n: int = 5
    missed_value_share: float = 0.4
    missed_value_equity: float = 0.6  # true equity at or above this counts as a strong hand
    intent_mislabel_min_n: int = 5
    intent_mislabel_share: float = 0.4

    draw_overestimate_min_n: int = 5
    draw_overestimate_mean: float = 0.08
    equity_min_n: int = 10
    equity_mean: float = 0.07  # over- at >= +this, under- at <= -this
    range_read_min_n: int = 10
    range_read_mean: float = 0.08  # high at >= +this, low at <= -this


DEFAULT = LeakThresholds()
LEAK_WINDOW = DEFAULT.window


def _pct(x: float) -> int:
    """A share as a whole percent, half up (not banker's rounding)."""
    return math.floor(100 * x + 0.5)


def _one_decimal(x: float) -> str:
    """``x`` (non-negative) with one decimal, half up."""
    return f"{math.floor(10 * x + 0.5) / 10:.1f}"


def _share_leak(
    id_: str,
    title: str,
    detail: str,
    rows: Sequence[StatRow],
    looked_at: Callable[[StatRow], bool],
    flagged: Callable[[StatRow], bool],
    min_n: int,
    share: float,
) -> dict[str, Any] | None:
    """``detail`` may use ``{n}``, ``{count}``, ``{pct}`` and ``{ev}`` (bb, one decimal)."""
    seen = [r for r in rows if looked_at(r)]
    bad = [r for r in seen if flagged(r)]
    n, count = len(seen), len(bad)
    if n < min_n or count / n < share:
        return None
    ev = math.fsum(r.ev_lost_bb for r in bad)
    return {
        "id": id_,
        "kind": "share",
        "title": title,
        "detail": detail.format(n=n, count=count, pct=_pct(count / n), ev=_one_decimal(ev)),
        "count": count,
        "sample": n,
        "ev_lost_bb": ev,
        "mean_error": None,
    }


def _mean_leak(
    id_: str,
    title: str,
    detail: str,
    errors: Sequence[float],
    min_n: int,
    fires: Callable[[float], bool],
) -> dict[str, Any] | None:
    """``errors`` are signed (guess - truth); ``detail`` may use ``{mean}`` (absolute, pts)
    and ``{n}``."""
    n = len(errors)
    if n < min_n:
        return None
    mean = math.fsum(errors) / n
    if not fires(mean):
        return None
    return {
        "id": id_,
        "kind": "mean",
        "title": title,
        "detail": detail.format(n=n, mean=_one_decimal(abs(mean) * 100)),
        "count": n,
        "sample": n,
        "ev_lost_bb": None,
        "mean_error": mean,
    }


def _equity_errors(rows: Sequence[StatRow], only: Callable[[StatRow], bool]) -> list[float]:
    return [r.equity_guess - r.true_equity for r in rows if r.true_equity is not None and only(r)]


def detect(rows: Sequence[StatRow], t: LeakThresholds = DEFAULT) -> list[dict[str, Any]]:
    """``Leak``-shaped dicts for ``rows`` (every attempt, in id order).

    Only first attempts count, and only the newest ``t.window`` of them. Share leaks come
    first, by bb lost then count (both descending); mean leaks follow, by the size of the mean
    error.
    """
    first = [r for r in rows if r.is_first]
    recent = first[-t.window :] if t.window > 0 else []

    share = [
        _share_leak(
            "river_overcall",
            "Calling too often on the river",
            "You called {n} river bets; folding was better {count} times ({pct}%), "
            "costing {ev} bb.",
            recent,
            lambda r: r.street == "river" and r.action_kind == "call",
            lambda r: r.best_kind == "fold",
            t.river_overcall_min_n,
            t.river_overcall_share,
        ),
        _share_leak(
            "overfold",
            "Folding too often",
            "You folded {n} times; continuing was better {count} times ({pct}%), costing {ev} bb.",
            recent,
            lambda r: r.action_kind == "fold",
            lambda r: r.best_kind != "fold",
            t.overfold_min_n,
            t.overfold_share,
        ),
        _share_leak(
            "overbluff",
            "Over-bluffing",
            "{count} of your {n} bluffs ({pct}%) were mistakes or blunders, costing {ev} bb. "
            "Check how often Villain folds before bluffing.",
            recent,
            lambda r: r.action_kind in AGGRESSIVE and r.intent_truth == "bluff",
            lambda r: r.verdict in BAD_VERDICTS,
            t.overbluff_min_n,
            t.overbluff_share,
        ),
        _share_leak(
            "missed_value",
            "Missing value bets",
            "With a strong hand where betting was best, you checked or called {count} of {n} "
            "times ({pct}%), costing {ev} bb.",
            recent,
            lambda r: (
                r.best_kind in AGGRESSIVE
                and r.true_equity is not None
                and r.true_equity >= t.missed_value_equity
            ),
            lambda r: r.action_kind in PASSIVE,
            t.missed_value_min_n,
            t.missed_value_share,
        ),
        _share_leak(
            "intent_mislabel",
            "Mislabelling bets",
            "You labelled {count} of {n} bets or raises ({pct}%) differently from what they "
            "were (value vs bluff).",
            recent,
            lambda r: r.action_kind in AGGRESSIVE and r.intent is not None,
            lambda r: r.intent_flag is not None,
            t.intent_mislabel_min_n,
            t.intent_mislabel_share,
        ),
    ]

    equity = _equity_errors(recent, lambda _r: True)
    draws = _equity_errors(recent, lambda r: r.hero_category in DRAW_CATEGORIES)
    reads = [
        r.range_read_guess - r.ahead_now
        for r in recent
        if r.range_read_guess is not None and r.ahead_now is not None
    ]
    mean = [
        _mean_leak(
            "draw_overestimate",
            "Overestimating equity with draws",
            "With a draw you guessed {mean} pts too high on average ({n} spots).",
            draws,
            t.draw_overestimate_min_n,
            lambda m: m >= t.draw_overestimate_mean,
        ),
        _mean_leak(
            "equity_overestimate",
            "Overestimating your equity",
            "Your equity guesses are {mean} pts too high on average ({n} spots).",
            equity,
            t.equity_min_n,
            lambda m: m >= t.equity_mean,
        ),
        _mean_leak(
            "equity_underestimate",
            "Underestimating your equity",
            "Your equity guesses are {mean} pts too low on average ({n} spots).",
            equity,
            t.equity_min_n,
            lambda m: m <= -t.equity_mean,
        ),
        _mean_leak(
            "range_read_high",
            "Thinking you're ahead more often than you are",
            "Your range reads are {mean} pts too high on average ({n} spots): "
            "Villain's range is stronger than you think.",
            reads,
            t.range_read_min_n,
            lambda m: m >= t.range_read_mean,
        ),
        _mean_leak(
            "range_read_low",
            "Giving Villain too much credit",
            "Your range reads are {mean} pts too low on average ({n} spots): "
            "you're ahead more often than you think.",
            reads,
            t.range_read_min_n,
            lambda m: m <= -t.range_read_mean,
        ),
    ]

    shares = sorted(
        (x for x in share if x is not None), key=lambda x: (-x["ev_lost_bb"], -x["count"])
    )
    means = sorted((x for x in mean if x is not None), key=lambda x: -abs(x["mean_error"]))
    return shares + means
