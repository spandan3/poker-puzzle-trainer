"""Hand analysis over HTTP: each Hero decision graded once on click, stored, and explained."""

from dataclasses import replace

import pytest
from sqlalchemy import func, select, update

from poker_trainer.api import play_service
from poker_trainer.db import make_engine, make_sessionmaker
from poker_trainer.db.models import PlayDecisionRow, PlayHandRow, PlaySessionRow, User
from poker_trainer.engine.cards import card_str
from poker_trainer.explain.guardrail import check_claims, unknown_numbers
from poker_trainer.explain.ollama import fields_of
from poker_trainer.explain.template import text_of
from poker_trainer.game.state import amount_to_call, total_pot
from poker_trainer.play import analyse
from poker_trainer.play.analyse import DecisionAnalysis, hero_decisions
from poker_trainer.play.hand import bot_cards, replay
from poker_trainer.villain import strategy


@pytest.fixture
def play_db(play_client, db_url):
    engine = make_engine(db_url)
    yield make_sessionmaker(engine)
    engine.dispose()


@pytest.fixture
def solves(monkeypatch):
    """Counts the calls to ``analyse_decision`` the service makes, by decision index."""
    calls = []
    real = analyse.analyse_decision

    def counting(record, profile, n, **kw):
        calls.append(n)
        return real(record, profile, n, **kw)

    monkeypatch.setattr(play_service, "analyse_decision", counting)
    return calls


def _start(c):
    r = c.post("/api/play/sessions")
    assert r.status_code == 201, r.text
    return r.json()


def _deal(c, v):
    r = c.post(
        f"/api/play/sessions/{v['id']}/hands",
        json={"expected_hands": v["hands_played"], "top_up": True},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _act(c, v, index):
    hand = v["hand"]
    body = {"expected_actions": hand["action_count"], "option": index}
    r = c.post(f"/api/play/hands/{hand['id']}/actions", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _index(options, *kinds):
    """The first option of the first kind in ``kinds`` that is offered, else option 0."""
    for kind in kinds:
        for o in options:
            if o["kind"] == kind:
                return o["index"]
    return 0


def _passive(options):
    return _index(options, "check", "call")


def _folding(options):
    return _index(options, "fold")


def _finish(c, v, pick=_passive):
    while v["hand"]["status"] == "in_progress":
        v = _act(c, v, pick(v["hand"]["options"]))
    return v


def _hand_with(c, v, want, pick=_passive, tries=60):
    """Deal and play hands until ``want(hand)`` holds for a finished one; return the view."""
    v = _finish(c, v, pick)
    for _ in range(tries):
        if want(v["hand"]):
            return v
        v = _finish(c, _deal(c, v), pick)
    raise AssertionError("no such hand in the seeded session")


def _showdown_hand(c):
    return _hand_with(
        c,
        _start(c),
        lambda h: h["decision_count"] >= 2 and h["outcome"]["ended_by"] == "showdown",
    )


def _analysis(c, hand_id):
    r = c.get(f"/api/play/hands/{hand_id}/analysis")
    assert r.status_code == 200, r.text
    return r.json()


def _post(c, hand_id, n):
    return c.post(f"/api/play/hands/{hand_id}/analysis/{n}")


def _analyse_all(c, hand):
    out = []
    for n in range(hand["decision_count"]):
        r = _post(c, hand["id"], n)
        assert r.status_code == 200, r.text
        out.append(r.json())
    return out


def _record(play_db, hand_id):
    with play_db() as db:
        _, _, record, profile = play_service.load_hand(db, 1, hand_id)
    return record, profile


def test_running_hand_is_409(play_client):
    v = _start(play_client)
    while v["hand"]["status"] != "in_progress":
        v = _deal(play_client, v)
    hand_id = v["hand"]["id"]
    assert play_client.get(f"/api/play/hands/{hand_id}/analysis").status_code == 409
    assert _post(play_client, hand_id, 0).status_code == 409


def test_before_any_post_every_decision_is_null(play_client, play_db):
    v = _showdown_hand(play_client)
    hand = v["hand"]
    a = _analysis(play_client, hand["id"])
    assert a["hand_id"] == hand["id"]
    assert a["decisions"] == [None] * hand["decision_count"]
    assert a["summary"] is None
    assert a["model_changed"] is False
    assert a["judged_on_range_note"]
    record, profile = _record(play_db, hand["id"])
    reveal = a["reveal"]
    assert reveal["villain_cards"] == [card_str(c) for c in bot_cards(record)]
    assert reveal["board"] == hand["table"]["board"] and len(reveal["board"]) == 5
    assert reveal["showdown"] == hand["outcome"]["showdown"]
    assert reveal["profile"] == {
        "name": profile.name,
        "label": profile.label,
        "description": profile.description,
        "version": profile.version,
    }


def test_hand_without_a_hero_decision(play_client):
    v = _hand_with(play_client, _start(play_client), lambda h: h["decision_count"] == 0, _folding)
    a = _analysis(play_client, v["hand"]["id"])
    assert a["decisions"] == [] and a["summary"] is None
    assert len(a["reveal"]["villain_cards"]) == 2
    assert _post(play_client, v["hand"]["id"], 0).status_code == 404


def test_post_grades_once_with_the_table_as_it_stood(play_client, play_db, solves):
    v = _showdown_hand(play_client)
    hand_id = v["hand"]["id"]
    record, _ = _record(play_db, hand_id)
    r = _post(play_client, hand_id, 1)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["index"] == 1 and d["status"] == "graded" and d["reason"] is None
    i = hero_decisions(record)[1]
    s = replay(replace(record, actions=record.actions[:i]))
    assert len(d["view"]["board"]) == len(s.board)
    assert d["view"]["pot"] == total_pot(s)
    assert d["view"]["to_call"] == amount_to_call(s)
    assert len(d["view"]["history"]) == i
    assert sum(o["is_chosen"] for o in d["options"]) == 1
    assert sum(o["is_best"] for o in d["options"]) == 1
    chosen = next(o for o in d["options"] if o["is_chosen"])
    assert (chosen["kind"], chosen["to"]) == (record.actions[i].kind.value, record.actions[i].to)
    assert d["chosen_label"] == d["grade"]["chosen_label"] == chosen["label"]
    assert d["grade"]["verdict"] in ("best", "fine", "mistake", "blunder")
    assert d["explanation"]["source"] == "template"
    assert d["range_steps"]
    assert solves == [1]
    again = _post(play_client, hand_id, 1)
    assert again.status_code == 200 and again.json() == d
    assert solves == [1]  # stored: not solved again
    a = _analysis(play_client, hand_id)
    assert a["decisions"][1] == d and a["decisions"][0] is None and a["summary"] is None
    with play_db() as db:
        assert db.scalar(select(PlayHandRow.ev_loss_chips).where(PlayHandRow.id == hand_id)) is None


def test_summary_once_every_decision_is_stored(play_client):
    v = _showdown_hand(play_client)
    hand = v["hand"]
    reviews = _analyse_all(play_client, hand)
    a = _analysis(play_client, hand["id"])
    assert a["decisions"] == reviews
    losses = [d["grade"]["ev_loss_bb"] for d in reviews]
    assert a["summary"]["ev_loss_bb"] == pytest.approx(sum(losses))
    worst = max(range(len(losses)), key=lambda k: (losses[k], -k))
    assert a["summary"]["worst_index"] == (worst if losses[worst] > 0 else None)
    (row,) = [
        h
        for h in play_client.get(f"/api/play/sessions/{hand['session_id']}/hands").json()
        if h["id"] == hand["id"]
    ]
    assert row["analysed"] is True
    assert row["ev_loss_bb"] == pytest.approx(a["summary"]["ev_loss_bb"])


def test_fold_reveals_the_bot_cards_and_the_board_as_dealt(play_client, play_db):
    v = _hand_with(
        play_client,
        _start(play_client),
        lambda h: h["decision_count"] >= 1 and h["outcome"]["ended_by"] == "fold",
        _folding,
    )
    hand = v["hand"]
    record, _ = _record(play_db, hand["id"])
    a = _analysis(play_client, hand["id"])
    reveal = a["reveal"]
    assert reveal["villain_cards"] == [card_str(c) for c in bot_cards(record)]
    assert reveal["board"] == hand["table"]["board"]
    assert reveal["board"] == [card_str(c) for c in replay(record).board]
    assert reveal["showdown"] is None
    assert hand["outcome"]["villain_cards"] is None  # the table still hides them


def test_not_graded_is_stored_and_left_out_of_the_summary(play_client, monkeypatch):
    real = analyse.analyse_decision

    def patched(record, profile, n, **kw):
        if n == 0:
            return DecisionAnalysis(None, None, "the range tracker lost the bot's line")
        return real(record, profile, n, **kw)

    monkeypatch.setattr(play_service, "analyse_decision", patched)
    v = _showdown_hand(play_client)
    hand = v["hand"]
    reviews = _analyse_all(play_client, hand)
    first = reviews[0]
    assert first["status"] == "not_graded"
    assert first["reason"] == "the range tracker lost the bot's line"
    assert first["grade"] is None and first["options"] == [] and first["explanation"] is None
    assert first["view"] is not None
    assert all(d["status"] == "graded" for d in reviews[1:])
    a = _analysis(play_client, hand["id"])
    assert a["decisions"][0] == first
    losses = [d["grade"]["ev_loss_bb"] for d in reviews[1:]]
    assert a["summary"]["ev_loss_bb"] == pytest.approx(sum(losses))
    assert a["summary"]["worst_index"] != 0
    r = play_client.get(f"/api/play/hands/{hand['id']}/analysis/0/explanation")
    assert r.status_code == 404


def test_model_changed(play_client, monkeypatch):
    v = _finish(play_client, _start(play_client))
    hand_id = v["hand"]["id"]
    assert _analysis(play_client, hand_id)["model_changed"] is False
    monkeypatch.setattr(strategy, "STRATEGY_VERSION", strategy.STRATEGY_VERSION + 1)
    assert _analysis(play_client, hand_id)["model_changed"] is True


def test_ended_session_and_abandoned_hand_can_be_analysed(play_client):
    v = _start(play_client)
    while v["hand"]["status"] != "in_progress":
        v = _deal(play_client, v)
    v = _act(play_client, v, _passive(v["hand"]["options"]))
    if v["hand"]["status"] == "complete":
        assert play_client.post(f"/api/play/sessions/{v['id']}/end").status_code == 200
        hand = v["hand"]
    else:
        ended = play_client.post(f"/api/play/sessions/{v['id']}/end").json()
        hand = ended["hand"]
        assert hand["outcome"]["ended_by"] == "abandoned"
    reviews = _analyse_all(play_client, hand)
    assert len(reviews) == hand["decision_count"] >= 1
    assert _analysis(play_client, hand["id"])["summary"] is not None


def test_bad_index_and_other_users_hand_404(play_client, play_db):
    v = _showdown_hand(play_client)
    hand = v["hand"]
    n = hand["decision_count"]
    assert _post(play_client, hand["id"], n).status_code == 404
    assert _post(play_client, hand["id"], -1).status_code == 404
    assert play_client.get(
        f"/api/play/hands/{hand['id']}/analysis/{n}/explanation"
    ).status_code == (404)
    assert play_client.get("/api/play/hands/999/analysis").status_code == 404
    assert _post(play_client, 999, 0).status_code == 404
    assert _post(play_client, hand["id"], 0).status_code == 200
    with play_db() as db:
        db.add(User(id=2, name="other"))
        db.flush()
        db.execute(update(PlaySessionRow).values(user_id=2))
        db.execute(update(PlayHandRow).values(user_id=2))
        db.execute(update(PlayDecisionRow).values(user_id=2))
        db.commit()
    assert play_client.get(f"/api/play/hands/{hand['id']}/analysis").status_code == 404
    assert _post(play_client, hand["id"], 0).status_code == 404
    assert _post(play_client, hand["id"], 1).status_code == 404
    assert (
        play_client.get(f"/api/play/hands/{hand['id']}/analysis/0/explanation").status_code == 404
    )


def test_explanation_route(play_client):
    v = _showdown_hand(play_client)
    hand_id = v["hand"]["id"]
    url = f"/api/play/hands/{hand_id}/analysis/0/explanation"
    assert play_client.get(url).status_code == 404  # not analysed yet
    d = _post(play_client, hand_id, 0).json()
    r = play_client.get(url)
    assert r.status_code == 200, r.text
    assert r.json() == {**d["explanation"], "fallback": "off"}


def test_concurrent_insert_returns_the_stored_row(play_client, play_db, monkeypatch):
    """A decision stored by another request while this one solved: the stored row wins."""
    v = _showdown_hand(play_client)
    hand_id = v["hand"]["id"]
    first = _post(play_client, hand_id, 0).json()
    real = play_service._stored_decision
    calls = []

    def blind_once(db, user_id, hid, n):
        calls.append(n)
        return None if len(calls) == 1 else real(db, user_id, hid, n)

    monkeypatch.setattr(play_service, "_stored_decision", blind_once)
    again = _post(play_client, hand_id, 0)
    assert again.status_code == 200 and again.json() == first
    with play_db() as db:
        count = db.scalar(select(func.count()).select_from(PlayDecisionRow))
    assert count == 1


def test_template_explanations_pass_the_guardrail(play_client, play_db):
    """Every graded decision of 10 seeded hands: the template's numbers are all in its facts,
    and its claims pass the checks a model's text must pass."""
    v = _start(play_client)
    picks = (_passive, _folding, lambda o: len(o) - 1)
    hands = 0
    checked = 0
    while hands < 10:
        v = _finish(play_client, v, picks[hands % len(picks)])
        hand = v["hand"]
        if hand["decision_count"]:
            hands += 1
            for d in _analyse_all(play_client, hand):
                if d["status"] != "graded":
                    continue
                with play_db() as db:
                    template, facts = play_service.decision_explanation_inputs(
                        db, 1, hand["id"], d["index"]
                    )
                assert template == d["explanation"]
                assert facts.subject == "hand"
                text = text_of(template)
                assert "this hand was graded on" in text and "puzzle" not in text.lower(), text
                assert unknown_numbers(text, facts.values_text()) == set(), text
                assert check_claims(fields_of(template), facts) == {}, text
                checked += 1
        v = _deal(play_client, v)
    assert checked >= 10


def test_a_crash_before_the_hand_total_is_repaired_by_the_next_get(play_client, play_db):
    """Every decision stored but the hand's total never written: GET fills it in."""
    v = _showdown_hand(play_client)
    hand = v["hand"]
    reviews = _analyse_all(play_client, hand)
    with play_db() as db:
        db.execute(
            update(PlayHandRow).where(PlayHandRow.id == hand["id"]).values(ev_loss_chips=None)
        )
        db.commit()
    sid = hand["session_id"]

    def listed():
        (row,) = [
            h
            for h in play_client.get(f"/api/play/sessions/{sid}/hands").json()
            if h["id"] == hand["id"]
        ]
        return row

    assert listed()["analysed"] is False
    a = _analysis(play_client, hand["id"])
    row = listed()
    assert row["analysed"] is True
    assert row["ev_loss_bb"] == pytest.approx(sum(d["grade"]["ev_loss_bb"] for d in reviews))
    assert a["summary"]["ev_loss_bb"] == pytest.approx(row["ev_loss_bb"])
