"""5-max pre-flop policy: hand ranking, buckets, every spot by number of raises, and simulation."""

from __future__ import annotations

import json
import random
from dataclasses import replace
from importlib.resources import files
from itertools import pairwise

import numpy as np
import pytest

from poker_trainer.analysis.hand_ranking import ranking, render
from poker_trainer.engine.combos import HAND_CLASSES, combo_index, combos_of_class
from poker_trainer.game.state import (
    Action,
    ActionKind,
    HandState,
    Street,
    apply,
    legal_actions,
    new_hand,
    position_name,
)
from poker_trainer.puzzle.options import hero_options
from poker_trainer.villain import preflop5
from poker_trainer.villain.preflop5 import bucket, load_fivemax, load_ranking
from poker_trainer.villain.profiles import PROFILE_NAMES, load_profile
from poker_trainer.villain.strategy import (
    UnsupportedSpot,
    action_distribution,
    allin,
    raise_to,
    sample_action,
)

N = 1326
FM = load_fivemax()
FOLD, CALL, RAISE = ActionKind.FOLD, ActionKind.CALL, ActionKind.RAISE
ORDER = ("UTG", "CO", "BTN", "SB", "BB")  # pre-flop order to act, 5 seats


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def fold(s: HandState) -> HandState:
    return apply(s, Action(s.to_act, FOLD, Street.PREFLOP))


def call(s: HandState) -> HandState:
    lg = legal_actions(s)
    return apply(s, Action(s.to_act, CALL, Street.PREFLOP, s.street_bets[s.to_act] + lg.call))


def fold_to(s: HandState, pos: str) -> HandState:
    while position_name(s, s.to_act) != pos:
        s = fold(s)
    return s


def by_kind(dist) -> dict[ActionKind, tuple[Action, np.ndarray]]:
    out = {}
    for a, arr in dist.items():
        assert a.kind not in out, f"two keys of kind {a.kind}"
        out[a.kind] = (a, arr)
    return out


def assert_valid(s: HandState, dist) -> None:
    total = np.zeros(N)
    for a, arr in dist.items():
        assert arr.shape == (N,)
        assert np.all(arr >= 0.0) and np.all(arr <= 1.0 + 1e-12)
        apply(s, a)  # every key is a legal action
        total += arr
    np.testing.assert_allclose(total, 1.0, atol=1e-12)


def mass(arr: np.ndarray) -> float:
    return float(arr.sum()) / N * 100.0


def dist5(name: str, s: HandState):
    d = action_distribution(load_profile(name), s)
    assert_valid(s, d)
    return d


# ---------------------------------------------------------------------------
# hand ranking file
# ---------------------------------------------------------------------------


def test_ranking_file_shape():
    raw_bytes = files("poker_trainer.villain").joinpath("hand_ranking.json").read_bytes()
    assert b"\r" not in raw_bytes
    raw = json.loads(raw_bytes)
    assert set(raw) == {"version", "classes"}
    assert raw["version"] == 1
    classes = raw["classes"]
    assert len(classes) == 169 and len(set(classes)) == 169
    assert set(classes) == set(HAND_CLASSES)
    assert raw_bytes.decode("utf-8") == render(classes)  # canonical text: what the script writes
    assert classes[:4] == ["AA", "KK", "QQ", "JJ"] and classes[-1] == "32o"
    # Sanity of the order: pairs above their unpaired relatives, suited above offsuit.
    pos = {c: i for i, c in enumerate(classes)}
    assert pos["AKs"] < pos["AKo"] and pos["T9s"] < pos["T9o"] and pos["22"] < pos["32s"]
    assert load_ranking() == (1, tuple(classes))


@pytest.mark.slow
def test_ranking_regenerates_byte_identically():
    path = files("poker_trainer.villain").joinpath("hand_ranking.json")
    assert render(ranking()).encode("utf-8") == path.read_bytes()


def test_fivemax_file():
    raw = json.loads(files("poker_trainer.villain").joinpath("fivemax.json").read_text("utf-8"))
    assert raw["version"] == 1 and FM.version == 1
    assert FM.bb_call_mult == 1.6
    assert (FM.damping.bluff, FM.damping.thin, FM.damping.call) == (0.5, 0.6, 0.8)
    assert set(FM.profiles) == set(PROFILE_NAMES)
    assert FM.profiles["tag"].open == {"UTG": 14, "CO": 24, "BTN": 40, "SB": 34}
    bad = json.loads(json.dumps(raw))
    bad["profiles"]["tag"]["vs_open"]["threebet"] = 95
    with pytest.raises(ValueError):
        preflop5.fivemax_from_dict(bad)


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.pop("damping"),
        lambda d: d.update(extra=1),
        lambda d: d.update(version="1"),
        lambda d: d.update(version=0),
        lambda d: d.update(bb_call_mult=True),
        lambda d: d["damping"].update(bluff="0.5"),
        lambda d: d["damping"].update(extra=0.5),
        lambda d: d["profiles"].update(maniac=d["profiles"]["tag"]),
        lambda d: d["profiles"]["tag"].pop("vs_jam"),
        lambda d: d["profiles"]["tag"]["vs_jam"].update(fold=1),
        lambda d: d["profiles"]["tag"]["open"].pop("SB"),
        lambda d: d["profiles"]["tag"].update(vs_open=[4, 7]),
    ],
)
def test_fivemax_validation_is_strict(change):
    raw = json.loads(files("poker_trainer.villain").joinpath("fivemax.json").read_text("utf-8"))
    change(raw)
    with pytest.raises(ValueError):
        preflop5.fivemax_from_dict(raw)


def test_a_seat_snapshot_is_the_live_block():
    for name in PROFILE_NAMES:
        snap = preflop5.seat_snapshot(name)
        fm = preflop5.fivemax_from_snapshot(name, json.loads(json.dumps(snap)))
        assert (fm.version, fm.bb_call_mult, fm.damping) == (
            FM.version,
            FM.bb_call_mult,
            FM.damping,
        )
        assert dict(fm.profiles) == {name: FM.profiles[name]}
    with pytest.raises(ValueError):
        preflop5.seat_snapshot("maniac")
    with pytest.raises(ValueError):
        preflop5.fivemax_from_snapshot("tag", {**preflop5.seat_snapshot("tag"), "profiles": {}})


# ---------------------------------------------------------------------------
# buckets
# ---------------------------------------------------------------------------


def _rank_order() -> np.ndarray:
    return np.concatenate([combos_of_class(c) for c in load_ranking()[1]])


@pytest.mark.parametrize("pct", [0.0, 0.5, 2.5, 4, 11, 14, 33.3, 52, 99.9, 100])
def test_bucket_mass_is_exact(pct):
    np.testing.assert_allclose(bucket(0.0, pct).sum(), pct / 100 * N, atol=1e-9)


def test_buckets_nested_partitioned_and_in_ranking_order():
    order = _rank_order()
    cuts = [0.0, 3.0, 7.7, 14.0, 24.0, 40.0, 100.0]
    for a, b in pairwise(cuts):
        np.testing.assert_allclose(bucket(0, a) + bucket(a, b), bucket(0, b), atol=1e-12)
        assert np.all(bucket(0, a) <= bucket(0, b))
    for pct in cuts:
        w = bucket(0, pct)[order]
        assert np.all(np.diff(w) <= 1e-12), "weights must not increase down the ranking"
    # A straddling class is fractional; all its combos share the weight.
    w = bucket(0, 1.0)  # 13.26 combos: AA (6), KK (6), 1.26 of QQ's 6
    qq = list(combos_of_class("QQ"))
    np.testing.assert_allclose(w[qq], 1.26 / 6)
    assert w[combo_index(51, 50)] == 1.0  # AA
    assert w[list(combos_of_class("JJ"))].sum() == 0.0
    assert not bucket(0, 5).flags.writeable


# ---------------------------------------------------------------------------
# r == 0: opens
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", PROFILE_NAMES)
@pytest.mark.parametrize("button", range(5))
@pytest.mark.parametrize("pos", ["UTG", "CO", "BTN", "SB"])
def test_open_every_profile_and_position(name, button, pos):
    s = fold_to(new_hand(button, (200,) * 5), pos)
    d = by_kind(dist5(name, s))
    assert set(d) == {FOLD, RAISE}
    a, opened = d[RAISE]
    assert a.to == (6 if pos == "SB" else 5)  # 3 bb from the SB, else 2.5 bb
    np.testing.assert_allclose(mass(opened), FM.profiles[name].open[pos], atol=1e-9)
    np.testing.assert_allclose(opened, bucket(0, FM.profiles[name].open[pos]))


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_opens_widen_utg_co_btn(name):
    s0 = new_hand(0, (200,) * 5)
    opened = {pos: by_kind(dist5(name, fold_to(s0, pos)))[RAISE][1] for pos in ("UTG", "CO", "BTN")}
    assert mass(opened["UTG"]) < mass(opened["CO"]) < mass(opened["BTN"])
    assert np.all(opened["UTG"] <= opened["CO"]) and np.all(opened["CO"] <= opened["BTN"])


def test_open_all_in_when_short():
    # UTG (seat 3) has 8 chips: 2.5 bb = 5 >= 0.6 x 8, so the open is all-in.
    s = new_hand(0, (200, 200, 200, 8, 200))
    d = by_kind(dist5("tag", s))
    assert d[RAISE][0].to == 8 == legal_actions(s).max_to
    s = apply(s, d[RAISE][0])
    # Everyone after faces a jam: fold or call only, even while a raise is legal (CO).
    assert legal_actions(s).aggressive == RAISE
    while s.to_act is not None:
        d = by_kind(dist5("lag", s))
        assert set(d) == {FOLD, CALL}
        np.testing.assert_allclose(mass(d[CALL][1]), FM.profiles["lag"].call_vs_jam)
        s = fold(s)


def test_limp_unsupported():
    s = new_hand(0, (200,) * 5)
    s = call(s)  # UTG limps
    with pytest.raises(UnsupportedSpot):
        action_distribution(load_profile("tag"), s)
    with pytest.raises(UnsupportedSpot):
        hero_options(s)


# ---------------------------------------------------------------------------
# r == 1: facing an open
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", PROFILE_NAMES)
@pytest.mark.parametrize("opener", ["UTG", "CO", "BTN", "SB"])
def test_vs_open_every_profile_and_position(name, opener):
    p = FM.profiles[name]
    s = fold_to(new_hand(1, (200,) * 5), opener)
    s = apply(s, by_kind(dist5(name, s))[RAISE][0])
    open_to = max(s.street_bets)
    while s.to_act is not None:
        pos = position_name(s, s.to_act)
        if pos == opener:
            break
        d = by_kind(dist5(name, s))
        assert set(d) == {FOLD, CALL, RAISE}
        assert d[CALL][0].to == open_to
        assert d[RAISE][0].to == 3 * open_to
        call_pct = min(p.call * FM.bb_call_mult, 100 - p.threebet) if pos == "BB" else p.call
        np.testing.assert_allclose(mass(d[RAISE][1]), p.threebet, atol=1e-9)
        np.testing.assert_allclose(mass(d[CALL][1]), call_pct, atol=1e-9)
        np.testing.assert_allclose(d[RAISE][1], bucket(0, p.threebet))
        np.testing.assert_allclose(d[CALL][1], bucket(p.threebet, p.threebet + call_pct))
        assert np.all(d[RAISE][1] + d[CALL][1] <= 1 + 1e-12)
        s = fold(s)


def test_bb_call_multiplier_and_cap():
    s = fold_to(new_hand(0, (200,) * 5), "SB")
    s = apply(s, raise_to(s, 3.0))
    assert position_name(s, s.to_act) == "BB"
    p = FM.profiles["sticky"]
    d = by_kind(preflop5.distribution(FM, p, s))
    np.testing.assert_allclose(mass(d[CALL][1]), p.call * 1.6)  # 28.8%
    big = replace(FM, bb_call_mult=10.0)
    d = by_kind(preflop5.distribution(big, p, s))
    np.testing.assert_allclose(mass(d[CALL][1]), 100 - p.threebet)  # capped
    np.testing.assert_allclose(d[FOLD][1], 0.0, atol=1e-12)


@pytest.mark.parametrize("callers,expected", [(0, 15), (1, 20), (2, 25)])
def test_squeeze_size(callers, expected):
    s = new_hand(0, (200,) * 5)  # UTG = 3, CO = 4, BTN = 0, SB = 1, BB = 2
    s = apply(s, raise_to(s, 2.5))  # UTG opens to 5
    for _ in range(callers):
        s = call(s)
    d = by_kind(dist5("tag", s))
    assert d[RAISE][0].to == expected
    assert preflop5.callers_after_open(s) == callers


def test_squeeze_capped_to_all_in():
    s = new_hand(0, (200, 200, 200, 200, 24))  # CO has 24 chips
    s = apply(s, raise_to(s, 2.5))
    d = by_kind(dist5("tag", s))
    assert d[RAISE][0].to == 24  # 15 >= 0.6 x 24: the 3-bet is all-in


# ---------------------------------------------------------------------------
# r == 2: facing a 3-bet
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_vs_threebet_every_seat(name):
    p = FM.profiles[name]
    s = new_hand(2, (200,) * 5)  # UTG = 0, CO = 1, BTN = 2, SB = 3, BB = 4
    s = apply(s, raise_to(s, 2.5))  # UTG opens
    s = call(s)  # CO calls
    s = apply(s, by_kind(dist5(name, s))[RAISE][0])  # BTN squeezes to 20
    seen = []
    while s.to_act is not None:
        seen.append(position_name(s, s.to_act))
        d = by_kind(dist5(name, s))
        assert set(d) == {FOLD, CALL, RAISE}
        assert d[RAISE][0] == allin(s)
        assert d[CALL][0].to == 20
        np.testing.assert_allclose(mass(d[RAISE][1]), p.jam_vs_threebet, atol=1e-9)
        np.testing.assert_allclose(mass(d[CALL][1]), p.call_vs_threebet, atol=1e-9)
        np.testing.assert_allclose(
            d[CALL][1], bucket(p.jam_vs_threebet, p.jam_vs_threebet + p.call_vs_threebet)
        )
        s = fold(s) if len(seen) < 4 else call(s)
    assert seen == ["SB", "BB", "UTG", "CO"]  # cold seats, the opener and the caller


# ---------------------------------------------------------------------------
# facing a jam
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_vs_jam_after_threebet(name):
    s = new_hand(0, (200,) * 5)
    s = apply(s, raise_to(s, 2.5))  # UTG
    s = apply(s, raise_to(s, 3.0))  # CO 3-bets
    s = fold(fold(fold(s)))  # BTN, SB, BB
    s = apply(s, allin(s))  # UTG jams
    assert position_name(s, s.to_act) == "CO"
    d = by_kind(dist5(name, s))
    assert set(d) == {FOLD, CALL}
    assert d[CALL][0].to == 200
    np.testing.assert_allclose(d[CALL][1], bucket(0, FM.profiles[name].call_vs_jam))


def test_jam_with_deeper_player_behind_is_fold_or_call():
    # UTG (100) jams; CO and BTN have 300, so CO could technically raise.
    s = new_hand(0, (300, 300, 300, 100, 300))
    s = apply(s, allin(s))
    assert s.stacks[3] == 0
    lg = legal_actions(s)
    assert lg.aggressive == RAISE  # legal for the engine...
    for name in PROFILE_NAMES:
        assert set(by_kind(dist5(name, s))) == {FOLD, CALL}  # ...but not in the tree
    assert [o.label for o in hero_options(s)] == ["fold", "call"]
    s = call(s)  # CO calls; BTN, deeper, still faces the jam
    assert set(by_kind(dist5("lag", s))) == {FOLD, CALL}


def test_capped_jam_leaves_chips_behind_is_still_a_jam():
    # UTG has 600 and the deepest other 300: UTG's 4-bet "jam" is capped at 300, chips behind.
    s = new_hand(0, (300, 300, 300, 600, 300))
    s = apply(s, raise_to(s, 2.5))  # UTG
    s = apply(s, raise_to(s, 3.0))  # CO
    s = fold(fold(fold(s)))
    s = apply(s, allin(s))
    assert s.stacks[3] == 300
    assert set(by_kind(dist5("tag", s))) == {FOLD, CALL}


def test_three_raises_is_a_jam_even_with_raises_legal():
    # A non-all-in 4-bet (not in the tree, built by hand) still leaves fold or call: r >= 3.
    s = new_hand(0, (600,) * 5)
    s = apply(s, raise_to(s, 2.5))  # UTG 5
    s = apply(s, raise_to(s, 3.0))  # CO 15
    s = apply(s, Action(0, RAISE, Street.PREFLOP, 45))  # BTN 45
    assert legal_actions(s).aggressive == RAISE
    assert set(by_kind(dist5("tag", s))) == {FOLD, CALL}
    assert [o.label for o in hero_options(s)] == ["fold", "call"]


# ---------------------------------------------------------------------------
# routing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [3, 4, 6])
def test_other_table_sizes_unsupported(n):
    s = new_hand(0, (200,) * n)
    with pytest.raises(UnsupportedSpot):
        action_distribution(load_profile("tag"), s)
    with pytest.raises(UnsupportedSpot):
        hero_options(s)


def test_unknown_profile_unsupported():
    s = new_hand(0, (200,) * 5)
    with pytest.raises(UnsupportedSpot):
        action_distribution(replace(load_profile("tag"), name="maniac"), s)


def test_deterministic():
    s = fold_to(new_hand(0, (200,) * 5), "CO")
    a, b = dist5("tag", s), dist5("tag", s)
    assert a.keys() == b.keys()
    for k in a:
        assert np.array_equal(a[k], b[k])
        assert a[k] is not b[k]


# ---------------------------------------------------------------------------
# simulation
# ---------------------------------------------------------------------------


def _random_stacks(rng: random.Random) -> tuple[int, ...]:
    def one() -> int:
        x = rng.random()
        if x < 0.15:
            return rng.randint(3, 40)  # short: all-in opens and 3-bets
        if x < 0.85:
            return rng.randint(80, 300)  # session range for bots
        return rng.randint(300, 700)  # deep (Hero after winning)

    return tuple(one() for _ in range(5))


def _branch(s: HandState) -> str:
    if preflop5.facing_jam(s, legal_actions(s)):
        return "jam"
    return f"r{len(preflop5.preflop_raises(s))}"


def _play_preflop(i: int, hero: bool) -> list[tuple[bool, str, ActionKind]]:
    rng = random.Random(f"preflop5-sim:{hero}:{i}")
    profiles = {seat: load_profile(rng.choice(PROFILE_NAMES)) for seat in range(5)}
    s = new_hand(rng.randrange(5), _random_stacks(rng))
    deck = list(range(52))
    rng.shuffle(deck)
    log = []
    while s.street == Street.PREFLOP and s.to_act is not None:
        seat = s.to_act
        branch = _branch(s)
        if hero and seat == 0:
            opts = hero_options(s)
            assert len({o.action for o in opts}) == len(opts)
            a = rng.choice(opts).action
        else:
            d = action_distribution(profiles[seat], s)
            assert_valid(s, d)
            a = sample_action(profiles[seat], s, (deck[2 * seat], deck[2 * seat + 1]), rng)
        log.append((hero and seat == 0, branch, a.kind))
        s = apply(s, a)
    assert sum(s.stacks) + s.pot + sum(s.street_bets) == s.total_chips
    return log


@pytest.mark.parametrize("hero", [False, True], ids=["bots", "hero"])
def test_simulated_preflop_rounds(hero):
    """300 seeded pre-flop rounds: never UnsupportedSpot, every distribution valid."""
    kinds, branches = set(), set()
    for i in range(300):
        for is_hero, branch, kind in _play_preflop(i, hero):
            kinds.add(kind)
            branches.add((is_hero, branch))
    assert kinds == {FOLD, CALL, RAISE}
    every = {"r0", "r1", "r2", "jam"}
    assert {b for h, b in branches if not h} == every
    if hero:
        assert {b for h, b in branches if h} == every
