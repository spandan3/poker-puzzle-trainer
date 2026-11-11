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
        "action_kind",
        "best_label",
        "best_kind",
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


def test_history_kind_and_best_columns(client):
    pid = _new(client, street="flop")["id"]
    res = _submit(client, pid, option=1)
    item = client.get("/api/history").json()["items"][0]
    assert item["chosen_label"] == res["grade"]["chosen_label"]
    assert item["best_label"] == res["grade"]["best_label"]
    chosen = next(o for o in res["options"] if o["is_chosen"])
    best = next(o for o in res["options"] if o["is_best"])
    assert item["action_kind"] == chosen["kind"] and item["best_kind"] == best["kind"]


def test_history_never_reads_chosen_json(client, sessions):
    """Summaries come from the ``chosen_label`` column, not the ~20 KB ``chosen`` JSON."""
    pid = _new(client, street="flop")["id"]
    label = _submit(client, pid, option=1)["grade"]["chosen_label"]
    with sessions() as db:
        db.execute(update(AttemptRow).values(chosen={}))
        db.commit()
    assert client.get("/api/history").json()["items"][0]["chosen_label"] == label
    assert client.get(f"/api/puzzles/{pid}/attempts").json()[0]["chosen_label"] == label


def test_history_filters(client, sessions):
    _make_history(client)
    with sessions() as db:  # give the turn puzzle another profile, so the filter has work to do
        db.execute(update(PuzzleRow).where(PuzzleRow.id == 2).values(profile="zzz"))
        db.commit()
    everything = client.get("/api/history").json()["items"]

    def check(query, keep):
        body = client.get(f"/api/history?{query}").json()
        want = [i["attempt_id"] for i in everything if keep(i)]
        assert [i["attempt_id"] for i in body["items"]] == want, query
        assert body["total"] == len(want), query

    check("street=flop", lambda i: i["street"] == "flop")
    check("street=river", lambda i: i["street"] == "river")
    check("profile=zzz", lambda i: i["profile"] == "zzz")
    kind = everything[0]["action_kind"]
    check(f"action_kind={kind}", lambda i: i["action_kind"] == kind)
    verdict = everything[0]["verdict"]
    check(f"verdict={verdict}", lambda i: i["verdict"] == verdict)
    check(
        "street=flop&first_only=true",
        lambda i: i["street"] == "flop" and i["is_first"],
    )


def test_history_filter_validation(client):
    for q in ("street=postflop", "verdict=nope", "action_kind=jam", "profile="):
        assert client.get(f"/api/history?{q}").status_code == 422, q
