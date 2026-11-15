"""Play vs Bots over HTTP: sessions, hands, the stale-click rules and the stack rules."""

import pytest
from sqlalchemy import select, update

from poker_trainer.api import service
from poker_trainer.db import make_engine, make_sessionmaker
from poker_trainer.db.models import PlayHandRow, PlaySessionRow
from poker_trainer.play.hand import outcome
from poker_trainer.play.session import START
from poker_trainer.villain import profiles


@pytest.fixture
def play_db(play_client, db_url):
    engine = make_engine(db_url)
    yield make_sessionmaker(engine)
    engine.dispose()


def _start(c):
    r = c.post("/api/play/sessions")
    assert r.status_code == 201, r.text
    return r.json()


def _act(c, view, index=0, **extra):
    hand = view["hand"]
    body = {"expected_actions": hand["action_count"], "option": index, **extra}
    return c.post(f"/api/play/hands/{hand['id']}/actions", json=body)


def _finish(c, view, pick=lambda k, n: k % n):
    """Play the running hand to its end, choosing option ``pick(step, len(options))``."""
    k = 0
    while view["hand"]["status"] == "in_progress":
        n = len(view["hand"]["options"])
        r = _act(c, view, pick(k, n))
        assert r.status_code == 200, r.text
        nxt = r.json()
        assert (
            nxt["hand"]["table"]["history"][: len(view["hand"]["table"]["history"])]
            == (view["hand"]["table"]["history"])
        )
        assert c.get("/api/play/sessions/current").json() == nxt  # resume between actions
        view = nxt
        k += 1
    return view


def _jam_or_cycle(jam):
    """Pick the biggest option every time (stacks swing, rebuys happen) or cycle through them."""
    return lambda k, n: n - 1 if jam else k % n


def _start_stacks(play_db):
    with play_db() as db:
        return db.scalars(select(PlayHandRow).order_by(PlayHandRow.id.desc())).first().start_stacks


def _force(play_db, **values):
    with play_db() as db:
        db.execute(update(PlaySessionRow).values(**values))
        db.commit()


def test_start_and_current(play_client):
    v = _start(play_client)
    assert v["open"] and v["hands_played"] == 0 and v["hero_bought_chips"] == START
    assert v["profile"]["name"] in profiles.PROFILE_NAMES
    hand = v["hand"]
    assert hand["hand_no"] == 1 and hand["session_id"] == v["id"]
    assert hand["status"] == "in_progress" or hand["outcome"] is not None
    if hand["status"] == "in_progress":
        assert hand["table"]["villain_profile"]["name"] == v["profile"]["name"]
        assert hand["options"]
        assert hand["frames"][-1]["to_act"] == "hero"
    assert play_client.get("/api/play/sessions/current").json() == v
    assert play_client.post("/api/play/sessions").status_code == 409
    assert play_client.get("/api/play/sessions/current").json() == v


def test_end_then_current_404_and_end_twice(play_client):
    v = _start(play_client)
    r = play_client.post(f"/api/play/sessions/{v['id']}/end")
    assert r.status_code == 200 and r.json()["open"] is False
    assert play_client.get("/api/play/sessions/current").status_code == 404
    again = play_client.post(f"/api/play/sessions/{v['id']}/end")
    assert again.status_code == 200 and again.json() == r.json()
    assert play_client.post(f"/api/play/sessions/{v['id']}/hands", json={}).status_code == 409
    assert play_client.post("/api/play/sessions").status_code == 201  # a new one may start


def test_play_a_hand_to_the_end(play_client, play_db):
    v = _start(play_client)
    v = _finish(play_client, v)
    hand = v["hand"]
    assert hand["status"] == "complete" and hand["options"] == []
    assert hand["custom"] == {"allowed": False, "min_to": None, "max_to": None}
    assert v["hands_played"] == 1
    assert v["hero_stack"] + v["bot_stack"] == 2 * START
    assert hand["outcome"]["hero_delta_chips"] == v["hero_stack"] - START
    assert v["net_chips"] == hand["outcome"]["hero_delta_chips"]
    got = play_client.get(f"/api/play/hands/{hand['id']}").json()
    assert got == hand


def test_stored_outcome_matches_engine(play_client, play_db):
    from poker_trainer.api import play_service

    v = _finish(play_client, _start(play_client))
    with play_db() as db:
        row, sess, record, _ = play_service.load_hand(db, 1, v["hand"]["id"])
        out = outcome(record)
        assert (row.status, row.ended_by, row.winner) == ("complete", out.ended_by, out.winner)
        assert row.hero_delta_chips == out.hero_delta
        assert (sess.hero_stack, sess.bot_stack) == out.stacks
        assert row.action_count == len(record.actions)


def test_stale_and_double_clicks(play_client):
    v = _start(play_client)
    while v["hand"]["status"] != "in_progress":  # the bot folded the button: deal another
        v = play_client.post(f"/api/play/sessions/{v['id']}/hands", json={}).json()
    hid = v["hand"]["id"]
    first = _act(play_client, v, 0)
    assert first.status_code == 200
    before = play_client.get(f"/api/play/hands/{hid}").json()
    again = _act(play_client, v, 0)  # same expected_actions
    assert again.status_code == 409
    assert play_client.get(f"/api/play/hands/{hid}").json() == before
    cur = first.json()
    if cur["hand"]["status"] == "in_progress":
        n = len(cur["hand"]["options"])
        assert _act(play_client, cur, n).status_code == 422  # out of range
        bad = play_client.post(
            f"/api/play/hands/{hid}/actions",
            json={"expected_actions": cur["hand"]["action_count"], "option": n + 5},
        )
        assert bad.status_code == 422
        assert play_client.post(f"/api/play/sessions/{cur['id']}/hands", json={}).status_code == 409
        done = _finish(play_client, cur)
    else:
        done = cur
    stale = play_client.post(
        f"/api/play/hands/{hid}/actions",
        json={"expected_actions": done["hand"]["action_count"], "option": 0},
    )
    assert stale.status_code == 409  # a finished hand


def test_custom_size_preflop_422_and_postflop_ok(play_client):
    v = _start(play_client)
    while v["hand"]["status"] != "in_progress":
        v = play_client.post(f"/api/play/sessions/{v['id']}/hands", json={}).json()
    hand = v["hand"]
    assert hand["table"]["street"] == "preflop" and not hand["custom"]["allowed"]
    body = {"expected_actions": hand["action_count"], "custom_to": 6}
    assert play_client.post(f"/api/play/hands/{hand['id']}/actions", json=body).status_code == 422
    both = {"expected_actions": hand["action_count"], "custom_to": 6, "option": 0}
    assert play_client.post(f"/api/play/hands/{hand['id']}/actions", json=both).status_code == 422
    # reach a post-flop decision by calling/checking (the first non-fold option that exists)
    for _ in range(40):
        while v["hand"]["status"] != "in_progress":
            v = play_client.post(f"/api/play/sessions/{v['id']}/hands", json={}).json()
        h = v["hand"]
        if h["custom"]["allowed"]:
            break
        kinds = [o["kind"] for o in h["options"]]
        pick = next((i for i, k in enumerate(kinds) if k in ("check", "call")), 0)
        v = _act(play_client, v, pick).json()
    else:
        pytest.fail("never reached a post-flop decision")
    lo = h["custom"]["min_to"]
    low = {"expected_actions": h["action_count"], "custom_to": lo - 1}
    assert play_client.post(f"/api/play/hands/{h['id']}/actions", json=low).status_code == 422
    ok = {"expected_actions": h["action_count"], "custom_to": lo}
    r = play_client.post(f"/api/play/hands/{h['id']}/actions", json=ok)
    assert r.status_code == 200
    assert r.json()["hand"]["table"]["history"][len(h["table"]["history"])]["to"] == lo


def test_next_hand_double_click(play_client):
    v = _finish(play_client, _start(play_client))
    sid = v["id"]
    a = play_client.post(f"/api/play/sessions/{sid}/hands", json={})
    assert a.status_code == 201 and a.json()["hand"]["hand_no"] == 2
    if a.json()["hand"]["status"] == "in_progress":
        b = play_client.post(f"/api/play/sessions/{sid}/hands", json={})
        assert b.status_code == 409
    hands = play_client.get(f"/api/play/sessions/{sid}/hands").json()
    assert [h["hand_no"] for h in hands] == sorted({h["hand_no"] for h in hands})


def test_button_alternates(play_client, play_db):
    v = _finish(play_client, _start(play_client))
    first = v["hand"]["table"]["hero_position"]
    v = play_client.post(f"/api/play/sessions/{v['id']}/hands", json={}).json()
    assert v["hand"]["table"]["hero_position"] != first


def test_rebuy_top_up_and_bot_stacks(play_client, play_db):
    v = _finish(play_client, _start(play_client))
    _force(play_db, hero_stack=6, bot_stack=394)
    cur = play_client.get("/api/play/sessions/current").json()
    assert cur["must_rebuy"] and not cur["can_top_up"]
    bought = cur["hero_bought_chips"]
    n = play_client.post(f"/api/play/sessions/{v['id']}/hands", json={}).json()
    assert n["hero_bought_chips"] == bought + 194
    assert _start_stacks(play_db) == [START, START]  # rebought, and the bot 394 > 300 reset
    assert n["net_chips"] == n["hero_stack"] - n["hero_bought_chips"]


def test_top_up_and_bot_below_min(play_client, play_db):
    v = _finish(play_client, _start(play_client))
    _force(play_db, hero_stack=150, bot_stack=60)
    cur = play_client.get("/api/play/sessions/current").json()
    assert cur["can_top_up"] and not cur["must_rebuy"]
    n = play_client.post(f"/api/play/sessions/{v['id']}/hands", json={"top_up": True}).json()
    assert n["hero_bought_chips"] == cur["hero_bought_chips"] + 50
    assert _start_stacks(play_db) == [START, START]  # topped up, and the bot 60 < 80 rebought
    assert n["net_chips"] == cur["net_chips"]  # a top-up never changes the tally


def test_no_top_up_keeps_stacks(play_client, play_db):
    v = _finish(play_client, _start(play_client))
    _force(play_db, hero_stack=150, bot_stack=250)
    n = play_client.post(f"/api/play/sessions/{v['id']}/hands", json={}).json()
    assert n["hero_bought_chips"] == START
    assert _start_stacks(play_db) == [150, 250]


def test_tally_over_30_hands(play_client):
    v = _start(play_client)
    total = 0
    for i in range(30):
        v = _finish(play_client, v, pick=_jam_or_cycle(i % 2 == 1))
        hand = v["hand"]
        total += hand["outcome"]["hero_delta_chips"]
        assert v["hands_played"] == i + 1
        assert v["net_chips"] == v["hero_stack"] - v["hero_bought_chips"] == total
        assert v["net_bb"] == total / 2
        assert v["must_rebuy"] == (v["hero_stack"] < 10)
        v = play_client.post(
            f"/api/play/sessions/{v['id']}/hands", json={"top_up": i % 3 == 0}
        ).json()
        assert v["hand"]["hand_no"] == i + 2
        if v["hand"]["status"] == "in_progress":
            assert v["net_chips"] == total  # rebuys and top-ups never change the tally
    assert v["hero_bought_chips"] > START  # the seeded session did rebuy or top up


def test_end_mid_hand_abandons(play_client):
    v = _start(play_client)
    while v["hand"]["status"] != "in_progress":
        v = play_client.post(f"/api/play/sessions/{v['id']}/hands", json={}).json()
    stack = v["hero_stack"]
    played = v["hands_played"]
    posted = v["hand"]["table"]["street_bets"][0]
    r = play_client.post(f"/api/play/sessions/{v['id']}/end")
    assert r.status_code == 200
    e = r.json()
    assert e["open"] is False and e["hands_played"] == played + 1
    out = e["hand"]["outcome"]
    assert out["ended_by"] == "abandoned" and out["winner"] == "villain"
    assert out["villain_cards"] is None and out["showdown"] is None
    assert out["hero_delta_chips"] == -posted
    assert e["hero_stack"] == stack - posted
    assert e["hero_stack"] + e["bot_stack"] == 2 * START
    assert e["net_chips"] == e["hero_stack"] - e["hero_bought_chips"]
    assert play_client.post(f"/api/play/sessions/{v['id']}/end").json() == e
    assert _act(play_client, v, 0).status_code == 409


def test_profile_is_a_snapshot(play_client, monkeypatch):
    v = _start(play_client)

    def boom(*a, **k):
        raise AssertionError("load_profile used after the session started")

    monkeypatch.setattr(profiles, "load_profile", boom)
    monkeypatch.setattr(service, "load_profile", boom)
    v = _finish(play_client, v)
    assert play_client.get("/api/play/sessions/current").status_code == 200
    n = play_client.post(f"/api/play/sessions/{v['id']}/hands", json={})
    assert n.status_code == 201


def test_lists(play_client):
    v = _finish(play_client, _start(play_client))
    sid = v["id"]
    v2 = play_client.post(f"/api/play/sessions/{sid}/hands", json={}).json()
    sessions_ = play_client.get("/api/play/sessions").json()
    assert len(sessions_) == 1
    s = sessions_[0]
    assert s["id"] == sid and s["open"] and s["profile_label"] == v["profile"]["label"]
    assert s["hands_played"] == v2["hands_played"]
    assert s["created_at"].endswith("+00:00") and s["ended_at"] is None
    hands = play_client.get(f"/api/play/sessions/{sid}/hands").json()
    assert [h["hand_no"] for h in hands] == [1, 2]
    h1 = hands[0]
    assert h1["id"] == v["hand"]["id"] and h1["analysed"] is False
    assert h1["result_bb"] == v["hand"]["outcome"]["hero_delta_bb"]
    assert h1["ended_by"] == v["hand"]["outcome"]["ended_by"]
    assert h1["hero_position"] == v["hand"]["table"]["hero_position"]
    assert h1["decision_count"] >= 0 and h1["ev_loss_bb"] is None
    if v2["hand"]["status"] == "in_progress":
        assert hands[1]["result_bb"] is None and hands[1]["ended_by"] is None
    play_client.post(f"/api/play/sessions/{sid}/end")
    s = play_client.get("/api/play/sessions").json()[0]
    assert not s["open"] and s["ended_at"] is not None


def test_decision_count_counts_hero_actions(play_client, play_db):
    v = _start(play_client)
    while v["hand"]["status"] != "in_progress":
        v = play_client.post(f"/api/play/sessions/{v['id']}/hands", json={}).json()
    assert v["hand"]["decision_count"] == 0
    v = _act(play_client, v, 0).json()
    assert v["hand"]["decision_count"] == 1
    with play_db() as db:
        rows = db.scalars(select(PlayHandRow)).all()
        assert rows[-1].decision_count == 1 and rows[-1].action_count == len(
            v["hand"]["table"]["history"]
        )


def test_unknown_ids_404(play_client):
    assert play_client.get("/api/play/hands/999").status_code == 404
    assert play_client.post("/api/play/sessions/999/end").status_code == 404
    assert play_client.post("/api/play/sessions/999/hands", json={}).status_code == 404
    body = {"expected_actions": 0, "option": 0}
    assert play_client.post("/api/play/hands/999/actions", json=body).status_code == 404
    huge = 2**70
    assert play_client.get(f"/api/play/hands/{huge}").status_code == 404
    assert play_client.post(f"/api/play/sessions/{huge}/end").status_code == 404
    assert play_client.get("/api/play/sessions/current").status_code == 404


def test_second_session_blocked_by_the_constraint_alone(play_client, monkeypatch):
    """With the pre-check blinded, the partial unique index still gives a 409."""
    from poker_trainer.api import play_service

    _start(play_client)
    monkeypatch.setattr(play_service, "_open_session", lambda db, user_id: None)
    r = play_client.post("/api/play/sessions")
    assert r.status_code == 409
    monkeypatch.undo()
    assert len(play_client.get("/api/play/sessions").json()) == 1


def test_doubled_next_hand_blocked_by_the_constraint_alone(play_client, monkeypatch):
    from poker_trainer.api import play_service

    v = _finish(play_client, _start(play_client))
    first = play_client.post(f"/api/play/sessions/{v['id']}/hands", json={})
    assert first.status_code == 201
    with play_client.app.state.sessionmaker() as db:
        stale = db.scalars(select(PlayHandRow).where(PlayHandRow.hand_no == 1)).one()
        db.expunge(stale)
    monkeypatch.setattr(play_service, "_latest_hand", lambda db, user_id, sid: stale)
    r = play_client.post(f"/api/play/sessions/{v['id']}/hands", json={})
    assert r.status_code == 409
    monkeypatch.undo()
    hands = play_client.get(f"/api/play/sessions/{v['id']}/hands").json()
    assert [h["hand_no"] for h in hands] == [1, 2]


def test_compare_and_set_refuses_a_racing_write(play_client, play_db, monkeypatch):
    """Another request advances the hand between this one's read and write: 409, no change."""
    from poker_trainer.api import play_service

    v = _start(play_client)
    while v["hand"]["status"] != "in_progress":
        v = play_client.post(f"/api/play/sessions/{v['id']}/hands", json={}).json()
    hid = v["hand"]["id"]
    real = play_service.load_hand

    def racing(db, user_id, hand_id):
        loaded = real(db, user_id, hand_id)
        with play_db() as other:
            other.execute(update(PlayHandRow).values(action_count=loaded[0].action_count + 1))
            other.commit()
        return loaded

    monkeypatch.setattr(play_service, "load_hand", racing)
    r = _act(play_client, v, 0)
    assert r.status_code == 409
    monkeypatch.undo()
    with play_db() as db:
        row = db.get(PlayHandRow, hid)
        assert row.action_count == v["hand"]["action_count"] + 1
        assert (
            len(row.actions) == v["hand"]["action_count"]
        )  # the racing write changed nothing else
        assert db.get(PlaySessionRow, v["id"]).hands_played == 0
