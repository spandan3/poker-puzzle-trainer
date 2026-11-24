"""Multiway post-flop: roles and SPR with 3-5 seats, the damping rule, and a 5-seat simulation."""

from __future__ import annotations

import random
from collections import defaultdict

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
    live_seats,
    needs_board,
    new_hand,
    total_pot,
)
from poker_trainer.puzzle.options import custom_action, hero_options
from poker_trainer.villain import strategy
from poker_trainer.villain.features import (
    HandCategory,
    categorize,
    load_thresholds,
    range_features,
    street_spr,
)
from poker_trainer.villain.narrowing import describe
from poker_trainer.villain.preflop5 import Damping, load_fivemax
from poker_trainer.villain.profiles import FACING_ACTIONS, PROFILE_NAMES, load_profile
from poker_trainer.villain.strategy import (
    UnsupportedSpot,
    action_distribution,
    bet_to,
    raise_to,
    role,
    sample_action,
)

N = 1326
DRY = "Kh7d2c"
WET = "Th9h4c"
F, X, C, B, R = (
    ActionKind.FOLD,
    ActionKind.CHECK,
    ActionKind.CALL,
    ActionKind.BET,
    ActionKind.RAISE,
)
D = load_fivemax().damping
H = HandCategory
BLUFF = (H.AIR, H.WEAK_DRAW, H.WEAK)
BELOW_STRONG = (H.AIR, H.WEAK_DRAW, H.WEAK, H.MEDIUM, H.STRONG_DRAW)
COMMITTED = (H.MEDIUM, H.STRONG_DRAW, H.STRONG, H.NUTS)
PROFILES = {name: load_profile(name) for name in PROFILE_NAMES}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def act(s: HandState, kind: ActionKind, to: int = 0) -> HandState:
    if kind == C:
        to = s.street_bets[s.to_act] + legal_actions(s).call
    return apply(s, Action(s.to_act, kind, s.street, to))


def cats_of(s: HandState) -> np.ndarray:
    return categorize(range_features(s.board), load_thresholds())


def five_flop(
    callers: tuple[int, ...] = (4, 0, 1, 2),
    board: str = DRY,
    stacks: tuple[int, ...] = (200,) * 5,
) -> HandState:
    """Five seats, button 0 (SB 1, BB 2, UTG 3, CO 4): UTG opens to 5, ``callers`` call, the rest
    fold; the flop is dealt."""
    s = new_hand(0, stacks)
    s = apply(s, raise_to(s, 2.5))
    while s.to_act is not None:
        s = act(s, C if s.to_act in callers else F)
    return deal(s, parse_cards(board))


def run_to(s: HandState, street: Street, cards: str = "5s9c") -> HandState:
    """Check every street down until ``street`` is dealt."""
    extra = list(parse_cards(cards))
    while s.street < street:
        while s.to_act is not None:
            s = act(s, X)
        s = deal(s, (extra.pop(0),))
    return s


def total(dist, kinds) -> np.ndarray:
    return sum((arr for a, arr in dist.items() if a.kind in kinds), np.zeros(N))


def damped(p, s: HandState, k: int):
    return strategy._postflop(p, s, legal_actions(s), k)


def assert_valid(s: HandState, dist) -> None:
    blocked = cats_of(s) < 0 if s.board else np.zeros(N, dtype=bool)
    tot = np.zeros(N)
    for a, arr in dist.items():
        assert arr.shape == (N,)
        assert np.all(arr >= 0.0) and np.all(arr <= 1.0 + 1e-12)
        assert np.all(arr[blocked] == 0.0)
        apply(s, a)  # every key is a legal action
        tot += arr
    np.testing.assert_allclose(tot[~blocked], 1.0, atol=1e-12)


def same(d1, d2) -> None:
    assert d1.keys() == d2.keys()
    for a in d1:
        np.testing.assert_array_equal(d1[a], d2[a])


# ---------------------------------------------------------------------------
# roles, SPR, describe
# ---------------------------------------------------------------------------


def test_roles_five_seats():
    s = five_flop()  # all five see the flop; UTG (3) was the pre-flop raiser
    assert s.to_act == 1
    assert role(s) == "lead"
    s = act(s, X)
    assert s.to_act == 2 and role(s) == "stab"
    s = act(s, X)
    assert s.to_act == 3 and role(s) == "cbet"
    s = act(s, X)
    assert s.to_act == 4 and role(s) == "stab"
    s = apply(s, bet_to(s, 0.5))
    assert s.to_act == 0 and role(s) == "facing_bet"
    s = apply(s, raise_to(s, 3.0))
    assert s.to_act == 1 and role(s) == "facing_raise"
    s = act(s, F)
    assert role(s) == "facing_raise"  # BB, checked earlier, now faces bet and raise


def test_roles_three_and_four_live_seats():
    s = five_flop(callers=(2,))  # UTG vs BB: heads-up from five seats
    assert live_seats(s) == (2, 3)
    assert role(s) == "lead"
    s = five_flop(callers=(4, 2))  # BB, UTG, CO
    assert s.to_act == 2 and role(s) == "lead"
    s = apply(s, bet_to(s, 0.33))  # BB leads
    assert role(s) == "facing_bet"  # UTG, the aggressor, faces it
    s = act(s, C)
    assert role(s) == "facing_bet"  # CO still faces one bet
    s = act(s, C)
    s = deal(s, parse_cards("5s"))
    assert role(s) == "cbet"  # BB bet the flop last
    s = act(s, X)
    assert role(s) == "stab"


def test_roles_three_seat_table():
    s = new_hand(0, (200, 200, 200))  # BTN 0 first to act three-handed
    s = apply(s, raise_to(s, 2.5))
    s = act(s, C)
    s = act(s, C)
    s = deal(s, parse_cards(DRY))
    assert s.to_act == 1 and role(s) == "lead"
    s = act(s, X)
    assert role(s) == "stab"
    s = act(s, X)
    assert s.to_act == 0 and role(s) == "cbet"
    s = apply(s, bet_to(s, 0.75))
    assert role(s) == "facing_bet"


def _old_spr(s: HandState) -> float:
    return min(s.stacks[i] + s.street_bets[i] for i in (0, 1)) / s.pot


def test_street_spr_heads_up_unchanged():
    """Seeded heads-up hands: every post-flop state gives the pre-M12 two-seat formula."""
    n = 0
    for i in range(60):
        rng = random.Random(f"hu-spr:{i}")
        stacks = (rng.randint(20, 400), rng.randint(20, 400))
        s = new_hand(rng.randrange(2), stacks)
        deck = list(range(52))
        rng.shuffle(deck)
        board = iter(deck[4:])
        p = PROFILES[rng.choice(PROFILE_NAMES)]
        while s.folded is None and not (s.street == Street.RIVER and s.to_act is None):
            if needs_board(s):
                s = deal(s, tuple(next(board) for _ in range(3 if s.street == 0 else 1)))
                continue
            if s.street != Street.PREFLOP:
                assert street_spr(s) == _old_spr(s)
                n += 1
            seat = s.to_act
            s = apply(s, sample_action(p, s, (deck[2 * seat], deck[2 * seat + 1]), rng))
    assert n > 100


def test_street_spr_uses_deepest_live_opponent():
    s = five_flop(stacks=(300, 100, 150, 400, 250))
    # Pot 25; behind: BTN 295, SB 95, BB 145, UTG 395, CO 245.
    assert s.pot == 25 and s.to_act == 1
    assert street_spr(s) == 95 / 25  # SB is the shortest: its own stack
    s = act(s, X)
    assert street_spr(s) == 145 / 25
    s = act(s, X)
    assert street_spr(s) == 295 / 25  # UTG (deepest) vs BTN, the deepest other seat
    # The deepest seat folds: the next deepest opponent counts.
    s = five_flop(callers=(4, 0, 2), stacks=(300, 100, 150, 400, 250))
    s = apply(s, bet_to(s, 0.5))  # BB bets
    s = act(s, F)  # UTG (the deepest) folds
    assert s.to_act == 4
    assert s.street_bets[2] > 0  # BB: 145 = its stack + its bet, below BTN's 295
    assert street_spr(s) == min(245, 295) / s.pot  # CO vs BTN


def test_street_spr_counts_all_in_opponent():
    s = five_flop(callers=(4, 0, 2), stacks=(300, 300, 60, 300, 250))  # pot 21
    s = apply(s, Action(2, B, Street.FLOP, 10))  # BB (55 behind) bets 10
    s = act(s, F)  # UTG folds
    s = apply(s, Action(4, R, Street.FLOP, 245))  # CO raises all-in to 245
    assert s.stacks[4] == 0 and 4 in live_seats(s)
    assert s.to_act == 0
    # BTN (295): opponents BB 55 and CO 245 all-in; the all-in CO is the deepest.
    assert street_spr(s) == 245 / 21


def test_describe_five_seat_actions():
    s = new_hand(0, (200,) * 5)
    assert describe(raise_to(s, 2.5), s) == "Pre-flop: opens to 5"
    s = apply(s, raise_to(s, 2.5))
    assert describe(Action(4, F, Street.PREFLOP), s) == "Pre-flop: folds"
    s = act(s, C)  # CO calls
    assert describe(raise_to(s, 4.0), s) == "Pre-flop: 3-bets to 20"
    s = five_flop()
    s = act(s, X)
    assert describe(Action(2, X, Street.FLOP), s) == "Flop: checks"
    a = bet_to(s, 0.5)
    assert describe(a, s) == f"Flop: bets {a.to} ({round(100 * a.to / s.pot)}% pot)"
    s = apply(s, a)
    assert describe(Action(3, R, Street.FLOP, 40), s) == "Flop: raises to 40"
    assert describe(Action(3, R, Street.FLOP, 195), s) == "Flop: goes all-in"
    assert describe(Action(3, C, Street.FLOP, a.to), s) == "Flop: calls"


# ---------------------------------------------------------------------------
# damping
# ---------------------------------------------------------------------------


def _unopened_states() -> list[tuple[str, HandState]]:
    out = []
    for board in (DRY, WET):
        s = five_flop(board=board)
        out.append((f"{board}:lead", s))
        out.append((f"{board}:stab", act(s, X)))
        out.append((f"{board}:cbet", act(act(s, X), X)))
    s = run_to(five_flop(), Street.RIVER)
    out.append(("river:lead", s))
    out.append(("river:stab", act(act(s, X), X)))
    return out


def _facing_states() -> list[tuple[str, HandState]]:
    out = []
    for board in (DRY, WET):
        for frac in (0.33, 0.75):
            s = five_flop(board=board)
            out.append((f"{board}:bet{frac}", apply(s, bet_to(s, frac))))
        s = five_flop(board=board)
        s = apply(s, bet_to(s, 0.5))
        out.append((f"{board}:raise", apply(s, raise_to(s, 3.0))))
    s = five_flop()
    out.append(("overbet", apply(s, Action(1, B, Street.FLOP, 60))))  # 2.4x pot
    s = run_to(five_flop(), Street.RIVER)
    out.append(("river:bet", apply(s, bet_to(s, 0.75))))
    return out


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_unopened_damping_monotonic(name):
    p = PROFILES[name]
    for label, s in _unopened_states():
        cats = cats_of(s)
        dists = [damped(p, s, k) for k in range(4)]
        bets = [total(d, (B,)) for d in dists]
        for k, d in enumerate(dists):
            assert_valid(s, d)
            for cat, factor in [(c, D.bluff) for c in BLUFF] + [(H.MEDIUM, D.thin)]:
                mask = cats == cat
                np.testing.assert_allclose(
                    bets[k][mask], bets[0][mask] * factor**k, rtol=1e-12, err_msg=label
                )
            if k:
                for cat in (*BLUFF, H.MEDIUM):
                    mask = (cats == cat) & (bets[0] > 0)
                    assert np.all(bets[k][mask] < bets[k - 1][mask]), (label, cat, k)
            for cat in (H.STRONG_DRAW, H.STRONG, H.NUTS):
                mask = cats == cat
                for a in d:
                    np.testing.assert_array_equal(d[a][mask], dists[0][a][mask])
        assert any(np.any(bets[0][cats == c] > 0) for c in BLUFF), label


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_facing_damping_monotonic(name):
    p = PROFILES[name]
    for label, s in _facing_states():
        cats = cats_of(s)
        assert street_spr(s) > 1.0
        dists = [damped(p, s, k) for k in range(4)]
        conts = [total(d, (C, R)) for d in dists]
        raises = [total(d, (R,)) for d in dists]
        calls = [total(d, (C,)) for d in dists]
        for k, d in enumerate(dists):
            assert_valid(s, d)
            c, b = D.call**k, D.bluff**k
            for cat in BLUFF:
                m = cats == cat
                expect = (calls[0][m] + raises[0][m] * b) * c
                np.testing.assert_allclose(conts[k][m], expect, rtol=1e-12, err_msg=label)
                np.testing.assert_allclose(raises[k][m], raises[0][m] * b * c, rtol=1e-12)
            for cat in (H.MEDIUM, H.STRONG_DRAW):
                m = cats == cat
                np.testing.assert_allclose(conts[k][m], conts[0][m] * c, rtol=1e-12)
            if k:
                assert np.all(raises[k][cats == H.MEDIUM] == 0.0)
                np.testing.assert_allclose(
                    raises[k][cats == H.STRONG_DRAW], raises[0][cats == H.STRONG_DRAW] * c
                )
                for cat in BELOW_STRONG:
                    m = (cats == cat) & (conts[0] > 0)
                    assert np.all(conts[k][m] < conts[k - 1][m]), (label, cat, k)
            for cat in (H.STRONG, H.NUTS):
                m = cats == cat
                for a in d:
                    np.testing.assert_array_equal(d[a][m], dists[0][a][m])


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_facing_jam_no_raise_damping(name):
    """Facing an all-in (no raise legal): continuing still falls with k, STRONG/NUTS unchanged."""
    p = PROFILES[name]
    s = five_flop()
    s = apply(s, Action(1, B, Street.FLOP, 195))  # SB jams 195 into 25
    assert legal_actions(s).aggressive is None
    cats = cats_of(s)
    dists = [damped(p, s, k) for k in range(4)]
    for k, d in enumerate(dists):
        assert_valid(s, d)
        assert {a.kind for a in d} == {F, C}
        for cat in BELOW_STRONG:
            m = cats == cat
            assert np.all(total(d, (C,))[m] <= total(dists[0], (C,))[m] + 1e-15)
        for cat in (H.STRONG, H.NUTS):
            m = cats == cat
            for a in d:
                np.testing.assert_array_equal(d[a][m], dists[0][a][m])
    # Pin the order: the bluff-raise and call damping apply BEFORE "no raise legal -> raise
    # moves to call", so a bluff category calls (call0 + raise0 * bluff^k) * call^k.
    assert street_spr(s) > 1.0
    m0 = strategy._matrix(p.facing[strategy.role(s)], FACING_ACTIONS)
    lg = legal_actions(s)
    cont = strategy._continue(m0[:, 1] + m0[:, 2], lg.call / (total_pot(s) - lg.call))
    base = m0[:, 1] + m0[:, 2]
    share = np.divide(cont, base, out=np.zeros_like(base), where=base > 0)
    call0, raise0 = m0[:, 1] * share, m0[:, 2] * share
    for k in (1, 2, 3):
        for cat in BLUFF:
            m = cats == cat
            expected = (call0[int(cat)] + raise0[int(cat)] * D.bluff**k) * D.call**k
            assert raise0[int(cat)] > 0, cat  # the order matters only if there is a raise to move
            np.testing.assert_allclose(total(dists[k], (C,))[m], expected, rtol=1e-12, atol=0)


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_low_spr_committed_rows_not_damped(name):
    p = PROFILES[name]
    seen: set[HandCategory] = set()
    for board in (DRY, WET, "9h8h8c"):
        s = five_flop(board=board, stacks=(30,) * 5)  # pot 25, 25 behind each: SPR 1
        s = apply(s, bet_to(s, 0.33))  # 8 into 25, not all-in
        assert street_spr(s) <= 1.0
        cats = cats_of(s)
        dists = [damped(p, s, k) for k in range(4)]
        conts = [total(d, (C, R)) for d in dists]
        for k, d in enumerate(dists):
            assert_valid(s, d)
            for cat in COMMITTED:
                m = cats == cat
                seen |= {cat} if m.any() else set()
                assert np.all(total(d, (F,))[m] == 0.0)
                for a in d:
                    np.testing.assert_array_equal(d[a][m], dists[0][a][m])
            if k:
                for cat in BLUFF:
                    m = (cats == cat) & (conts[0] > 0)
                    assert np.all(conts[k][m] < conts[k - 1][m])
    assert seen == set(COMMITTED)


def test_k_counts_live_opponents_including_all_in():
    p = PROFILES["tag"]
    for callers, k in (((4, 0, 1, 2), 3), ((4, 0, 2), 2), ((4, 2), 1), ((2,), 0)):
        s = five_flop(callers=callers)
        assert strategy._extra_opponents(s) == k
        same(action_distribution(p, s), damped(p, s, k))
    # CO all-in pre-flop still counts.
    s = five_flop(callers=(4, 0, 2), stacks=(200, 200, 200, 200, 5))
    assert s.stacks[4] == 0
    assert strategy._extra_opponents(s) == 2
    same(action_distribution(p, s), damped(p, s, 2))


def _as_kinds(dist) -> dict[tuple[ActionKind, int], np.ndarray]:
    out = {(a.kind, a.to): arr for a, arr in dist.items()}
    assert len(out) == len(dist)
    return out


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_k0_never_touches_the_tables(name, monkeypatch):
    """Heads-up and a five-seat hand down to two live seats never read the damping constants,
    and the five-seat state acts exactly like the matching heads-up state."""

    def boom() -> Damping:
        raise AssertionError("damping read at k = 0")

    monkeypatch.setattr(strategy, "_damping", boom)
    p = PROFILES[name]
    five = five_flop(callers=(2,), stacks=(200, 200, 180, 240, 200))  # BB (2) vs UTG (3)
    # The same spot dealt heads-up: BB is seat 0, UTG seat 1 (the button, pre-flop raiser).
    hu = HandState(
        button=1,
        stacks=(five.stacks[2], five.stacks[3]),
        street_bets=(0, 0),
        pot=five.pot,
        street=Street.FLOP,
        board=five.board,
        to_act=0,
        history=(Action(1, R, Street.PREFLOP, 5), Action(0, C, Street.PREFLOP, 5)),
        last_raise=2,
        folded=None,
        total_chips=five.pot + five.stacks[2] + five.stacks[3],
    )
    seat = {2: 0, 3: 1}
    for _ in range(3):  # lead, facing a bet, facing a raise
        assert role(five) == role(hu)
        assert street_spr(five) == street_spr(hu)
        d5, d2 = action_distribution(p, five), action_distribution(p, hu)
        same(d5, damped(p, five, 0))
        k5, k2 = _as_kinds(d5), _as_kinds(d2)
        assert k5.keys() == k2.keys()
        for key in k5:
            np.testing.assert_array_equal(k5[key], k2[key])
        kind, to = max(k5, key=lambda kt: kt[1])  # the biggest bet or raise
        five = apply(five, Action(five.to_act, kind, Street.FLOP, to))
        hu = apply(hu, Action(seat[five.history[-1].seat], kind, Street.FLOP, to))
        if kind not in (B, R):
            break


def test_damping_constants_from_fivemax():
    assert D == Damping(bluff=0.5, thin=0.6, call=0.8)
    assert strategy._damping() is D


def test_damping_parameter_overrides_the_live_constants():
    p = PROFILES["lag"]
    custom = Damping(bluff=0.1, thin=0.2, call=0.3)
    assert custom != D
    for _, s in _unopened_states() + _facing_states():
        live = action_distribution(p, s)
        same(live, action_distribution(p, s, damping=None))
        same(live, action_distribution(p, s, damping=D))
        if strategy._extra_opponents(s) == 0:  # heads-up: constants are never read
            same(live, action_distribution(p, s, damping=custom))
            continue
        d = action_distribution(p, s, damping=custom)
        facing = role(s).startswith("facing")
        kinds = (C, R) if facing else (B,)
        assert np.all(total(d, kinds) <= total(live, kinds) + 1e-15)
        assert np.any(total(d, kinds) < total(live, kinds) - 1e-6)
        assert_valid(s, d)
    # sample_action threads it too: with ~zero call damping an AIR hand always folds.
    s = apply(five_flop(), bet_to(five_flop(), 0.33))
    cats = cats_of(s)
    hole = next(
        (a, b) for a in range(52) for b in range(a + 1, 52) if cats[combo_index(a, b)] == H.AIR
    )
    tiny = Damping(bluff=1e-9, thin=1e-9, call=1e-9)
    rng = random.Random(1)
    assert all(sample_action(p, s, hole, rng, damping=tiny).kind == F for _ in range(20))


def test_unit_damping_is_identity(monkeypatch):
    monkeypatch.setattr(strategy, "_damping", lambda: Damping(bluff=1.0, thin=1.0, call=1.0))
    p = PROFILES["lag"]
    for _, s in _unopened_states() + _facing_states():
        undamped = damped(p, s, 0)
        d = damped(p, s, 3)
        for a in undamped:
            if a.kind == R:  # MEDIUM's raise still moves to call when k > 0
                medium = cats_of(s) == H.MEDIUM
                assert np.all(d[a][medium] == 0.0)
                np.testing.assert_allclose(d[a][~medium], undamped[a][~medium], atol=1e-15)
            elif a.kind != C:
                np.testing.assert_allclose(d[a], undamped[a], atol=1e-15)
        np.testing.assert_allclose(total(d, (C, R)), total(undamped, (C, R)), atol=1e-15)


# ---------------------------------------------------------------------------
# simulation
# ---------------------------------------------------------------------------


def _random_stacks(rng: random.Random) -> tuple[int, ...]:
    def one() -> int:
        x = rng.random()
        if x < 0.1:
            return rng.randint(10, 60)
        if x < 0.9:
            return rng.randint(80, 300)
        return rng.randint(300, 600)

    return tuple(one() for _ in range(5))


def _hero_action(s: HandState, rng: random.Random) -> Action:
    lg = legal_actions(s)
    if s.street != Street.PREFLOP and lg.aggressive is not None and rng.random() < 0.15:
        return custom_action(s, rng.randint(lg.min_to, lg.max_to))
    return rng.choice(hero_options(s)).action


def _forced_multiway_start(rng: random.Random) -> HandState:
    """UTG opens; two to four of the other seats call (short stacks call all-in), the rest fold."""
    s = new_hand(rng.randrange(5), _random_stacks(rng))
    s = apply(s, raise_to(s, 2.5))
    others = [(s.button + j) % 5 for j in (4, 0, 1, 2)]  # CO, BTN, SB, BB
    callers = set(rng.sample(others, rng.randint(2, 4)))
    while s.street == Street.PREFLOP and s.to_act is not None:
        s = act(s, C if s.to_act in callers else F)
    return s


def _play(i: int, hero: bool, forced: bool, stats) -> bool:
    """One seeded five-seat hand to the end; returns whether the flop was multiway.

    ``stats[(facing, k)]`` collects, per post-flop bot decision, the mean over unblocked combos of
    the bet mass (unopened) or continue mass (facing) with damping and at k = 0.
    """
    rng = random.Random(f"multiway-sim:{hero}:{forced}:{i}")
    profiles = {seat: PROFILES[rng.choice(PROFILE_NAMES)] for seat in range(5)}
    s = _forced_multiway_start(rng) if forced else new_hand(rng.randrange(5), _random_stacks(rng))
    deck = list(range(52))
    rng.shuffle(deck)
    board = iter(deck[10:])
    multiway = False
    while s.folded is None and not (s.street == Street.RIVER and s.to_act is None):
        if needs_board(s):
            s = deal(s, tuple(next(board) for _ in range(3 if s.street == 0 else 1)))
            if s.street == Street.FLOP:
                multiway = len(live_seats(s)) >= 3
            continue
        seat = s.to_act
        if hero and seat == 0:
            a = _hero_action(s, rng)
        else:
            hole = (deck[2 * seat], deck[2 * seat + 1])
            d = action_distribution(profiles[seat], s)
            assert_valid(s, d)
            a = sample_action(profiles[seat], s, hole, rng)
            if s.street != Street.PREFLOP:
                k = strategy._extra_opponents(s)
                facing = role(s).startswith("facing")
                kinds = (C, R) if facing else (B,)
                live = cats_of(s) >= 0
                d0 = damped(profiles[seat], s, 0) if k else d
                stats[(facing, k)].append(
                    (total(d, kinds)[live].mean(), total(d0, kinds)[live].mean())
                )
        s = apply(s, a)
    assert sum(s.stacks) + s.pot + sum(s.street_bets) == s.total_chips
    return multiway


@pytest.mark.parametrize(
    "forced",
    [False, pytest.param(True, marks=pytest.mark.slow)],
    ids=["natural", "multiway"],
)
@pytest.mark.parametrize("hero", [False, True], ids=["bots", "hero"])
def test_simulated_five_seat_hands(hero, forced):
    """Seeded five-seat hands to the end: no UnsupportedSpot, every distribution valid.

    200 ``natural`` hands start pre-flop (``preflop5``); 50 ``multiway`` hands force two to four
    callers of the UTG open so that k = 1, 2 and 3 are all played post-flop. Run with ``-s`` to
    see the share of multiway flops and the bet / continue mass by k.
    """
    stats: dict[tuple[bool, int], list[tuple[float, float]]] = defaultdict(list)
    try:
        flops = [_play(i, hero, forced, stats) for i in range(50 if forced else 200)]
    except UnsupportedSpot as e:  # pragma: no cover - the failure message is the point
        pytest.fail(f"UnsupportedSpot: {e}")
    assert any(flops)
    assert {k for _, k in stats} >= ({0, 1, 2, 3} if forced else {0, 1})
    lines = [f"multiway flops: {sum(flops)}/{len(flops)}"]
    for (facing, k), rows in sorted(stats.items()):
        damped_mean, undamped_mean = np.mean(rows, axis=0)
        what = "continue" if facing else "bet"
        lines.append(
            f"{'facing' if facing else 'unopened'} k={k}: {what} {damped_mean:.3f}"
            f" (undamped {undamped_mean:.3f}, n={len(rows)})"
        )
        if k:
            assert damped_mean < undamped_mean
    print("\n" + "\n".join(lines))
