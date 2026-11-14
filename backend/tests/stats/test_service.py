"""``stats.service.compute``: pure aggregation over attempt rows (no DB)."""

from __future__ import annotations

import math
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from poker_trainer.api.schemas import StatsView
from poker_trainer.stats.service import (
    TREND_MAX_POINTS,
    StatRow,
    compute,
    parse_tz,
)

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
LABELS = {"tag": "TAG", "lag": "LAG", "tight": "Tight", "sticky": "Sticky"}


def row(i: int, **kw) -> StatRow:
    base = {
        "id": i,
        "created_at": T0 + timedelta(minutes=i),
        "is_first": True,
        "street": "flop",
        "profile": "tag",
        "action_kind": "call",
        "best_kind": "call",
        "verdict": "best",
        "ev_loss_chips": 0.0,
        "equity_guess": 0.5,
        "equity_error": 0.0,
        "true_equity": 0.5,
        "range_read_guess": None,
        "range_read_error": None,
        "ahead_now": None,
        "hero_category": None,
        "intent": None,
        "intent_truth": None,
        "intent_flag": None,
        "bluff_required": None,
        "bluff_actual": None,
    }
    base.update(kw)
    return StatRow(**base)


def run(rows, *, tz="UTC", now=NOW, goal=10, labels=LABELS):
    out = compute(rows, tz=ZoneInfo(tz), now=now, goal=goal, profile_labels=labels)
    StatsView.model_validate(out)  # always the API shape
    return out


def mean(xs):
    return math.fsum(xs) / len(xs)


# ---------------------------------------------------------------------------
# Empty, retries
# ---------------------------------------------------------------------------


def test_empty():
    out = run([])
    assert out["tz"] == "UTC"
    assert out["totals"] == {"first_attempts": 0, "retries": 0}
    assert all(v is None for v in out["headline"].values())
    assert out["trend"] == []
    assert out["breakdowns"] == {"street": [], "action": [], "profile": []}
    assert out["streak"] == {"current": 0, "best": 0}
    days = out["days"]
    assert days["goal"] == 10 and days["today"] == 0
    assert days["current_streak"] == 0 and days["best_streak"] == 0
    assert len(days["recent"]) == 14
    assert all(d["count"] == 0 for d in days["recent"])
    assert days["recent"][-1]["date"] == "2026-11-12"
    assert days["recent"][0]["date"] == "2026-10-30"
    assert out["leaks"] == []


def test_retries_change_only_the_retry_count():
    rows = [
        row(i, verdict="best" if i % 3 else "fine", ev_loss_chips=float(i)) for i in range(1, 8)
    ]
    before = run(rows)
    retry = row(
        8,
        is_first=False,
        verdict="blunder",
        ev_loss_chips=500.0,
        equity_error=0.9,
        range_read_error=0.9,
        street="river",
        action_kind="fold",
        profile="lag",
        created_at=NOW,
    )
    after = run([*rows, retry])
    assert after["totals"] == {"first_attempts": 7, "retries": 1}
    assert before["totals"]["retries"] == 0
    for key in ("headline", "trend", "breakdowns", "streak", "days", "leaks"):
        assert after[key] == before[key], key


# ---------------------------------------------------------------------------
# Trend and headline
# ---------------------------------------------------------------------------


def test_rolling_means_and_prev50_null_below_100():
    rows = [row(i, ev_loss_chips=2.0 * i, equity_error=i / 1000) for i in range(1, 61)]
    out = run(rows)
    trend = out["trend"]
    assert [p["n"] for p in trend] == list(range(1, 61))
    p1 = trend[0]
    assert p1["ev_lost_bb"] == 1.0 and p1["ev_lost_bb_avg"] == 1.0
    p51 = trend[50]
    assert p51["n"] == 51 and p51["attempt_id"] == 51
    assert p51["ev_lost_bb"] == 51.0
    assert p51["ev_lost_bb_avg"] == pytest.approx(mean(range(2, 52)))  # attempts 2..51
    assert p51["equity_error_avg"] == pytest.approx(mean([i / 1000 for i in range(2, 52)]))
    assert p51["created_at"] == rows[50].created_at.isoformat()
    head = out["headline"]
    assert head["ev_lost_bb_last50"] == pytest.approx(mean(range(11, 61)))
    assert head["ev_lost_bb_prev50"] is None
    assert head["accuracy_last50"] == 1.0
    assert head["range_read_error_last50"] is None


def test_prev50_with_120_attempts():
    rows = [row(i, ev_loss_chips=2.0 * i) for i in range(1, 121)]
    head = run(rows)["headline"]
    assert head["ev_lost_bb_last50"] == pytest.approx(mean(range(71, 121)))
    assert head["ev_lost_bb_prev50"] == pytest.approx(mean(range(21, 71)))  # attempts 21..70


def test_prev50_needs_exactly_100():
    assert run([row(i) for i in range(1, 100)])["headline"]["ev_lost_bb_prev50"] is None
    assert run([row(i) for i in range(1, 101)])["headline"]["ev_lost_bb_prev50"] == 0.0


def test_range_read_mean_ignores_nulls():
    rows = [row(i) for i in range(1, 11)]  # all null range reads
    rows += [row(i, range_read_error=0.1 * (i - 10)) for i in range(11, 14)]  # 0.1, 0.2, 0.3
    rows += [row(14)]  # null again
    trend = run(rows)["trend"]
    assert trend[0]["range_read_error"] is None and trend[0]["range_read_error_avg"] is None
    assert trend[9]["range_read_error_avg"] is None
    assert trend[10]["range_read_error_avg"] == pytest.approx(0.1)
    assert trend[12]["range_read_error_avg"] == pytest.approx(0.2)
    assert trend[13]["range_read_error"] is None
    assert trend[13]["range_read_error_avg"] == pytest.approx(0.2)
    assert run(rows)["headline"]["range_read_error_last50"] == pytest.approx(0.2)


def test_range_read_window_of_nulls_is_null_again():
    rows = [row(1, range_read_error=0.3)] + [row(i) for i in range(2, 52)]
    trend = run(rows)["trend"]
    assert trend[49]["range_read_error_avg"] == pytest.approx(0.3)  # window 1..50
    assert trend[50]["range_read_error_avg"] is None  # window 2..51: all null


def test_trend_cap_keeps_full_windows():
    rows = [row(i, ev_loss_chips=2.0 * i) for i in range(1, 601)]
    trend = run(rows)["trend"]
    assert len(trend) == TREND_MAX_POINTS == 500
    assert trend[0]["n"] == 101 and trend[0]["attempt_id"] == 101
    assert trend[0]["ev_lost_bb_avg"] == pytest.approx(mean(range(52, 102)))  # 52..101
    assert trend[-1]["n"] == 600


def test_trend_numbers_over_first_attempts_only():
    rows = [row(1, ev_loss_chips=4.0), row(2, is_first=False, ev_loss_chips=100.0)]
    rows.append(row(3, ev_loss_chips=8.0))
    trend = run(rows)["trend"]
    assert [p["n"] for p in trend] == [1, 2]
    assert [p["attempt_id"] for p in trend] == [1, 3]
    assert trend[1]["ev_lost_bb_avg"] == 3.0


def test_accuracy_counts_best_and_fine():
    verdicts = ["best", "fine", "mistake", "blunder"]
    rows = [row(i, verdict=verdicts[i % 4]) for i in range(1, 9)]
    assert run(rows)["headline"]["accuracy_last50"] == 0.5


def test_rows_out_of_id_order_are_sorted():
    rows = [row(i, ev_loss_chips=2.0 * i) for i in range(1, 6)]
    assert run(rows[::-1]) == run(rows)


# ---------------------------------------------------------------------------
# Streaks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("verdicts", "current", "best"),
    [
        (["best", "mistake", "fine", "best", "fine"], 3, 3),
        (["best", "best", "blunder", "fine", "best"], 2, 2),  # tie of runs
        (["best", "best", "best", "mistake", "fine"], 1, 3),
        (["best", "fine", "mistake"], 0, 2),
        (["blunder"], 0, 0),
    ],
)
def test_streak(verdicts, current, best):
    rows = [row(i, verdict=v) for i, v in enumerate(verdicts, 1)]
    assert run(rows)["streak"] == {"current": current, "best": best}


def test_streak_ignores_retries():
    rows = [row(1), row(2, is_first=False, verdict="blunder"), row(3, verdict="fine")]
    assert run(rows)["streak"] == {"current": 2, "best": 2}


# ---------------------------------------------------------------------------
# Days
# ---------------------------------------------------------------------------


def test_day_boundary_by_time_zone():
    at = datetime(2026, 11, 11, 23, 30, tzinfo=UTC)
    now = datetime(2026, 11, 12, 1, 0, tzinfo=UTC)
    rows = [row(1, created_at=at)]
    tokyo = run(rows, tz="Asia/Tokyo", now=now)["days"]
    assert tokyo["recent"][-1] == {"date": "2026-11-12", "count": 1}
    assert tokyo["today"] == 1
    ny = run(rows, tz="America/New_York", now=now)["days"]
    assert ny["recent"][-1] == {"date": "2026-11-11", "count": 1}  # still the 11th in NY
    assert ny["today"] == 1
    utc = run(rows, tz="UTC", now=now)["days"]
    assert utc["recent"][-1] == {"date": "2026-11-12", "count": 0}
    assert utc["recent"][-2] == {"date": "2026-11-11", "count": 1}
    assert utc["today"] == 0


def test_dst_day_buckets_by_local_date():
    # 2026-11-01 in New York: EDT (UTC-4) until 06:00Z, EST (UTC-5) after.
    times = [
        datetime(2026, 11, 1, 3, 30, tzinfo=UTC),  # Oct 31, 23:30 EDT
        datetime(2026, 11, 1, 4, 30, tzinfo=UTC),  # Nov 1, 00:30 EDT
        datetime(2026, 11, 2, 4, 30, tzinfo=UTC),  # Nov 1, 23:30 EST
        datetime(2026, 11, 2, 5, 30, tzinfo=UTC),  # Nov 2, 00:30 EST
    ]
    now = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
    days = run(
        [row(i, created_at=t) for i, t in enumerate(times, 1)], tz="America/New_York", now=now
    )["days"]
    counts = {d["date"]: d["count"] for d in days["recent"]}
    assert counts["2026-10-31"] == 1
    assert counts["2026-11-01"] == 2
    assert counts["2026-11-02"] == 1
    assert days["recent"][-1]["date"] == "2026-11-02"
    dates = [d["date"] for d in days["recent"]]
    assert len(dates) == len(set(dates)) == 14


def _on_days(counts: list[int], now: datetime) -> list[StatRow]:
    """``counts[-1]`` attempts today, ``counts[-2]`` yesterday, ..."""
    rows: list[StatRow] = []
    i = 0
    for back, c in enumerate(reversed(counts)):
        day = now - timedelta(days=back)
        for _ in range(c):
            i += 1
            rows.append(row(i, created_at=day.replace(hour=1, minute=i % 60)))
    rows.sort(key=lambda r: r.created_at)
    return [replace(r, id=k) for k, r in enumerate(rows, 1)]


def test_day_streak_today_unfinished():
    days = run(_on_days([2, 2, 1], NOW), goal=2)["days"]
    assert days["today"] == 1
    assert days["current_streak"] == 2 and days["best_streak"] == 2


def test_day_streak_today_met():
    days = run(_on_days([2, 2, 2], NOW), goal=2)["days"]
    assert days["current_streak"] == 3 and days["best_streak"] == 3


def test_day_streak_broken_yesterday():
    days = run(_on_days([3, 3, 3, 0, 1], NOW), goal=2)["days"]
    assert days["current_streak"] == 0 and days["best_streak"] == 3
    assert days["goal"] == 2
    assert [d["count"] for d in days["recent"][-5:]] == [3, 3, 3, 0, 1]


def test_day_streak_gap_resets_the_run():
    # two days met, a day with none, one met, today unfinished
    days = run(_on_days([2, 2, 0, 2, 1], NOW), goal=2)["days"]
    assert days["current_streak"] == 1 and days["best_streak"] == 2


def test_days_after_today_are_ignored_by_streaks():
    future = [row(i, created_at=NOW + timedelta(days=d)) for i, d in ((1, 1), (2, 2), (3, 3))]
    days = run([*_on_days([1], NOW), *[replace(r, id=r.id + 10) for r in future]], goal=1)["days"]
    assert days["today"] == 1
    assert days["current_streak"] == 1 and days["best_streak"] == 1  # not 4
    assert days["recent"][-1]["date"] == "2026-11-12"
    future_only = run(future, goal=1)["days"]
    assert future_only["current_streak"] == 0 and future_only["best_streak"] == 0


def test_day_streak_beyond_recent_window():
    days = run(_on_days([1] * 20, NOW), goal=1)["days"]
    assert days["current_streak"] == 20 and days["best_streak"] == 20


# ---------------------------------------------------------------------------
# Breakdowns
# ---------------------------------------------------------------------------


def test_breakdown_orders_labels_and_values():
    rows = [
        row(
            1,
            street="river",
            action_kind="raise",
            profile="old",
            verdict="blunder",
            ev_loss_chips=10.0,
            equity_error=0.2,
        ),
        row(2, street="preflop", action_kind="fold", profile="sticky", verdict="best"),
        row(
            3,
            street="river",
            action_kind="call",
            profile="tag",
            verdict="fine",
            ev_loss_chips=2.0,
            equity_error=0.1,
        ),
        row(
            4,
            street="turn",
            action_kind="bet",
            profile="archived",
            verdict="mistake",
            ev_loss_chips=4.0,
        ),
        row(5, street="flop", action_kind="check", profile="tag", verdict="best"),
        row(6, is_first=False, street="flop", action_kind="raise", profile="lag"),
    ]
    b = run(rows)["breakdowns"]
    assert [(r["key"], r["label"]) for r in b["street"]] == [
        ("preflop", "Pre-flop"),
        ("flop", "Flop"),
        ("turn", "Turn"),
        ("river", "River"),
    ]
    assert [(r["key"], r["label"]) for r in b["action"]] == [
        ("fold", "Fold"),
        ("check", "Check"),
        ("call", "Call"),
        ("bet", "Bet"),
        ("raise", "Raise"),
    ]
    # PROFILE_NAMES order (the labels mapping's order), then unknown names alphabetically;
    # "lag" only has a retry, so it has no row
    assert [(r["key"], r["label"]) for r in b["profile"]] == [
        ("tag", "TAG"),
        ("sticky", "Sticky"),
        ("archived", "Archived"),
        ("old", "Old"),
    ]
    river = b["street"][3]
    assert river["count"] == 2
    assert river["accuracy"] == 0.5
    assert river["ev_lost_bb_avg"] == pytest.approx(3.0)
    assert river["equity_error_avg"] == pytest.approx(0.15)
    assert river["verdicts"] == {"best": 0, "fine": 1, "mistake": 0, "blunder": 1}
    flop = b["street"][1]
    assert flop["count"] == 1  # the retry on the flop doesn't count


# ---------------------------------------------------------------------------
# Time zones, performance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["Not/AZone", "../etc", "/etc/passwd", "Europe", "a" * 64, "", "localtime", "Factory"]
)
def test_parse_tz_rejects(name):
    with pytest.raises(ValueError):
        parse_tz(name)


@pytest.mark.parametrize("name", ["UTC", "Europe/London", "Asia/Tokyo", "America/New_York"])
def test_parse_tz_accepts(name):
    assert parse_tz(name).key == name


def test_compute_is_fast():
    verdicts = ["best", "fine", "mistake", "blunder"]
    streets = ["preflop", "flop", "turn", "river"]
    rows = [
        row(
            i,
            created_at=T0 - timedelta(hours=5000 - i),
            street=streets[i % 4],
            verdict=verdicts[(i * 7) % 4],
            ev_loss_chips=float(i % 13),
            equity_error=(i % 17) / 100,
            range_read_error=None if i % 3 else 0.1,
            is_first=i % 10 != 0,
        )
        for i in range(1, 5001)
    ]
    start = time.perf_counter()
    compute(rows, tz=ZoneInfo("Europe/London"), now=NOW, goal=10, profile_labels=LABELS)
    assert time.perf_counter() - start < 0.5
