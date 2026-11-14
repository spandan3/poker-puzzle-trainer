import random

import numpy as np
import pytest

from poker_trainer.engine.cards import parse_cards
from poker_trainer.engine.combos import combo_index
from poker_trainer.game.state import (
    Action,
    ActionKind,
    HandState,
    Street,
    apply,
    deal,
    legal_actions,
    new_hand,
)
from poker_trainer.villain.features import (
    HandCategory,
    board_texture,
    categorize,
    load_thresholds,
    range_features,
)
from poker_trainer.villain.profiles import PROFILE_NAMES, load_profile
from poker_trainer.villain.strategy import (
    ALLIN_FRACTION,
    HERO_PROFILE,
    OPEN_MULT,
    RAISE_MULT,
    THREEBET_MULT,
    UnsupportedSpot,
    action_distribution,
    allin,
    bet_to,
    raise_to,
    role,
    sample_action,
)

DRY = "Kh7d2c"
WET = "Th9h4c"

F, X, C, B, R = (
    ActionKind.FOLD,
    ActionKind.CHECK,
    ActionKind.CALL,
    ActionKind.BET,
    ActionKind.RAISE,
)


def idx(s: str) -> int:
    a, b = parse_cards(s)
    return combo_index(a, b)


def cats_for(board: str) -> np.ndarray:
    return categorize(range_features(parse_cards(board)), load_thresholds())


def act(s: HandState, kind: ActionKind, to: int = 0) -> HandState:
    if kind == ActionKind.CALL:
        to = s.street_bets[s.to_act] + legal_actions(s).call
    return apply(s, Action(s.to_act, kind, s.street, to))


def opened() -> HandState:
    """BTN (seat 0) opens to 5; BB to act."""
    s = new_hand(0)
    return apply(s, raise_to(s, OPEN_MULT))


def flop(board: str = DRY, stacks: tuple[int, int] = (200, 200)) -> HandState:
    """BTN opens to 5, BB calls, flop dealt; BB (seat 1) to act."""
    s = new_hand(0, stacks)
    s = apply(s, raise_to(s, OPEN_MULT))
    s = act(s, C)
    return deal(s, parse_cards(board))


def facing_bet(frac: float, board: str = DRY) -> HandState:
    """Flop: BB checks, BTN bets frac of the pot; BB to act."""
    s = act(flop(board), X)
    return apply(s, bet_to(s, frac))


def manual_flop(pot: int, stacks: tuple[int, int], board: str = DRY) -> HandState:
    return HandState(
        button=0,
        stacks=stacks,
        street_bets=(0, 0),
        pot=pot,
        street=Street.FLOP,
        board=parse_cards(board),
        to_act=1,
        history=(),
        last_raise=2,
        folded=None,
        total_chips=pot + sum(stacks),
    )


def check_sums(dist: dict[Action, np.ndarray], blocked: np.ndarray) -> None:
    total = sum(dist.values())
    assert np.allclose(total[~blocked], 1.0, atol=1e-9)
    for arr in dist.values():
        assert arr.shape == (1326,)
        assert np.all(arr[blocked] == 0.0)
        assert np.all(arr >= 0.0)


def fold_of(dist: dict[Action, np.ndarray]) -> np.ndarray:
    folds = [a for a in dist if a.kind == F]
    assert len(folds) == 1
    return dist[folds[0]]


def test_constants():
    assert ALLIN_FRACTION == 0.6
    assert OPEN_MULT == 2.5
    assert THREEBET_MULT == 3.0
    assert RAISE_MULT == 3.0
    assert HERO_PROFILE == "tag"
    assert issubclass(UnsupportedSpot, ValueError)


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_distribution_sums_to_one(name):
    p = load_profile(name)
    none = np.zeros(1326, dtype=bool)
    check_sums(action_distribution(p, new_hand(0)), none)
    check_sums(action_distribution(p, opened()), none)
    blocked = cats_for(DRY) < 0
    assert blocked.sum() > 0
    cbet = act(flop(), X)
    assert role(cbet) == "cbet"
    check_sums(action_distribution(p, cbet), blocked)
    fb = facing_bet(0.75)
    assert role(fb) == "facing_bet"
    check_sums(action_distribution(p, fb), blocked)
    # Wet board (draw boost) and the facing-raise spot too.
    wet = act(flop(WET), X)
    check_sums(action_distribution(p, wet), cats_for(WET) < 0)
    fr = apply(fb, raise_to(fb, RAISE_MULT))
    assert role(fr) == "facing_raise"
    check_sums(action_distribution(p, fr), blocked)


def test_preflop_open_matches_range():
    tag = load_profile("tag")
    dist = action_distribution(tag, new_hand(0))
    assert set(dist) == {Action(0, R, Street.PREFLOP, 5), Action(0, F, Street.PREFLOP)}
    assert np.array_equal(dist[Action(0, R, Street.PREFLOP, 5)], tag.preflop.open)
    assert np.allclose(dist[Action(0, F, Street.PREFLOP)], 1.0 - tag.preflop.open)


def test_preflop_tree_mapping():
    tag = load_profile("tag")
    pf = tag.preflop
    s = opened()
    d = action_distribution(tag, s)
    assert np.array_equal(d[Action(1, R, Street.PREFLOP, 15)], pf.bb_threebet)
    assert np.array_equal(d[Action(1, C, Street.PREFLOP, 5)], pf.bb_call)
    # BTN facing a non-all-in 3-bet: jam / call / fold.
    s3 = apply(s, raise_to(s, THREEBET_MULT))
    d = action_distribution(tag, s3)
    assert np.array_equal(d[Action(0, R, Street.PREFLOP, 200)], pf.btn_jam)
    assert np.array_equal(d[Action(0, C, Street.PREFLOP, 15)], pf.btn_call_threebet)
    # BB facing the 4-bet jam: call / fold.
    s4 = apply(s3, allin(s3))
    d = action_distribution(tag, s4)
    assert set(d) == {Action(1, C, Street.PREFLOP, 200), Action(1, F, Street.PREFLOP)}
    assert np.array_equal(d[Action(1, C, Street.PREFLOP, 200)], pf.bb_call_jam)
    # BB facing an open-jam.
    s0 = new_hand(0)
    sj = apply(s0, allin(s0))
    d = action_distribution(tag, sj)
    assert set(d) == {Action(1, C, Street.PREFLOP, 200), Action(1, F, Street.PREFLOP)}
    assert np.array_equal(d[Action(1, C, Street.PREFLOP, 200)], pf.bb_call_open_jam)
    # BTN facing a 3-bet jam.
    s3j = apply(s, allin(s))
    d = action_distribution(tag, s3j)
    assert set(d) == {Action(0, C, Street.PREFLOP, 200), Action(0, F, Street.PREFLOP)}
    assert np.array_equal(d[Action(0, C, Street.PREFLOP, 200)], pf.btn_call_jam)


def test_short_stack_threebet_becomes_jam():
    tag = load_profile("tag")
    s = new_hand(0, (20, 20))
    s = apply(s, raise_to(s, OPEN_MULT))
    d = action_distribution(tag, s)
    # 3 x 5 = 15 >= 0.6 * 20 -> the 3-bet is an all-in.
    assert Action(1, R, Street.PREFLOP, 20) in d
    s3 = apply(s, Action(1, R, Street.PREFLOP, 20))
    d = action_distribution(tag, s3)
    assert np.array_equal(d[Action(0, C, Street.PREFLOP, 20)], tag.preflop.btn_call_jam)


def test_unequal_stacks_capped_open_is_a_jam():
    """BTN deeper than BB: an open to the effective cap leaves BB only fold/call."""
    tag = load_profile("tag")
    s = new_hand(0, (300, 100))
    s = apply(s, allin(s))
    assert s.stacks[0] > 0
    d = action_distribution(tag, s)
    assert set(d) == {Action(1, C, Street.PREFLOP, 100), Action(1, F, Street.PREFLOP)}
    assert np.array_equal(d[Action(1, C, Street.PREFLOP, 100)], tag.preflop.bb_call_open_jam)


def test_unsupported_spots():
    tag = load_profile("tag")
    limp = act(new_hand(0), C)
    with pytest.raises(UnsupportedSpot):
        action_distribution(tag, limp)
    s = opened()
    s = apply(s, raise_to(s, THREEBET_MULT))
    s = act(s, R, 40)
    assert s.stacks[0] > 0
    with pytest.raises(UnsupportedSpot):
        action_distribution(tag, s)


def test_bet_to_values():
    s = flop()
    assert s.pot == 10 and s.stacks == (195, 195)
    assert bet_to(s, 0.33) == Action(1, B, Street.FLOP, 3)
    assert bet_to(s, 0.75).to == 8
    s0 = new_hand(0)
    s0 = act(s0, C)
    s0 = act(s0, X)
    s0 = deal(s0, parse_cards(DRY))
    assert s0.pot == 4
    assert bet_to(s0, 0.33).to == 2  # min bet


def test_allin_threshold():
    s = manual_flop(30, (30, 30))
    assert bet_to(s, 0.75) == Action(1, B, Street.FLOP, 30)  # 22 >= 18 -> all-in
    assert bet_to(s, 0.33).to == 10  # 10 < 18 stays


def test_sizing_never_outside_legal_bounds():
    for pot in (2, 3, 4, 7, 10, 40, 333):
        for stack in (1, 2, 3, 5, 9, 50, 400):
            s = manual_flop(pot, (stack, stack))
            lg = legal_actions(s)
            for frac in (0.0, 0.25, 0.33, 0.5, 0.75, 1.0, 1.5, 3.0):
                a = bet_to(s, frac)
                assert a.kind == B
                assert lg.min_to <= a.to <= lg.max_to
                if a.to >= ALLIN_FRACTION * lg.max_to:
                    assert a.to == lg.max_to
                apply(s, a)
            assert allin(s).to == lg.max_to


def test_raise_below_min_clamps_up():
    # BTN bets 10 into 10; a min-raise is to 20. 1.5x the bet (15) clamps up to 20.
    s = act(flop(), X)
    s = act(s, B, 10)
    assert legal_actions(s).min_to == 20
    assert raise_to(s, 1.5) == Action(1, R, Street.FLOP, 20)
    assert raise_to(s, RAISE_MULT).to == 30
    assert raise_to(s, 100.0).to == 195  # clamped to max
    assert raise_to(s, 11.0).to == 110  # 110 < 0.6 * 195 = 117 stays
    assert raise_to(s, 12.0).to == 195  # 120 >= 117 -> all-in


def test_sizing_errors():
    s = flop()
    with pytest.raises(ValueError):
        raise_to(s, 3.0)  # nothing to raise
    fb = facing_bet(0.75)
    with pytest.raises(ValueError):
        bet_to(fb, 0.5)  # facing a bet: betting is not legal
    # Pre-flop BB facing an open-jam cannot raise.
    s0 = new_hand(0)
    sj = apply(s0, allin(s0))
    with pytest.raises(ValueError):
        raise_to(sj, 3.0)
    with pytest.raises(ValueError):
        allin(sj)


def test_sizes_merge():
    tag = load_profile("tag")
    s = manual_flop(20, (10, 10))
    assert bet_to(s, 0.33) == bet_to(s, 0.75) == Action(1, B, Street.FLOP, 10)
    assert role(s) == "lead"
    dist = action_distribution(tag, s)
    bets = [a for a in dist if a.kind == B]
    assert bets == [Action(1, B, Street.FLOP, 10)]
    cats = cats_for(DRY)
    table = tag.unopened["lead"]
    want = np.array(
        [
            0.0 if c < 0 else table[HandCategory(c)]["bet_33"] + table[HandCategory(c)]["bet_75"]
            for c in cats
        ]
    )
    assert board_texture(parse_cards(DRY)).wet is False
    assert np.allclose(dist[bets[0]], want, atol=1e-12)


def test_wet_board_boosts_draw_bets():
    tag = load_profile("tag")
    assert board_texture(parse_cards(WET)).wet
    s = act(flop(WET), X)
    dist = action_distribution(tag, s)
    cats = cats_for(WET)
    table = tag.unopened["cbet"]
    for cat in (HandCategory.STRONG_DRAW, HandCategory.WEAK_DRAW, HandCategory.MEDIUM):
        i = int(np.flatnonzero(cats == cat)[0])
        row = table[cat]
        k = 1.25 if cat in (HandCategory.STRONG_DRAW, HandCategory.WEAK_DRAW) else 1.0
        raw = {"check": row["check"], "bet_33": k * row["bet_33"], "bet_75": k * row["bet_75"]}
        z = sum(raw.values())
        got = {a.kind if a.kind == X else a.to: dist[a][i] for a in dist}
        assert got[X] == pytest.approx(raw["check"] / z)
        assert got[bet_to(s, 0.33).to] == pytest.approx(raw["bet_33"] / z)
        assert got[bet_to(s, 0.75).to] == pytest.approx(raw["bet_75"] / z)


def test_bigger_bet_folds_more():
    tag = load_profile("tag")
    w = tag.preflop.bb_call
    small = facing_bet(0.25)
    big = facing_bet(1.0)
    assert small.street_bets[0] < big.street_bets[0]
    f_small = float((fold_of(action_distribution(tag, small)) * w).sum())
    f_big = float((fold_of(action_distribution(tag, big)) * w).sum())
    assert f_big > f_small


def test_facing_scaling_formula():
    tag = load_profile("tag")
    s = facing_bet(1.0)  # BTN bets 10 into 10: f = 10 / 10 = 1
    dist = action_distribution(tag, s)
    cats = cats_for(DRY)
    i = int(np.flatnonzero(cats == HandCategory.MEDIUM)[0])
    row = tag.facing["facing_bet"][HandCategory.MEDIUM]
    c0 = row["call"] + row["raise"]
    c = c0 ** ((1 + 1.0) / 1.5)
    assert fold_of(dist)[i] == pytest.approx(1 - c)
    assert dist[Action(1, C, Street.FLOP, 10)][i] == pytest.approx(c * row["call"] / c0)
    assert dist[Action(1, R, Street.FLOP, 30)][i] == pytest.approx(c * row["raise"] / c0)


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_strong_rarely_folds(name):
    p = load_profile(name)
    s = facing_bet(1.0)
    cats = cats_for(DRY)
    strong = cats == HandCategory.STRONG
    assert strong.any()
    assert fold_of(action_distribution(p, s))[strong].max() <= 0.10


@pytest.mark.parametrize("name", PROFILE_NAMES)
@pytest.mark.parametrize("frac", [0.33, 0.75, 1.5])
def test_nuts_never_fold_any_size(name, frac):
    p = load_profile(name)
    s = facing_bet(frac)
    cats = cats_for(DRY)
    nuts = cats == HandCategory.NUTS
    assert nuts.any()
    assert np.all(fold_of(action_distribution(p, s))[nuts] == 0.0)


# Continue (call + raise) limits per category facing a 2.5x-pot bet (MDF 0.29): bluff
# catchers mostly fold, value keeps going.
BIG_BET_LIMITS = {
    HandCategory.WEAK: (0.0, 0.20),
    HandCategory.MEDIUM: (0.0, 0.55),
    HandCategory.STRONG: (0.80, 1.0),
    HandCategory.NUTS: (1.0, 1.0),
}


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_big_bet_continue_by_category(name):
    p = load_profile(name)
    s = facing_bet(2.5)  # BTN bets 25 into 10
    assert legal_actions(s).call == 25 and s.pot == 10
    cont = 1.0 - fold_of(action_distribution(p, s))
    cats = cats_for(DRY)
    for cat, (lo, hi) in BIG_BET_LIMITS.items():
        mask = cats == cat
        assert mask.any(), cat
        assert lo - 1e-12 <= cont[mask].min(), (cat, cont[mask].min())
        assert cont[mask].max() <= hi + 1e-12, (cat, cont[mask].max())


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_strong_never_folds_much_to_overjams(name):
    p = load_profile(name)
    s = act(flop(stacks=(205, 205)), X)  # pot 10, 200 behind each
    s = apply(s, allin(s))  # a 20x-pot jam
    assert legal_actions(s).call == 200 and s.pot == 10
    cats = cats_for(DRY)
    strong = cats == HandCategory.STRONG
    cont = 1.0 - fold_of(action_distribution(p, s))
    assert cont[strong].min() >= 0.70


OVERBET_BOARDS = ("Kh7d2c", "Ah8c5d", "Qs8s3d", "Ts9s4d", "Jh6h2s")  # dry, dry, two-tone x3
OVERBET_SIZES = (1.25, 1.5, 2.0, 2.5)


def _bb_checked_flop(p, board: str) -> tuple[HandState, np.ndarray]:
    """TAG BTN opens, ``p`` calls in the BB and checks the flop: the state and its range."""
    from poker_trainer.villain.narrowing import RangeTracker

    tracker = RangeTracker(p, 1)
    s = opened()
    call = Action(1, C, Street.PREFLOP, 5)
    tracker.observe(s, call)
    s = deal(apply(s, call), parse_cards(board))
    check = Action(1, X, Street.FLOP)
    tracker.observe(s, check)
    live = cats_for(board) >= 0
    return apply(s, check), np.asarray(tracker.current) * live


def _defence_ratio(p, s: HandState, frac: float, w: np.ndarray) -> float:
    """Whole-range continue / MDF facing a bet of ``frac`` pot."""
    t = apply(s, bet_to(s, frac))
    cont = 1.0 - fold_of(action_distribution(p, t))
    call = legal_actions(t).call
    prior = t.pot + sum(t.street_bets) - call
    return float(w @ cont) / float(w.sum()) * (prior + call) / prior


# A category policy defends a little more with a STRONG-heavy range (Tight's two-tone
# checking ranges) and a little less with an air-heavy one (K72): one board may sit up to
# BOARD_SLACK outside the band; the mean over the boards may not.
BOARD_SLACK = 0.10


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_overbet_defence_stays_in_band_at_every_size(name):
    """The BB's real check range defends near MDF at every overbet size, not only at the
    sizes the competence report probes (no dip at 1.5-2x pot that a bluff exploits): at each
    size the mean over five flops is inside the profile's band and no flop is more than
    BOARD_SLACK outside it. At 4x pot no flop under-defends by more than BOARD_SLACK; over-
    defence is allowed there: STRONG keeps a floor (test_strong_never_folds_much_to_overjams),
    so a STRONG-heavy range defends more."""
    p = load_profile(name)
    lo, hi = p.bands.defence_ratio
    spots = [_bb_checked_flop(p, board) for board in OVERBET_BOARDS]
    for frac in OVERBET_SIZES:
        ratios = [_defence_ratio(p, s, frac, w) for s, w in spots]
        assert lo <= float(np.mean(ratios)) <= hi, (frac, ratios)
        for board, ratio in zip(OVERBET_BOARDS, ratios, strict=True):
            assert lo - BOARD_SLACK <= ratio <= hi + BOARD_SLACK, (board, frac, ratio)
    for board, (s, w) in zip(OVERBET_BOARDS, spots, strict=True):
        ratio = _defence_ratio(p, s, 4.0, w)
        assert ratio >= lo - BOARD_SLACK, (board, 4.0, ratio)


def test_jam_into_small_pot_medium_can_fold():
    tag = load_profile("tag")
    s = act(flop(), X)
    assert s.pot == 10 and s.stacks == (195, 195)
    s = apply(s, allin(s))
    cats = cats_for(DRY)
    medium = cats == HandCategory.MEDIUM
    assert medium.any()
    dist = action_distribution(tag, s)
    assert fold_of(dist)[medium].max() > 0
    # No raise is possible facing the jam; raise mass went to call.
    assert {a.kind for a in dist} == {F, C}


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_low_spr_commits_medium(name):
    p = load_profile(name)
    s = flop(stacks=(10, 10))  # pot 10, 5 behind each: SPR 0.5
    s = act(s, X)
    s = apply(s, bet_to(s, 0.33))  # 3 >= 0.6 * 5 -> all-in for 5
    cats = cats_for(DRY)
    dist = action_distribution(p, s)
    fold = fold_of(dist)
    for cat in (HandCategory.MEDIUM, HandCategory.STRONG, HandCategory.NUTS):
        mask = cats == cat
        assert mask.any()
        assert np.all(fold[mask] == 0.0)
    # Weaker hands may still fold.
    assert fold[cats == HandCategory.AIR].min() > 0


def test_role_detection():
    s = flop()
    assert role(s) == "lead"
    s = act(s, X)
    assert role(s) == "cbet"
    s = act(s, X)
    s = deal(s, parse_cards("5s"))
    assert role(s) == "lead"
    s = act(s, X)
    assert role(s) == "stab"
    s = apply(s, bet_to(s, 0.5))
    assert role(s) == "facing_bet"
    s = apply(s, raise_to(s, RAISE_MULT))
    assert role(s) == "facing_raise"


def test_role_cbet_out_of_position():
    # BB 3-bets pre-flop, BTN calls: BB is the aggressor and first to act on the flop.
    s = opened()
    s = apply(s, raise_to(s, THREEBET_MULT))
    s = act(s, C)
    s = deal(s, parse_cards(DRY))
    assert s.to_act == 1
    assert role(s) == "cbet"
    s = act(s, X)
    assert role(s) == "stab"


def test_role_preflop_raises():
    with pytest.raises(ValueError):
        role(new_hand(0))


def test_sample_action_deterministic_and_legal():
    tag = load_profile("tag")
    s = facing_bet(0.75)
    hole = parse_cards("AsKs")
    for seed in range(20):
        a1 = sample_action(tag, s, hole, random.Random(seed))
        a2 = sample_action(tag, s, hole, random.Random(seed))
        assert a1 == a2
        apply(s, a1)
    s0 = new_hand(0)
    i = idx("3c2d")
    assert tag.preflop.open[i] == 0
    for seed in range(200):
        a = sample_action(tag, s0, parse_cards("3c2d"), random.Random(seed))
        assert a == Action(0, F, Street.PREFLOP)
        apply(s0, a)


def test_sample_action_blocked_hole_raises():
    tag = load_profile("tag")
    with pytest.raises(ValueError):
        sample_action(tag, flop(), parse_cards("KhAs"), random.Random(0))


def test_distribution_keys_are_legal():
    for name in PROFILE_NAMES:
        p = load_profile(name)
        for s in (new_hand(0), opened(), flop(), act(flop(), X), facing_bet(0.5)):
            for a in action_distribution(p, s):
                apply(s, a)
                assert a.seat == s.to_act


def _cbet_row(dist: dict[Action, np.ndarray], s: HandState, i: int) -> list[float]:
    """[check, bet_33, bet_75] probabilities of combo i in an unopened state."""
    check = next(a for a in dist if a.kind == X)
    return [dist[check][i], dist[bet_to(s, 0.33)][i], dist[bet_to(s, 0.75)][i]]


def river_cbet(board: str = DRY + "4s9c") -> HandState:
    """BTN bets the turn and is called; river, BB checks: BTN (seat 0) to act as c-bettor."""
    s = act(flop(board[:6]), X)
    s = act(s, X)
    s = deal(s, parse_cards(board[6:8]))
    s = act(s, X)
    s = apply(s, bet_to(s, 0.75))
    s = act(s, C)
    s = deal(s, parse_cards(board[8:]))
    return act(s, X)


def test_river_override_applies_on_river_only():
    from dataclasses import replace

    tag = load_profile("tag")
    override = {"cbet": {HandCategory.AIR: {"check": 0.0, "bet_33": 1.0, "bet_75": 0.0}}}
    p = replace(tag, river_unopened=override)
    shared = tag.unopened["cbet"]

    flop_s = act(flop(), X)  # BTN c-bets the flop
    assert role(flop_s) == "cbet"
    river_s = river_cbet()
    assert role(river_s) == "cbet" and river_s.street == Street.RIVER

    flop_air = int(np.flatnonzero(cats_for(DRY) == HandCategory.AIR)[0])
    row = shared[HandCategory.AIR]
    want = [row["check"], row["bet_33"], row["bet_75"]]
    assert _cbet_row(action_distribution(p, flop_s), flop_s, flop_air) == pytest.approx(want)

    river_cats = cats_for(DRY + "4s9c")
    river_dist = action_distribution(p, river_s)
    air = int(np.flatnonzero(river_cats == HandCategory.AIR)[0])
    assert _cbet_row(river_dist, river_s, air) == pytest.approx([0.0, 1.0, 0.0])
    # Categories without an override fall back to the shared table on the river.
    strong = int(np.flatnonzero(river_cats == HandCategory.STRONG)[0])
    row = shared[HandCategory.STRONG]
    want = [row["check"], row["bet_33"], row["bet_75"]]
    assert _cbet_row(river_dist, river_s, strong) == pytest.approx(want)


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_shipped_river_overrides_are_used(name):
    p = load_profile(name)
    assert p.river_unopened["cbet"][HandCategory.AIR] != p.unopened["cbet"][HandCategory.AIR]
    s = river_cbet()
    cats = cats_for(DRY + "4s9c")
    dist = action_distribution(p, s)
    for cat, row in p.river_unopened["cbet"].items():
        i = int(np.flatnonzero(cats == cat)[0])
        want = [row["check"], row["bet_33"], row["bet_75"]]
        assert _cbet_row(dist, s, i) == pytest.approx(want)


def river_facing_bet(board: str = DRY + "4s9c") -> HandState:
    """River after ``river_cbet``: BTN bets 75% pot, BB (seat 1) faces it."""
    s = river_cbet(board)
    return apply(s, bet_to(s, 0.75))


def _facing_row(dist: dict[Action, np.ndarray], i: int) -> list[float]:
    """[fold, call, raise] probabilities of combo i facing a bet."""
    by_kind = {k: 0.0 for k in (F, C, R)}
    for a, arr in dist.items():
        by_kind[a.kind] += float(arr[i])
    return [by_kind[F], by_kind[C], by_kind[R]]


def test_river_facing_override_applies_on_river_only():
    from dataclasses import replace

    tag = replace(load_profile("tag"), river_facing={})  # the shared tables only
    row = {"fold": 0.0, "call": 0.0, "raise": 1.0}
    p = replace(tag, river_facing={"facing_bet": {HandCategory.MEDIUM: row}})

    flop_s = facing_bet(1.0)
    flop_medium = int(np.flatnonzero(cats_for(DRY) == HandCategory.MEDIUM)[0])
    assert _facing_row(action_distribution(p, flop_s), flop_medium) == pytest.approx(
        _facing_row(action_distribution(tag, flop_s), flop_medium)
    )

    river_s = river_facing_bet()
    assert role(river_s) == "facing_bet" and river_s.street == Street.RIVER
    river_cats = cats_for(DRY + "4s9c")
    dist = action_distribution(p, river_s)
    medium = int(np.flatnonzero(river_cats == HandCategory.MEDIUM)[0])
    assert _facing_row(dist, medium) == pytest.approx([0.0, 0.0, 1.0])
    # Categories without an override use the shared table on the river.
    strong = int(np.flatnonzero(river_cats == HandCategory.STRONG)[0])
    assert _facing_row(dist, strong) == pytest.approx(
        _facing_row(action_distribution(tag, river_s), strong)
    )


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_river_bluff_catchers_never_raise(name):
    """On the river WEAK and MEDIUM hands call or fold a bet: a raise only folds out worse
    and gets called by better (the ``raise_dominated`` check)."""
    p = load_profile(name)
    s = river_facing_bet()
    cats = cats_for(DRY + "4s9c")
    raises = sum(arr for a, arr in action_distribution(p, s).items() if a.kind == R)
    for cat in (HandCategory.WEAK, HandCategory.MEDIUM):
        mask = cats == cat
        assert mask.any(), cat
        assert raises[mask].max() == 0.0, cat
