"""5-max Play vs Bots over HTTP (M12): sessions, seats, stacks, pot awards, no card leaks, and
the analysis routes refusing 5-max hands. Heads-up responses only gain the new fields."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import select, update

from poker_trainer.api import play_service
from poker_trainer.db import make_engine, make_sessionmaker
from poker_trainer.db.models import PlayHandRow, PlaySessionRow
from poker_trainer.engine.cards import card_str
from poker_trainer.game.settle import settle_pots
from poker_trainer.game.state import folded_seats, live_seats
from poker_trainer.play.hand import SeatBot, hole, holes, outcome5, replay
from poker_trainer.play.session import START, next_stacks5
from poker_trainer.villain.preflop5 import load_fivemax, load_ranking
from poker_trainer.villain.profiles import PROFILE_NAMES

NO_ANALYSIS = "Analysis of 5-max hands comes in a later version."
POSITIONS = ["BTN", "SB", "BB", "UTG", "CO"]  # seat button + k


@pytest.fixture
def play_db(play_client, db_url):
    engine = make_engine(db_url)
    yield make_sessionmaker(engine)
    engine.dispose()


def _start5(c):
    r = c.post("/api/play/sessions", json={"table_size": 5})
    assert r.status_code == 201, r.text
    return r.json()


def _act(c, view, index):
    hand = view["hand"]
    body = {"expected_actions": hand["action_count"], "option": index}
    r = c.post(f"/api/play/hands/{hand['id']}/actions", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _deal(c, v, **body):
    r = c.post(
        f"/api/play/sessions/{v['id']}/hands", json={"expected_hands": v["hands_played"], **body}
    )
    assert r.status_code == 201, r.text
    return r.json()


def _pick(k, options):
    """Cycle through Hero's options, folding less often than not."""
    return (k * 7 + 1) % len(options)


def _record(play_db, hand_id):
    with play_db() as db:
        return play_service.load_hand(db, 1, hand_id)[2]


def _check_no_leak(view, record):
    """Bot cards appear only for seats shown at a showdown; undealt board cards never."""
    text = json.dumps(view)
    hand = view.get("hand", view)  # a session view, or a hand view itself
    out = hand["outcome"]
    shown = {x["seat"] for x in out["shown"]} if out else set()
    s = replay(record)
    if not (out and out["ended_by"] == "showdown"):
        assert shown == set()
    assert shown <= set(live_seats(s)) - {0} and not shown & folded_seats(s)
    for seat in range(1, 5):
        for c in (card_str(x) for x in hole(record, seat)):
            assert (f'"{c}"' in text) == (seat in shown), (hand["id"], seat, c)
    dealt = len(hand["table"]["board"])
    for c in (card_str(x) for x in record.deck[10 + dealt :]):
        assert f'"{c}"' not in text, (hand["id"], c)
    assert "deck" not in text and "bot_seed" not in text


def test_start_a_five_max_session(play_client, play_db):
    v = _start5(play_client)
    assert v["table_size"] == 5 and v["open"] and v["hands_played"] == 0
    assert v["profile"] is None and v["bot_stack"] is None
    assert [b["name"] for b in v["bots"]] == ["Bot 1", "Bot 2", "Bot 3", "Bot 4"]
    assert [b["seat"] for b in v["bots"]] == [1, 2, 3, 4]
    assert all(b["stack"] == START and b["profile"]["name"] in PROFILE_NAMES for b in v["bots"])
    assert v["hero_stack"] == START and v["hero_bought_chips"] == START
    t = v["hand"]["table"]
    assert t["table_size"] == 5 and len(t["seats"]) == 5
    assert t["villain_position"] is None and t["villain_profile"] is None
    for b, seat in zip(v["bots"], t["seats"][1:], strict=True):
        assert seat["name"] == b["name"] and seat["profile"] == b["profile"]
    with play_db() as db:
        sess = db.scalar(select(PlaySessionRow))
        hand = db.scalar(select(PlayHandRow))
    assert sess.table_size == 5 and sess.bot_stack == 0
    assert [set(e) for e in sess.seats] == [{"seat", "name", "stack", "bot"}] * 4
    bots = [SeatBot.from_dict(e["bot"]) for e in sess.seats]
    assert [b.profile.name for b in bots] == [x["profile"]["name"] for x in v["bots"]]
    # the legacy columns hold Bot 1's snapshot
    assert sess.profile == sess.seats[0]["bot"]["profile"]
    assert sess.profile_data == sess.seats[0]["bot"]["profile_data"]
    assert hand.table_size == 5 and hand.start_stacks == [START] * 5
    assert hand.bot_versions == {
        "hand_ranking": load_ranking()[0],
        "fivemax": load_fivemax().version,
    }
    assert play_client.get("/api/play/sessions/current").json() == v
    assert play_client.post("/api/play/sessions", json={"table_size": 5}).status_code == 409


@pytest.mark.parametrize("body", [{"table_size": 3}, {"table_size": "5"}, {"seats": 5}])
def test_bad_table_size_is_422(play_client, body):
    assert play_client.post("/api/play/sessions", json=body).status_code == 422
    assert play_client.get("/api/play/sessions/current").status_code == 404


@pytest.mark.parametrize("body", [None, {}, {"table_size": 2}])
def test_no_body_or_two_is_heads_up(play_client, play_db, body):
    r = play_client.post("/api/play/sessions", json=body)
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["table_size"] == 2 and v["profile"] is not None and v["bot_stack"] == START
    assert v["bots"] == [{"seat": 1, "name": "Villain", "profile": v["profile"], "stack": START}]
    t = v["hand"]["table"]
    assert t["table_size"] == 2 and [s["name"] for s in t["seats"]] == ["You", "Villain"]
    with play_db() as db:
        sess = db.scalar(select(PlaySessionRow))
        hand = db.scalar(select(PlayHandRow))
    assert (sess.table_size, sess.seats, hand.table_size, hand.bot_versions) == (2, None, 2, None)


def test_play_a_five_max_session(play_client, play_db):
    """Thirty hands to the end: the button and positions rotate, stacks carry over under the
    stack rules, the outcome matches the engine, and no response leaks a card."""
    v = _start5(play_client)
    total = 0
    seen = {"showdown": 0, "fold": 0, "hero_folded": 0, "side_pot": 0}
    prev_button = None
    k = played = 0
    for i in range(30):
        hand = v["hand"]
        record = _record(play_db, hand["id"])
        if prev_button is not None:
            assert record.button == (prev_button + 1) % 5
        prev_button = record.button
        seats = hand["table"]["seats"]
        assert [s["position"] for s in seats] == [
            POSITIONS[(j - record.button) % 5] for j in range(5)
        ]
        assert hand["table"]["hero_position"] == seats[0]["position"]
        assert [s["is_button"] for s in seats] == [j == record.button for j in range(5)]
        _check_no_leak(v, record)
        while v["hand"]["status"] == "in_progress":
            options = v["hand"]["options"]
            assert options and v["hand"]["frames"][-1]["to_act_seat"] == 0
            v = _act(play_client, v, _pick(k, options))
            k += 1
            assert play_client.get("/api/play/sessions/current").json() == v
            _check_no_leak(v, _record(play_db, v["hand"]["id"]))
        hand = v["hand"]
        got = play_client.get(f"/api/play/hands/{hand['id']}")
        assert got.status_code == 200
        assert got.json() == hand
        _check_no_leak(got.json(), _record(play_db, hand["id"]))
        out = hand["outcome"]
        record = _record(play_db, hand["id"])
        o = outcome5(record)
        st = settle_pots(replay(record), holes(record), record.start_stacks)
        assert (out["ended_by"], out["winner"], out["hero_delta_chips"]) == (
            o.ended_by,
            o.winner,
            o.hero_delta,
        )
        assert [(p["amount"], p["eligible"], p["winners"]) for p in out["pots"]] == [
            (p.amount, list(p.eligible), list(p.winners)) for p in st.pots
        ]
        assert sum(p["amount"] for p in out["pots"]) == hand["table"]["pot"]
        assert hand["table"]["stacks"] == list(st.stacks)
        total += o.hero_delta
        played += 1
        assert v["hands_played"] == played
        assert v["hero_stack"] == o.stacks[0]
        assert [b["stack"] for b in v["bots"]] == list(o.stacks[1:])
        assert v["net_chips"] == v["hero_stack"] - v["hero_bought_chips"] == total
        with play_db() as db:
            row = db.get(PlayHandRow, hand["id"])
            assert (row.status, row.ended_by, row.winner) == ("complete", o.ended_by, o.winner)
            assert row.hero_delta_chips == o.hero_delta
            assert row.pots == [
                {"amount": p.amount, "eligible": list(p.eligible), "winners": list(p.winners)}
                for p in o.pots
            ]
        seen[out["ended_by"]] += 1
        seen["hero_folded"] += o.hero_folded
        seen["side_pot"] += len(out["pots"]) > 1
        hero, bots, bought = next_stacks5(
            v["hero_stack"], [b["stack"] for b in v["bots"]], top_up=i % 4 == 0
        )
        before = v["hero_bought_chips"]
        v = _deal(play_client, v, top_up=i % 4 == 0)
        _check_no_leak(v, _record(play_db, v["hand"]["id"]))  # also a walk, already complete
        assert v["hero_bought_chips"] == before + bought
        assert _record(play_db, v["hand"]["id"]).start_stacks == (hero, *bots)
        if v["hand"]["status"] == "complete":
            total += v["hand"]["outcome"]["hero_delta_chips"]  # a walk to Hero's big blind
            played += 1
            prev_button = _record(play_db, v["hand"]["id"]).button
            v = _deal(play_client, v)
            _check_no_leak(v, _record(play_db, v["hand"]["id"]))
    assert seen["showdown"] and seen["fold"] and seen["hero_folded"], seen


def _force_seats(play_db, stacks, **values):
    with play_db() as db:
        sess = db.scalar(select(PlaySessionRow))
        seats = [{**e, "stack": s} for e, s in zip(sess.seats, stacks, strict=True)]
        db.execute(update(PlaySessionRow).values(seats=seats, **values))
        db.commit()


def _finish(c, v):
    k = 0
    while v["hand"]["status"] == "in_progress":
        v = _act(c, v, _pick(k, v["hand"]["options"]))
        k += 1
    return v


def test_bot_stack_rules_and_top_up(play_client, play_db):
    _finish(play_client, _start5(play_client))
    _force_seats(play_db, [60, 350, 150, 300], hero_stack=150)
    cur = play_client.get("/api/play/sessions/current").json()
    assert [b["stack"] for b in cur["bots"]] == [60, 350, 150, 300]
    assert cur["can_top_up"] and not cur["must_rebuy"]
    n = _deal(play_client, cur, top_up=True)
    assert n["hero_bought_chips"] == cur["hero_bought_chips"] + 50
    assert _record(play_db, n["hand"]["id"]).start_stacks == (200, 200, 200, 150, 300)
    assert n["net_chips"] == cur["net_chips"]  # a top-up never changes the tally
    n = _finish(play_client, n)
    _force_seats(play_db, [79, 80, 300, 301], hero_stack=6)
    cur = play_client.get("/api/play/sessions/current").json()
    assert cur["must_rebuy"] and not cur["can_top_up"]
    n = _deal(play_client, cur)
    assert n["hero_bought_chips"] == cur["hero_bought_chips"] + 194
    assert _record(play_db, n["hand"]["id"]).start_stacks == (200, 200, 80, 300, 200)


def test_end_mid_hand_abandons(play_client, play_db):
    """Hero calls something, the hand is still running, the session ends: Hero loses what it
    committed and the live bots share it (``outcome5``'s abandon rule)."""
    v = _start5(play_client)
    for _ in range(40):
        if v["hand"]["status"] == "in_progress":
            kinds = [o["kind"] for o in v["hand"]["options"]]
            nxt = _act(play_client, v, kinds.index("call") if "call" in kinds else 1)
            if (
                nxt["hand"]["status"] == "in_progress"
                and nxt["hand"]["table"]["stacks"][0]
                < (_record(play_db, nxt["hand"]["id"]).start_stacks[0])
            ):
                v = nxt
                break
            v = _finish(play_client, nxt)
        v = _deal(play_client, v)
    else:
        pytest.fail("no running hand with Hero's chips in")
    record = replace(_record(play_db, v["hand"]["id"]), abandoned=True)
    e = play_client.post(f"/api/play/sessions/{v['id']}/end").json()
    out = e["hand"]["outcome"]
    o = outcome5(record)
    assert o.hero_delta < 0
    assert out["ended_by"] == "abandoned" and out["winner"] == "villain"
    assert out["hero_delta_chips"] == o.hero_delta
    assert out["pots"] == [] and out["shown"] == [] and out["villain_cards"] is None
    assert e["hero_stack"] == o.stacks[0] == v["hand"]["table"]["stacks"][0]
    assert [b["stack"] for b in e["bots"]] == list(o.stacks[1:])
    assert e["hands_played"] == v["hands_played"] + 1 and e["open"] is False
    _check_no_leak(e, record)
    assert play_client.post(f"/api/play/sessions/{v['id']}/end").json() == e
    last = play_client.get(f"/api/play/sessions/{v['id']}/hands").json()[-1]
    assert last["ended_by"] == "abandoned" and last["winner_names"] == []


def test_a_failing_bot_is_a_500_without_cards_and_a_bad_answer_is_a_422(
    play_client, play_db, monkeypatch
):
    v = _start5(play_client)
    while v["hand"]["status"] != "in_progress":
        v = _deal(play_client, v)
    hand = v["hand"]
    bad = {"expected_actions": hand["action_count"], "option": len(hand["options"])}
    r = play_client.post(f"/api/play/hands/{hand['id']}/actions", json=bad)
    assert r.status_code == 422

    def boom(*a, **k):
        raise ValueError("bot broke: cards 2c 3d")

    monkeypatch.setattr(play_service, "hero_act_seats", boom)
    good = {"expected_actions": hand["action_count"], "option": 0}
    quiet = type(play_client)(play_client.app, raise_server_exceptions=False)
    r = quiet.post(f"/api/play/hands/{hand['id']}/actions", json=good)
    assert r.status_code == 500
    assert "2c" not in r.text and "bot broke" not in r.text


def test_analysis_routes_refuse_five_max_hands(play_client):
    v = _finish(play_client, _start5(play_client))
    hid = v["hand"]["id"]
    for method, path in (
        ("GET", f"/api/play/hands/{hid}/analysis"),
        ("POST", f"/api/play/hands/{hid}/analysis/0"),
        ("GET", f"/api/play/hands/{hid}/analysis/0/explanation"),
    ):
        r = play_client.request(method, path)
        assert r.status_code == 409 and r.json() == {"detail": NO_ANALYSIS}, path
    v = _deal(play_client, v)  # a running hand is refused for the same reason
    if v["hand"]["status"] == "in_progress":
        r = play_client.get(f"/api/play/hands/{v['hand']['id']}/analysis")
        assert r.status_code == 409 and r.json() == {"detail": NO_ANALYSIS}


def test_lists_and_winner_names(play_client, play_db):
    v = _start5(play_client)
    for _ in range(12):
        v = _deal(play_client, _finish(play_client, v))
    sid = v["id"]
    (summary,) = play_client.get("/api/play/sessions").json()
    assert summary["table_size"] == 5 and summary["profile_label"] == "5-max"
    rows = play_client.get(f"/api/play/sessions/{sid}/hands").json()
    names = {b["seat"]: b["name"] for b in v["bots"]} | {0: "You"}
    for row in rows:
        assert row["table_size"] == 5 and row["analysed"] is False and row["ev_loss_bb"] is None
        if row["ended_by"] is None:
            assert row["winner_names"] == []
            continue
        record = _record(play_db, row["id"])
        o = outcome5(record)
        winners = sorted({w for p in o.pots for w in p.winners})
        assert row["winner_names"] == [names[w] for w in winners]
        assert row["hero_position"] == POSITIONS[(0 - record.button) % 5]
    assert any(row["winner_names"] and row["winner_names"] != ["You"] for row in rows)
    text = json.dumps(rows)  # the list never carries a card
    for row in rows:
        record = _record(play_db, row["id"])
        cards = [x for seat in range(1, 5) for x in hole(record, seat)] + list(record.deck[10:])
        assert all(f'"{card_str(c)}"' not in text for c in cards), row["id"]
        got = play_client.get(f"/api/play/hands/{row['id']}").json()
        _check_no_leak(got, record)


def test_bots_profiles_follow_the_setting(play_client):
    assert play_client.patch("/api/settings", json={"show_profile": False}).status_code == 200
    v = _start5(play_client)
    assert all(b["profile"] is None for b in v["bots"])
    # the seat views always carry the profile: the client hides it, as heads-up does
    assert all(s["profile"] is not None for s in v["hand"]["table"]["seats"][1:])
    play_client.patch("/api/settings", json={"show_profile": True})
    cur = play_client.get("/api/play/sessions/current").json()
    assert all(b["profile"] is not None for b in cur["bots"])


def test_seat_snapshots_are_used_not_the_live_files(play_client, monkeypatch):
    v = _start5(play_client)

    def boom(*a, **k):
        raise AssertionError("live 5-max data read after the session started")

    monkeypatch.setattr(SeatBot, "live", boom)
    v = _deal(play_client, _finish(play_client, v))
    assert _finish(play_client, v)["hand"]["status"] == "complete"


# ---------------------------------------------------------------------------
# Heads-up is unchanged apart from the new fields
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).resolve().parents[3] / "frontend" / "src" / "test" / "fixtures"
ADDED = {"seats", "table_size", "to_act_seat", "folded", "pots", "shown", "bots", "winner_names"}
# sha256 of each heads-up play fixture as committed before M12 (canonical JSON: sorted keys,
# no spaces); none of them had a key in ADDED
PRE_M12 = {
    "play_session_hero_to_act.json": (
        "32748d21164a3d9e7e51355bbf0b5e70fbf6e91c413e92686dee1f2b130b9b45"
    ),
    "play_session_hand_over_fold.json": (
        "de557c719f0ce913e5015c31cf4bf8f650620f10b0c006686c2bb0426a9efa70"
    ),
    "play_session_hand_over_showdown.json": (
        "dcce87f6a0a636071dbfd825a25a247a03d0178acc4e08181142db750218396e"
    ),
    "play_hand_analysis.json": "1dcebef52d64cb33d021103439b59309ed597724f330ae5ecca870e290a3d95d",
    "play_hands.json": "b5f019f736649a90e069f7368e368288f848ddcb0f7507706f6ee618177ebc97",
    "play_sessions.json": "d17f6e1dd340434000f2ecee63e9e4f1a5df2ca4b5a352190059dcec9ddb22f6",
}


def _strip(data):
    if isinstance(data, dict):
        return {k: _strip(v) for k, v in data.items() if k not in ADDED}
    if isinstance(data, list):
        return [_strip(v) for v in data]
    return data


def _digest(data) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@pytest.mark.parametrize("name", sorted(PRE_M12))
def test_heads_up_fixtures_unchanged_but_for_the_new_fields(name):
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert _digest(_strip(data)) == PRE_M12[name]
    assert ADDED & _keys(data), name  # the new fields are there


def _keys(data) -> set[str]:
    if isinstance(data, dict):
        return set(data).union(*(_keys(v) for v in data.values()))
    if isinstance(data, list):
        return set().union(*(_keys(v) for v in data))
    return set()


def test_heads_up_fixture_new_fields():
    v = json.loads((FIXTURES / "play_session_hand_over_showdown.json").read_text("utf-8"))
    t, out = v["hand"]["table"], v["hand"]["outcome"]
    assert v["table_size"] == t["table_size"] == 2
    assert v["bots"] == [
        {"seat": 1, "name": "Villain", "profile": v["profile"], "stack": v["bot_stack"]}
    ]
    assert t["seats"][1]["cards"] == out["villain_cards"]
    assert out["shown"] == [{"seat": 1, "cards": out["villain_cards"]}]
    assert [p["label"] for p in out["pots"]] == ["main pot"]
    assert all(len(f["folded"]) == 2 for f in v["hand"]["frames"])
