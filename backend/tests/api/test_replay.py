BAD_KEYS = {"range", "steps", "solution", "seed", "villain_hole", "runout", "combo_equity"}


def _new(client, **body):
    r = client.post("/api/puzzles", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _submit(client, pid, **body):
    body.setdefault("equity_guess", 0.4)
    return client.post(f"/api/puzzles/{pid}/attempts", json=body)


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def test_replay_get_puzzle_hidden(client, cached_puzzles):
    p = cached_puzzles["flop"]
    created = _new(client, street="flop")
    pid = created["id"]
    assert client.get(f"/api/puzzles/{pid}").json() == created
    assert _submit(client, pid, option=0).json()["attempt"]["attempt_no"] == 1
    r = client.get(f"/api/puzzles/{pid}")
    assert r.status_code == 200
    body = r.json()
    assert body["attempts_so_far"] == 1
    assert not BAD_KEYS & set(_keys(body))
    for c in p.spot.villain_hole:
        from poker_trainer.engine.cards import card_str

        assert f'"{card_str(c)}"' not in r.text
    second = _submit(client, pid, option=0).json()["attempt"]
    assert second["attempt_no"] == 2 and second["is_first"] is False
    assert client.get(f"/api/puzzles/{pid}").json()["attempts_so_far"] == 2


def test_puzzle_attempts_list(client):
    pid = _new(client, street="flop")["id"]
    other = _new(client, street="turn")["id"]
    assert client.get(f"/api/puzzles/{pid}/attempts").json() == []
    a1 = _submit(client, pid, option=0).json()["attempt"]["id"]
    _submit(client, other, option=0)
    a2 = _submit(client, pid, option=1).json()["attempt"]["id"]
    r = client.get(f"/api/puzzles/{pid}/attempts")
    assert r.status_code == 200
    items = r.json()
    assert [i["attempt_id"] for i in items] == [a1, a2]
    assert [i["attempt_no"] for i in items] == [1, 2]
    assert all(i["puzzle_id"] == pid for i in items)


def test_replay_unknown_404(client):
    assert client.get("/api/puzzles/999").status_code == 404
    assert client.get("/api/puzzles/999/attempts").status_code == 404
    assert client.get(f"/api/puzzles/{2**70}").json() == {"detail": "puzzle not found"}


def test_current_puzzle(client):
    assert client.get("/api/puzzles/current").status_code == 404
    first = _new(client, street="flop")
    r = client.get("/api/puzzles/current")
    assert r.status_code == 200 and r.json() == first
    assert _submit(client, first["id"], option=0).status_code == 201
    assert client.get("/api/puzzles/current").status_code == 404
    _new(client, street="turn")  # unanswered, older
    newer = _new(client, street="river")
    assert client.get("/api/puzzles/current").json() == newer


def test_current_puzzle_never_returns_a_skipped_one(client):
    """Asking for a new puzzle skips the unanswered one; once the newer is answered, the
    skipped puzzle must not come back as "current"."""
    skipped = _new(client, street="flop")
    answered = _new(client, street="turn")
    assert _submit(client, answered["id"], option=0).status_code == 201
    r = client.get("/api/puzzles/current")
    assert r.status_code == 404, f"skipped puzzle {skipped['id']} came back"
    # a replay of the skipped puzzle is still reachable by id
    assert client.get(f"/api/puzzles/{skipped['id']}").status_code == 200
