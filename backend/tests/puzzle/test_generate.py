import random
import time
from collections import Counter

import numpy as np
import pytest

from poker_trainer.engine.ranges import full_range, total_weight
from poker_trainer.game.state import (
    Action,
    ActionKind,
    Street,
    apply,
    deal,
    legal_actions,
    new_hand,
)
from poker_trainer.puzzle import generate
from poker_trainer.puzzle.cli import main
from poker_trainer.puzzle.generate import generate_puzzle, generate_spot
from poker_trainer.puzzle.model import load_config, puzzle_to_dict, visible_range
from poker_trainer.villain.profiles import PROFILE_NAMES
from poker_trainer.villain.strategy import OPEN_MULT, allin, raise_to

STREETS = [Street.PREFLOP, Street.FLOP, Street.TURN, Street.RIVER]


@pytest.fixture(scope="module")
def puzzles():
    """One puzzle per (street, profile) pair, varied seeds."""
    out = []
    for i, street in enumerate(STREETS):
        for j, prof in enumerate(PROFILE_NAMES):
            out.append(generate_puzzle(100 + 10 * i + j, street=street, profile=prof))
    return out


def test_generate_deterministic():
    a = generate_puzzle(7)
    b = generate_puzzle(7)
    assert puzzle_to_dict(a) == puzzle_to_dict(b)
    assert puzzle_to_dict(generate_puzzle(8)) != puzzle_to_dict(a)


def test_generate_respects_street_and_profile(puzzles):
    for i, street in enumerate(STREETS):
        for j, prof in enumerate(PROFILE_NAMES):
            p = puzzles[i * len(PROFILE_NAMES) + j]
            assert p.spot.state.street == street
            assert p.spot.profile == prof
    p = generate_puzzle(3, street="turn", profile="lag")
    assert p.spot.state.street == Street.TURN and p.spot.profile == "lag"


def test_hero_to_act_at_decision(puzzles):
    for p in puzzles:
        s = p.spot.state
        assert s.to_act == p.spot.hero_seat
        assert s.folded is None


def test_runout_consistent(puzzles):
    for p in puzzles:
        sp = p.spot
        board = tuple(sp.state.board)
        assert len(sp.runout) == 5
        assert sp.runout[: len(board)] == board
        cards = [*sp.hero, *sp.villain_hole, *sp.runout]
        assert len(set(cards)) == 9
        assert all(0 <= c < 52 for c in cards)


def test_steps_start_full_and_end_at_range(puzzles):
    for p in puzzles:
        sp = p.spot
        board = tuple(sp.state.board)
        first, last = sp.steps[0], sp.steps[-1]
        assert first.label == "Start" and first.street == Street.PREFLOP
        np.testing.assert_array_equal(first.range, visible_range(full_range(), sp.hero, board))
        assert sp.range is last.range
        assert sp.config_version == load_config().version
        assert total_weight(sp.range) > 0
        for v in sp.steps:
            assert v.street <= sp.state.street
            # every step is the visible range at the decision board
            np.testing.assert_array_equal(v.range, visible_range(v.range, sp.hero, board))
        # one step per Villain action, plus Start
        villain_actions = [a for a in sp.state.history if a.seat != sp.hero_seat]
        assert len(sp.steps) == len(villain_actions) + 1


def test_generate_spot_failure_returns_none_or_spot():
    rng = random.Random(0)
    results = [generate_spot(rng, Street.RIVER, "tight", seed=0, attempt=k) for k in range(30)]
    assert any(r is None for r in results)
    assert any(r is not None for r in results)


def test_cli_runs(capsys):
    assert main(["--n", "2", "--seed", "1"]) == 0
    out = capsys.readouterr().out
    assert out.count("seed ") == 2
    out.encode("ascii")  # plain ASCII for Windows consoles


def test_street_mix_not_biased():
    streets = Counter(generate_puzzle(seed).spot.state.street for seed in range(40))
    assert set(streets) == set(STREETS)
    assert streets[Street.PREFLOP] / 40 <= 0.40


@pytest.mark.slow
def test_generation_speed():
    times = []
    for seed in range(10):
        t = time.perf_counter()
        generate_puzzle(1000 + seed)
        times.append(time.perf_counter() - t)
    mean = sum(times) / len(times)
    print(f"mean generation time: {mean:.3f} s over {len(times)} seeds")
    assert mean < 6.0


def test_generate_raises_after_max_attempts(monkeypatch):
    calls = []

    def never(*args, **kwargs):
        calls.append(kwargs["attempt"])

    monkeypatch.setattr(generate, "generate_spot", never)
    with pytest.raises(RuntimeError, match="no puzzle for seed 5"):
        generate_puzzle(5, street="flop", profile="tag")
    assert calls == list(range(load_config().max_attempts))


def test_cli_rejects_unknown_profile(capsys):
    with pytest.raises(SystemExit):
        main(["--n", "1", "--profile", "nobody"])
    assert "invalid choice" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Paused spots (pre-M7 fixes): BB facing a non-all-in open is not generated until M9
# ---------------------------------------------------------------------------


def _preflop_kind(spot) -> str:
    s = spot.state
    acts = [a for a in s.history if a.street == Street.PREFLOP]
    hero_is_btn = spot.hero_seat == s.button
    can_raise = legal_actions(s).aggressive is not None
    if hero_is_btn and not acts:
        return "btn_first_in"
    if not hero_is_btn and len(acts) == 1 and can_raise:
        return "bb_vs_open"
    if hero_is_btn and len(acts) == 2:
        return "btn_vs_3bet"
    if not hero_is_btn and not can_raise:
        return "bb_vs_jam"
    return "other"


def _preflop_spots(paused=None, n=20000):
    """Spot kinds over ``n`` pre-flop attempts (no solving: generate_spot is cheap)."""
    rng = random.Random(11)
    kinds = Counter()
    for k in range(n):
        prof = PROFILE_NAMES[k % len(PROFILE_NAMES)]
        spot = generate_spot(rng, Street.PREFLOP, prof, seed=11, attempt=k, paused=paused)
        if spot is not None:
            kinds[_preflop_kind(spot)] += 1
    return kinds


def test_paused_bb_vs_open_never_generated_other_preflop_spots_are():
    paused = _preflop_spots()
    unpaused = _preflop_spots(paused=())
    assert paused["bb_vs_open"] == 0 and unpaused["bb_vs_open"] > 0, (paused, unpaused)
    # The pause only fails the attempt at that decision: every other kind is unaffected.
    assert paused == unpaused - Counter({"bb_vs_open": unpaused["bb_vs_open"]})
    assert paused["btn_first_in"] > 0 and paused["btn_vs_3bet"] > 0, paused
    assert paused["bb_vs_jam"] > 0 and paused["other"] == 0, paused


def test_paused_spot_helper():
    s = new_hand(0)  # seat 0 is the button
    assert not generate._paused_spot(s, 0, ("preflop_bb_vs_open",))  # BTN first in
    opened = apply(s, raise_to(s, OPEN_MULT))
    assert generate._paused_spot(opened, 1, ("preflop_bb_vs_open",))
    assert not generate._paused_spot(opened, 1, ())
    threebet = apply(opened, raise_to(opened, 3.0))
    assert not generate._paused_spot(threebet, 0, ("preflop_bb_vs_open",))  # BTN vs 3-bet
    short = new_hand(0, (8, 8))
    jammed = apply(short, allin(short))  # an open-jam leaves BB unable to raise
    assert not generate._paused_spot(jammed, 1, ("preflop_bb_vs_open",))
    flop = deal(apply(opened, Action(1, ActionKind.CALL, Street.PREFLOP, 5)), (0, 1, 2))
    assert not generate._paused_spot(flop, 1, ("preflop_bb_vs_open",))


def test_no_bb_vs_open_puzzle_over_seeds():
    kinds = Counter()
    for seed in range(40):
        p = generate_puzzle(seed, street="preflop")
        assert p.spot.config_version == load_config().version
        kinds[_preflop_kind(p.spot)] += 1
    # BTN facing a 3-bet and BB facing a jam are rare puzzles: the spot-level test above
    # shows they are still generated.
    assert kinds["bb_vs_open"] == 0 and kinds["btn_first_in"] > 0, kinds
