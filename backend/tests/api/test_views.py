import json
import random
from dataclasses import replace

import numpy as np
import pytest

from poker_trainer.api import views
from poker_trainer.engine.cards import card_str, parse_cards
from poker_trainer.engine.combos import combo_index
from poker_trainer.engine.ranges import empty_range, parse_range
from poker_trainer.game.state import (
    Action,
    ActionKind,
    Street,
    amount_to_call,
    apply,
    deal,
    legal_actions,
    new_hand,
    total_pot,
)
from poker_trainer.puzzle.generate import generate_puzzle
from poker_trainer.puzzle.grade import Answer, grade
from poker_trainer.puzzle.model import (
    OptionEV,
    Puzzle,
    RangeView,
    Spot,
    load_config,
    option_ev_from_dict,
    option_ev_to_dict,
    visible_range,
)
from poker_trainer.puzzle.options import custom_action
from poker_trainer.puzzle.solve import solve
from poker_trainer.villain.features import load_thresholds
from poker_trainer.villain.narrowing import describe
from poker_trainer.villain.profiles import load_profile
from poker_trainer.villain.strategy import raise_to

SEEDS = {
    "pre_first_in": (1, "preflop"),
    "pre_facing": (3, "preflop"),
    "flop": (1, "flop"),
    "flop_b": (3, "flop"),
    "turn": (1, "turn"),
    "river": (1, "river"),
    "river_b": (2, "river"),
}
HERO = parse_cards("KhQh")
BOARD = parse_cards("Ks7h2c4d9s")
BAD_KEYS = {"range", "steps", "solution", "seed", "villain_hole", "runout", "combo_equity"}
# The exact PuzzleView schema: any new field must be added here deliberately (leak review).
VIEW_KEYS = {
    "id",
    "street",
    "hero_seat",
    "hero_position",
    "villain_position",
    "hero_cards",
    "board",
    "stacks",
    "street_bets",
    "pot",
    "to_call",
    "pot_odds",
    "history",
    "villain_profile",
    "options",
    "custom",
    "range_read_asked",
    "attempts_so_far",
}


def _river_checked():
    """BTN (seat 0) opens, BB calls, checked down; BB checks the river; Hero (seat 0) to act."""
    s = new_hand(0)
    s = apply(s, raise_to(s, 2.5))
    s = apply(s, Action(1, ActionKind.CALL, Street.PREFLOP, 5))
    s = deal(s, BOARD[:3])
    for cards in (BOARD[3:4], BOARD[4:]):  # flop and turn checked down, then deal
        s = apply(s, Action(s.to_act, ActionKind.CHECK, s.street))
        s = apply(s, Action(s.to_act, ActionKind.CHECK, s.street))
        s = deal(s, cards)
    return apply(s, Action(s.to_act, ActionKind.CHECK, s.street))


def _range_d():
    return visible_range(parse_range("AsKd, JcTc"), HERO, BOARD)


def _respond(s2):
    """AsKd calls any bet, JcTc folds; Villain checks behind when not facing a bet."""
    r = _range_d()
    ak = np.zeros_like(r)
    ak[combo_index(*parse_cards("AsKd"))] = 1.0
    jt = np.zeros_like(r)
    jt[combo_index(*parse_cards("JcTc"))] = 1.0
    me, st = s2.to_act, s2.street
    if legal_actions(s2).call > 0:
        return {
            Action(me, ActionKind.FOLD, st): jt,
            Action(me, ActionKind.CALL, st, s2.street_bets[me] + legal_actions(s2).call): ak,
        }
    return {Action(me, ActionKind.CHECK, st): ak + jt}


@pytest.fixture(scope="module")
def puzzles():
    return {k: generate_puzzle(seed, street=st) for k, (seed, st) in SEEDS.items()}


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def _view(p, **kw):
    kw.setdefault("custom_sizes_allowed", True)
    kw.setdefault("attempts_so_far", 0)
    return views.puzzle_view(7, p, **kw)


def _attempt_dict(p, g, *, option_index=None, custom_to=None, intent=None):
    return {
        "id": 3,
        "puzzle_id": 7,
        "attempt_no": 1,
        "is_first": True,
        "created_at": "2026-11-11T10:00:00+00:00",
        "option_index": option_index,
        "custom_to": custom_to,
        "action": {
            "seat": g.chosen.option.action.seat,
            "kind": g.chosen.option.action.kind.value,
            "street": int(g.chosen.option.action.street),
            "to": g.chosen.option.action.to,
        },
        "equity_guess": 0.4,
        "range_read_guess": 0.5,
        "intent": intent,
        "verdict": g.verdict,
        "ev_loss_chips": g.ev_loss_chips,
        "equity_error": g.equity_error,
        "equity_score": g.equity_score,
        "range_read_error": g.range_read_error,
        "range_read_score": g.range_read_score,
        "intent_truth": g.intent_truth,
        "intent_flag": g.intent_flag,
        "bluff_required": None if g.bluff_check is None else g.bluff_check[0],
        "bluff_actual": None if g.bluff_check is None else g.bluff_check[1],
        "best_label": g.best.option.label,
    }


def _result(p, idx=0, **kw):
    o = p.solution.options[idx]
    g = grade(p, Answer(o.option.action, 0.4, 0.5))
    return views.attempt_result(
        attempt=_attempt_dict(p, g, option_index=idx, **kw), puzzle=p, chosen=g.chosen
    ), g


def test_puzzle_view_hides_villain(puzzles):
    for p in puzzles.values():
        text = json.dumps(_view(p), allow_nan=False)
        sp = p.spot
        hidden = [*sp.villain_hole, *sp.runout[len(sp.state.board) :]]
        for c in hidden:
            assert f'"{card_str(c)}"' not in text
        assert not BAD_KEYS & set(_keys(_view(p)))
        sol = p.solution
        secret_floats = [sol.equity, sol.equity_std_error]
        secret_floats += [sol.ahead_now] if sol.ahead_now is not None else []
        for o in sol.options:
            secret_floats += [o.ev_chips, o.fold_freq, o.equity_vs_continue, o.ahead_vs_continue]
        for f in secret_floats:
            if f is not None and f not in (0.0, 1.0):
                assert repr(float(f)) not in text
        v = _view(p)
        assert set(v) == VIEW_KEYS
        assert {k for o in v["options"] for k in o} == {"index", "label", "kind", "to"}
        assert {k for e in v["history"] for k in e} <= {"street", "actor", "kind", "to", "text"}
        assert set(v["custom"]) == {"allowed", "min_to", "max_to"}
        assert set(v["villain_profile"]) == {"name", "label", "description"}
        assert len(v["board"]) == len(sp.state.board)


def test_action_log_replays_to_state(puzzles):
    for p in puzzles.values():
        sp = p.spot
        log, final = views._replay(sp)
        assert final == sp.state
        assert views.action_log(sp) == log
        assert len(log) == len(sp.state.history)
        for e, a in zip(log, sp.state.history, strict=True):
            assert e["actor"] == ("hero" if a.seat == sp.hero_seat else "villain")
            assert (e["kind"], e["to"]) == (a.kind.value, a.to)
            assert e["text"].startswith({0: "Pre-flop", 1: "Flop", 2: "Turn", 3: "River"}[a.street])
        # Villain's texts are exactly the narrowing tracker's step labels from generation
        # (describe() on the true state before each Villain action), e.g. "bets 8 (80% pot)".
        assert [e["text"] for e in log if e["actor"] == "villain"] == [
            v.label for v in sp.steps[1:]
        ]
    p = puzzles["flop"]
    log, _ = views._replay(p.spot)
    assert log[0]["text"] == describe(p.spot.state.history[0], new_hand(p.spot.state.button))
    assert any("% pot)" in e["text"] for e in views.action_log(puzzles["river"].spot))


def test_puzzle_view_numbers(puzzles):
    for p in puzzles.values():
        s = p.spot.state
        v = _view(p)
        assert v["pot"] == total_pot(s)
        assert v["to_call"] == amount_to_call(s)
        has_call = any(o.option.action.kind == ActionKind.CALL for o in p.solution.options)
        assert v["pot_odds"] == (p.solution.pot_odds if has_call else None)
        assert [(o["label"], o["kind"], o["to"]) for o in v["options"]] == [
            (o.option.label, o.option.action.kind.value, o.option.action.to)
            for o in p.solution.options
        ]
        assert [o["index"] for o in v["options"]] == list(range(len(v["options"])))
        assert v["range_read_asked"] == (s.street != Street.RIVER)
        assert v["hero_cards"] == [card_str(c) for c in p.spot.hero]
        assert {v["hero_position"], v["villain_position"]} == {"BTN", "BB"}
        assert v["villain_profile"]["name"] == p.spot.profile
    first_in = _view(puzzles["pre_first_in"])
    assert first_in["pot_odds"] is None
    assert _view(puzzles["pre_facing"])["pot_odds"] is not None
    assert _view(puzzles["river"], attempts_so_far=2)["attempts_so_far"] == 2


def test_custom_view_and_allowed(puzzles, monkeypatch):
    pre = puzzles["pre_first_in"]
    assert views.custom_bounds(pre) == (None, None)
    assert not views.custom_allowed(pre)
    assert _view(pre)["custom"] == {"allowed": False, "min_to": None, "max_to": None}

    p = puzzles["flop"]
    lo, hi = views.custom_bounds(p)
    assert lo is not None and hi is not None
    assert views.custom_allowed(p)
    assert _view(p)["custom"] == {"allowed": True, "min_to": lo, "max_to": hi}
    assert _view(p, custom_sizes_allowed=False)["custom"]["allowed"] is False
    custom_action(p.spot.state, lo)  # bounds are legal

    prof = load_profile(p.spot.profile)
    monkeypatch.setattr(views, "load_profile", lambda name: replace(prof, version=prof.version + 1))
    assert not views.custom_allowed(p)
    monkeypatch.undo()
    cats = views.load_thresholds()
    monkeypatch.setattr(views, "load_thresholds", lambda: replace(cats, version=cats.version + 1))
    assert not views.custom_allowed(p)


def test_range_grid_unblocked_mean():
    hero = parse_cards("AhAs")
    r = empty_range()
    r[combo_index(*parse_cards("AcAd"))] = 0.5  # the only unblocked AA combo
    r[combo_index(*parse_cards("AhAd"))] = 1.0  # blocked by Hero; must be ignored
    grid = views.range_grid(r, hero)
    assert len(grid) == 13 and all(len(row) == 13 for row in grid)
    assert grid[0][0] == pytest.approx(0.5)  # AA: mean over 1 unblocked combo
    # AKs: 4 combos, Ah/As ones blocked, AcKc and AdKd live with weight 0
    assert grid[0][1] == 0.0
    # naive class mean would be diluted: 1.5 / 6
    assert grid[0][0] != pytest.approx(1.5 / 6)
    # all-blocked cell: every ace is dead (Hero's two plus two on the board)
    dead = (*hero, *parse_cards("AcAd"))
    assert views.range_grid(r, dead)[0][0] is None


def test_range_combos():
    r = empty_range()
    r[combo_index(*parse_cards("AsKd"))] = 0.25
    assert views.range_combos(r) == [["AsKd", 0.25]]


def test_attempt_result_shape(puzzles):
    for key, p in puzzles.items():
        n = len(p.solution.options)
        res, g = _result(p, idx=n - 1)
        json.dumps(res, allow_nan=False)
        assert sum(o["is_best"] for o in res["options"]) == 1
        assert sum(o["is_chosen"] for o in res["options"]) == 1
        best = next(o for o in res["options"] if o["is_best"])
        assert best["label"] == p.solution.options[p.solution.best].option.label
        assert best["label"] == res["grade"]["best_label"]
        assert best["ev_chips"] == p.solution.options[p.solution.best].ev_chips
        assert res["options"][n - 1]["is_chosen"]
        assert len(res["options"]) == n
        assert res["grade"]["verdict"] == g.verdict
        assert res["grade"]["equity"] == p.solution.equity
        assert res["reveal"]["runout"] == [card_str(c) for c in p.spot.runout]
        assert len(res["range_steps"]) == len(p.spot.steps)
        step = res["range_steps"][0]
        assert len(step["grid"]) == 13 and len(step["grid"][0]) == 13
        assert all(isinstance(c[0], str) and len(c[0]) == 4 for c in step["combos"])
        assert res["judged_on_range_note"]
        for s in res["simplifications"]:
            assert s["text"]
        if key.startswith("pre"):
            assert res["categories"] is None
        else:
            assert res["categories"]
            assert all(c["name"] for c in res["categories"])
        assert res["attempt"]["created_at"].endswith("+00:00")


def test_attempt_result_custom_chosen_appended(puzzles):
    p = puzzles["river_b"]
    lo, hi = views.custom_bounds(p)
    listed = {o.option.action.to for o in p.solution.options}
    to = next(t for t in range(lo, hi + 1) if t not in listed)
    g = grade(p, Answer(custom_action(p.spot.state, to), 0.4))
    res = views.attempt_result(attempt=_attempt_dict(p, g, custom_to=to), puzzle=p, chosen=g.chosen)
    assert len(res["options"]) == len(p.solution.options) + 1
    last = res["options"][-1]
    assert last["is_chosen"] and not last["is_best"] and last["to"] == to
    assert sum(o["is_chosen"] for o in res["options"]) == 1
    assert res["answer"]["custom_to"] == to
    json.dumps(res, allow_nan=False)


def test_attempt_result_custom_equal_to_listed(puzzles):
    """A custom size equal to a listed option grades as that option and is not appended."""
    p = puzzles["flop"]
    idx, listed = next(
        (i, o) for i, o in enumerate(p.solution.options) if o.option.action.kind == ActionKind.BET
    )
    g = grade(p, Answer(custom_action(p.spot.state, listed.option.action.to), 0.4, 0.5))
    chosen = option_ev_from_dict(option_ev_to_dict(g.chosen))  # as the service stores it
    att = _attempt_dict(p, g, custom_to=listed.option.action.to)
    res = views.attempt_result(attempt=att, puzzle=p, chosen=chosen)
    assert len(res["options"]) == len(p.solution.options)
    assert [o["is_chosen"] for o in res["options"]].index(True) == idx
    assert res["answer"]["chosen_label"] == listed.option.label


def test_custom_bounds_facing_all_in(puzzles):
    """Facing an all-in there is nothing to raise: no custom sizes, no bounds."""
    p = puzzles["flop"]
    s = p.spot.state
    shove = apply(s, Action(s.to_act, ActionKind.BET, s.street, s.stacks[s.to_act]))
    assert legal_actions(shove).aggressive is None
    q = Puzzle(replace(p.spot, state=shove, hero_seat=shove.to_act), p.solution)
    assert views.custom_bounds(q) == (None, None)
    assert not views.custom_allowed(q)


def test_attempt_result_simplifications_and_bluff(puzzles):
    p = puzzles["pre_first_in"]
    res, _ = _result(p, idx=1)
    codes = {s["code"] for s in res["simplifications"]}
    assert codes >= set(p.solution.simplifications) | set(p.solution.options[1].simplifications)
    assert res["categories"] is None
    p = puzzles["flop"]
    res, g = _result(p, idx=1)
    bc = res["grade"]["bluff_check"]
    assert (bc is None) == (g.bluff_check is None)
    if bc:
        assert bc == {"required": g.bluff_check[0], "actual": g.bluff_check[1]}


def test_option_ev_aliases_round_trip(puzzles):
    o = puzzles["flop"].solution.options[1]
    back = option_ev_from_dict(option_ev_to_dict(o))
    assert isinstance(back, OptionEV)
    assert option_ev_to_dict(back) == option_ev_to_dict(o)


def _known_river(villain: str) -> Puzzle:
    s = _river_checked()
    sol = solve(s, HERO, _range_d(), _respond, rng=random.Random(0), samples=2000)
    board = tuple(s.board)
    spot = Spot(
        seed=0,
        attempt=0,
        state=s,
        hero_seat=s.to_act,
        hero=HERO,
        villain_hole=parse_cards(villain),
        runout=board,
        profile="tag",
        profile_version=load_profile("tag").version,
        categories_version=load_thresholds().version,
        config_version=load_config().version,
        steps=(RangeView("d", s.street, _range_d()),),
    )
    return Puzzle(spot, sol)


def test_showdown_known_river():
    # Hero KhQh on Ks7h2c4d9s: pair of kings, queen kicker
    lose = views.showdown(_known_river("AsKd").spot)  # Villain has the ace kicker
    assert lose == {"hero_hand": "Pair", "villain_hand": "Pair", "winner": "villain"}
    win = views.showdown(_known_river("Kd2d").spot)  # kings and deuces beat Hero's one pair
    assert win["villain_hand"] == "Two pair" and win["winner"] == "villain"
    hero_wins = views.showdown(_known_river("Jd8d").spot)
    assert hero_wins == {"hero_hand": "Pair", "villain_hand": "High card", "winner": "hero"}
    split = views.showdown(_known_river("KdQc").spot)  # same pair, same kicker
    assert split["winner"] == "split"
    assert split["hero_hand"] == split["villain_hand"] == "Pair"
    with pytest.raises(ValueError):
        views.showdown(replace(_known_river("AsKd").spot, runout=()))


def test_known_river_result_reveal():
    p = _known_river("AsKd")
    res, _ = _result(p, idx=0)
    assert res["reveal"]["villain_cards"] == ["As", "Kd"]
    assert res["reveal"]["showdown"]["winner"] == "villain"
    assert np.isfinite(res["grade"]["equity"])
