"""The play hand engine: the bot acts from the policy, a record replays and resumes exactly."""

import random
from collections.abc import Callable
from dataclasses import replace

import pytest

from poker_trainer.engine.cards import parse_cards
from poker_trainer.game.state import (
    Action,
    ActionKind,
    HandState,
    Street,
    is_terminal,
    legal_actions,
)
from poker_trainer.play.hand import (
    BOT_SEAT,
    HERO_SEAT,
    HandRecord,
    abandon,
    advance,
    board,
    bot_cards,
    hero_act,
    hero_cards,
    outcome,
    replay,
)
from poker_trainer.play.session import new_record
from poker_trainer.puzzle.options import hero_options
from poker_trainer.villain.profiles import PROFILE_NAMES, Profile, load_profile
from poker_trainer.villain.strategy import sample_action

TAG = load_profile("tag")
STACKS = (200, 200)

Chooser = Callable[[HandState], Action]


def deck_with(hero: str, bot: str, runout: str = "") -> tuple[int, ...]:
    """A deck with Hero's and the bot's cards (and optionally the run-out) dealt first."""
    first = [*parse_cards(hero), *parse_cards(bot), *parse_cards(runout)]
    return (*first, *(c for c in range(52) if c not in first))


def record(button: int, deck: tuple[int, ...], seed: int = 7) -> HandRecord:
    return HandRecord(button=button, start_stacks=STACKS, deck=deck, bot_seed=seed, actions=())


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


def hero_to_act_postflop(profile: Profile) -> HandRecord:
    """The first seeded record that reaches a post-flop Hero decision where betting is legal."""
    for seed in range(200):
        r = advance(new_record(seed % 2, STACKS, random.Random(seed)), profile)
        while outcome(r) is None:
            s = replay(r)
            if s.street >= Street.FLOP and legal_actions(s).aggressive is not None:
                return r
            r = hero_act(r, profile, passive(s))
    raise AssertionError("no post-flop Hero decision found")


def test_cards_come_from_the_deck():
    deck = deck_with("AsKd", "7c2h", "QsJsTs9s8s")
    r = record(HERO_SEAT, deck)
    assert hero_cards(r) == deck[0:2]
    assert bot_cards(r) == deck[2:4]
    assert board(r) == ()


@pytest.mark.parametrize("seed", range(20))
def test_bot_on_the_button_acts_until_hero_or_the_end(seed):
    r = advance(new_record(BOT_SEAT, STACKS, random.Random(seed)), TAG)
    s = replay(r)
    assert len(r.actions) == 1 and r.actions[0].seat == BOT_SEAT
    if is_terminal(s):
        assert s.folded == BOT_SEAT
    else:
        assert s.to_act == HERO_SEAT


def test_bot_folding_the_button_ends_the_hand():
    r = advance(record(BOT_SEAT, deck_with("AsKd", "7c2h")), TAG)
    assert r.actions == (Action(BOT_SEAT, ActionKind.FOLD, Street.PREFLOP),)
    o = outcome(r)
    assert o is not None
    assert (o.ended_by, o.winner, o.stacks, o.hero_delta) == ("fold", "hero", (201, 199), 1)


@pytest.mark.parametrize("name", PROFILE_NAMES)
@pytest.mark.parametrize("seed", range(5))
def test_bot_action_is_the_policy_seeded_by_its_history_index(name, seed):
    profile = load_profile(name)
    r = play_out(new_record(seed % 2, STACKS, random.Random(seed)), profile, seeded(seed))
    for i, a in enumerate(r.actions):
        if a.seat != BOT_SEAT:
            continue
        s = replay(replace(r, actions=r.actions[:i]))
        assert len(s.history) == i
        rng = random.Random(f"{r.bot_seed}:{i}")
        assert a == sample_action(profile, s, bot_cards(r), rng)


@pytest.mark.parametrize("seed", range(10))
def test_advance_is_idempotent(seed):
    r = advance(new_record(seed % 2, STACKS, random.Random(seed)), TAG)
    assert advance(r, TAG) == r
    done = play_out(r, TAG, seeded(seed))
    assert advance(done, TAG) == done


@pytest.mark.parametrize("name", PROFILE_NAMES)
@pytest.mark.parametrize("seed", range(5))
def test_resuming_from_any_prefix_gives_the_same_hand(name, seed):
    profile = load_profile(name)
    full = play_out(new_record(seed % 2, STACKS, random.Random(seed)), profile, seeded(seed))
    for k in range(len(full.actions) + 1):
        r = advance(replace(full, actions=full.actions[:k]), profile)
        while outcome(r) is None:
            assert r.actions == full.actions[: len(r.actions)]
            nxt = full.actions[len(r.actions)]
            assert nxt.seat == HERO_SEAT
            r = hero_act(r, profile, nxt)
        assert r == full


def test_replay_deals_the_board_from_the_deck():
    r = hero_to_act_postflop(TAG)
    b = board(r)
    assert len(b) >= 3
    assert b == r.deck[4 : 4 + len(b)]


def test_action_not_in_the_menu_is_refused():
    # Hero on the button opens; 2.5x and 3x are on the menu, a raise to 7 chips is not.
    r = advance(record(HERO_SEAT, deck_with("AsKd", "7c2h")), TAG)
    s = replay(r)
    assert s.to_act == HERO_SEAT
    with pytest.raises(ValueError):
        hero_act(r, TAG, Action(HERO_SEAT, ActionKind.RAISE, Street.PREFLOP, 7))
    with pytest.raises(ValueError):
        hero_act(r, TAG, Action(BOT_SEAT, ActionKind.FOLD, Street.PREFLOP))
    with pytest.raises(ValueError):
        hero_act(r, TAG, Action(HERO_SEAT, ActionKind.CHECK, Street.PREFLOP))


def test_custom_size_postflop_inside_the_legal_range_is_accepted():
    r = hero_to_act_postflop(TAG)
    s = replay(r)
    lg = legal_actions(s)
    assert lg.aggressive is not None and lg.min_to is not None and lg.max_to is not None
    menu = {o.action.to for o in hero_options(s)}
    to = next(t for t in range(lg.min_to, lg.max_to + 1) if t not in menu)
    custom = Action(HERO_SEAT, lg.aggressive, s.street, to)
    after = hero_act(r, TAG, custom)
    assert after.actions[len(r.actions)] == custom
    for bad in (lg.min_to - 1, lg.max_to + 1):
        with pytest.raises(ValueError):
            hero_act(r, TAG, Action(HERO_SEAT, lg.aggressive, s.street, bad))


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_allin_and_call_preflop_runs_out_to_showdown(name):
    profile = load_profile(name)
    deck = deck_with("7c2d", "AsAh", "KsQdJh5c3h")
    r = advance(record(HERO_SEAT, deck), profile)
    jam = next(o.action for o in hero_options(replay(r)) if o.label == "all-in")
    r = hero_act(r, profile, jam)
    assert r.actions[-1].kind == ActionKind.CALL  # AA always calls the jam
    assert board(r) == deck[4:9]
    o = outcome(r)
    assert o is not None
    assert (o.ended_by, o.winner, o.stacks, o.hero_delta) == ("showdown", "villain", (0, 400), -200)


def test_outcome_is_none_while_the_hand_is_running():
    r = advance(record(HERO_SEAT, deck_with("AsKd", "7c2h")), TAG)
    assert outcome(r) is None


def test_abandon_keeps_heros_stack_and_gives_the_rest_to_the_bot():
    r = hero_to_act_postflop(TAG)
    s = replay(r)
    a = abandon(r)
    assert a.abandoned and a.actions == r.actions
    o = outcome(a)
    assert o is not None
    assert (o.ended_by, o.winner) == ("abandoned", "villain")
    assert o.stacks[HERO_SEAT] == s.stacks[HERO_SEAT]
    assert sum(o.stacks) == sum(STACKS)
    assert o.hero_delta == s.stacks[HERO_SEAT] - STACKS[HERO_SEAT]


def test_hero_act_refuses_when_it_is_not_heros_turn_or_the_hand_is_over():
    fresh = record(BOT_SEAT, deck_with("AsKd", "QcQh"))  # not advanced: the bot is to act
    with pytest.raises(ValueError):
        hero_act(fresh, TAG, Action(HERO_SEAT, ActionKind.FOLD, Street.PREFLOP))

    running = hero_to_act_postflop(TAG)
    fold_or_check = hero_options(replay(running))[0].action
    with pytest.raises(ValueError):
        hero_act(abandon(running), TAG, fold_or_check)
    with pytest.raises(ValueError):
        advance(abandon(running), TAG)

    folded = advance(record(BOT_SEAT, deck_with("AsKd", "7c2h")), TAG)
    assert outcome(folded) is not None
    with pytest.raises(ValueError):
        hero_act(folded, TAG, Action(HERO_SEAT, ActionKind.CHECK, Street.PREFLOP))
