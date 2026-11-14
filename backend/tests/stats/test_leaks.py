"""``stats.leaks.detect``: rule-based leaks over the newest first attempts (pure, no DB)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from poker_trainer.api.schemas import Leak, StatsView
from poker_trainer.stats import leaks
from poker_trainer.stats.leaks import DEFAULT, LEAK_WINDOW, LeakThresholds, detect
from poker_trainer.stats.service import StatRow, compute

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)

_NEUTRAL = {  # flags nothing: a correct flop call, exact equity guess, no range read
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


def build(*specs: tuple[int, dict]) -> list[StatRow]:
    """Rows in id order from ``(how_many, overrides)`` pairs."""
    out: list[StatRow] = []
    for times, kw in specs:
        for _ in range(times):
            i = len(out) + 1
            out.append(StatRow(id=i, created_at=T0 + timedelta(minutes=i), **{**_NEUTRAL, **kw}))
    return out


def by_id(found: list[dict]) -> dict[str, dict]:
    return {leak["id"]: leak for leak in found}


def check_shape(found: list[dict]) -> None:
    for leak in found:
        Leak.model_validate(leak)


def test_defaults():
    assert LEAK_WINDOW == DEFAULT.window == 200
    with pytest.raises(AttributeError):  # frozen
        DEFAULT.window = 5  # type: ignore[misc]


def test_nothing_on_empty_or_clean_rows():
    assert detect([]) == []
    assert detect(build((250, {}))) == []


# ---------------------------------------------------------------------------
# Share rules
# ---------------------------------------------------------------------------

# id -> (flagged row, looked-at but fine row, min_n, share)
SHARE_RULES: dict[str, tuple[dict, dict, int, float]] = {
    "river_overcall": (
        {
            "street": "river",
            "action_kind": "call",
            "best_kind": "fold",
            "verdict": "mistake",
            "ev_loss_chips": 1.0,
        },
        {"street": "river", "action_kind": "call", "best_kind": "call"},
        DEFAULT.river_overcall_min_n,
        DEFAULT.river_overcall_share,
    ),
    "overfold": (
        {"action_kind": "fold", "best_kind": "call", "verdict": "mistake", "ev_loss_chips": 1.0},
        {"action_kind": "fold", "best_kind": "fold"},
        DEFAULT.overfold_min_n,
        DEFAULT.overfold_share,
    ),
    "overbluff": (
        {"action_kind": "bet", "intent_truth": "bluff", "verdict": "mistake", "ev_loss_chips": 1.0},
        {"action_kind": "bet", "intent_truth": "bluff", "verdict": "fine"},
        DEFAULT.overbluff_min_n,
        DEFAULT.overbluff_share,
    ),
    "missed_value": (
        {
            "best_kind": "bet",
            "action_kind": "check",
            "verdict": "mistake",
            "true_equity": 0.65,
            "equity_guess": 0.65,
            "ev_loss_chips": 1.0,
        },
        {"best_kind": "bet", "action_kind": "bet", "true_equity": 0.65, "equity_guess": 0.65},
        DEFAULT.missed_value_min_n,
        DEFAULT.missed_value_share,
    ),
    "intent_mislabel": (
        {"action_kind": "raise", "intent": "value", "intent_flag": "x", "ev_loss_chips": 1.0},
        {"action_kind": "raise", "intent": "value"},
        DEFAULT.intent_mislabel_min_n,
        DEFAULT.intent_mislabel_share,
    ),
}

# 81 flagged of 200: 40.5% -> 41 (half up), 81 x 0.5 bb = 40.5 bb
SHARE_TEXTS = {
    "river_overcall": (
        "Calling too often on the river",
        (
            "You called 200 river bets or raises; folding was better 81 times (41%), "
            "costing 40.5 bb."
        ),
    ),
    "overfold": (
        "Folding too often",
        "You folded 200 times; continuing was better 81 times (41%), costing 40.5 bb.",
    ),
    "overbluff": (
        "Over-bluffing",
        (
            "81 of your 200 bluffs (41%) were mistakes or blunders, costing 40.5 bb. "
            "Check how often Villain folds before bluffing."
        ),
    ),
    "missed_value": (
        "Missing value bets",
        (
            "With a strong hand where betting was best, you checked or called 81 of 200 times "
            "(41%), costing 40.5 bb."
        ),
    ),
    "intent_mislabel": (
        "Mislabelling bets",
        (
            "You labelled 81 of 200 bets or raises (41%) differently from what they were "
            "(value, semi-bluff or bluff)."
        ),
    ),
}


@pytest.mark.parametrize("rule", SHARE_RULES)
def test_share_rule_threshold(rule):
    bad, fine, _min_n, share = SHARE_RULES[rule]
    at = round(share * 200)  # exactly on the threshold: see test_share_rule_exact_threshold
    above = by_id(detect(build((at + 1, bad), (199 - at, fine))))  # share + 0.005
    below = by_id(detect(build((at - 1, bad), (201 - at, fine))))  # share - 0.005
    assert rule in above and rule not in below
    leak = above[rule]
    assert leak["kind"] == "share"
    assert leak["count"] == at + 1 and leak["sample"] == 200
    assert leak["ev_lost_bb"] == pytest.approx((at + 1) * 0.5)
    assert leak["mean_error"] is None


@pytest.mark.parametrize("rule", SHARE_RULES)
def test_share_rule_min_n(rule):
    bad, _fine, min_n, _share = SHARE_RULES[rule]
    assert rule in by_id(detect(build((min_n, bad))))
    assert rule not in by_id(detect(build((min_n - 1, bad))))


@pytest.mark.parametrize("rule", SHARE_RULES)
def test_share_rule_texts(rule):
    bad, fine, _min_n, _share = SHARE_RULES[rule]
    found = detect(build((81, bad), (119, fine)))
    check_shape(found)
    leak = by_id(found)[rule]
    assert (leak["title"], leak["detail"]) == SHARE_TEXTS[rule]


def test_share_rules_only_look_at_their_rows():
    # calls off the river, checks, bets that aren't bluffs, bets with no intent given
    rows = build(
        (10, {"street": "turn", "action_kind": "call", "best_kind": "fold"}),
        (10, {"action_kind": "check", "best_kind": "check"}),
        (10, {"action_kind": "bet", "intent_truth": "value", "verdict": "blunder"}),
        (10, {"action_kind": "bet", "intent_truth": "semi_bluff", "verdict": "blunder"}),
        (10, {"action_kind": "bet", "intent_flag": "x"}),  # no intent given
        # betting best but not strong enough, or no stored equity
        (
            10,
            {
                "best_kind": "bet",
                "action_kind": "check",
                "true_equity": 0.595,
                "equity_guess": 0.595,
            },
        ),
        (10, {"best_kind": "raise", "action_kind": "call", "true_equity": None}),
    )
    assert by_id(detect(rows)).keys().isdisjoint(SHARE_RULES)


def test_overbluff_counts_blunders_and_missed_value_counts_calls():
    rows = build(
        (5, {"action_kind": "raise", "intent_truth": "bluff", "verdict": "blunder"}),
        (
            5,
            {
                "best_kind": "raise",
                "action_kind": "call",
                "verdict": "blunder",
                "true_equity": 0.605,
                "equity_guess": 0.605,
            },
        ),
    )
    assert {"overbluff", "missed_value"} <= by_id(detect(rows)).keys()


# ---------------------------------------------------------------------------
# Mean rules
# ---------------------------------------------------------------------------


def _draw(e: float) -> dict:
    return {"hero_category": "strong_draw", "true_equity": 0.3, "equity_guess": 0.3 + e}


def _equity(e: float) -> dict:
    return {"true_equity": 0.5, "equity_guess": 0.5 + e}


def _read(e: float) -> dict:
    return {"ahead_now": 0.5, "range_read_guess": 0.5 + e}


# id -> (row maker for a signed error, min_n, signed threshold)
MEAN_RULES = {
    "draw_overestimate": (_draw, DEFAULT.draw_overestimate_min_n, DEFAULT.draw_overestimate_mean),
    "equity_overestimate": (_equity, DEFAULT.equity_min_n, DEFAULT.equity_mean),
    "equity_underestimate": (_equity, DEFAULT.equity_min_n, -DEFAULT.equity_mean),
    "range_read_high": (_read, DEFAULT.range_read_min_n, DEFAULT.range_read_mean),
    "range_read_low": (_read, DEFAULT.range_read_min_n, -DEFAULT.range_read_mean),
}

MEAN_TEXTS = {  # 10 spots, 0.5 pts past the threshold
    "draw_overestimate": (
        "Overestimating equity with draws",
        "With a draw you guessed 8.5 pts too high on average (10 spots).",
    ),
    "equity_overestimate": (
        "Overestimating your equity",
        "Your equity guesses are 7.5 pts too high on average (10 spots).",
    ),
    "equity_underestimate": (
        "Underestimating your equity",
        "Your equity guesses are 7.5 pts too low on average (10 spots).",
    ),
    "range_read_high": (
        "Thinking you're ahead more often than you are",
        (
            "Your range reads are 8.5 pts too high on average (10 spots): "
            "Villain's range is stronger than you think."
        ),
    ),
    "range_read_low": (
        "Giving Villain too much credit",
        (
            "Your range reads are 8.5 pts too low on average (10 spots): "
            "you're ahead more often than you think."
        ),
    ),
}


def _past(threshold: float, by: float) -> float:
    """``by`` further from zero than ``threshold`` (negative ``by``: closer to zero)."""
    return threshold + by if threshold > 0 else threshold - by


@pytest.mark.parametrize("rule", MEAN_RULES)
def test_mean_rule_threshold(rule):
    make, _min_n, thr = MEAN_RULES[rule]
    above = by_id(detect(build((20, make(_past(thr, 0.005))))))
    below = by_id(detect(build((20, make(_past(thr, -0.005))))))
    assert rule in above and rule not in below
    leak = above[rule]
    assert leak["kind"] == "mean"
    assert leak["count"] == leak["sample"] == 20
    assert leak["ev_lost_bb"] is None
    assert leak["mean_error"] == pytest.approx(_past(thr, 0.005))


@pytest.mark.parametrize("rule", MEAN_RULES)
def test_mean_rule_min_n(rule):
    make, min_n, thr = MEAN_RULES[rule]
    assert rule in by_id(detect(build((min_n, make(_past(thr, 0.005))))))
    assert rule not in by_id(detect(build((min_n - 1, make(_past(thr, 0.005))))))


@pytest.mark.parametrize("rule", MEAN_RULES)
def test_mean_rule_texts(rule):
    make, _min_n, thr = MEAN_RULES[rule]
    found = detect(build((10, make(_past(thr, 0.005)))))
    check_shape(found)
    leak = by_id(found)[rule]
    assert (leak["title"], leak["detail"]) == MEAN_TEXTS[rule]


def test_mean_rules_average_signed_errors_and_skip_nulls():
    # +0.21 and -0.04 average to +0.085 over the 10 spots with a stored truth
    rows = build(
        (5, _equity(0.21)),
        (5, _equity(-0.04)),
        (20, {"true_equity": None, "equity_guess": 0.0}),  # no stored truth: skipped
        (
            20,
            {"range_read_guess": 0.9, "ahead_now": None, "true_equity": None},
        ),  # river: no truth, skipped
        (
            20,
            {"range_read_guess": None, "ahead_now": 0.9, "true_equity": None},
        ),  # no read given: skipped
    )
    leak = by_id(detect(rows))["equity_overestimate"]
    assert leak["sample"] == 10 and leak["mean_error"] == pytest.approx(0.085)
    assert "range_read_high" not in by_id(detect(rows))
    assert "range_read_low" not in by_id(detect(rows))


def test_draw_rule_only_looks_at_draws():
    rows = build(
        (3, {**_draw(0.2), "hero_category": "weak_draw"}),
        (2, _draw(0.2)),
        (10, {"hero_category": "medium", "true_equity": 0.3, "equity_guess": 0.3}),
        (10, {"hero_category": "strong_draw", "true_equity": None}),
    )
    leak = by_id(detect(rows))["draw_overestimate"]
    assert leak["sample"] == 5 and leak["mean_error"] == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# Window, retries, thresholds, sorting, formatting
# ---------------------------------------------------------------------------

RIVER_LEAK = SHARE_RULES["river_overcall"][0]
OVERFOLD = SHARE_RULES["overfold"][0]


def test_only_the_newest_window_of_first_attempts_counts():
    old = build((50, RIVER_LEAK), (210, {}))  # leak in attempts 1-50 of 260
    assert detect(old) == []
    new = build((210, {}), (50, RIVER_LEAK))  # the same leak in attempts 211-260
    assert "river_overcall" in by_id(detect(new))


def test_retries_never_count():
    rows = build((4, RIVER_LEAK), (50, {**RIVER_LEAK, "is_first": False}))
    assert detect(rows) == []
    # nor do they push first attempts out of the window: the newest 200 first attempts
    # still hold 5 of the leak rows even though 100 retries follow
    rows = build((10, RIVER_LEAK), (195, {}), (100, {**_NEUTRAL, "is_first": False}))
    leak = by_id(detect(rows))["river_overcall"]
    assert leak["sample"] == leak["count"] == 5


def test_custom_thresholds():
    rows = build((3, RIVER_LEAK))
    assert detect(rows) == []
    t = LeakThresholds(river_overcall_min_n=3)
    assert "river_overcall" in by_id(detect(rows, t))
    leak = by_id(detect(build((210, {}), (50, RIVER_LEAK)), LeakThresholds(window=40)))
    assert leak["river_overcall"]["sample"] == 40


def test_sorting():
    mis = {"true_equity": 0.5, "equity_guess": 0.4, "ahead_now": 0.5, "range_read_guess": 0.62}
    rows = build(
        (5, {**RIVER_LEAK, "ev_loss_chips": 4.0, **mis}),  # 10 bb, 5 rows
        (8, {**OVERFOLD, "ev_loss_chips": 5.0, **mis}),  # 20 bb
    )
    assert [x["id"] for x in detect(rows)] == [
        "overfold",
        "river_overcall",
        "range_read_high",  # |+0.12|
        "equity_underestimate",  # |-0.10|
    ]


def test_sorting_ties_on_bb_go_to_the_larger_count():
    rows = build(
        (5, {**RIVER_LEAK, "ev_loss_chips": 4.0}),  # 10 bb over 5 rows
        (8, {**OVERFOLD, "ev_loss_chips": 2.5}),  # 10 bb over 8
    )
    assert [x["id"] for x in detect(rows)] == ["overfold", "river_overcall"]


def test_numbers_round_half_up():
    # 1 of 8 folds = 12.5% -> 13; 0.25 bb -> 0.3 (not banker's 12 / 0.2)
    rows = build(
        (1, {**OVERFOLD, "ev_loss_chips": 0.5}),
        (7, {"action_kind": "fold", "best_kind": "fold"}),
    )
    t = LeakThresholds(overfold_share=0.1)
    leak = by_id(detect(rows, t))["overfold"]
    assert leak["detail"] == (
        "You folded 8 times; continuing was better once (13%), costing 0.3 bb."
    )


def test_compute_includes_detect(monkeypatch):
    rows = build((10, {}), (6, RIVER_LEAK), (3, {**RIVER_LEAK, "is_first": False}))
    out = compute(rows, tz=ZoneInfo("UTC"), now=NOW, goal=10, profile_labels={"tag": "TAG"})
    StatsView.model_validate(out)
    assert out["leaks"] == detect(rows) != []

    seen = []
    monkeypatch.setattr(leaks, "detect", lambda r: seen.append(list(r)) or [])
    compute(list(reversed(rows)), tz=ZoneInfo("UTC"), now=NOW, goal=10, profile_labels={})
    assert seen == [rows]  # every row, retries included, in id order


# ---------------------------------------------------------------------------
# Review fixes: Best plays, grammar, exact thresholds, sort by bb
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rule", ["river_overcall", "overfold", "missed_value"])
def test_best_plays_are_never_flagged(rule):
    bad, _fine, min_n, _share = SHARE_RULES[rule]
    best = {**bad, "verdict": "best"}
    assert rule not in by_id(detect(build((50, best))))
    leak = by_id(detect(build((min_n, best), (min_n, bad))))[rule]
    assert leak["sample"] == 2 * min_n and leak["count"] == min_n  # still in the sample


ONE = LeakThresholds(
    river_overcall_min_n=1,
    overfold_min_n=1,
    overbluff_min_n=1,
    missed_value_min_n=1,
    intent_mislabel_min_n=1,
    draw_overestimate_min_n=1,
)

ONE_TEXTS = {
    "river_overcall": (
        "You called 1 river bet or raise; folding was better once (100%), costing 0.5 bb."
    ),
    "overfold": "You folded once; continuing was better once (100%), costing 0.5 bb.",
    "overbluff": (
        "1 of your 1 bluff (100%) was a mistake or blunder, costing 0.5 bb. "
        "Check how often Villain folds before bluffing."
    ),
    "missed_value": (
        "With a strong hand where betting was best, you checked or called 1 of 1 time (100%), "
        "costing 0.5 bb."
    ),
    "intent_mislabel": (
        "You labelled 1 of 1 bet or raise (100%) differently from what it was "
        "(value, semi-bluff or bluff)."
    ),
}


@pytest.mark.parametrize("rule", SHARE_RULES)
def test_share_texts_for_a_single_row(rule):
    bad, _fine, _min_n, _share = SHARE_RULES[rule]
    assert by_id(detect(build((1, bad)), ONE))[rule]["detail"] == ONE_TEXTS[rule]


def test_single_counts_in_a_larger_sample():
    bad, fine, _min_n, _share = SHARE_RULES["overbluff"]
    leak = by_id(detect(build((1, bad), (1, fine)), ONE))["overbluff"]
    assert leak["detail"] == (
        "1 of your 2 bluffs (50%) was a mistake or blunder, costing 0.5 bb. "
        "Check how often Villain folds before bluffing."
    )
    bad, fine, _min_n, _share = SHARE_RULES["intent_mislabel"]
    leak = by_id(detect(build((1, bad), (1, fine)), ONE))["intent_mislabel"]
    assert leak["detail"] == (
        "You labelled 1 of 2 bets or raises (50%) differently from what it was "
        "(value, semi-bluff or bluff)."
    )


def test_mean_text_for_a_single_spot():
    leak = by_id(detect(build((1, _draw(0.085))), ONE))["draw_overestimate"]
    assert leak["detail"] == "With a draw you guessed 8.5 pts too high on average (1 spot)."


def test_exactly_on_the_threshold_fires():
    river, river_fine, _n, _s = SHARE_RULES["river_overcall"]
    assert 2 / 5 == DEFAULT.river_overcall_share
    assert "river_overcall" in by_id(detect(build((2, river), (3, river_fine))))
    fold, fold_fine, _n, _s = SHARE_RULES["overfold"]
    assert 7 / 20 == DEFAULT.overfold_share
    assert "overfold" in by_id(detect(build((7, fold), (13, fold_fine))))
    # a strong hand at exactly the equity cut-off is looked at
    value, _fine, min_n, _s = SHARE_RULES["missed_value"]
    edge = {**value, "true_equity": 0.6, "equity_guess": 0.6}
    assert by_id(detect(build((min_n, edge))))["missed_value"]["sample"] == min_n
    # a mean exactly on its threshold (0.75 - 0.5 == 0.25 exactly)
    t = LeakThresholds(equity_mean=0.25)
    assert "equity_overestimate" in by_id(detect(build((10, _equity(0.25))), t))
    assert "equity_underestimate" in by_id(detect(build((10, _equity(-0.25))), t))


def test_sorting_is_by_bb_before_count():
    rows = build(
        (5, {**RIVER_LEAK, "ev_loss_chips": 8.0}),  # 20 bb over 5 rows
        (8, {**OVERFOLD, "ev_loss_chips": 2.0}),  # 8 bb over 8 rows
    )
    assert [x["id"] for x in detect(rows)] == ["river_overcall", "overfold"]
