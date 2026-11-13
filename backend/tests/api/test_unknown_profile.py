"""Stored rows whose profile is no longer in ``PROFILE_NAMES`` still render (never a 500)."""

from dataclasses import replace

from sqlalchemy import select, update

from poker_trainer.db import PuzzleRow
from poker_trainer.db.blob import decode_puzzle, encode_puzzle


def _rename_profile(sessions, name: str) -> None:
    with sessions() as db:
        for row in db.scalars(select(PuzzleRow)).all():
            p = decode_puzzle(row.data)
            p = replace(p, spot=replace(p.spot, profile=name))
            db.execute(
                update(PuzzleRow)
                .where(PuzzleRow.id == row.id)
                .values(profile=name, data=encode_puzzle(p))
            )
        db.commit()


def test_unknown_profile_rows_render(client, sessions):
    pid = client.post("/api/puzzles", json={"street": "flop"}).json()["id"]
    r = client.post(f"/api/puzzles/{pid}/attempts", json={"option": 0, "equity_guess": 0.4})
    assert r.status_code == 201, r.text
    aid = r.json()["attempt"]["id"]
    _rename_profile(sessions, "maniac")

    r = client.get(f"/api/attempts/{aid}")
    assert r.status_code == 200, r.text
    reveal = r.json()["reveal"]["profile"]
    assert (reveal["name"], reveal["label"], reveal["description"]) == ("maniac", "Maniac", "")

    assert client.get(f"/api/attempts/{aid}/explanation").status_code == 200

    h = client.get("/api/history")
    assert h.status_code == 200, h.text
    s = client.get("/api/stats")
    assert s.status_code == 200, s.text
    assert [(b["key"], b["label"]) for b in s.json()["breakdowns"]["profile"]] == [
        ("maniac", "Maniac")
    ]

    v = client.get(f"/api/puzzles/{pid}")
    assert v.status_code == 200, v.text
    assert v.json()["custom"]["allowed"] is False

    listed = {o["to"] for o in client.get(f"/api/attempts/{aid}").json()["options"]}
    to = next(t for t in range(2, 195) if t not in listed)
    c = client.post(f"/api/puzzles/{pid}/attempts", json={"custom_to": to, "equity_guess": 0.5})
    assert c.status_code == 409, c.text
