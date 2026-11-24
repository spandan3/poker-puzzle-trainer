"""5-max play hands: per-seat cards and bot seed streams, outcomes with pots, the abandoned-hand
rule, the winner rule, per-seat bot snapshots and the 5-max session stack rules. Heads-up
records replay exactly as before."""

import hashlib
import json
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
    folded_seats,
    is_terminal,
    legal_actions,
    live_seats,
    total_pot,
)
from poker_trainer.play import hand as hand_module
from poker_trainer.play.hand import (
    HERO_SEAT,
    HandRecord,
    SeatBot,
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
from poker_trainer.villain.preflop5 import load_fivemax
from poker_trainer.villain.profiles import PROFILE_NAMES, load_profile
from poker_trainer.villain.strategy import sample_action

PROFILES = {name: load_profile(name) for name in PROFILE_NAMES}  # heads-up
BOTS = {name: SeatBot.live(name) for name in PROFILE_NAMES}  # 5-max seats, live snapshots
STACKS5 = (200,) * SEATS5

Chooser = Callable[[HandState], Action]


def seat_profiles(seed: int) -> dict[int, SeatBot]:
    rng = random.Random(f"profiles:{seed}")
    return {seat: BOTS[rng.choice(PROFILE_NAMES)] for seat in range(1, SEATS5)}


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


def play_out5(r: HandRecord, profiles: dict[int, SeatBot], choose: Chooser) -> HandRecord:
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
            bot, cards = profiles[a.seat], hole(r, a.seat)
            p, fm = bot.profile, bot.fivemax
            rng = random.Random(f"{r.bot_seed}:{a.seat}:{i}")
            assert a == sample_action(p, s, cards, rng, fivemax=fm)
            # The heads-up stream would have played differently somewhere in the sample.
            other = sample_action(p, s, cards, random.Random(f"{r.bot_seed}:{i}"), fivemax=fm)
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
    assert advance(r, tag) == advance_seats(r, {1: BOTS["tag"]})


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
    assert o.hero_delta <= 0 and o.hero_folded and o.winner == "villain"
    assert HERO_SEAT not in o.shown
    assert all(HERO_SEAT not in p.eligible for p in o.pots)


def test_missing_profile_and_bad_actions_are_rejected():
    profiles = seat_profiles(0)
    r = fresh5(0)
    with pytest.raises(ValueError, match="no profile"):
        advance_seats(r, {1: BOTS["tag"]})
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
    assert o.hero_folded == (HERO_SEAT in folded_seats(s))
    want = "hero" if o.hero_delta > 0 else "villain" if o.hero_delta < 0 else "split"
    assert o.winner == ("villain" if o.hero_folded else want)
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


def test_abandoned_hand_gives_a_bot_that_folded_after_betting_its_start_stack():
    """Button 0 (Hero). UTG (3) opens 5, CO (4) calls, Hero 3-bets to 20, SB (1) and BB (2)
    fold, UTG folds its 5 chips, CO calls: Hero is heads-up with CO on the flop."""
    pre = Street.PREFLOP
    acts = (
        Action(3, ActionKind.RAISE, pre, 5),
        Action(4, ActionKind.CALL, pre, 5),
        Action(0, ActionKind.RAISE, pre, 20),
        Action(1, ActionKind.FOLD, pre),
        Action(2, ActionKind.FOLD, pre),
        Action(3, ActionKind.FOLD, pre),
        Action(4, ActionKind.CALL, pre, 20),
    )
    start = (200, 150, 120, 250, 90)
    r = HandRecord(button=0, start_stacks=start, deck=tuple(range(52)), bot_seed=1, actions=acts)
    s = replay(r)
    assert s.street == Street.FLOP and not is_terminal(s)
    assert s.stacks[3] == 245 and s.stacks[2] == 118 and s.stacks[1] == 149
    o = outcome5(abandon(r))
    assert o is not None
    # UTG put in 5 and folded, the blinds folded after posting: each gets its start stack back.
    # Hero's 20 all go to CO, the only live bot.
    assert o.stacks == (180, 150, 120, 250, 110)
    assert (o.winner, o.hero_delta, o.hero_folded) == ("villain", -20, False)


# --- the winner rule and hero_folded ---------------------------------------------------------


def _hero_utg() -> HandRecord:
    """Button 2, so Hero (seat 0 = button+3) is UTG and acts first with nothing committed."""
    r = advance_seats(new_record5(2, STACKS5, random.Random("utg")), seat_profiles(0))
    assert r.actions == () and replay(r).to_act == HERO_SEAT
    return r


def test_utg_fold_with_nothing_committed_reads_as_a_loss():
    r = _hero_utg()
    r = hero_act_seats(r, seat_profiles(0), Action(HERO_SEAT, ActionKind.FOLD, Street.PREFLOP))
    o = outcome5(r)
    assert o is not None and o.hero_delta == 0
    assert (o.winner, o.hero_folded) == ("villain", True)
    assert HERO_SEAT not in o.shown


def test_abandon_with_nothing_committed_reads_as_a_loss():
    o = outcome5(abandon(_hero_utg()))
    assert o is not None
    assert (o.ended_by, o.winner, o.hero_delta, o.hero_folded) == ("abandoned", "villain", 0, False)
    assert o.stacks == STACKS5


def test_hero_folds_and_the_bots_reach_a_showdown():
    for seed in range(300):
        profiles = seat_profiles(seed)
        r = advance_seats(fresh5(seed), profiles)
        if outcome5(r) is not None:
            continue
        r = hero_act_seats(r, profiles, Action(HERO_SEAT, ActionKind.FOLD, replay(r).street))
        o = outcome5(r)
        assert o is not None and o.hero_folded and o.winner == "villain"
        if o.ended_by != "showdown":
            continue
        assert o.shown and HERO_SEAT not in o.shown
        assert len(o.shown) >= 2 and set(o.shown) == set(live_seats(replay(r)))
        assert all(HERO_SEAT not in p.eligible for p in o.pots)
        return
    raise AssertionError("no hand where Hero folded reached a showdown")


# --- per-seat bot snapshots ------------------------------------------------------------------


def test_seat_bot_round_trips_through_a_plain_json_dict():
    for name in PROFILE_NAMES:
        bot = SeatBot.live(name)
        d = bot.to_dict()
        assert set(d) == {"profile", "profile_data", "fivemax_data"} and d["profile"] == name
        assert set(d["fivemax_data"]) == {"version", "bb_call_mult", "damping", "block"}
        back = SeatBot.from_dict(json.loads(json.dumps(d)))
        assert back == bot and back.to_dict() == d
        assert set(back.fivemax.profiles) == {name}
        assert back.fivemax.version == load_fivemax().version
        assert back.fivemax.profiles[name] == load_fivemax().profiles[name]
        assert back.fivemax.damping == load_fivemax().damping
        d["fivemax_data"]["block"]["open"]["UTG"] = 99  # to_dict is a fresh copy
        assert bot.to_dict()["fivemax_data"]["block"]["open"]["UTG"] != 99


def _bad(change: Callable[[dict], None]) -> dict:
    d = SeatBot.live("tag").to_dict()
    change(d)
    return d


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.pop("fivemax_data"),
        lambda d: d.update(extra=1),
        lambda d: d.update(profile="maniac"),
        lambda d: d.update(profile="lag"),  # the profile file declares "tag"
        lambda d: d["profile_data"].pop("unopened"),
        lambda d: d["fivemax_data"].pop("damping"),
        lambda d: d["fivemax_data"].update(extra=1),
        lambda d: d["fivemax_data"].update(version="1"),
        lambda d: d["fivemax_data"].update(version=True),
        lambda d: d["fivemax_data"].update(bb_call_mult=0.5),
        lambda d: d["fivemax_data"]["damping"].update(bluff=0),
        lambda d: d["fivemax_data"]["damping"].pop("thin"),
        lambda d: d["fivemax_data"]["block"]["open"].pop("UTG"),
        lambda d: d["fivemax_data"]["block"]["open"].update(BB=10),
        lambda d: d["fivemax_data"]["block"]["vs_open"].update(threebet=101),
        lambda d: d["fivemax_data"]["block"].update(vs_limp={"call": 5}),
        lambda d: d["fivemax_data"].update(block=[]),
    ],
)
def test_seat_bot_from_dict_is_strict(change):
    with pytest.raises(ValueError):
        SeatBot.from_dict(_bad(change))


def _play_snapshots(bots: dict[int, SeatBot], seed: int) -> HandRecord:
    return play_out5(fresh5(seed), bots, random_hero(seed))


def _play_live_files(names: dict[int, str], seed: int) -> HandRecord:
    """The same hand with bare profiles: every bot reads the live data files (no snapshot)."""
    profiles = {seat: PROFILES[name] for seat, name in names.items()}
    choose = random_hero(seed)
    r = hand_module._advance(fresh5(seed), profiles)
    while outcome5(r) is None:
        r = hand_module._hero_act(r, profiles, choose(replay(r)))
    return r


def test_a_live_equivalent_snapshot_plays_exactly_as_the_live_files():
    for seed in range(40):
        names = {seat: bot.profile.name for seat, bot in seat_profiles(seed).items()}
        stored = {
            s: SeatBot.from_dict(json.loads(json.dumps(BOTS[n].to_dict())))
            for s, n in names.items()
        }
        assert _play_snapshots(stored, seed) == _play_live_files(names, seed)


def test_a_changed_snapshot_plays_differently_and_stably():
    def loose(name: str) -> SeatBot:
        d = SeatBot.live(name).to_dict()
        d["fivemax_data"]["block"]["open"] = {"UTG": 100, "CO": 100, "BTN": 100, "SB": 100}
        d["fivemax_data"]["damping"] = {"bluff": 1, "thin": 1, "call": 1}
        return SeatBot.from_dict(d)

    differs = 0
    for seed in range(30):
        live = seat_profiles(seed)
        changed = {seat: loose(bot.profile.name) for seat, bot in live.items()}
        a = _play_snapshots(changed, seed)
        assert a == _play_snapshots(changed, seed)  # stable: a pure function of the record
        assert replay(replace(a, actions=())) == replay(fresh5(seed))
        differs += a != _play_snapshots(live, seed)
        # Unopened bots always open with the changed snapshot.
        for act in a.actions:
            if act.street != Street.PREFLOP or act.kind == ActionKind.RAISE:
                break
            assert act.seat == HERO_SEAT
    assert differs > 0
    # The live files are untouched.
    assert SeatBot.live("tag") == BOTS["tag"]


@pytest.mark.parametrize(
    "bad",
    [
        lambda b: {0: b[1], **b},  # Hero's seat
        lambda b: {**b, 5: b[1]},  # not at the table
        lambda b: {k: v for k, v in b.items() if k != 4},  # missing
    ],
)
def test_bot_seats_must_be_exactly_the_bot_seats(bad):
    bots = seat_profiles(0)
    r = fresh5(0)
    with pytest.raises(ValueError, match="no profile|not a bot seat"):
        advance_seats(r, bad(bots))
    r = advance_seats(r, bots)
    fold = Action(HERO_SEAT, ActionKind.FOLD, Street.PREFLOP)
    with pytest.raises(ValueError, match="no profile|not a bot seat"):
        hero_act_seats(r, bad(bots), fold)


def test_bot_seats_need_snapshots_not_bare_profiles():
    r = fresh5(0)
    with pytest.raises(TypeError, match="SeatBot"):
        advance_seats(r, {seat: PROFILES["tag"] for seat in range(1, SEATS5)})  # type: ignore[dict-item]


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
