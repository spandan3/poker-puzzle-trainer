"""Per-decision analysis of a played hand: the puzzle solver and grader on the bot's real line."""

import random
import time
from collections.abc import Callable
from dataclasses import replace

import numpy as np
import pytest

from poker_trainer.api.views import showdown
from poker_trainer.engine.cards import parse_cards
from poker_trainer.engine.combos import combo_index
from poker_trainer.game.state import Action, ActionKind, HandState, Street, legal_actions
from poker_trainer.play.analyse import (
    DecisionAnalysis,
    analyse_decision,
    decision_spot,
    hero_decisions,
)
from poker_trainer.play.hand import (
    BOT_SEAT,
    HERO_SEAT,
    HandRecord,
    advance,
    bot_cards,
    hero_act,
    hero_cards,
    outcome,
    replay,
)
from poker_trainer.play.session import new_record
from poker_trainer.puzzle.model import load_config, visible_range
from poker_trainer.puzzle.options import custom_action, hero_options
from poker_trainer.villain import profiles
from poker_trainer.villain.features import load_thresholds
from poker_trainer.villain.narrowing import RangeTracker
from poker_trainer.villain.profiles import (
    PROFILE_NAMES,
    Profile,
    load_profile,
    profile_data,
    profile_from_dict,
)
from poker_trainer.villain.strategy import UnsupportedSpot

TAG = load_profile("tag")
STACKS = (200, 200)
FAST = 2_000

Chooser = Callable[[HandState], Action]


def deck_with(hero: str, bot: str, runout: str = "") -> tuple[int, ...]:
    first = [*parse_cards(hero), *parse_cards(bot), *parse_cards(runout)]
    return (*first, *(c for c in range(52) if c not in first))


def passive(s: HandState) -> Action:
    """Check, else call, else open 2.5x: keeps hands going to later streets."""
    by_label = {o.label: o.action for o in hero_options(s)}
    for label in ("check", "call", "raise 2.5x"):
        if label in by_label:
            return by_label[label]
    return next(iter(by_label.values()))


def seeded(seed: int) -> Chooser:
    rng = random.Random(f"hero:{seed}")
    return lambda s: rng.choice(hero_options(s)).action


def play_out(r: HandRecord, profile: Profile, choose: Chooser) -> HandRecord:
    r = advance(r, profile)
    while outcome(r) is None:
        r = hero_act(r, profile, choose(replay(r)))
    return r


def seeded_hand(seed: int) -> tuple[HandRecord, Profile]:
    profile = load_profile(PROFILE_NAMES[seed % len(PROFILE_NAMES)])
    r = play_out(new_record(seed % 2, STACKS, random.Random(seed)), profile, seeded(seed))
    return r, profile


# ---------------------------------------------------------------------------
# hero_decisions
# ---------------------------------------------------------------------------


def test_hero_decisions_are_heros_actions_in_order_to_the_river():
    deck = deck_with("Ah2c", "7d7s", "Kc9h4s3dJh")
    r = play_out(
        HandRecord(button=BOT_SEAT, start_stacks=STACKS, deck=deck, bot_seed=3, actions=()),
        TAG,
        passive,
    )
    s = replay(r)
    assert s.street == Street.RIVER and len(s.board) == 5 and s.folded is None
    idx = hero_decisions(r)
    assert idx == tuple(i for i, a in enumerate(r.actions) if a.seat == HERO_SEAT)
    # Hero acts at least once on each of the four streets.
    assert {r.actions[i].street for i in idx} == set(Street)
    assert all(r.actions[i].seat == HERO_SEAT for i in idx)


def test_a_bot_fold_on_the_button_leaves_no_decisions():
    r = advance(
        HandRecord(BOT_SEAT, STACKS, deck_with("AsKd", "7c2h"), bot_seed=7, actions=()), TAG
    )
    assert outcome(r) is not None
    assert hero_decisions(r) == ()


# ---------------------------------------------------------------------------
# decision_spot
# ---------------------------------------------------------------------------


def _expected_range(r: HandRecord, profile: Profile, upto: int, hero, board) -> np.ndarray:
    tracker = RangeTracker(profile, BOT_SEAT)
    for i in range(upto):
        a = r.actions[i]
        if a.seat == BOT_SEAT:
            tracker.observe(replay(replace(r, actions=r.actions[:i])), a)
    return visible_range(tracker.current, hero, board)


@pytest.mark.parametrize("seed", range(30))
def test_decision_spot_is_the_hand_as_it_stood(seed):
    r, profile = seeded_hand(seed)
    idx = hero_decisions(r)
    for n, i in enumerate(idx):
        spot, action = decision_spot(r, profile, n)
        s = spot.state
        assert action == r.actions[i]
        assert s.to_act == HERO_SEAT == spot.hero_seat
        assert s.history == r.actions[:i]
        assert spot.start_stacks == r.start_stacks
        assert spot.hero == hero_cards(r)
        assert spot.villain_hole == bot_cards(r)
        assert spot.runout == r.deck[4:9]
        assert (spot.seed, spot.attempt) == (r.bot_seed, n)
        assert (spot.profile, spot.profile_version) == (profile.name, profile.version)
        assert spot.categories_version == load_thresholds().version
        assert spot.config_version == load_config().version
        bot_actions = sum(1 for a in r.actions[:i] if a.seat == BOT_SEAT)
        assert len(spot.steps) == bot_actions + 1
        want = _expected_range(r, profile, i, spot.hero, tuple(s.board))
        assert np.array_equal(spot.steps[-1].range, want)
        # The bot's actual combo is in the range Hero is graded against.
        assert spot.range[combo_index(*bot_cards(r))] > 0


def test_decision_index_out_of_range_raises():
    r, profile = seeded_hand(0)
    k = len(hero_decisions(r))
    for n in (k, -1):
        with pytest.raises(IndexError):
            decision_spot(r, profile, n)
        with pytest.raises(IndexError):
            analyse_decision(r, profile, n, samples=FAST)


@pytest.mark.parametrize("seed", range(6))
def test_showdown_works_for_every_decision(seed):
    r, profile = seeded_hand(seed)
    for n in range(len(hero_decisions(r))):
        spot, _ = decision_spot(r, profile, n)
        assert spot.villain_hole == bot_cards(r)
        assert spot.runout == r.deck[4:9]
        assert showdown(spot)["winner"] in ("hero", "villain", "split")


# ---------------------------------------------------------------------------
# analyse_decision
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(4))
def test_analysis_grades_heros_action_and_is_deterministic(seed):
    r, profile = seeded_hand(seed)
    for n in range(len(hero_decisions(r))):
        a = analyse_decision(r, profile, n, samples=FAST)
        assert isinstance(a, DecisionAnalysis)
        assert a.not_graded is None and a.puzzle is not None and a.grade is not None
        _, action = decision_spot(r, profile, n)
        assert a.grade.chosen.option.action == action
        b = analyse_decision(r, profile, n, samples=FAST)
        assert b.puzzle is not None
        assert [o.ev_chips for o in a.puzzle.solution.options] == [
            o.ev_chips for o in b.puzzle.solution.options
        ]
        assert a.grade.ev_loss_chips == b.grade.ev_loss_chips


def _bb_three_bet_record() -> tuple[HandRecord, int]:
    """A hand where the bot opens the button and Hero 3-bets 2.5x from the big blind."""
    for seed in range(200):
        r = advance(new_record(BOT_SEAT, STACKS, random.Random(seed)), TAG)
        s = replay(r)
        if outcome(r) is not None or s.history[-1].kind != ActionKind.RAISE:
            continue
        three = next(o.action for o in hero_options(s) if o.label == "raise 2.5x")
        return hero_act(r, TAG, three), 0
    raise AssertionError("no button open found")


def _option_ev(a: DecisionAnalysis, label: str) -> float:
    assert a.puzzle is not None
    return next(o.ev_chips for o in a.puzzle.solution.options if o.option.label == label)


def test_analysis_grades_with_the_snapshot_not_the_live_file():
    r, n = _bb_three_bet_record()
    before = profile_data("tag")
    edited = profile_data("tag")
    edited["preflop"]["btn_call_threebet"] = ""
    snapshot = profile_from_dict("tag", edited)

    live = analyse_decision(r, TAG, n, samples=FAST)
    snap = analyse_decision(r, snapshot, n, samples=FAST)
    assert snap.grade is not None
    assert snap.grade.chosen.option.label == "raise 2.5x"
    assert _option_ev(snap, "raise 2.5x") != _option_ev(live, "raise 2.5x")
    assert profile_data("tag") == before


def test_custom_size_is_graded_without_loading_a_profile(monkeypatch):
    r = None
    for seed in range(200):
        r = advance(new_record(seed % 2, STACKS, random.Random(seed)), TAG)
        while outcome(r) is None:
            s = replay(r)
            lg = legal_actions(s)
            if s.street >= Street.FLOP and lg.aggressive is not None:
                listed = {o.action.to for o in hero_options(s)}
                to = next(t for t in range(lg.min_to, lg.max_to + 1) if t not in listed)
                r = hero_act(r, TAG, custom_action(s, to))
                break
            r = hero_act(r, TAG, passive(s))
        else:
            continue
        break
    assert r is not None
    n = len(hero_decisions(r)) - 1
    _, action = decision_spot(r, TAG, n)

    def refuse(name):
        raise AssertionError("load_profile must not be called")

    monkeypatch.setattr(profiles, "load_profile", refuse)
    monkeypatch.setattr("poker_trainer.puzzle.grade.load_profile", refuse)
    a = analyse_decision(r, TAG, n, samples=FAST)
    assert a.grade is not None and a.puzzle is not None
    assert a.grade.chosen.option.action == action
    assert all(o.option.action != action for o in a.puzzle.solution.options)


def _bot_open_record() -> tuple[HandRecord, Profile]:
    """A finished hand whose first Hero decision follows a bot action."""
    for seed in range(1, 200, 2):  # odd seeds put the bot on the button
        r, profile = seeded_hand(seed)
        if hero_decisions(r):
            return r, profile
    raise AssertionError("no hand found")


def test_unsupported_spot_from_the_solver_is_not_graded(monkeypatch):
    r, profile = seeded_hand(1)
    assert hero_decisions(r)

    def boom(*args, **kwargs):
        raise UnsupportedSpot("solver says no")

    monkeypatch.setattr("poker_trainer.play.analyse.solve", boom)
    a = analyse_decision(r, profile, 0, samples=FAST)
    assert a == DecisionAnalysis(None, None, "solver says no")


def test_range_tracker_error_is_not_graded(monkeypatch):
    r, profile = _bot_open_record()
    assert hero_decisions(r)[0] > 0

    def boom(self, s, action):
        raise ValueError("categories changed")

    monkeypatch.setattr(RangeTracker, "observe", boom)
    a = analyse_decision(r, profile, 0, samples=FAST)
    assert a == DecisionAnalysis(None, None, "categories changed")


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_six_decision_hand_at_default_samples_is_fast():
    r = None
    for seed in range(2_000):
        cand, profile = seeded_hand(seed)
        if len(hero_decisions(cand)) == 6:
            r = cand
            break
    assert r is not None, "no 6-decision hand found"
    t0 = time.perf_counter()
    results = [analyse_decision(r, profile, n) for n in range(6)]
    elapsed = time.perf_counter() - t0
    print(f"\n6-decision hand analysed in {elapsed:.2f} s (seed {seed}, {profile.name})")
    assert all(a.grade is not None for a in results)
    assert elapsed < 10.0
