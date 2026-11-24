"""5-max simulation: bots with random profiles against a random Hero, stacks carried over under
the session rules. Every hand finishes with chips conserved and every pot awarded; opens widen
from UTG to BTN for each profile (soft check over the slow sample)."""

import random
from dataclasses import dataclass, field

import pytest

from poker_trainer.game.state import (
    Action,
    ActionKind,
    HandState,
    Street,
    legal_actions,
    position_name,
    total_pot,
)
from poker_trainer.play.hand import (
    HERO_SEAT,
    HandRecord,
    SeatBot,
    advance_seats,
    hero_act_seats,
    outcome5,
    replay,
)
from poker_trainer.play.session import (
    SEATS5,
    START,
    new_record5,
    next_button,
    next_stacks5,
)
from poker_trainer.puzzle.options import custom_action, hero_options
from poker_trainer.villain.profiles import PROFILE_NAMES

BOTS = {name: SeatBot.live(name) for name in PROFILE_NAMES}
SESSION_HANDS = 100  # each session deals fresh random profiles to the four bot seats
CUSTOM_PROB = 0.2
TOP_UP_PROB = 0.1
MAX_ACTIONS = 120  # far beyond any real 5-max hand; guards against a loop that never ends


@dataclass
class Stats:
    hands: int = 0
    flops: int = 0
    multiway_flops: int = 0  # 3+ live seats on the flop
    showdowns: int = 0
    side_pots: int = 0  # hands settled with more than one listed pot
    all_ins: int = 0  # hands where some seat ended all-in
    hero_folds: int = 0
    rebuys: int = 0
    # (profile, position) -> [unopened decisions, opens]
    opens: dict[tuple[str, str], list[int]] = field(default_factory=dict)


def _hero_choice(s: HandState, rng: random.Random) -> Action:
    lg = legal_actions(s)
    if s.street >= Street.FLOP and lg.min_to is not None and rng.random() < CUSTOM_PROB:
        assert lg.max_to is not None
        return custom_action(s, rng.randint(lg.min_to, lg.max_to))
    return rng.choice(hero_options(s)).action


def _count_opens(r: HandRecord, s: HandState, names: dict[int, str], stats: Stats) -> None:
    """Tally each bot's unopened pre-flop decisions (fold or open) by profile and position."""
    for a in r.actions:
        if a.street != Street.PREFLOP:
            break
        if a.seat != HERO_SEAT:
            tally = stats.opens.setdefault((names[a.seat], position_name(s, a.seat)), [0, 0])
            tally[0] += 1
            tally[1] += a.kind == ActionKind.RAISE
        if a.kind == ActionKind.RAISE:
            break


def simulate(n_hands: int, seed: int) -> Stats:
    rng = random.Random(f"fivemax-sim:{seed}")
    stats = Stats()
    hero, bots = START, [START] * (SEATS5 - 1)
    button = rng.randrange(SEATS5)
    names: dict[int, str] = {}
    for h in range(n_hands):
        if h % SESSION_HANDS == 0:
            names = {seat: rng.choice(PROFILE_NAMES) for seat in range(1, SEATS5)}
            hero, bots = START, [START] * (SEATS5 - 1)
        profiles = {seat: BOTS[name] for seat, name in names.items()}
        hero, new_bots, bought = next_stacks5(hero, bots, top_up=rng.random() < TOP_UP_PROB)
        stats.rebuys += bought > 0
        stacks = (hero, *new_bots)
        r = advance_seats(new_record5(button, stacks, rng), profiles)
        while (o := outcome5(r)) is None:
            assert len(r.actions) < MAX_ACTIONS
            r = hero_act_seats(r, profiles, _hero_choice(replay(r), rng))

        s = replay(r)
        assert sum(o.stacks) == sum(stacks), f"chips not conserved in hand {h}"
        assert o.hero_delta == o.stacks[HERO_SEAT] - hero
        assert o.pots and all(p.winners and set(p.winners) <= set(p.eligible) for p in o.pots)
        assert sum(p.amount for p in o.pots) <= total_pot(s)

        stats.hands += 1
        stats.showdowns += o.ended_by == "showdown"
        stats.side_pots += len(o.pots) > 1
        stats.all_ins += any(x == 0 for x in s.stacks)
        stats.hero_folds += any(
            a.seat == HERO_SEAT and a.kind == ActionKind.FOLD for a in r.actions
        )
        if len(s.board) >= 3:
            stats.flops += 1
            pre_folds = sum(
                a.street == Street.PREFLOP and a.kind == ActionKind.FOLD for a in r.actions
            )
            stats.multiway_flops += SEATS5 - pre_folds >= 3
        _count_opens(r, s, names, stats)

        hero, bots = o.stacks[HERO_SEAT], list(o.stacks[1:])
        button = next_button(button, SEATS5)
    return stats


def _report(stats: Stats) -> str:
    def pct(x: int, of: int) -> str:
        return f"{100 * x / max(of, 1):.1f}%"

    summary = (
        f"hands {stats.hands}, flops {pct(stats.flops, stats.hands)}, "
        f"multiway flops {pct(stats.multiway_flops, stats.flops)} of flops, "
        f"showdowns {pct(stats.showdowns, stats.hands)}, "
        f"side pots {pct(stats.side_pots, stats.hands)}, "
        f"all-ins {pct(stats.all_ins, stats.hands)}, "
        f"Hero folds {pct(stats.hero_folds, stats.hands)}, Hero rebuys {stats.rebuys}"
    )
    lines = [summary]
    for name in PROFILE_NAMES:
        row = []
        for pos in ("UTG", "CO", "BTN", "SB"):
            n, k = stats.opens.get((name, pos), [0, 0])
            row.append(f"{pos} {pct(k, n)} (n={n})")
        lines.append(f"  {name}: " + ", ".join(row))
    return "\n".join(lines)


def test_fivemax_simulation_fast():
    stats = simulate(200, seed=0)
    print(_report(stats))
    assert stats.hands == 200
    assert stats.flops > 0 and stats.showdowns > 0


@pytest.mark.slow
def test_fivemax_simulation_slow():
    stats = simulate(5000, seed=1)
    print(_report(stats))
    assert stats.side_pots > 0 and stats.multiway_flops > 0
    for name in PROFILE_NAMES:
        rates = []
        for pos in ("UTG", "CO", "BTN"):
            n, k = stats.opens[(name, pos)]
            assert n >= 100, f"too few {name} {pos} decisions: {n}"
            rates.append(k / n)
        assert rates[0] < rates[1] < rates[2], f"{name} opens UTG/CO/BTN: {rates}"
