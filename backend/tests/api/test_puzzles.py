import json
import zlib
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

import poker_trainer
from poker_trainer.api import service, views
from poker_trainer.api.app import create_app
from poker_trainer.db import DEFAULT_USER_ID, AttemptRow, PuzzleRow, User, UserSettings
from poker_trainer.engine.cards import card_str
from poker_trainer.game.state import Street
from poker_trainer.puzzle.grade import Answer, grade
from poker_trainer.puzzle.model import load_config
from poker_trainer.puzzle.options import custom_action
from poker_trainer.settings import AppSettings
from poker_trainer.villain.features import load_thresholds
from poker_trainer.villain.profiles import load_profile

BAD_KEYS = {"range", "steps", "solution", "seed", "villain_hole", "runout", "combo_equity"}
STALE_DETAIL = (
    "Villain model changed since this puzzle was generated; custom sizes are disabled for this "
    "puzzle"
)


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def _new(client, **body):
    r = client.post("/api/puzzles", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _submit(client, puzzle_id, **body):
    body.setdefault("equity_guess", 0.4)
    return client.post(f"/api/puzzles/{puzzle_id}/attempts", json=body)


def _stale_profile(monkeypatch, p):
    prof = load_profile(p.spot.profile)
    stale = lambda name: replace(prof, version=prof.version + 1)
    monkeypatch.setattr(views, "load_profile", stale)  # the one version check, used by both


def _stale_categories(monkeypatch):
    cats = load_thresholds()
    stale = lambda: replace(cats, version=cats.version + 1)
    monkeypatch.setattr(views, "load_thresholds", stale)


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": poker_trainer.__version__}


@pytest.mark.parametrize("street", ["preflop", "flop", "turn", "river"])
def test_new_puzzle_201_hidden(client, sessions, cached_puzzles, street):
    p = cached_puzzles[street]
    r = client.post("/api/puzzles", json={"street": street})
    assert r.status_code == 201
    text = r.text
    view = r.json()
    for c in p.spot.villain_hole:
        assert json.dumps(card_str(c)) not in text
    for c in p.spot.runout[len(p.spot.state.board) :]:
        assert json.dumps(card_str(c)) not in text
    assert not set(_keys(view)) & BAD_KEYS
    for o in p.solution.options:
        assert repr(float(o.ev_chips)) not in text
    assert view["street"] == street
    assert view["attempts_so_far"] == 0
    with sessions() as db:
        row = db.get(PuzzleRow, view["id"])
        assert row is not None and row.user_id == DEFAULT_USER_ID
        assert row.street == street and row.profile == p.spot.profile
        assert row.profile_version == p.spot.profile_version
        assert row.categories_version == p.spot.categories_version
        assert row.config_version == p.spot.config_version
        assert row.seed == p.spot.seed and row.format == 1


def test_new_puzzle_without_body(client, factory):
    r = client.post("/api/puzzles")
    assert r.status_code == 201
    assert factory.calls[-1][1:] == (None, None)


def test_new_puzzle_passes_street_and_profile(client, factory):
    _new(client, street="turn", profile="tight")
    _seed, street, profile = factory.calls[-1]
    assert street == Street.TURN and profile == "tight"


def test_new_puzzle_uses_settings_profile(client, sessions, factory):
    with sessions() as db:
        db.execute(update(UserSettings).values(profile="sticky"))
        db.commit()
    _new(client)
    assert factory.calls[-1][2] == "sticky"
    _new(client, profile="tag")  # an explicit profile wins
    assert factory.calls[-1][2] == "tag"


def test_new_puzzle_bad_street_422(client):
    assert client.post("/api/puzzles", json={"street": "fourth"}).status_code == 422
    assert client.post("/api/puzzles", json={"profile": "maniac"}).status_code == 422
    assert client.post("/api/puzzles", json={"seed": 5}).status_code == 422


def test_generation_failure_retries_then_503(client, factory):
    factory.fail = 3
    r = client.post("/api/puzzles", json={})
    assert r.status_code == 503
    assert r.json() == {"detail": "could not generate a puzzle, try again"}
    assert len(factory.calls) == 3
    assert len({seed for seed, _, _ in factory.calls}) == 3  # a fresh seed each time

    factory.calls.clear()
    factory.fail = 2
    assert client.post("/api/puzzles", json={}).status_code == 201
    assert len(factory.calls) == 3


def test_submit_listed_option(client, cached_puzzles):
    p = cached_puzzles["flop"]
    pid = _new(client, street="flop")["id"]
    r = _submit(client, pid, option=1, equity_guess=0.35, range_read_guess=0.6, intent="bluff")
    assert r.status_code == 201, r.text
    res = r.json()
    g = grade(p, Answer(p.solution.options[1].option.action, 0.35, 0.6, "bluff"))
    assert res["grade"]["verdict"] == g.verdict
    assert res["grade"]["ev_loss_chips"] == g.ev_loss_chips
    assert res["grade"]["equity_error"] == g.equity_error
    assert res["grade"]["range_read_error"] == g.range_read_error
    assert res["grade"]["intent_truth"] == g.intent_truth
    assert res["grade"]["intent_flag"] == g.intent_flag
    assert res["grade"]["best_label"] == g.best.option.label
    assert res["grade"]["chosen_label"] == p.solution.options[1].option.label
    assert res["attempt"]["is_first"] is True
    assert res["attempt"]["attempt_no"] == 1
    assert res["attempt"]["puzzle_id"] == pid
    assert res["answer"]["option_index"] == 1 and res["answer"]["custom_to"] is None
    act = p.solution.options[1].option.action
    assert res["answer"]["action"] == {
        "seat": act.seat,
        "kind": act.kind.value,
        "street": "flop",  # a name, like every other street in the API (stored as an int)
        "to": act.to,
    }
    assert res["reveal"]["villain_cards"] == [card_str(c) for c in p.spot.villain_hole]
    assert sum(o["is_chosen"] for o in res["options"]) == 1
    assert len(res["options"]) == len(p.solution.options)


def test_submit_second_attempt_not_first(client, sessions):
    pid = _new(client)["id"]
    first = _submit(client, pid, option=0).json()["attempt"]
    second = _submit(client, pid, option=1).json()["attempt"]
    third = _submit(client, pid, option=0).json()["attempt"]
    assert (first["attempt_no"], first["is_first"]) == (1, True)
    assert (second["attempt_no"], second["is_first"]) == (2, False)
    assert (third["attempt_no"], third["is_first"]) == (3, False)
    with sessions() as db:
        rows = db.scalars(select(AttemptRow).where(AttemptRow.puzzle_id == pid)).all()
        assert sorted(r.attempt_no for r in rows) == [1, 2, 3]
        assert [r.is_first for r in sorted(rows, key=lambda r: r.attempt_no)] == [
            True,
            False,
            False,
        ]


def test_submit_retries_attempt_no_conflict(client, monkeypatch):
    pid = _new(client)["id"]
    _submit(client, pid, option=0)
    real = service._next_attempt_no
    calls = []

    def stale_once(db, puzzle_id):
        calls.append(puzzle_id)
        return 1 if len(calls) == 1 else real(db, puzzle_id)  # first try collides with no 1

    monkeypatch.setattr(service, "_next_attempt_no", stale_once)
    r = _submit(client, pid, option=1)
    assert r.status_code == 201, r.text
    assert r.json()["attempt"]["attempt_no"] == 2
    assert len(calls) == 2


@pytest.mark.parametrize(
    "body",
    [
        {"option": 0, "custom_to": 5, "equity_guess": 0.4},
        {"equity_guess": 0.4},
        {"option": 99, "equity_guess": 0.4},
        {"option": -1, "equity_guess": 0.4},
        {"option": 0, "equity_guess": 1.5},
        {"option": 0, "equity_guess": -0.1},
        {"option": 0},
        {"option": 0, "equity_guess": 0.4, "range_read_guess": 2},
        {"option": 0, "equity_guess": 0.4, "intent": "trap"},
        {"option": 0, "equity_guess": 0.4, "action": {"kind": "fold"}},
        {"option": True, "equity_guess": 0.4},
        {"option": "1", "equity_guess": 0.4},
        {"option": 1.0, "equity_guess": 0.4},
        {"custom_to": "50", "equity_guess": 0.4},
    ],
)
def test_submit_validation(client, body):
    pid = _new(client, street="flop")["id"]
    r = client.post(f"/api/puzzles/{pid}/attempts", json=body)
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize(
    "template",
    [
        '{{"option": 0, "equity_guess": {}}}',
        '{{"option": 0, "equity_guess": 0.4, "range_read_guess": {}}}',
    ],
)
def test_submit_rejects_non_finite(client, bad, template):
    pid = _new(client, street="flop")["id"]
    r = client.post(
        f"/api/puzzles/{pid}/attempts",
        content=template.format(bad),
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 422, r.text


def test_custom_size_postflop(client, cached_puzzles):
    p = cached_puzzles["flop"]
    pid = _new(client, street="flop")["id"]
    lo, hi = views.custom_bounds(p)
    listed = {o.option.action.to for o in p.solution.options}
    to = next(t for t in range(lo, hi + 1) if t not in listed)
    r = _submit(client, pid, custom_to=to, equity_guess=0.5)
    assert r.status_code == 201, r.text
    res = r.json()
    g = grade(p, Answer(custom_action(p.spot.state, to), 0.5))
    assert res["grade"]["verdict"] == g.verdict
    assert res["grade"]["ev_loss_chips"] == g.ev_loss_chips
    assert len(res["options"]) == len(p.solution.options) + 1
    assert res["options"][-1]["is_chosen"] and res["options"][-1]["to"] == to
    assert res["answer"]["custom_to"] == to and res["answer"]["option_index"] is None
    assert res["answer"]["action"]["to"] == to


def test_custom_size_out_of_bounds_422(client, cached_puzzles):
    p = cached_puzzles["flop"]
    pid = _new(client, street="flop")["id"]
    _lo, hi = views.custom_bounds(p)
    r = _submit(client, pid, custom_to=hi + 1)
    assert r.status_code == 422
    assert r.json()["detail"] == custom_action_error(p, hi + 1)


def custom_action_error(p, to):
    try:
        custom_action(p.spot.state, to)
    except ValueError as e:
        return str(e)
    raise AssertionError("expected ValueError")


def test_custom_size_preflop_422(client):
    pid = _new(client, street="preflop")["id"]
    r = _submit(client, pid, custom_to=7)
    assert r.status_code == 422
    assert r.json()["detail"] == "custom sizes are only allowed after the flop"


def _check_stale(client, p):
    view = _new(client, street="flop")
    assert view["custom"] == {"allowed": False, "min_to": None, "max_to": None}
    pid = view["id"]
    lo, hi = views.custom_bounds(p)
    listed = {o.option.action.to for o in p.solution.options}
    to = next(t for t in range(lo, hi + 1) if t not in listed)
    r = _submit(client, pid, custom_to=to)
    assert r.status_code == 409
    assert r.json() == {"detail": STALE_DETAIL}
    assert _submit(client, pid, option=1).status_code == 201
    same = p.solution.options[2]
    r = _submit(client, pid, custom_to=same.option.action.to)
    assert r.status_code == 201, r.text
    assert r.json()["grade"]["chosen_label"] == same.option.label
    assert len(r.json()["options"]) == len(p.solution.options)


def test_custom_size_stale_profile_409(client, cached_puzzles, monkeypatch):
    p = cached_puzzles["flop"]
    _stale_profile(monkeypatch, p)
    _check_stale(client, p)


def test_custom_size_stale_categories_409(client, cached_puzzles, monkeypatch):
    p = cached_puzzles["flop"]
    _stale_categories(monkeypatch)
    _check_stale(client, p)


def test_attempt_kinds_stored(client, sessions, cached_puzzles):
    p = cached_puzzles["flop"]
    pid = _new(client, street="flop")["id"]
    aid = _submit(client, pid, option=0, range_read_guess=0.5).json()["attempt"]["id"]
    best = p.solution.options[p.solution.best]
    with sessions() as db:
        row = db.get(AttemptRow, aid)
        assert row.user_id == DEFAULT_USER_ID
        assert row.action_kind == p.solution.options[0].option.action.kind.value
        assert row.best_kind == best.option.action.kind.value
        assert row.best_label == best.option.label
        assert row.best_ev_chips == best.ev_chips
        assert row.config_version == load_config().version
        assert row.option_index == 0 and row.custom_to is None
        assert row.action == {
            "seat": p.spot.hero_seat,
            "kind": row.action_kind,
            "street": int(Street.FLOP),
            "to": p.solution.options[0].option.action.to,
        }
        assert row.chosen == views.option_ev_to_dict(p.solution.options[0])
        assert row.equity_guess == 0.4 and row.range_read_guess == 0.5


def test_attempt_config_version_is_live(client, sessions, monkeypatch):
    live = replace(load_config(), version=load_config().version + 7)
    monkeypatch.setattr(service, "load_config", lambda: live)
    pid = _new(client, street="flop")["id"]
    aid = _submit(client, pid, option=0).json()["attempt"]["id"]
    with sessions() as db:
        assert db.get(AttemptRow, aid).config_version == live.version
        assert db.get(PuzzleRow, pid).config_version != live.version


def test_created_at_utc(client):
    pid = _new(client)["id"]
    posted = _submit(client, pid, option=0).json()["attempt"]
    assert posted["created_at"].endswith("+00:00")
    got = client.get(f"/api/attempts/{posted['id']}").json()["attempt"]
    assert got["created_at"].endswith("+00:00")
    assert got["created_at"] == posted["created_at"]


def test_get_attempt_returns_stored_grade(client, sessions):
    pid = _new(client, street="flop")["id"]
    posted = _submit(client, pid, option=0).json()
    aid = posted["attempt"]["id"]
    assert client.get(f"/api/attempts/{aid}").json() == posted
    new_verdict = "blunder" if posted["grade"]["verdict"] != "blunder" else "best"
    with sessions() as db:
        db.execute(
            update(AttemptRow)
            .where(AttemptRow.id == aid)
            .values(verdict=new_verdict, ev_loss_chips=123.5)
        )
        db.commit()
    got = client.get(f"/api/attempts/{aid}").json()
    assert got["grade"]["verdict"] == new_verdict
    assert got["grade"]["ev_loss_chips"] == 123.5


def test_unknown_ids_404(client):
    assert client.get("/api/attempts/999").status_code == 404
    assert _submit(client, 999, option=0).status_code == 404
    huge = 2**70  # beyond SQLite's integer range: still a plain 404
    for bad in (0, -1, huge):
        assert client.get(f"/api/attempts/{bad}").json() == {"detail": "attempt not found"}
        assert _submit(client, bad, option=0).json() == {"detail": "puzzle not found"}
    assert client.get("/api/nope").status_code == 404


def test_other_users_rows_404(client, sessions):
    pid = _new(client, street="flop")["id"]
    aid = _submit(client, pid, option=0).json()["attempt"]["id"]
    with sessions() as db:
        db.add(User(id=2, name="other"))
        db.execute(update(PuzzleRow).values(user_id=2))
        db.execute(update(AttemptRow).values(user_id=2))
        db.commit()
    assert client.get(f"/api/attempts/{aid}").json() == {"detail": "attempt not found"}
    assert _submit(client, pid, option=0).json() == {"detail": "puzzle not found"}


def test_unsupported_format_500(client, sessions):
    pid = _new(client)["id"]
    with sessions() as db:
        row = db.get(PuzzleRow, pid)
        raw = json.loads(zlib.decompress(row.data).decode("utf-8"))
        raw["format"] = 2
        row.data = zlib.compress(json.dumps(raw).encode("utf-8"))
        db.commit()
    r = _submit(client, pid, option=0)
    assert r.status_code == 500
    assert r.json() == {"detail": "unsupported puzzle format"}


def test_responses_utf8(client, cached_puzzles):
    p = cached_puzzles["flop"]
    assert any("—" in b.label for o in p.solution.options for b in o.branches)
    pid = _new(client, street="flop")["id"]
    r = _submit(client, pid, option=0)
    assert r.headers["content-type"].startswith("application/json")
    assert "—".encode() in r.content  # UTF-8, not \u escapes
    labels = [b["label"] for o in r.json()["options"] for b in o["branches"]]
    assert any("—" in label for label in labels)


def test_concurrent_submit_exhausted_retry_409(client, monkeypatch):
    pid = _new(client, street="flop")["id"]
    assert _submit(client, pid, option=0).status_code == 201
    monkeypatch.setattr(service, "_next_attempt_no", lambda db, puzzle_id: 1)
    r = _submit(client, pid, option=0)
    assert r.status_code == 409
    assert r.json() == {"detail": "concurrent submit, try again"}


def test_unexpected_error_is_json_500(tmp_path):
    """Any unhandled error still answers ``{"detail": ...}`` as JSON, never plain text."""

    def broken(seed, street, profile):
        raise ValueError("boom")

    settings = AppSettings(
        _env_file=None, database_url=f"sqlite:///{(tmp_path / 'e.db').as_posix()}"
    )
    app = create_app(settings, puzzle_factory=broken)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/api/puzzles", json={})
    assert r.status_code == 500
    assert r.json() == {"detail": "internal server error"}
