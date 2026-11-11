from sqlalchemy import update

from poker_trainer.db import AttemptRow, PuzzleRow, User


def _new(client, **body):
    r = client.post("/api/puzzles", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _submit(client, pid, **body):
    body.setdefault("equity_guess", 0.4)
    return client.post(f"/api/puzzles/{pid}/attempts", json=body)


def test_user_isolation(client, sessions):
    pid = _new(client, street="flop")["id"]
    aid = _submit(client, pid, option=0).json()["attempt"]["id"]
    mine = _new(client, street="turn")["id"]  # stays with user 1
    _submit(client, mine, option=0)
    with sessions() as db:
        db.add(User(id=2, name="other"))
        db.flush()
        db.execute(update(PuzzleRow).where(PuzzleRow.id == pid).values(user_id=2))
        db.execute(update(AttemptRow).where(AttemptRow.id == aid).values(user_id=2))
        db.commit()
    assert client.get(f"/api/puzzles/{pid}").json() == {"detail": "puzzle not found"}
    assert client.get(f"/api/puzzles/{pid}/attempts").status_code == 404
    assert client.get(f"/api/attempts/{aid}").status_code == 404
    assert _submit(client, pid, option=0).status_code == 404
    hist = client.get("/api/history").json()
    assert hist["total"] == 1 and hist["items"][0]["puzzle_id"] == mine
    assert (
        client.get("/api/puzzles/current").status_code == 404
    )  # user 2's is not mine, mine answered


def test_current_ignores_other_users_unanswered(client, sessions):
    pid = _new(client, street="flop")["id"]
    with sessions() as db:
        db.add(User(id=2, name="other"))
        db.flush()
        db.execute(update(PuzzleRow).where(PuzzleRow.id == pid).values(user_id=2))
        db.commit()
    assert client.get("/api/puzzles/current").status_code == 404


def test_other_users_attempts_not_counted(client, sessions):
    pid = _new(client, street="flop")["id"]
    _submit(client, pid, option=0)
    with sessions() as db:
        db.add(User(id=2, name="other"))
        db.flush()
        db.execute(update(AttemptRow).values(user_id=2))
        db.commit()
    assert client.get(f"/api/puzzles/{pid}").json()["attempts_so_far"] == 0
    assert client.get(f"/api/puzzles/{pid}/attempts").json() == []
    assert client.get("/api/history").json() == {"items": [], "total": 0}


def test_current_skips_newer_puzzle_of_other_user(client, sessions):
    mine = _new(client, street="flop")
    theirs = _new(client, street="turn")["id"]
    with sessions() as db:
        db.add(User(id=2, name="other"))
        db.flush()
        db.execute(update(PuzzleRow).where(PuzzleRow.id == theirs).values(user_id=2))
        db.commit()
    assert client.get("/api/puzzles/current").json() == mine


def test_current_ignores_other_users_attempts(client, sessions):
    pid = _new(client, street="flop")["id"]
    _submit(client, pid, option=0)
    with sessions() as db:
        db.add(User(id=2, name="other"))
        db.flush()
        db.execute(update(AttemptRow).values(user_id=2))
        db.commit()
    assert client.get("/api/puzzles/current").json()["id"] == pid  # 0 attempts of mine


def test_history_skips_attempts_on_other_users_puzzles(client, sessions):
    pid = _new(client, street="flop")["id"]
    _submit(client, pid, option=0)
    with sessions() as db:
        db.add(User(id=2, name="other"))
        db.flush()
        db.execute(update(PuzzleRow).values(user_id=2))
        db.commit()
    assert client.get("/api/history").json() == {"items": [], "total": 0}
