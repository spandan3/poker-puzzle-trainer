"""Pure play views: the table, its frames, the hand and session views, and what they never leak."""

import json
import random
from dataclasses import replace

import pytest
from pydantic import ValidationError

from poker_trainer.api import play_views, schemas, views
from poker_trainer.engine.cards import card_str
from poker_trainer.game.settle import settle_pots
from poker_trainer.game.state import ActionKind, Street, folded_seats, legal_actions, live_seats
from poker_trainer.play.analyse import analyse_decision, hero_decisions
from poker_trainer.play.hand import (
    HandRecord,
    SeatBot,
    advance,
    advance_seats,
    bot_cards,
    hero_act,
    hero_act_seats,
    hole,
    holes,
    outcome,
    outcome5,
    replay,
)
from poker_trainer.play.session import new_record, new_record5
from poker_trainer.puzzle.options import hero_options
from poker_trainer.villain.profiles import PROFILE_NAMES, load_profile

STACKS = (200, 200)


def _hand(seed: int, *, stacks=STACKS):
    """A seeded hand played to the end by a random Hero; returns (record, profile)."""
    profile = load_profile(PROFILE_NAMES[seed % len(PROFILE_NAMES)])
    r = advance(new_record(seed % 2, stacks, random.Random(seed)), profile)
    rng = random.Random(f"hero:{seed}")
    while outcome(r) is None:
        r = hero_act(r, profile, rng.choice(hero_options(replay(r))).action)
    return r, profile


def _find(pred, limit: int = 400):
    for seed in range(limit):
        r, profile = _hand(seed)
        if pred(r):
            return r, profile
    raise AssertionError("no hand matched")


def _at_decision(r: HandRecord, n: int) -> HandRecord:
    """The record as it stood when Hero was to act for the n-th time."""
    return replace(r, actions=r.actions[: hero_decisions(r)[n]])


def _view(r: HandRecord, profile, *, decision_count: int | None = None):
    n = len(hero_decisions(r)) if decision_count is None else decision_count
    return play_views.hand_view(5, 3, 2, r, profile, decision_count=n)


# ---------------------------------------------------------------------------
# table_view
# ---------------------------------------------------------------------------


def _flop_or_later_decision():
    for seed in range(300):
        r, profile = _hand(seed)
        for n, i in enumerate(hero_decisions(r)):
            if r.actions[i].street >= Street.FLOP:
                return r, profile, n
    raise AssertionError("no post-flop decision")


def test_table_view_matches_puzzle_view_for_the_same_spot():
    r, profile, n = _flop_or_later_decision()
    edited = replace(profile, label="Edited label", description="Edited description")
    analysis = analyse_decision(r, profile, n, samples=500)
    assert analysis.puzzle is not None
    pv = views.puzzle_view(1, analysis.puzzle, custom_sizes_allowed=False, attempts_so_far=0)
    tv = play_views.table_view(_at_decision(r, n), edited)
    for key in (
        "street",
        "hero_seat",
        "hero_position",
        "villain_position",
        "hero_cards",
        "to_call",
        "pot_odds",
        "stacks",
        "street_bets",
        "pot",
        "board",
        "history",
    ):
        assert tv[key] == pv[key], key
    assert set(tv) == set(schemas.TableView.model_fields)
    assert tv["villain_profile"] == {
        "name": profile.name,
        "label": "Edited label",
        "description": "Edited description",
    }
    assert tv["to_call"] > 0 or tv["pot_odds"] is None


def test_table_view_pot_odds_only_when_facing_a_bet():
    for seed in range(40):
        r, profile = _hand(seed)
        for n in range(len(hero_decisions(r))):
            tv = play_views.table_view(_at_decision(r, n), profile)
            assert (tv["pot_odds"] is not None) == (tv["to_call"] > 0)


# ---------------------------------------------------------------------------
# frames
# ---------------------------------------------------------------------------


def test_frames_follow_the_history_and_conserve_chips():
    saw_river = False
    for seed in range(60):
        r, profile = _hand(seed)
        v = _view(r, profile)
        history = v["table"]["history"]
        frames = v["frames"]
        assert len(frames) == len(history) + 1
        assert sorted(frames[0]["street_bets"]) == [1, 2] and frames[0]["board_len"] == 0
        assert frames[0]["pot"] == 3
        for f in frames:
            assert sum(f["stacks"]) + f["pot"] == sum(r.start_stacks)
        lens = [f["board_len"] for f in frames]
        assert lens == sorted(lens) and set(lens) <= {0, 3, 4, 5}
        if 5 in lens:
            saw_river = True
        # the table during play: the last frame is the state after the last action
        s = replay(r)
        last = frames[-1]
        assert last["board_len"] == len(s.board)
    assert saw_river


def test_frame_steps_through_every_street_when_the_hand_goes_to_the_river():
    r, profile = _find(lambda r: len(replay(r).board) == 5 and replay(r).street == Street.RIVER)
    lens = [f["board_len"] for f in _view(r, profile)["frames"]]
    assert {0, 3, 4, 5} <= set(lens)
    assert lens == sorted(lens)


def test_last_frame_of_a_running_hand_equals_the_table():
    r, profile, n = _flop_or_later_decision()
    v = _view(_at_decision(r, n), profile)
    t, last = v["table"], v["frames"][-1]
    assert last["stacks"] == t["stacks"]
    assert last["street_bets"] == t["street_bets"]
    assert last["pot"] == t["pot"]
    assert last["board_len"] == len(t["board"])
    assert last["to_act"] == "hero"


def test_frames_to_act():
    r, profile = _find(lambda r: outcome(r).ended_by == "fold")
    frames = _view(r, profile)["frames"]
    assert frames[-1]["to_act"] is None
    assert frames[0]["to_act"] in ("hero", "villain")


# ---------------------------------------------------------------------------
# hand_view: running and finished
# ---------------------------------------------------------------------------


def test_running_hand_has_options_and_custom_bounds():
    r, profile, n = _flop_or_later_decision()
    rec = _at_decision(r, n)
    v = _view(rec, profile, decision_count=n)
    s = replay(rec)
    assert v["status"] == "in_progress" and v["outcome"] is None
    assert (v["id"], v["hand_no"], v["session_id"]) == (5, 3, 2)
    assert v["action_count"] == len(rec.actions) and v["decision_count"] == n
    assert [o["index"] for o in v["options"]] == list(range(len(v["options"])))
    assert [(o["label"], o["kind"], o["to"]) for o in v["options"]] == [
        (o.label, o.action.kind.value, o.action.to) for o in hero_options(s)
    ]
    lg = legal_actions(s)
    if lg.aggressive is None:
        assert v["custom"] == {"allowed": False, "min_to": None, "max_to": None}
    else:
        assert v["custom"] == {"allowed": True, "min_to": lg.min_to, "max_to": lg.max_to}


def test_custom_sizes_are_off_preflop():
    r, profile = _hand(1)
    v = _view(_at_decision(r, 0), profile)
    assert replay(_at_decision(r, 0)).street == Street.PREFLOP
    assert v["custom"] == {"allowed": False, "min_to": None, "max_to": None}
    assert v["options"]


def test_finished_showdown_hand():
    r, profile = _find(lambda r: outcome(r).ended_by == "showdown")
    v = _view(r, profile)
    o = outcome(r)
    assert v["status"] == "complete" and v["options"] == []
    assert v["custom"] == {"allowed": False, "min_to": None, "max_to": None}
    t = v["table"]
    assert t["stacks"] == list(o.stacks)
    assert t["street_bets"] == [0, 0]
    assert t["pot"] == sum(r.start_stacks) - sum(replay(r).stacks)
    assert t["to_call"] == 0 and t["pot_odds"] is None
    assert len(t["board"]) == 5
    out = v["outcome"]
    assert out["ended_by"] == "showdown" and out["winner"] == o.winner
    assert out["hero_delta_chips"] == o.hero_delta and out["hero_delta_bb"] == o.hero_delta / 2
    assert out["villain_cards"] == [card_str(c) for c in bot_cards(r)]
    assert set(out["showdown"]) == {"hero_hand", "villain_hand", "winner"}
    assert out["showdown"]["winner"] == o.winner
    # frames describe the table during play: the last one is before the award
    last = v["frames"][-1]
    assert last["board_len"] == 5 and last["to_act"] is None
    assert last["stacks"] != t["stacks"] or last["pot"] != t["pot"]


def test_finished_fold_hand_hides_the_bot_cards():
    r, profile = _find(lambda r: outcome(r).ended_by == "fold")
    v = _view(r, profile)
    assert v["status"] == "complete" and v["options"] == []
    assert v["outcome"]["villain_cards"] is None and v["outcome"]["showdown"] is None
    assert v["table"]["street_bets"] == [0, 0]
    assert sum(v["table"]["stacks"]) == sum(r.start_stacks)
    assert v["table"]["stacks"] == list(outcome(r).stacks)


def test_abandoned_hand_hides_the_bot_cards():
    r, profile, n = _flop_or_later_decision()
    rec = replace(_at_decision(r, n), abandoned=True)
    v = _view(rec, profile)
    assert v["status"] == "complete" and v["options"] == []
    assert v["custom"]["allowed"] is False
    assert v["outcome"]["ended_by"] == "abandoned"
    assert v["outcome"]["villain_cards"] is None and v["outcome"]["showdown"] is None
    assert v["table"]["street_bets"] == [0, 0]
    assert v["table"]["stacks"] == list(outcome(rec).stacks)


def test_no_leak_over_seeded_hands():
    for seed in range(200):
        r, profile = _hand(seed)
        bot = [card_str(c) for c in bot_cards(r)]
        runout = [card_str(c) for c in r.deck[4:9]]
        for k in range(len(r.actions) + 1):
            rec = replace(r, actions=r.actions[:k])
            v = _view(rec, profile)
            text = json.dumps(v)
            ended = v["outcome"]["ended_by"] if v["outcome"] else None
            for c in bot:
                assert (f'"{c}"' in text) == (ended == "showdown"), (seed, k, c)
            dealt = len(v["table"]["board"])
            assert v["table"]["board"] == runout[:dealt]
            for c in runout[dealt:]:
                assert f'"{c}"' not in text, (seed, k, c)
            assert "deck" not in text and "bot_seed" not in text
            assert "deck" not in v and "bot_seed" not in v


# ---------------------------------------------------------------------------
# session_view and schemas
# ---------------------------------------------------------------------------


def _fields(**kw):
    base = {
        "id": 2,
        "open": True,
        "profile": {"name": "tag", "label": "TAG", "description": "tight"},
        "hero_stack": 240,
        "bot_stack": 160,
        "hero_bought_chips": 200,
        "hands_played": 3,
    }
    return {**base, **kw}


def test_session_view_tally_and_rebuy_flags():
    sv = play_views.session_view(_fields(), None)
    assert sv["net_chips"] == 40 and sv["net_bb"] == 20.0
    assert sv["must_rebuy"] is False and sv["can_top_up"] is False
    assert sv["hand"] is None and sv["open"] is True
    low = play_views.session_view(_fields(hero_stack=150), None)
    assert low["can_top_up"] is True and low["must_rebuy"] is False
    broke = play_views.session_view(_fields(hero_stack=5, hero_bought_chips=400), None)
    assert broke["must_rebuy"] is True and broke["can_top_up"] is False
    assert broke["net_chips"] == -395
    ended = play_views.session_view(_fields(hero_stack=150, open=False), None)
    assert ended["can_top_up"] is False and ended["must_rebuy"] is False


def test_session_view_no_top_up_while_a_hand_runs():
    r, profile, n = _flop_or_later_decision()
    hv = _view(_at_decision(r, n), profile)
    sv = play_views.session_view(_fields(hero_stack=150), hv)
    assert sv["hand"] == hv
    assert sv["can_top_up"] is False and sv["must_rebuy"] is False


def test_views_validate_against_the_models():
    r, profile = _find(lambda r: outcome(r).ended_by == "showdown")
    for rec in (r, _at_decision(r, 0), replace(_at_decision(r, 0), abandoned=True)):
        hv = _view(rec, profile)
        schemas.PlayHandView.model_validate(hv)
        schemas.PlaySessionView.model_validate(play_views.session_view(_fields(), hv))
    schemas.PlaySessionView.model_validate(play_views.session_view(_fields(), None))


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (
            schemas.TableFrame,
            {"stacks": [1, 2], "street_bets": [0, 0], "pot": 0, "board_len": 0, "to_act": None},
        ),
        (
            schemas.PlayOutcome,
            {
                "ended_by": "fold",
                "winner": "hero",
                "hero_delta_chips": 2,
                "hero_delta_bb": 1.0,
                "villain_cards": None,
                "showdown": None,
            },
        ),
        (
            schemas.PlaySessionSummary,
            {
                "id": 1,
                "created_at": "x",
                "ended_at": None,
                "profile_label": "TAG",
                "hands_played": 0,
                "net_bb": 0.0,
                "open": True,
            },
        ),
        (
            schemas.PlayHandSummary,
            {
                "id": 1,
                "hand_no": 1,
                "hero_position": "BB",
                "result_bb": None,
                "ended_by": None,
                "decision_count": 0,
                "analysed": False,
                "ev_loss_bb": None,
            },
        ),
    ],
)
def test_new_models_forbid_extra_keys(model, data):
    model.model_validate(data)
    with pytest.raises(ValidationError):
        model.model_validate({**data, "extra": 1})


def test_table_and_hand_models_forbid_extra_keys():
    r, profile = _find(lambda r: outcome(r).ended_by == "fold")
    hv = _view(r, profile)
    for model, data in (
        (schemas.TableView, hv["table"]),
        (schemas.PlayHandView, hv),
        (schemas.PlaySessionView, play_views.session_view(_fields(), hv)),
    ):
        with pytest.raises(ValidationError):
            model.model_validate({**data, "extra": 1})


def test_request_models():
    assert schemas.PlayActionIn(expected_actions=2, option=0).custom_to is None
    assert schemas.PlayActionIn(expected_actions=2, custom_to=12).option is None
    for bad in (
        {"expected_actions": 2},
        {"expected_actions": 2, "option": 0, "custom_to": 5},
        {"option": 0},
        {"expected_actions": 2, "option": 0, "extra": 1},
        {"expected_actions": "2", "option": 0},
    ):
        with pytest.raises(ValidationError):
            schemas.PlayActionIn.model_validate(bad)
    assert schemas.NextHandIn(expected_hands=0).top_up is False
    assert schemas.NextHandIn(expected_hands=3, top_up=True).top_up is True
    for bad in (
        {},
        {"expected_hands": -1},
        {"expected_hands": "1"},
        {"expected_hands": 0, "top_up": 1},
    ):
        with pytest.raises(ValidationError):
            schemas.NextHandIn.model_validate(bad)


# ---------------------------------------------------------------------------
# the pot award (M11 S10): table.pot of a finished hand is what the winner was awarded
# ---------------------------------------------------------------------------


def test_the_pot_shown_is_the_award_over_seeded_hands():
    seen = {"fold": 0, "showdown": 0, "split": 0, "all_in": 0, "unequal_all_in": 0}
    for seed in range(200):
        stacks = STACKS if seed % 2 == 0 else (200, 60 + seed % 70)
        stacks = stacks if seed % 4 < 2 else stacks[::-1]
        r, profile = _hand(seed, stacks=stacks)
        v = _view(r, profile)
        out = v["outcome"]
        last = v["frames"][-1]
        assert v["table"]["pot"] == sum(r.start_stacks) - sum(last["stacks"])
        settled, before, pot = v["table"]["stacks"], last["stacks"], v["table"]["pot"]
        if out["winner"] == "split":
            assert settled[0] - before[0] == settled[1] - before[1] == pot // 2 and pot % 2 == 0
            seen["split"] += 1
        else:
            w = 0 if out["winner"] == "hero" else 1
            assert settled[w] - before[w] == pot, (seed, out["winner"])
            assert settled[1 - w] == before[1 - w], seed
        seen[out["ended_by"]] += 1
        seen["all_in"] += 0 in before
        seen["unequal_all_in"] += 0 in before and stacks[0] != stacks[1]
    assert all(seen.values()), seen


def test_an_abandoned_hands_pot_goes_to_the_bot():
    r, profile, n = _flop_or_later_decision()
    rec = replace(_at_decision(r, n), abandoned=True)
    v = _view(rec, profile)
    last, settled, pot = v["frames"][-1], v["table"]["stacks"], v["table"]["pot"]
    assert v["outcome"]["winner"] == "villain" and pot > 0
    assert settled[1] - last["stacks"][1] == pot
    assert settled[0] == last["stacks"][0]


# ---------------------------------------------------------------------------
# 5-max (M12): seat views, frames, pot awards and what they never leak
# ---------------------------------------------------------------------------

FIVE_BOTS = {name: SeatBot.live(name) for name in PROFILE_NAMES}
FIVE_POSITIONS = {"BTN", "SB", "BB", "UTG", "CO"}


def _seat_bots(seed: int) -> dict[int, SeatBot]:
    rng = random.Random(f"seats:{seed}")
    return {seat: FIVE_BOTS[rng.choice(PROFILE_NAMES)] for seat in range(1, 5)}


def _infos(bots: dict[int, SeatBot]):
    return [play_views.SeatBotInfo(s, f"Bot {s}", b.profile) for s, b in sorted(bots.items())]


def _hand5(seed: int):
    """A seeded 5-max hand played to the end by a random Hero (a jam now and then, so all-ins
    and side pots turn up), with uneven stacks; returns (record, bots)."""
    rng = random.Random(f"hand5:{seed}")
    stacks = (rng.randint(10, 400), *(rng.randint(80, 300) for _ in range(4)))
    bots = _seat_bots(seed)
    r = advance_seats(new_record5(seed % 5, stacks, random.Random(seed)), bots)
    while outcome5(r) is None:
        options = hero_options(replay(r))
        pick = options[-1] if rng.random() < 0.3 else rng.choice(options)
        r = hero_act_seats(r, bots, pick.action)
    return r, bots


def _view5(r: HandRecord, bots, *, decision_count: int = 0):
    return play_views.hand_view(7, 2, 3, r, None, decision_count=decision_count, bots=_infos(bots))


def _responses(r: HandRecord):
    """Every record the API can serve for this hand: Hero to act, the end, and an abandon at
    each Hero decision."""
    for i in hero_decisions(r):
        rec = replace(r, actions=r.actions[:i])
        yield rec
        yield replace(rec, abandoned=True)
    yield r


def _prefixes(r: HandRecord):
    """``_responses`` and the record after every action (more than the API serves)."""
    yield from _responses(r)
    for k in range(len(r.actions)):
        yield replace(r, actions=r.actions[:k])


def test_five_max_table_seats_and_positions():
    seen_buttons = set()
    for seed in range(40):
        r, bots = _hand5(seed)
        for rec in _responses(r):
            v = _view5(rec, bots)
            t = v["table"]
            schemas.PlayHandView.model_validate(v)
            assert t["table_size"] == 5 and len(t["seats"]) == 5
            assert t["villain_position"] is None and t["villain_profile"] is None
            assert len(t["stacks"]) == len(t["street_bets"]) == 5
            s = replay(rec)
            assert {x["position"] for x in t["seats"]} == FIVE_POSITIONS
            assert [x["is_button"] for x in t["seats"]] == [i == rec.button for i in range(5)]
            assert t["seats"][rec.button]["position"] == "BTN"
            assert [x["name"] for x in t["seats"]] == ["You", "Bot 1", "Bot 2", "Bot 3", "Bot 4"]
            assert [x["is_hero"] for x in t["seats"]] == [True, False, False, False, False]
            assert t["seats"][0]["profile"] is None and t["seats"][0]["cards"] == t["hero_cards"]
            for x in t["seats"][1:]:
                assert x["profile"]["name"] == bots[x["seat"]].profile.name
            assert [x["stack"] for x in t["seats"]] == t["stacks"]
            assert [x["street_bet"] for x in t["seats"]] == t["street_bets"]
            assert [x["folded"] for x in t["seats"]] == [i in folded_seats(s) for i in range(5)]
            done = v["outcome"] is not None
            for x in t["seats"]:
                assert x["all_in"] == (not done and not x["folded"] and s.stacks[x["seat"]] == 0)
            seen_buttons.add(rec.button)
    assert seen_buttons == set(range(5))


def test_five_max_frames_carry_seat_folds_and_live_pots():
    seen = {"side_pots": 0, "folds": 0}
    for seed in range(60):
        r, bots = _hand5(seed)
        frames = _view5(r, bots)["frames"]
        assert len(frames) == len(r.actions) + 1
        for k, f in enumerate(frames):
            schemas.TableFrame.model_validate(f)
            s = replay(replace(r, actions=r.actions[:k]))
            if k < len(r.actions):
                assert f["to_act_seat"] == r.actions[k].seat  # who acts next is who acted
            assert f["to_act"] == (
                None if f["to_act_seat"] is None else "hero" if f["to_act_seat"] == 0 else "villain"
            )
            folded = {a.seat for a in r.actions[:k] if a.kind == ActionKind.FOLD}
            assert f["folded"] == [i in folded for i in range(5)]
            assert sum(f["stacks"]) + f["pot"] == sum(r.start_stacks)
            middle = f["pot"] - sum(f["street_bets"])
            assert sum(f["pots"]) <= middle and all(p > 0 for p in f["pots"])
            if not any(st == 0 for st in s.stacks):  # nobody all-in: one pot, all of it
                assert f["pots"] == ([middle] if middle else [])
            seen["side_pots"] += len(f["pots"]) > 1
            seen["folds"] += any(f["folded"])
    assert all(seen.values()), seen


def test_five_max_live_pots_by_hand():
    """Three seats in the middle at 20, 50 and 50 (seat 1 all-in for 20): a main pot of 60 and
    a side pot of 60; the uncalled excess of a lone deeper seat is left out."""
    from poker_trainer.game.state import Action, Street, apply, deal, new_hand

    s = new_hand(0, (200, 20, 200, 200, 200))  # SB seat 1, BB seat 2, UTG seat 3 first
    for a in (
        Action(3, ActionKind.RAISE, Street.PREFLOP, 50),
        Action(4, ActionKind.FOLD, Street.PREFLOP, 0),
        Action(0, ActionKind.FOLD, Street.PREFLOP, 0),
        Action(1, ActionKind.CALL, Street.PREFLOP, 20),
        Action(2, ActionKind.CALL, Street.PREFLOP, 50),
    ):
        s = apply(s, a)
    s = deal(s, (0, 1, 2))
    assert play_views._live_pots(s, (200, 20, 200, 200, 200)) == [60, 60]
    s = apply(s, Action(2, ActionKind.BET, Street.FLOP, 100))
    assert play_views._live_pots(s, (200, 20, 200, 200, 200)) == [60, 60]  # bets in front
    s = apply(s, Action(3, ActionKind.CALL, Street.FLOP, 100))
    s = deal(s, (3,))
    assert play_views._live_pots(s, (200, 20, 200, 200, 200)) == [60, 260]


def test_five_max_pot_awards_match_settle_pots():
    seen = {"fold": 0, "showdown": 0, "side": 0, "uncalled": 0}
    for seed in range(300):
        r, bots = _hand5(seed)
        v = _view5(r, bots)
        out, t = v["outcome"], v["table"]
        o = outcome5(r)
        st = settle_pots(replay(r), holes(r), r.start_stacks)
        assert out["winner"] == o.winner and out["hero_delta_chips"] == o.hero_delta
        assert out["villain_cards"] is None and out["showdown"] is None
        assert [(p["amount"], p["eligible"], p["winners"]) for p in out["pots"]] == [
            (p.amount, list(p.eligible), list(p.winners)) for p in st.pots
        ]
        assert [p["label"] for p in out["pots"]] == [
            "main pot",
            *(f"side pot {k}" for k in range(1, len(out["pots"]))),
        ]
        assert t["stacks"] == list(st.stacks) and t["street_bets"] == [0] * 5
        assert sum(p["amount"] for p in out["pots"]) == t["pot"]
        assert sum(t["stacks"]) == sum(r.start_stacks)
        pot = sum(r.start_stacks) - sum(v["frames"][-1]["stacks"])
        seen["uncalled"] += t["pot"] < pot
        seen[out["ended_by"]] += 1
        seen["side"] += len(out["pots"]) > 1
        if out["ended_by"] == "fold":
            assert out["shown"] == []
        else:
            shown = [x["seat"] for x in out["shown"]]
            assert shown == list(o.shown)
            assert set(shown) == set(live_seats(replay(r))) - {0}
    assert all(seen.values()), seen


def test_five_max_abandoned_hand():
    r, bots = _hand5(3)
    rec = replace(r, actions=r.actions[: hero_decisions(r)[0]], abandoned=True)
    v = _view5(rec, bots)
    out = v["outcome"]
    assert out["ended_by"] == "abandoned" and out["winner"] == "villain"
    assert out["pots"] == [] and out["shown"] == []
    assert v["table"]["stacks"] == list(outcome5(rec).stacks)
    assert v["frames"][-1]["to_act"] is None and v["frames"][-1]["to_act_seat"] is None
    assert v["options"] == [] and v["status"] == "complete"


def _card_fields(v) -> list[str]:
    """Every card-typed field of a hand view."""
    t = v["table"]
    cards = [*t["hero_cards"], *t["board"]]
    for x in t["seats"]:
        cards += x["cards"] or []
    if v["outcome"] is not None:
        cards += v["outcome"]["villain_cards"] or []
        for x in v["outcome"]["shown"]:
            cards += x["cards"]
    return cards


def test_no_leak_over_300_seeded_five_max_hands():
    """No bot card in any response before a showdown, only the shown seats' after one, never a
    folded seat's (the last folder included), never an undealt board card."""
    shown_any = folded_after_bet = 0
    for seed in range(300):
        r, bots = _hand5(seed)
        runout = [card_str(c) for c in r.deck[10:15]]
        for rec in _prefixes(r):
            v = _view5(rec, bots)
            text = json.dumps(v)
            cards = _card_fields(v)
            out = v["outcome"]
            shown = {x["seat"] for x in out["shown"]} if out else set()
            if not (out and out["ended_by"] == "showdown"):
                assert shown == set()
            s = replay(rec)
            assert shown <= set(live_seats(s)) - {0}
            assert not shown & folded_seats(s)
            for seat in range(1, 5):
                for c in (card_str(x) for x in hole(rec, seat)):
                    visible = seat in shown
                    assert (c in cards) == visible, (seed, seat, c)
                    assert (f'"{c}"' in text) == visible, (seed, seat, c)
            dealt = len(v["table"]["board"])
            assert v["table"]["board"] == runout[:dealt]
            for c in runout[dealt:]:
                assert f'"{c}"' not in text, (seed, c)
            assert "deck" not in text and "bot_seed" not in text
            shown_any += bool(shown)
            folded_after_bet += bool(folded_seats(s) - {0}) and bool(out)
    assert shown_any and folded_after_bet


def test_heads_up_views_gain_seats_and_pots():
    r, profile = _find(lambda r: outcome(r).ended_by == "showdown")
    v = _view(r, profile)
    t, out = v["table"], v["outcome"]
    assert t["table_size"] == 2 and [x["name"] for x in t["seats"]] == ["You", "Villain"]
    assert t["seats"][1]["profile"] == t["villain_profile"]
    assert t["seats"][1]["position"] == t["villain_position"]
    assert t["seats"][1]["cards"] == out["villain_cards"]
    assert out["shown"] == [{"seat": 1, "cards": out["villain_cards"]}]
    assert sum(p["amount"] for p in out["pots"]) == t["pot"]
    assert out["pots"][0]["label"] == "main pot"
    running = _view(_at_decision(r, 0), profile)
    assert running["table"]["seats"][1]["cards"] is None
    assert [f["to_act_seat"] for f in running["frames"]][-1] == 0
    folded, fp = _find(lambda r: outcome(r).ended_by == "fold")
    fv = _view(folded, fp)
    assert fv["outcome"]["shown"] == [] and fv["table"]["seats"][1]["cards"] is None
    assert len(fv["outcome"]["pots"]) == 1


def test_session_view_five_max():
    bots = [{"seat": s, "name": f"Bot {s}", "profile": None, "stack": 150 + s} for s in range(1, 5)]
    sv = play_views.session_view(
        _fields(profile=None, bot_stack=None, table_size=5, bots=bots), None
    )
    schemas.PlaySessionView.model_validate(sv)
    assert sv["profile"] is None and sv["bot_stack"] is None and sv["table_size"] == 5
    assert sv["bots"] == bots
    hu = play_views.session_view(_fields(), None)
    assert hu["table_size"] == 2
    assert hu["bots"] == [
        {"seat": 1, "name": "Villain", "profile": _fields()["profile"], "stack": 160}
    ]
