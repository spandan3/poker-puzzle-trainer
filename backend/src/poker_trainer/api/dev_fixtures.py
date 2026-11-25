"""Dev-only: write the JSON fixtures the frontend tests and gallery use.

Run from ``backend/``::

    uv run python -m poker_trainer.api.dev_fixtures ../frontend/src/test/fixtures

For each named predicate the generator searches puzzle seeds in a fixed order (seed 1, 2, ... on
each street in turn) and keeps the first puzzle that satisfies it. The puzzles are then served by
the real app (a temporary SQLite database and a ``puzzle_factory`` that hands out the chosen
puzzles), so every file holds exactly what the API returns. Output is deterministic: sorted keys,
LF line endings, fixed timestamps.

``write_stats_fixtures`` answers a scripted series of puzzles on its own database, with the
service clock replaced, for the Progress page's ``stats.json``, ``stats_empty.json`` and
``history_page.json``.

``write_play_fixtures`` plays a scripted session against the bot on its own database, with a
seeded ``play_rng`` and the service clock replaced, for the Play page's ``play_*.json``. Only
those files are written with ``--play-only``, together with the 5-max ``play5_*.json`` from
``write_play5_fixtures`` (its own seeded session)::

    uv run python -m poker_trainer.api.dev_fixtures ../frontend/src/test/fixtures --play-only
"""

from __future__ import annotations

import json
import random
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from poker_trainer.api import service, views
from poker_trainer.api.app import create_app
from poker_trainer.api.schemas import StatsView
from poker_trainer.explain import ollama
from poker_trainer.explain.service import Explainer
from poker_trainer.game.state import ActionKind, Street
from poker_trainer.puzzle.generate import generate_puzzle
from poker_trainer.puzzle.model import Puzzle
from poker_trainer.settings import AppSettings
from poker_trainer.stats.service import compute

STREETS = ("preflop", "flop", "turn", "river")
MAX_SEED = 400  # per street; the search stops (and reports) when a predicate is not found
NEVER_CONTINUES_MAX_SEED = 200
FIXED_TIME = "2026-01-01T00:00:00+00:00"

# stats fixtures: first attempt k (0-based) at STATS_START + k * STATS_STEP, plus STATS_GAP from
# attempt STATS_GAP_AT on (a break, so a recent day misses the goal), so 105 of them span about
# 31 days; FIXED_NOW is on the last one's day
STATS_START = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
STATS_STEP = timedelta(hours=7)
STATS_GAP_AT = 95
STATS_GAP = timedelta(hours=30)
STATS_FIRST_ATTEMPTS = 105  # over 100, so the headline's "previous 50" is set
STATS_RETRY_AFTER = (50, 90, 100)  # first attempts followed by a retry of the same puzzle
STATS_GOAL = 3  # 3 or 4 attempts a day: met on most days, so the day streaks aren't trivial


def _stats_time(k: int) -> datetime:
    """When first attempt ``k`` (0-based) of the stats fixtures is made."""
    return STATS_START + k * STATS_STEP + (STATS_GAP if k >= STATS_GAP_AT else timedelta(0))


FIXED_NOW = _stats_time(STATS_FIRST_ATTEMPTS - 1) + timedelta(hours=2)

View = dict[str, Any]


def _entries(v: View, street: str) -> list[dict[str, Any]]:
    return [e for e in v["history"] if e["street"] == street]


def _raises(v: View, street: str) -> int:
    return sum(1 for e in _entries(v, street) if e["kind"] == "raise")


def _kinds(v: View) -> set[str]:
    return {o["kind"] for o in v["options"]}


def _facing_all_in(v: View) -> bool:
    last = v["history"][-1] if v["history"] else None
    return (
        last is not None
        and last["actor"] == "villain"
        and last["all_in"]
        and _kinds(v) == {"fold", "call"}
    )


# name -> predicate over the puzzle view; searched in this (fixed) order
PREDICATES: dict[str, Callable[[View], bool]] = {
    "preflop_btn_first_in": lambda v: (
        v["street"] == "preflop" and v["hero_position"] == "BTN" and not v["history"]
    ),
    "preflop_bb_facing_open": lambda v: (
        v["street"] == "preflop" and v["hero_position"] == "BB" and _raises(v, "preflop") == 1
    ),
    "preflop_facing_3bet": lambda v: (
        v["street"] == "preflop" and _raises(v, "preflop") == 2 and "call" in _kinds(v)
    ),
    "facing_all_in": _facing_all_in,
    "flop_unopened": lambda v: v["street"] == "flop" and not _entries(v, "flop"),
    "facing_postflop_raise": lambda v: (
        v["street"] != "preflop"
        and bool(v["history"])
        and v["history"][-1]["kind"] == "raise"
        and v["history"][-1]["actor"] == "villain"
        and "call" in _kinds(v)
    ),
    "turn": lambda v: v["street"] == "turn",
    "river": lambda v: v["street"] == "river",
    "history_3bet_and_all_in": lambda v: (
        _raises(v, "preflop") >= 2 and any(e["all_in"] for e in v["history"])
    ),
    "custom_allowed": lambda v: v["custom"]["allowed"] and v["street"] != "preflop",
}


def _view(p: Puzzle) -> View:
    return views.puzzle_view(1, p, custom_sizes_allowed=views.custom_allowed(p), attempts_so_far=0)


def search(
    max_seed: int = MAX_SEED, log: Callable[[str], None] = lambda _m: None
) -> dict[str, tuple[int, str]]:
    """``{name: (seed, street)}`` for the first puzzle meeting each predicate (``KeyError`` if
    one is not found within ``max_seed`` seeds per street)."""
    found: dict[str, tuple[int, str]] = {}
    for seed in range(1, max_seed + 1):
        for street in STREETS:
            todo = [n for n in PREDICATES if n not in found]
            if not todo:
                return found
            try:
                p = generate_puzzle(seed, street=street)
            except RuntimeError:
                continue
            v = _view(p)
            for name in todo:
                if PREDICATES[name](v):
                    found[name] = (seed, street)
                    log(f"found {name}: seed={seed} street={street}")
    missing = [n for n in PREDICATES if n not in found]
    if missing:
        raise KeyError(f"no puzzle found within {max_seed} seeds per street for: {missing}")
    return found


def find_never_continues(
    max_seed: int = NEVER_CONTINUES_MAX_SEED, log: Callable[[str], None] = lambda _m: None
) -> tuple[int, str, int]:
    """``(seed, street, option index)`` of the first bet or raise Villain always folds to,
    searched in ``search()``'s order (``RuntimeError`` if none within ``max_seed`` seeds)."""
    for seed in range(1, max_seed + 1):
        for street in STREETS:
            try:
                p = generate_puzzle(seed, street=street)
            except RuntimeError:
                continue
            for i, o in enumerate(p.solution.options):
                kind = o.option.action.kind
                if kind in (ActionKind.BET, ActionKind.RAISE) and o.fold_freq == 1.0:
                    log(f"found never_continues: seed={seed} street={street} option={i}")
                    return seed, street, i
    raise RuntimeError(f"no bet or raise that Villain always folds to within {max_seed} seeds")


def _round_floats(data: Any) -> Any:
    """``data`` with every float rounded to 10 significant digits (dicts, lists and tuples are
    walked; ``bool`` is checked first as it is an ``int``)."""
    if isinstance(data, bool):
        return data
    if isinstance(data, float):
        return float(f"{data:.10g}")
    if isinstance(data, dict):
        return {k: _round_floats(v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [_round_floats(v) for v in data]
    return data


def _dump(path: Path, data: Any) -> None:
    text = json.dumps(_round_floats(data), indent=2, sort_keys=True) + "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _fix_times(result: dict[str, Any]) -> dict[str, Any]:
    result["attempt"]["created_at"] = FIXED_TIME
    return result


@contextmanager
def _scripted_clock(start: datetime) -> Iterator[list[datetime]]:
    """Replace ``api.service.utcnow`` (every stored timestamp comes from it) with a clock that
    returns ``now[0]``; the caller moves it by assigning ``now[0]``."""
    now = [start]
    real = service.utcnow
    service.utcnow = lambda: now[0]
    try:
        yield now
    finally:
        service.utcnow = real


def _clamp(x: float) -> float:
    return round(min(1.0, max(0.0, x)), 2)


def _stats_answer(p: Puzzle, k: int) -> dict[str, Any]:
    """A deterministic answer for first attempt ``k``: mostly the best option, every fourth a
    fold when folding isn't best (so the "Folding too often" leak shows), else a rotating other
    one; equity guesses about 9 pts high on average (the "Overestimating your equity" leak),
    range reads around the truth."""
    sol = p.solution
    index = sol.best
    if k % 4 == 3:
        folds = [i for i, o in enumerate(sol.options) if o.option.action.kind == ActionKind.FOLD]
        best_kind = sol.options[sol.best].option.action.kind
        index = folds[0] if folds and best_kind != ActionKind.FOLD else (k // 4) % len(sol.options)
    kind = sol.options[index].option.action.kind
    body: dict[str, Any] = {
        "option": index,
        "equity_guess": _clamp(sol.equity + ((k * 8) % 21 - 1) / 100),
    }
    if sol.ahead_now is not None:
        body["range_read_guess"] = _clamp(sol.ahead_now + ((k * 11) % 25 - 12) / 100)
    if kind in (ActionKind.BET, ActionKind.RAISE):
        truth = "value" if sol.equity >= 0.5 else "bluff"
        body["intent"] = truth if k % 5 else ("bluff" if truth == "value" else "value")
    return body


def write_stats_fixtures(
    out: Path, puzzles: Sequence[Puzzle], log: Callable[[str], None] = lambda _m: None
) -> None:
    """Write ``stats.json``, ``stats_empty.json`` and ``history_page.json``.

    Runs on its own temporary database: ``STATS_FIRST_ATTEMPTS`` new puzzles (``puzzles`` in
    turn, each a new puzzle row) answered by ``_stats_answer`` on a scripted clock, plus a retry
    after each of ``STATS_RETRY_AFTER``, with the daily goal set to ``STATS_GOAL``.
    ``stats.json`` is ``GET /api/stats?tz=UTC`` at ``FIXED_NOW``. Deterministic: the same
    ``puzzles`` give the same bytes.
    """
    if not puzzles:
        raise ValueError("write_stats_fixtures needs at least one puzzle")
    out.mkdir(parents=True, exist_ok=True)
    queue: list[Puzzle] = []

    def factory(_seed: int, _street: Street | None, _profile: str | None) -> Puzzle:
        return queue.pop(0)

    def empty_stats() -> dict[str, Any]:
        view = compute(
            [],
            tz=ZoneInfo("UTC"),
            now=FIXED_NOW,
            goal=STATS_GOAL,
            profile_labels=service.profile_labels(),
        )
        return StatsView.model_validate(view).model_dump(mode="json")

    def submit(pid: int, body: dict[str, Any]) -> None:
        res = client.post(f"/api/puzzles/{pid}/attempts", json=body)
        if res.status_code != 201:
            raise RuntimeError(res.text)

    with tempfile.TemporaryDirectory() as tmp, _scripted_clock(STATS_START) as now:
        url = f"sqlite:///{(Path(tmp) / 'stats.db').as_posix()}"
        app = create_app(
            AppSettings(_env_file=None, database_url=url, llm_provider="none"),
            puzzle_factory=factory,
        )
        with TestClient(app) as client:
            res = client.patch("/api/settings", json={"daily_goal": STATS_GOAL})
            if res.status_code != 200:
                raise RuntimeError(res.text)
            for k in range(STATS_FIRST_ATTEMPTS):
                now[0] = _stats_time(k)
                p = puzzles[k % len(puzzles)]
                queue.append(p)
                res = client.post("/api/puzzles", json={})
                if res.status_code != 201:
                    raise RuntimeError(res.text)
                pid = res.json()["id"]
                submit(pid, _stats_answer(p, k))
                if k in STATS_RETRY_AFTER:  # practice: the best option, a better equity guess
                    now[0] += timedelta(hours=1)
                    submit(
                        pid, {"option": p.solution.best, "equity_guess": _clamp(p.solution.equity)}
                    )
            now[0] = FIXED_NOW
            res = client.get("/api/stats", params={"tz": "UTC"})
            if res.status_code != 200:
                raise RuntimeError(res.text)
            _dump(out / "stats.json", res.json())
            log("wrote stats.json")
            _dump(out / "stats_empty.json", empty_stats())
            log("wrote stats_empty.json")
            _dump(out / "history_page.json", client.get("/api/history?limit=25").json())
            log("wrote history_page.json")


# play fixtures: the seeded session and the clock it runs on (one minute per request)
PLAY_SEED = 1
PLAY_START = datetime(2026, 11, 14, 18, 0, tzinfo=UTC)
PLAY_STEP = timedelta(minutes=1)
PLAY_MAX_HANDS = 40  # the script stops (and reports) when a wanted hand is not dealt by then


def _play_pick(options: list[dict[str, Any]]) -> int:
    """Hero's scripted choice: check, else call, else the smallest bet or raise (so hands reach
    the flop and the bot sometimes folds to Hero), else option 0."""
    for kind in ("check", "call"):
        for o in options:
            if o["kind"] == kind:
                return int(o["index"])
    aggressive = [o for o in options if o["kind"] in ("bet", "raise")]
    if aggressive:
        return int(min(aggressive, key=lambda o: o["to"])["index"])
    return int(options[0]["index"])


def write_play_fixtures(
    out: Path, *, samples: int | None = None, log: Callable[[str], None] = lambda _m: None
) -> None:
    """Write the six ``play_*.json`` files: a seeded session played by ``_play_pick`` on a scripted clock.

    - ``play_session_hero_to_act.json``: the first post-flop spot with Hero to act;
    - ``play_session_hand_over_fold.json``: the first hand that ended in a fold after a Hero
      decision;
    - ``play_session_hand_over_showdown.json``: the first showdown with two or more Hero
      decisions;
    - ``play_hand_analysis.json``: that showdown hand, every decision analysed;
    - ``play_hands.json``: the session's hands (the showdown hand analysed);
    - ``play_sessions.json``: that session (ended) and a new open one.

    ``samples`` is the analysis' equity samples (None: the config's). Deterministic: the same
    ``samples`` give the same bytes.
    """
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(PLAY_SEED)
    found: dict[str, dict[str, Any]] = {}

    with tempfile.TemporaryDirectory() as tmp, _scripted_clock(PLAY_START) as now:
        url = f"sqlite:///{(Path(tmp) / 'play.db').as_posix()}"
        app = create_app(
            AppSettings(_env_file=None, database_url=url, llm_provider="none"),
            play_rng=lambda: rng,
            play_samples=samples,
        )

        def call(method: str, path: str, status: int = 200, **kw: Any) -> Any:
            now[0] += PLAY_STEP
            res = client.request(method, path, **kw)
            if res.status_code != status:
                raise RuntimeError(f"{method} {path}: {res.text}")
            return res.json()

        with TestClient(app) as client:
            v = call("POST", "/api/play/sessions", 201)
            for _ in range(PLAY_MAX_HANDS):
                while v["hand"]["status"] == "in_progress":
                    hand = v["hand"]
                    if "hero_to_act" not in found and hand["table"]["board"]:
                        found["hero_to_act"] = v
                    body = {
                        "expected_actions": hand["action_count"],
                        "option": _play_pick(hand["options"]),
                    }
                    v = call("POST", f"/api/play/hands/{hand['id']}/actions", json=body)
                hand = v["hand"]
                ended_by = hand["outcome"]["ended_by"]
                if "fold" not in found and ended_by == "fold" and hand["decision_count"] >= 1:
                    found["fold"] = v
                if (
                    "showdown" not in found
                    and ended_by == "showdown"
                    and hand["decision_count"] >= 2
                ):
                    found["showdown"] = v
                if len(found) == 3:
                    break
                body = {"expected_hands": v["hands_played"], "top_up": True}
                v = call("POST", f"/api/play/sessions/{v['id']}/hands", 201, json=body)
            else:
                missing = {"hero_to_act", "fold", "showdown"} - set(found)
                raise RuntimeError(f"no {sorted(missing)} within {PLAY_MAX_HANDS} hands")

            for name in ("hero_to_act", "hand_over_fold", "hand_over_showdown"):
                _dump(out / f"play_session_{name}.json", found[name.removeprefix("hand_over_")])
                log(f"wrote play_session_{name}.json")

            showdown = found["showdown"]["hand"]
            for n in range(showdown["decision_count"]):
                call("POST", f"/api/play/hands/{showdown['id']}/analysis/{n}")
            analysis = call("GET", f"/api/play/hands/{showdown['id']}/analysis")
            graded = [d for d in analysis["decisions"] if d and d["status"] == "graded"]
            if len(graded) < 2:
                raise RuntimeError("the showdown hand has fewer than two graded decisions")
            _dump(out / "play_hand_analysis.json", analysis)
            log("wrote play_hand_analysis.json")

            sid = v["id"]
            _dump(out / "play_hands.json", call("GET", f"/api/play/sessions/{sid}/hands"))
            log("wrote play_hands.json")
            call("POST", f"/api/play/sessions/{sid}/end")
            call("POST", "/api/play/sessions", 201)
            _dump(out / "play_sessions.json", call("GET", "/api/play/sessions"))
            log("wrote play_sessions.json")


# 5-max play fixtures: their own seeded session on their own database and clock
PLAY5_SEED = 5
PLAY5_MAX_HANDS = 600  # the script stops (and reports) when a wanted hand is not dealt by then
PLAY5_FILES = (
    "play5_session_hero_to_act.json",
    "play5_session_hero_folded.json",
    "play5_session_side_pot.json",
    "play5_hands.json",
    "play5_sessions.json",
)


def _play5_pick(options: list[dict[str, Any]], hand_no: int, jam: bool) -> int:
    """Hero's scripted 5-max choice. ``jam``: the last option (all-in) pre-flop, then check or
    call. Otherwise: fold to a pre-flop raise on every third hand, else ``_play_pick``."""
    preflop_raise_faced = any(o["kind"] == "call" for o in options)
    if jam:
        if any(o["kind"] in ("bet", "raise") for o in options) and not any(
            o["kind"] == "check" for o in options
        ):
            return int(options[-1]["index"])
        return _play_pick(options)
    if hand_no % 3 == 0 and preflop_raise_faced:
        return int(next(o["index"] for o in options if o["kind"] == "fold"))
    return _play_pick(options)


def _live_count(hand: dict[str, Any]) -> int:
    return sum(1 for s in hand["table"]["seats"] if not s["folded"])


def _hero_folded_and_bots_played_on(hand: dict[str, Any]) -> bool:
    """Hero folded, and the bots then played on to the flop or later."""
    history = hand["table"]["history"]
    hero = [i for i, e in enumerate(history) if e["actor"] == "hero"]
    return (
        bool(hero)
        and history[hero[-1]]["kind"] == "fold"
        and any(e["street"] != "preflop" for e in history[hero[-1] + 1 :])
    )


def write_play5_fixtures(out: Path, *, log: Callable[[str], None] = lambda _m: None) -> None:
    """Write the ``play5_*.json`` files from one seeded 5-max session on a scripted clock.

    - ``play5_session_hero_to_act.json``: the first post-flop spot with Hero to act and at
      least three seats still in;
    - ``play5_session_hero_folded.json``: the first finished hand Hero folded in, after which
      the bots played on to the flop or later;
    - ``play5_session_side_pot.json``: the first showdown with a side pot that goes to someone
      other than the main pot's winner. Once the first two are found Hero jams every hand
      pre-flop (then checks or calls), so a jam called by two bots with different stacks
      behind turns up; the session's seed is fixed, so the search is too;
    - ``play5_hands.json``: the session's hands;
    - ``play5_sessions.json``: that session (ended) and a new open heads-up one.

    Deterministic: the same code gives the same bytes. Nothing here touches the heads-up
    fixtures' seeded stream.
    """
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(PLAY5_SEED)
    found: dict[str, dict[str, Any]] = {}

    with tempfile.TemporaryDirectory() as tmp, _scripted_clock(PLAY_START) as now:
        url = f"sqlite:///{(Path(tmp) / 'play5.db').as_posix()}"
        app = create_app(
            AppSettings(_env_file=None, database_url=url, llm_provider="none"),
            play_rng=lambda: rng,
        )

        def call(method: str, path: str, status: int = 200, **kw: Any) -> Any:
            now[0] += PLAY_STEP
            res = client.request(method, path, **kw)
            if res.status_code != status:
                raise RuntimeError(f"{method} {path}: {res.text}")
            return res.json()

        with TestClient(app) as client:
            v = call("POST", "/api/play/sessions", 201, json={"table_size": 5})
            for _ in range(PLAY5_MAX_HANDS):
                jam = "hero_to_act" in found and "hero_folded" in found
                while v["hand"]["status"] == "in_progress":
                    hand = v["hand"]
                    if (
                        "hero_to_act" not in found
                        and hand["table"]["board"]
                        and _live_count(hand) >= 3
                    ):
                        found["hero_to_act"] = v
                    body = {
                        "expected_actions": hand["action_count"],
                        "option": _play5_pick(hand["options"], hand["hand_no"], jam),
                    }
                    v = call("POST", f"/api/play/hands/{hand['id']}/actions", json=body)
                hand = v["hand"]
                out5 = hand["outcome"]
                if "hero_folded" not in found and _hero_folded_and_bots_played_on(hand):
                    found["hero_folded"] = v
                if (
                    "side_pot" not in found
                    and out5["ended_by"] == "showdown"
                    and len({tuple(p["winners"]) for p in out5["pots"]}) >= 2
                ):
                    found["side_pot"] = v
                if len(found) == 3:
                    break
                body = {"expected_hands": v["hands_played"], "top_up": True}
                v = call("POST", f"/api/play/sessions/{v['id']}/hands", 201, json=body)
            else:
                missing = {"hero_to_act", "hero_folded", "side_pot"} - set(found)
                raise RuntimeError(f"no 5-max {sorted(missing)} within {PLAY5_MAX_HANDS} hands")

            for name in ("hero_to_act", "hero_folded", "side_pot"):
                _dump(out / f"play5_session_{name}.json", found[name])
                log(f"wrote play5_session_{name}.json")
            sid = v["id"]
            _dump(out / "play5_hands.json", call("GET", f"/api/play/sessions/{sid}/hands"))
            log("wrote play5_hands.json")
            call("POST", f"/api/play/sessions/{sid}/end")
            call("POST", "/api/play/sessions", 201)
            _dump(out / "play5_sessions.json", call("GET", "/api/play/sessions"))
            log("wrote play5_sessions.json")


def reword(_url: str, _model: str, _system: str, prompt: str, *_rest: Any) -> str:
    """A fake model for ``explanation_llm.json``: the template's own text, visibly reworded
    ("In short: ", the hand in one paragraph, the verdict's first two paragraphs joined) and
    with no number added, so it passes the guardrail."""
    fields = ollama.template_fields(prompt)
    verdict = fields["verdict"].split("\n\n")
    return json.dumps(
        {
            "headline": "In short: " + fields["headline"],
            "hand": " ".join(fields["hand"].split("\n\n")),
            "verdict": "\n\n".join([" ".join(verdict[:2]), *verdict[2:]]),
        }
    )


def write_llm_fixture(
    out: Path,
    app: Any,
    client: TestClient,
    attempt_id: int,
    log: Callable[[str], None] = lambda _m: None,
) -> None:
    """Write ``explanation_llm.json``: ``GET /api/attempts/{attempt_id}/explanation`` from the
    real app with provider ``ollama`` and the fake model ``reword``. The app's explainer is
    restored afterwards."""
    settings = app.state.settings.model_copy(update={"llm_provider": "ollama"})
    real = app.state.explainer
    app.state.explainer = Explainer(settings, generate=reword, probe=lambda *_a: ("ready", None))
    try:
        res = client.get(f"/api/attempts/{attempt_id}/explanation")
    finally:
        app.state.explainer = real
    body = res.json()
    if res.status_code != 200 or body["source"] != "llm":
        raise RuntimeError(f"no LLM explanation: {res.text}")
    _dump(out / "explanation_llm.json", body)
    log("wrote explanation_llm.json")


def write_fixtures(
    out: Path,
    found: dict[str, tuple[int, str]],
    log: Callable[[str], None] = lambda _m: None,
    never_continues: tuple[int, str, int] | None = None,
) -> None:
    """Write every puzzle in ``found``, the attempt results, the settings and
    ``explanation_llm.json`` (``attempt_bet``'s explanation from a fake model).

    ``never_continues`` is ``find_never_continues()``'s result; ``None`` skips
    ``attempt_never_continues.json``.
    """
    out.mkdir(parents=True, exist_ok=True)
    chosen: dict[tuple[int, str], Puzzle] = {}
    queue: list[tuple[int, str]] = []

    def factory(_seed: int, _street: Street | None, _profile: str | None) -> Puzzle:
        return chosen[queue.pop(0)]

    with tempfile.TemporaryDirectory() as tmp:
        url = f"sqlite:///{(Path(tmp) / 'fixtures.db').as_posix()}"
        app = create_app(
            AppSettings(_env_file=None, database_url=url, llm_provider="none"),
            puzzle_factory=factory,
        )
        with TestClient(app) as client:
            ids: dict[str, int] = {}
            for name, key in found.items():
                seed, street = key
                chosen[key] = generate_puzzle(seed, street=street)
                queue.append(key)
                res = client.post("/api/puzzles", json={})
                if res.status_code != 201:
                    raise RuntimeError(res.text)
                view = res.json()
                ids[name] = view["id"]
                _dump(out / f"puzzle_{name}.json", view)
                log(f"wrote puzzle_{name}.json")

            # attempt results: a bet and a fold on the unopened flop
            bet_attempt_id = 0
            flop_id = ids["flop_unopened"]
            options = client.get(f"/api/puzzles/{flop_id}").json()["options"]
            for kind in ("bet", "fold"):
                matching = [o for o in options if o["kind"] == kind]
                if not matching:  # an unopened flop has no fold: use the facing-raise puzzle
                    pid = ids["facing_postflop_raise"]
                    options = client.get(f"/api/puzzles/{pid}").json()["options"]
                    matching = [o for o in options if o["kind"] == kind]
                    if not matching:
                        raise RuntimeError(f"no {kind} option in the fixture puzzles")
                else:
                    pid = flop_id
                res = client.post(
                    f"/api/puzzles/{pid}/attempts",
                    json={
                        "option": matching[0]["index"],
                        "equity_guess": 0.45,
                        "range_read_guess": 0.5,
                        "intent": "value" if kind == "bet" else None,
                    },
                )
                if res.status_code != 201:
                    raise RuntimeError(res.text)
                if kind == "bet":
                    bet_attempt_id = res.json()["attempt"]["id"]
                _dump(out / f"attempt_{kind}.json", _fix_times(res.json()))
                log(f"wrote attempt_{kind}.json")

            def options_of(pid: int) -> list[dict[str, Any]]:
                return client.get(f"/api/puzzles/{pid}").json()["options"]

            def first(name: str, kind: str) -> int:
                matching = [o for o in options_of(ids[name]) if o["kind"] == kind]
                if not matching:
                    raise RuntimeError(f"no {kind} option in puzzle_{name}")
                return matching[0]["index"]

            def attempt(file: str, pid: int, body: dict[str, Any]) -> None:
                res = client.post(
                    f"/api/puzzles/{pid}/attempts",
                    json={"equity_guess": 0.45, "range_read_guess": 0.5, **body},
                )
                if res.status_code != 201:
                    raise RuntimeError(res.text)
                _dump(out / f"attempt_{file}.json", _fix_times(res.json()))
                log(f"wrote attempt_{file}.json")

            pid = ids["facing_postflop_raise"]
            attempt("call", pid, {"option": first("facing_postflop_raise", "call")})
            pid = ids["preflop_bb_facing_open"]
            attempt(
                "raise_preflop",
                pid,
                {"option": first("preflop_bb_facing_open", "raise"), "intent": "value"},
            )
            pid = ids["preflop_btn_first_in"]
            attempt("fold_preflop", pid, {"option": first("preflop_btn_first_in", "fold")})
            attempt("check_river", ids["river"], {"option": first("river", "check")})

            pid = ids["custom_allowed"]
            view = client.get(f"/api/puzzles/{pid}").json()
            min_to = view["custom"]["min_to"]
            if any(o["to"] == min_to for o in view["options"]):
                raise RuntimeError("custom min_to matches a stored option: no custom row")
            attempt("custom", pid, {"custom_to": min_to})

            if never_continues is None:
                log("skipped attempt_never_continues.json (no such option found)")
            else:
                seed, street, index = never_continues
                key = (seed, street)
                chosen[key] = generate_puzzle(seed, street=street)
                queue.append(key)
                res = client.post("/api/puzzles", json={})
                if res.status_code != 201:
                    raise RuntimeError(res.text)
                # label it the opposite of the truth (value iff equity >= 0.5) so a flag shows
                intent = "bluff" if chosen[key].solution.equity >= 0.5 else "value"
                attempt("never_continues", res.json()["id"], {"option": index, "intent": intent})
            _dump(out / "settings.json", client.get("/api/settings").json())
            log("wrote settings.json")
            write_llm_fixture(out, app, client, bet_attempt_id, log=log)
    # the found puzzles, once each, in the search order
    puzzles = list({key: chosen[key] for key in found.values()}.values())
    write_stats_fixtures(out, puzzles, log=log)


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    play_only = "--play-only" in args
    if play_only:
        args.remove("--play-only")
    if len(args) != 1:
        raise SystemExit("usage: python -m poker_trainer.api.dev_fixtures OUT_DIR [--play-only]")
    start = time.perf_counter()
    if play_only:
        write_play_fixtures(Path(args[0]), log=print)
        write_play5_fixtures(Path(args[0]), log=print)
        print(f"total {time.perf_counter() - start:.1f}s")
        return
    found = search(log=print)
    print(f"search took {time.perf_counter() - start:.1f}s")
    never: tuple[int, str, int] | None
    try:
        never = find_never_continues(log=print)
    except RuntimeError as e:
        print(e)
        never = None
    write_fixtures(Path(args[0]), found, log=print, never_continues=never)
    write_play_fixtures(Path(args[0]), log=print)
    write_play5_fixtures(Path(args[0]), log=print)
    print(f"total {time.perf_counter() - start:.1f}s")


if __name__ == "__main__":
    main()
