"""5-max play hands: per-seat cards and bot seed streams, outcomes with pots, the abandoned-hand
rule and the 5-max session stack rules. Heads-up records replay exactly as before."""

import hashlib
import random
from collections.abc import Callable
from dataclasses import replace

import pytest

from poker_trainer.game.settle import settle_pots
from poker_trainer.game.state import (
    Action,
    ActionKind,
    HandState,
    Street,
    is_terminal,
    legal_actions,
    live_seats,
    total_pot,
)
from poker_trainer.play.hand import (
    HERO_SEAT,
    HandRecord,
    abandon,
    advance,
    advance_seats,
    board,
    hero_act,
    hero_act_seats,
    hole,
    holes,
    outcome,
    outcome5,
    replay,
)
from poker_trainer.play.session import (
    BOT_MAX,
    BOT_MIN,
    SEATS5,
    START,
    new_record,
    new_record5,
    next_button,
    next_stacks5,
)
from poker_trainer.puzzle.options import custom_action, hero_options
from poker_trainer.villain.profiles import PROFILE_NAMES, Profile, load_profile
from poker_trainer.villain.strategy import sample_action

PROFILES = {name: load_profile(name) for name in PROFILE_NAMES}
STACKS5 = (200,) * SEATS5

Chooser = Callable[[HandState], Action]


def seat_profiles(seed: int) -> dict[int, Profile]:
    rng = random.Random(f"profiles:{seed}")
    return {seat: PROFILES[rng.choice(PROFILE_NAMES)] for seat in range(1, SEATS5)}


def random_hero(seed: int, custom: float = 0.2) -> Chooser:
    rng = random.Random(f"hero5:{seed}")

    def choose(s: HandState) -> Action:
        lg = legal_actions(s)
        if s.street >= Street.FLOP and lg.min_to is not None and rng.random() < custom:
            assert lg.max_to is not None
            return custom_action(s, rng.randint(lg.min_to, lg.max_to))
        return rng.choice(hero_options(s)).action

    return choose


def shove(s: HandState) -> Action:
    """All-in when Hero can, else call, else check: makes all-ins and side pots common."""
    by_label = {o.label: o.action for o in hero_options(s)}
    for label in ("all-in", "call", "check"):
        if label in by_label:
            return by_label[label]
    raise AssertionError(f"no option among {list(by_label)}")


def play_out5(r: HandRecord, profiles: dict[int, Profile], choose: Chooser) -> HandRecord:
    r = advance_seats(r, profiles)
    while outcome5(r) is None:
        r = hero_act_seats(r, profiles, choose(replay(r)))
    return r


def fresh5(seed: int, stacks: tuple[int, ...] = STACKS5) -> HandRecord:
    return new_record5(seed % SEATS5, stacks, random.Random(f"deal5:{seed}"))


# --- cards -----------------------------------------------------------------------------------


def test_hole_and_board_slicing_for_five_seats():
    for seed in range(40):
        profiles = seat_profiles(seed)
        r = play_out5(fresh5(seed), profiles, shove)  # shoves reach the river often
        assert holes(r) == tuple((r.deck[2 * i], r.deck[2 * i + 1]) for i in range(5))
        assert hole(r, 3) == r.deck[6:8]
        b = board(r)
        assert b == r.deck[10 : 10 + len(b)]
        if len(b) == 5:
            return
    raise AssertionError("no 5-max hand reached the river")


def test_hole_rejects_a_seat_not_at_the_table():
    r = fresh5(0)
    with pytest.raises(ValueError):
        hole(r, 5)
    with pytest.raises(ValueError):
        hole(r, -1)


def test_heads_up_board_still_follows_four_hole_cards():
    for seed in range(40):
        r = advance(new_record(seed % 2, (200, 200), random.Random(seed)), PROFILES["sticky"])
        while outcome(r) is None:
            r = hero_act(r, PROFILES["sticky"], shove(replay(r)))
        b = board(r)
        assert b == r.deck[4 : 4 + len(b)]
        if len(b) == 5:
            return
    raise AssertionError("no heads-up hand reached the river")


# --- bots and seed streams -------------------------------------------------------------------


def passive(s: HandState) -> Action:
    """Check, else call: keeps several bots in the hand on later streets."""
    by_label = {o.label: o.action for o in hero_options(s)}
    for label in ("check", "call"):
        if label in by_label:
            return by_label[label]
    return by_label["fold"]


def test_each_bot_samples_from_its_own_seat_seed_stream():
    bot_actions = other_stream_differs = 0
    for seed in range(40):
        profiles = seat_profiles(seed)
        choose = passive if seed % 2 else random_hero(seed)
        r = play_out5(fresh5(seed), profiles, choose)
        for i, a in enumerate(r.actions):
            if a.seat == HERO_SEAT:
                continue
            bot_actions += 1
            s = replay(replace(r, actions=r.actions[:i]))
            assert len(s.history) == i and s.to_act == a.seat
            p, cards = profiles[a.seat], hole(r, a.seat)
            assert a == sample_action(p, s, cards, random.Random(f"{r.bot_seed}:{a.seat}:{i}"))
            # The heads-up stream would have played differently somewhere in the sample.
            other = sample_action(p, s, cards, random.Random(f"{r.bot_seed}:{i}"))
            other_stream_differs += other != a
    assert bot_actions > 0 and other_stream_differs > 0


def _hu_replay_digest() -> str:
    """Seeded heads-up hands played through ``advance``/``hero_act``; pinned before M12 Task 4."""
    h = hashlib.sha256()
    for name in PROFILE_NAMES:
        profile = PROFILES[name]
        for seed in range(30):
            rng = random.Random(f"hu-replay:{name}:{seed}")
            stacks = (rng.randint(10, 600), rng.randint(80, 300))
            r = advance(new_record(seed % 2, stacks, rng), profile)
            while (o := outcome(r)) is None:
                s = replay(r)
                lg = legal_actions(s)
                if s.street >= Street.FLOP and lg.min_to is not None and rng.random() < 0.2:
                    assert lg.max_to is not None
                    a = custom_action(s, rng.randint(lg.min_to, lg.max_to))
                else:
                    a = rng.choice(hero_options(s)).action
                r = hero_act(r, profile, a)
            h.update(repr((r.actions, o)).encode())
    return h.hexdigest()


def test_heads_up_hands_replay_exactly_as_before_m12():
    # Computed with the pre-Task-4 play/hand.py (stream f"{bot_seed}:{i}", board deck[4:9]).
    want = "3e4b98983dc80f0f0187c8bbfa1ec0bad39dcd9d47330115667bbf6f4f468312"
    assert _hu_replay_digest() == want


def test_heads_up_names_delegate_to_the_seat_functions():
    tag = PROFILES["tag"]
    r = new_record(1, (200, 200), random.Random(5))
    assert advance(r, tag) == advance_seats(r, {1: tag})


# --- advance and Hero's turn -----------------------------------------------------------------


@pytest.mark.parametrize("seed", range(25))
def test_advance_stops_at_hero_or_the_end_and_is_idempotent(seed):
    profiles = seat_profiles(seed)
    r = advance_seats(fresh5(seed), profiles)
    s = replay(r)
    assert is_terminal(s) or s.to_act == HERO_SEAT
    assert advance_seats(r, profiles) == r
    done = play_out5(r, profiles, random_hero(seed))
    assert advance_seats(done, profiles) == done


def test_bots_act_before_hero_from_utg():
    # Button 0 is Hero: UTG (3) and CO (4) act first, then Hero, with the blinds still behind.
    profiles = seat_profiles(1)
    r = advance_seats(fresh5(0), profiles)  # seed 0 -> button 0
    assert r.button == 0
    assert [a.seat for a in r.actions] == [3, 4]
    assert replay(r).to_act == HERO_SEAT


@pytest.mark.parametrize("seed", range(25))
def test_after_hero_folds_the_bots_finish_the_hand(seed):
    profiles = seat_profiles(seed)
    r = advance_seats(fresh5(seed), profiles)
    if outcome5(r) is not None:
        return
    fold = Action(HERO_SEAT, ActionKind.FOLD, replay(r).street)
    r = hero_act_seats(r, profiles, fold)
    o = outcome5(r)
    assert o is not None and o.ended_by in ("fold", "showdown")
    assert o.hero_delta <= 0
    assert HERO_SEAT not in o.shown
    assert all(HERO_SEAT not in p.eligible for p in o.pots)


def test_missing_profile_and_bad_actions_are_rejected():
    profiles = seat_profiles(0)
    r = fresh5(0)
    with pytest.raises(ValueError, match="no profile"):
        advance_seats(r, {1: PROFILES["tag"]})
    r = advance_seats(r, profiles)
    s = replay(r)
    with pytest.raises(ValueError, match="not an option"):
        hero_act_seats(r, profiles, Action(HERO_SEAT, ActionKind.RAISE, Street.PREFLOP, 7))
    with pytest.raises(ValueError, match="not Hero's turn"):
        hero_act_seats(replace(r, actions=r.actions[:-1]), profiles, hero_options(s)[0].action)
    with pytest.raises(ValueError, match="heads-up only"):
        outcome(r)


def test_hero_may_use_a_legal_post_flop_custom_size():
    for seed in range(200):
        profiles = seat_profiles(seed)
        r = advance_seats(fresh5(seed), profiles)
        while outcome5(r) is None:
            s = replay(r)
            lg = legal_actions(s)
            if s.street >= Street.FLOP and lg.min_to is not None and lg.max_to is not None:
                odd = lg.min_to + 1 if lg.min_to < lg.max_to else lg.min_to
                r2 = hero_act_seats(r, profiles, custom_action(s, odd))
                assert r2.actions[len(r.actions)] == Action(HERO_SEAT, lg.aggressive, s.street, odd)
                with pytest.raises(ValueError):
                    bad = Action(HERO_SEAT, lg.aggressive, s.street, lg.max_to + 1)
                    hero_act_seats(r, profiles, bad)
                return
            by_label = {o.label: o.action for o in hero_options(s)}
            pick = by_label.get("check") or by_label.get("call") or by_label["raise 2.5x"]
            r = hero_act_seats(r, profiles, pick)
    raise AssertionError("no post-flop Hero bet found")


# --- outcomes --------------------------------------------------------------------------------


def _check_outcome(r: HandRecord) -> None:
    o = outcome5(r)
    assert o is not None
    s = replay(r)
    n = len(r.start_stacks)
    assert sum(o.stacks) == sum(r.start_stacks)
    assert o.hero_delta == o.stacks[HERO_SEAT] - r.start_stacks[HERO_SEAT]
    want = "hero" if o.hero_delta > 0 else "villain" if o.hero_delta < 0 else "split"
    assert o.winner == want
    assert o.stacks == settle_pots(s, holes(r), r.start_stacks).stacks
    live = live_seats(s)
    paid = sum(r.start_stacks) - sum(s.stacks)
    assert paid == total_pot(s)
    assert 0 < sum(p.amount for p in o.pots) <= paid
    for p in o.pots:
        assert p.winners and set(p.winners) <= set(p.eligible) <= set(live)
    if o.ended_by == "fold":
        assert s.folded is not None and len(live) == 1 and o.shown == ()
        assert o.pots[0].amount == paid
    else:
        assert o.ended_by == "showdown" and len(board(r)) == 5
        bots = [i for i in live if i != HERO_SEAT]
        assert sorted(o.shown) == bots
        order = [(i - r.button - 1) % n for i in o.shown]
        assert order == sorted(order)  # clockwise from button+1


def test_outcomes_give_pots_shown_seats_and_heros_delta():
    side_pots = showdowns = folds = 0
    for seed in range(150):
        rng = random.Random(f"stacks:{seed}")
        stacks = (rng.randint(10, 400), *(rng.randint(80, 300) for _ in range(4)))
        choose = shove if seed % 2 else random_hero(seed)
        r = play_out5(fresh5(seed, stacks), seat_profiles(seed), choose)
        _check_outcome(r)
        o = outcome5(r)
        assert o is not None
        side_pots += len(o.pots) > 1
        showdowns += o.ended_by == "showdown"
        folds += o.ended_by == "fold"
    assert side_pots > 0 and showdowns > 0 and folds > 0


def test_outcome5_is_none_while_running_and_needs_three_seats():
    r = fresh5(0)
    assert outcome5(r) is None
    with pytest.raises(ValueError, match="three or more"):
        outcome5(new_record(0, (200, 200), random.Random(0)))


# --- the abandoned-hand rule -----------------------------------------------------------------


def _scripted_abandon() -> HandRecord:
    """Button 0 (Hero). UTG (3) opens 5, CO (4) folds, Hero 3-bets to 15, SB (1) folds,
    BB (2) and UTG call: a 3-way flop where Hero has committed 15 chips."""
    pre = Street.PREFLOP
    acts = (
        Action(3, ActionKind.RAISE, pre, 5),
        Action(4, ActionKind.FOLD, pre),
        Action(0, ActionKind.RAISE, pre, 15),
        Action(1, ActionKind.FOLD, pre),
        Action(2, ActionKind.CALL, pre, 15),
        Action(3, ActionKind.CALL, pre, 15),
    )
    start = (200, 150, 120, 250, 90)
    r = HandRecord(button=0, start_stacks=start, deck=tuple(range(52)), bot_seed=1, actions=acts)
    s = replay(r)
    assert s.street == Street.FLOP and not is_terminal(s)
    return r


def test_abandoned_hand_splits_heros_chips_among_live_bots_clockwise():
    r = abandon(_scripted_abandon())
    o = outcome5(r)
    assert o is not None
    assert (o.ended_by, o.winner, o.hero_delta, o.pots, o.shown) == (
        "abandoned",
        "villain",
        -15,
        (),
        (),
    )
    # Bots return to their pre-hand stacks; Hero's 15 go 8 to BB (2, first clockwise from
    # button+1 among the live bots) and 7 to UTG (3). Folded bots get nothing.
    assert o.stacks == (185, 150, 128, 257, 90)
    assert sum(o.stacks) == sum(r.start_stacks)


@pytest.mark.parametrize("seed", range(30))
def test_abandoned_hands_conserve_chips(seed):
    profiles = seat_profiles(seed)
    rng = random.Random(f"abandon:{seed}")
    stacks = (rng.randint(10, 400), *(rng.randint(80, 300) for _ in range(4)))
    r = advance_seats(fresh5(seed, stacks), profiles)
    choose = random_hero(seed, custom=0.0)
    for _ in range(rng.randint(0, 3)):
        if outcome5(r) is not None:
            return
        s = replay(r)
        options = [o.action for o in hero_options(s) if o.action.kind != ActionKind.FOLD]
        r = hero_act_seats(r, profiles, rng.choice(options) if options else choose(s))
    if outcome5(r) is not None:
        return
    s = replay(r)
    o = outcome5(abandon(r))
    assert o is not None and o.ended_by == "abandoned"
    assert sum(o.stacks) == sum(stacks)
    assert o.stacks[HERO_SEAT] == s.stacks[HERO_SEAT]
    for seat in range(1, SEATS5):
        if seat not in live_seats(s):
            assert o.stacks[seat] == stacks[seat]
        else:
            assert o.stacks[seat] >= stacks[seat]


# --- session rules ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hero", "bots", "top_up", "want"),
    [
        (200, (200, 200, 200, 200), False, (200, (200, 200, 200, 200), 0)),
        (200, (79, 80, 300, 301), False, (200, (200, 80, 300, 200), 0)),
        (200, (0, 150, 450, 99), True, (200, (200, 150, 200, 99), 0)),
        (9, (200, 200, 200, 200), False, (200, (200, 200, 200, 200), 191)),
        (150, (200, 200, 200, 200), True, (200, (200, 200, 200, 200), 50)),
        (150, (200, 200, 200, 200), False, (150, (200, 200, 200, 200), 0)),
        (450, (200, 200, 200, 200), True, (450, (200, 200, 200, 200), 0)),
    ],
)
def test_next_stacks5(hero, bots, top_up, want):
    assert next_stacks5(hero, bots, top_up=top_up) == want


def test_next_stacks5_uses_the_heads_up_limits_and_needs_four_bots():
    assert (BOT_MIN, BOT_MAX, START) == (80, 300, 200)
    with pytest.raises(ValueError):
        next_stacks5(200, (200, 200), top_up=False)


def test_new_record5_is_a_fresh_seeded_deal():
    stacks = (150, 250, 200, 90, 300)
    r = new_record5(3, stacks, random.Random(3))
    assert (r.button, r.start_stacks, r.actions, r.abandoned) == (3, stacks, (), False)
    assert sorted(r.deck) == list(range(52))
    assert 0 <= r.bot_seed < 2**62
    assert new_record5(3, stacks, random.Random(3)) == r
    assert new_record5(3, stacks, random.Random(4)) != r
    with pytest.raises(ValueError):
        new_record5(0, (200, 200), random.Random(0))
    with pytest.raises(ValueError):
        new_record5(5, stacks, random.Random(0))


def test_the_button_moves_one_seat_clockwise():
    assert [next_button(b, 5) for b in range(5)] == [1, 2, 3, 4, 0]
    assert [next_button(b, 2) for b in range(2)] == [1, 0]
