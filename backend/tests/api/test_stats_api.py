"""``GET /api/stats``: the route over ``stats.service.compute``."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import update

from poker_trainer.api import service
from poker_trainer.api.schemas import StatsView
from poker_trainer.db import AttemptRow, PuzzleRow, User


def _new(client, **body):
    r = client.post("/api/puzzles", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _submit(client, pid, **body):
    body.setdefault("equity_guess", 0.4)
    r = client.post(f"/api/puzzles/{pid}/attempts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _stats(client, **params):
    r = client.get("/api/stats", params=params)
    assert r.status_code == 200, r.text
    body = r.json()
    StatsView.model_validate(body)
    return body


def test_empty(client):
    body = _stats(client)
    assert body["tz"] == "UTC"
    assert body["totals"] == {"first_attempts": 0, "retries": 0}
    assert all(v is None for v in body["headline"].values())
    assert body["trend"] == [] and body["leaks"] == []
    assert body["breakdowns"] == {"street": [], "action": [], "profile": []}
    assert body["streak"] == {"current": 0, "best": 0}
    assert body["days"]["goal"] == 10 and body["days"]["today"] == 0
    assert len(body["days"]["recent"]) == 14


def test_counts_first_attempts_and_retries(client):
    flop = _new(client, street="flop")["id"]
    a1 = _submit(client, flop, option=0)
    turn = _new(client, street="turn")["id"]
    _submit(client, turn, option=0)
    _submit(client, flop, option=0)  # a retry
    body = _stats(client, tz="Europe/London")
    assert body["tz"] == "Europe/London"
    assert body["totals"] == {"first_attempts": 2, "retries": 1}
    assert [p["n"] for p in body["trend"]] == [1, 2]
    assert body["trend"][0]["attempt_id"] == a1["attempt"]["id"]
    assert body["trend"][0]["ev_lost_bb"] == a1["grade"]["ev_loss_bb"]
    assert body["trend"][0]["equity_error"] == a1["grade"]["equity_error"]
    assert [r["key"] for r in body["breakdowns"]["street"]] == ["flop", "turn"]
    assert sum(r["count"] for r in body["breakdowns"]["profile"]) == 2
    assert body["days"]["today"] == 2


def test_goal_comes_from_settings(client):
    assert client.patch("/api/settings", json={"daily_goal": 1}).status_code == 200
    _submit(client, _new(client, street="flop")["id"], option=0)
    days = _stats(client)["days"]
    assert days["goal"] == 1 and days["current_streak"] == 1


def test_now_is_the_service_clock(client, monkeypatch):
    _submit(client, _new(client, street="flop")["id"], option=0)
    monkeypatch.setattr(service, "utcnow", lambda: datetime(2030, 1, 1, 12, tzinfo=UTC))
    days = _stats(client)["days"]
    assert days["recent"][-1] == {"date": "2030-01-01", "count": 0}
    assert days["today"] == 0


@pytest.mark.parametrize("tz", ["Bad/Zone", "../etc", "Europe"])
def test_unknown_time_zone_is_422(client, tz):
    r = client.get("/api/stats", params={"tz": tz})
    assert r.status_code == 422
    assert r.json() == {"detail": "unknown time zone"}


def test_tz_length_is_validated(client):
    assert client.get("/api/stats", params={"tz": ""}).status_code == 422
    assert client.get("/api/stats", params={"tz": "a" * 65}).status_code == 422


def test_no_blob_decode_on_stats_or_history(client, monkeypatch):
    pid = _new(client, street="flop")["id"]
    _submit(client, pid, option=0)
    _submit(client, pid, option=0)

    def boom(*_a, **_k):
        raise AssertionError("a puzzle blob was decoded")

    monkeypatch.setattr("poker_trainer.db.blob.puzzle_from_dict", boom)
    with pytest.raises(AssertionError, match="blob was decoded"):  # the patch does bite
        client.get(f"/api/puzzles/{pid}")
    assert _stats(client)["totals"] == {"first_attempts": 1, "retries": 1}
    assert client.get("/api/history").status_code == 200


def test_other_users_attempts_not_counted(client, sessions):
    theirs = _new(client, street="flop")["id"]
    _submit(client, theirs, option=0)
    mine = _new(client, street="turn")["id"]
    _submit(client, mine, option=0)
    with sessions() as db:
        db.add(User(id=2, name="other"))
        db.flush()
        db.execute(update(PuzzleRow).where(PuzzleRow.id == theirs).values(user_id=2))
        db.execute(update(AttemptRow).where(AttemptRow.puzzle_id == theirs).values(user_id=2))
        db.commit()
    body = _stats(client)
    assert body["totals"] == {"first_attempts": 1, "retries": 0}
    assert [r["key"] for r in body["breakdowns"]["street"]] == ["turn"]


def test_attempts_on_other_users_puzzles_not_counted(client, sessions):
    pid = _new(client, street="flop")["id"]
    _submit(client, pid, option=0)
    with sessions() as db:
        db.add(User(id=2, name="other"))
        db.flush()
        db.execute(update(PuzzleRow).values(user_id=2))
        db.commit()
    assert _stats(client)["totals"] == {"first_attempts": 0, "retries": 0}


def test_stats_rows_has_every_stat_column(client, sessions):
    pid = _new(client, street="flop")["id"]
    a = _submit(client, pid, option=0, range_read_guess=0.3)
    with sessions() as db:
        (r,) = service.stats_rows(db, 1)
        stored = db.get(AttemptRow, a["attempt"]["id"])
        assert r.id == stored.id and r.created_at == stored.created_at
        assert r.street == "flop" and r.is_first is True
        for name in (
            "action_kind",
            "best_kind",
            "verdict",
            "ev_loss_chips",
            "equity_guess",
            "equity_error",
            "true_equity",
            "range_read_guess",
            "range_read_error",
            "ahead_now",
            "hero_category",
            "intent",
            "intent_truth",
            "intent_flag",
            "bluff_required",
            "bluff_actual",
        ):
            assert getattr(r, name) == getattr(stored, name), name
        assert r.true_equity is not None and r.range_read_guess == 0.3
