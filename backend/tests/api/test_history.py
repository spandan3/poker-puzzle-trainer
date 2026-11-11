import json

from sqlalchemy import update

from poker_trainer.db import AttemptRow, PuzzleRow


def _new(client, **body):
    r = client.post("/api/puzzles", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _submit(client, pid, **body):
    body.setdefault("equity_guess", 0.4)
    r = client.post(f"/api/puzzles/{pid}/attempts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _make_history(client):
    ids = []
    for street in ("flop", "turn", "river"):
        pid = _new(client, street=street)["id"]
        ids.append(_submit(client, pid, option=0)["attempt"]["id"])
    # a replay of the first puzzle: attempt_no 2
    ids.append(_submit(client, 1, option=0)["attempt"]["id"])
    return ids


def test_history_newest_first_and_paging(client):
    ids = _make_history(client)
    r = client.get("/api/history")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4
    assert [i["attempt_id"] for i in body["items"]] == ids[::-1]
    item = body["items"][-1]
    assert set(item) == {
        "attempt_id",
        "puzzle_id",
        "attempt_no",
        "is_first",
        "created_at",
        "street",
        "profile",
        "chosen_label",
        "verdict",
        "ev_loss_bb",
        "equity_error",
        "range_read_error",
    }
    assert item["street"] == "flop" and item["attempt_no"] == 1 and item["is_first"] is True
    assert item["created_at"].endswith("+00:00")
    assert body["items"][0]["attempt_no"] == 2 and body["items"][0]["is_first"] is False

    page = client.get("/api/history?limit=2&offset=1").json()
    assert page["total"] == 4
    assert [i["attempt_id"] for i in page["items"]] == ids[::-1][1:3]
    assert client.get("/api/history?offset=10").json() == {"items": [], "total": 4}

    first = client.get("/api/history?first_only=true").json()
    assert first["total"] == 3
    assert all(i["is_first"] for i in first["items"])

    for q in ("limit=0", "limit=201", "offset=-1", "limit=x"):
        assert client.get(f"/api/history?{q}").status_code == 422, q
    assert client.get("/api/history?limit=200").status_code == 200


def test_history_never_decodes_blobs(client, sessions):
    _make_history(client)
    with sessions() as db:
        db.execute(update(PuzzleRow).values(data=b"garbage"))
        db.commit()
    r = client.get("/api/history")
    assert r.status_code == 200 and r.json()["total"] == 4
    assert json.dumps(r.json(), allow_nan=False)


def test_history_matches_stored_columns(client, sessions):
    pid = _new(client, street="flop")["id"]
    res = _submit(client, pid, option=0, range_read_guess=0.5)
    with sessions() as db:
        db.execute(update(AttemptRow).values(verdict="blunder"))
        db.commit()
    item = client.get("/api/history").json()["items"][0]
    assert item["verdict"] == "blunder"
    assert item["chosen_label"] == res["grade"]["chosen_label"]
    assert item["ev_loss_bb"] == res["grade"]["ev_loss_bb"]
    assert item["equity_error"] == res["grade"]["equity_error"]
    assert item["range_read_error"] == res["grade"]["range_read_error"]
