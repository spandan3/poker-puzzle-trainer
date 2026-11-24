"""Pins the heads-up Villain strategy, Hero's options and the hand transitions before M12 (5-max).

Heads-up behaviour MUST NOT change in M12. Regenerating this file (``write``) needs the user's
explicit sign-off; never regenerate it to make a failing test pass.

What is pinned
--------------
Seeded heads-up hands are replayed with a self-contained copy of the hand loop (deck shuffle,
bot seed and board dealing are copied here, so the test depends only on ``game.state``,
``game.settle``, ``puzzle.options.hero_options`` and ``villain.strategy`` / ``villain.profiles``,
not on ``play/``). Hero is seat 0 and plays a seeded random option, biased towards aggressive
options in about half the hands; the bot is seat 1 and plays ``sample_action``.

Per pinned state (a "decision entry"):
  * a readable fingerprint: street, to_act, pot, stacks, street_bets, legal actions
    (fold/check/call/aggressive/min_to/max_to) and board. Compared field by field, so a failure
    names the field that moved (a transition or legality change);
  * bot to act: the full ``action_distribution`` per action, per combo, rounded to 6 decimals
    (stored as int32 micro-units, zlib + base64; the recomputed arrays must be within 5e-7 + 1e-9
    of the stored values) plus a sha256 of the stored data. zlib keeps the file near 1 MB, because
    the arrays only take a handful of distinct values;
  * Hero to act: the ``hero_options`` list (label and action), compared as a list.
Per hand a terminal entry pins the final fingerprint and ``settle`` stacks.

Coverage is by branch key, not by quota. Pre-flop: number of raises, facing a jam or not, whether
the seat to act is the button. Post-flop: street x role (``villain.strategy.role``), with ``:jam``
when the bet faced leaves no re-raise. Every branch in ``REQUIRED`` has at least ``MIN_PER_BRANCH``
pinned states for the bot (``dist``) and for Hero (``opts``). Random play is thin in some spots,
so ``DIRECTED`` scripts (lists of option labels) play them out for every profile, both buttons
and two stack depths. The per-branch counts are stored in the JSON under ``branch_counts`` and
printed by ``write``.

Rebuild (only with sign-off; the slow ``test_hu_pins_regenerate`` must then pass):

    cd backend && uv run python tests/villain/test_hu_pins.py
"""

from __future__ import annotations

import base64
import hashlib
import json
import random
import sys
import zlib
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from poker_trainer.game.settle import settle
from poker_trainer.game.state import (
    Action,
    ActionKind,
    HandState,
    Street,
    apply,
    deal,
    is_terminal,
    legal_actions,
    needs_board,
    new_hand,
)
from poker_trainer.puzzle.options import hero_options
from poker_trainer.villain.profiles import PROFILE_NAMES, load_profile
from poker_trainer.villain.strategy import action_distribution, role, sample_action

DATA = Path(__file__).resolve().parent.parent / "data" / "hu_strategy_digests.json"
HERO, BOT = 0, 1
STACKS = (10, 12, 15, 20, 25, 40, 60, 80, 100, 150, 200, 250, 300)
SCALE = 1_000_000  # distributions are stored rounded to 6 decimals, as int32 micro-units
TOL = 0.5 / SCALE + 1e-9
MIN_PER_BRANCH = 8
CAP_PER_BRANCH = 12  # random states stop being added to a branch once it holds this many
TERMINALS = 200  # random hands that also pin a terminal entry
MAX_RANDOM_HANDS = 30_000
DIRECTED_STACKS = (60, 200)
_AGGRESSIVE = (ActionKind.BET, ActionKind.RAISE)
_STREETS = {1: "flop", 2: "turn", 3: "river"}

# Scripts of option labels, played by whoever is to act (both seats), then stopped. The state
# reached after the last label is pinned.
_X = "check"
DIRECTED: dict[str, list[str]] = {
    "open_jam": ["all-in"],
    "open": ["raise 2.5x"],
    "3bet": ["raise 2.5x", "raise 3x"],
    "3bet_jam": ["raise 2.5x", "all-in"],
    "4bet_jam": ["raise 2.5x", "raise 3x", "all-in"],
    "flop_lead": ["raise 2.5x", "call"],
    "flop_cbet": ["raise 2.5x", "call", _X],
    "flop_bet": ["raise 2.5x", "call", _X, "bet 50%"],
    "flop_raise": ["raise 2.5x", "call", _X, "bet 50%", "raise 3x"],
    "flop_lead_bet": ["raise 2.5x", "call", "bet 50%"],
    "flop_lead_raise": ["raise 2.5x", "call", "bet 50%", "raise 3x"],
    "flop_stab": ["raise 2.5x", "raise 3x", "call", _X],
    "turn_lead": ["raise 2.5x", "call", _X, _X],
    "turn_bet": ["raise 2.5x", "call", _X, _X, "bet 50%"],
    "turn_raise": ["raise 2.5x", "call", _X, _X, "bet 50%", "raise 3x"],
    "turn_cbet": ["raise 2.5x", "call", _X, "bet 50%", "call"],
    "turn_stab": ["raise 2.5x", "raise 3x", "call", _X, _X],
    "river_lead": ["raise 2.5x", "call", _X, _X, _X, _X],
    "river_bet": ["raise 2.5x", "call", _X, _X, _X, _X, "bet 50%"],
    "river_raise": ["raise 2.5x", "call", _X, _X, _X, _X, "bet 50%", "raise 3x"],
    "river_cbet": ["raise 2.5x", "call", _X, "bet 50%", "call", _X, "bet 50%", "call", _X],
    "river_stab": ["raise 2.5x", "raise 3x", "call", _X, _X, _X, _X],
}

# (kind, branch) pairs that must each reach MIN_PER_BRANCH. kind: dist (bot to act) or opts (Hero).
_PRE_BRANCHES = (
    "pre:n0:open:btn",
    "pre:n1:open:bb",
    "pre:n1:jam:bb",
    "pre:n2:open:btn",
    "pre:n2:jam:btn",
    "pre:n3:jam:bb",
)
_POST_BRANCHES = tuple(
    f"{st}:{r}"
    for st in ("flop", "turn", "river")
    for r in ("lead", "cbet", "stab", "facing_bet", "facing_raise")
)
REQUIRED = tuple((kind, b) for kind in ("dist", "opts") for b in (*_PRE_BRANCHES, *_POST_BRANCHES))


# --------------------------------------------------------------------------------------------
# Hand replay (one loop for generation and checking)
# --------------------------------------------------------------------------------------------


def _deal_board(s: HandState, deck: list[int]) -> HandState:
    """Deal every street whose betting is complete, including the run-out after an all-in."""
    while needs_board(s):
        n = 3 if s.street == Street.PREFLOP else 1
        k = len(s.board)
        s = deal(s, tuple(deck[4 + k : 4 + k + n]))
    return s


def _spec_random(i: int) -> dict:
    rng = random.Random(f"hu-pin:{i}")
    stacks = [rng.choice(STACKS), rng.choice(STACKS)]
    return {
        "id": f"r{i}",
        "profile": PROFILE_NAMES[i % len(PROFILE_NAMES)],
        "button": rng.randint(0, 1),
        "stacks": stacks,
        "seed": f"hu-pin:{i}",
        "script": None,
    }


def _spec_directed(name: str, button: int, stack: int, profile: str) -> dict:
    hid = f"d.{name}.b{button}.s{stack}.{profile}"
    return {
        "id": hid,
        "profile": profile,
        "button": button,
        "stacks": [stack, stack],
        "seed": f"hu-pin-d:{hid}",
        "script": DIRECTED[name],
    }


def _pick(options, rng: random.Random, aggressive_hand: bool) -> Action:
    u = rng.random()
    i = rng.randrange(len(options))
    if aggressive_hand and u < 0.7:
        aggr = [o for o in options if o.action.kind in _AGGRESSIVE]
        if aggr:
            return aggr[i % len(aggr)].action
    return options[i].action


def replay(spec: dict) -> Iterator[tuple[int, HandState, tuple[tuple[int, int], tuple[int, int]]]]:
    """Yield ``(step, state, holes)`` for every state of the hand, the terminal one included.

    Random hands play to the end; directed hands stop after their script.
    """
    rng = random.Random(spec["seed"])
    if spec["script"] is None:  # the same draws as _spec_random, then the deck
        rng.choice(STACKS)
        rng.choice(STACKS)
        rng.randint(0, 1)
    deck = list(range(52))
    rng.shuffle(deck)
    bot_seed = rng.getrandbits(62)
    aggressive_hand = rng.random() < 0.5
    holes = ((deck[0], deck[1]), (deck[2], deck[3]))
    profile = load_profile(spec["profile"])
    s = _deal_board(new_hand(spec["button"], tuple(spec["stacks"])), deck)
    script = spec["script"]
    step = 0
    while True:
        yield step, s, holes
        if is_terminal(s) or (script is not None and step >= len(script)):
            return
        if script is not None:
            a = {o.label: o.action for o in hero_options(s)}[script[step]]
        elif s.to_act == HERO:
            a = _pick(hero_options(s), rng, aggressive_hand)
        else:
            a = sample_action(profile, s, holes[BOT], random.Random(f"{bot_seed}:{len(s.history)}"))
        s = _deal_board(apply(s, a), deck)
        step += 1


# --------------------------------------------------------------------------------------------
# Fingerprints, branches, distributions
# --------------------------------------------------------------------------------------------


def fingerprint(s: HandState) -> dict:
    fp: dict = {
        "street": Street(s.street).name.lower(),
        "to_act": s.to_act,
        "button": s.button,
        "pot": s.pot,
        "stacks": list(s.stacks),
        "street_bets": list(s.street_bets),
        "board": list(s.board),
        "folded": s.folded,
    }
    if s.to_act is not None:
        lg = legal_actions(s)
        fp["legal"] = {
            "fold": lg.fold,
            "check": lg.check,
            "call": lg.call,
            "aggressive": lg.aggressive.value if lg.aggressive else None,
            "min_to": lg.min_to,
            "max_to": lg.max_to,
        }
    return fp


def branch_key(s: HandState) -> tuple[str, str]:
    """(kind, branch) of a decision state: kind is ``dist`` for the bot and ``opts`` for Hero."""
    kind = "opts" if s.to_act == HERO else "dist"
    lg = legal_actions(s)
    jam = lg.call > 0 and lg.aggressive is None
    if s.street == Street.PREFLOP:
        n = sum(1 for a in s.history if a.street == Street.PREFLOP)
        seat = "btn" if s.to_act == s.button else "bb"
        return kind, f"pre:n{n}:{'jam' if jam else 'open'}:{seat}"
    return kind, f"{_STREETS[int(s.street)]}:{role(s)}{':jam' if jam else ''}"


def _action_key(a: Action) -> str:
    return f"{a.seat}:{a.kind.value}:{a.to}:{int(a.street)}"


def _encode(arr: np.ndarray) -> np.ndarray:
    return (np.rint(np.asarray(arr, dtype="<f8") * SCALE) + 0).astype("<i4")


def dist_record(profile_name: str, s: HandState) -> tuple[dict[str, str], str]:
    """Per-action compressed micro-unit arrays (keys sorted) and a sha256 of the stored data."""
    dist = action_distribution(load_profile(profile_name), s)
    out: dict[str, str] = {}
    h = hashlib.sha256()
    for a in sorted(dist, key=lambda a: (a.seat, a.kind.value, a.to)):
        raw = _encode(dist[a]).tobytes()
        key = f"{a.seat}:{a.kind.value}:{a.to}"
        out[key] = base64.b64encode(zlib.compress(raw, 9)).decode("ascii")
        h.update(f"{key}|".encode() + raw)
    return out, h.hexdigest()


def _key_order(key: str) -> tuple[int, str, int]:
    seat, kind, to = key.split(":")
    return int(seat), kind, int(to)


def stored_digest(dist: dict[str, str]) -> str:
    h = hashlib.sha256()
    for key in sorted(dist, key=_key_order):  # JSON may reorder the keys
        h.update(f"{key}|".encode() + zlib.decompress(base64.b64decode(dist[key])))
    return h.hexdigest()


def options_record(s: HandState) -> list[list[str]]:
    return [[o.label, _action_key(o.action)] for o in hero_options(s)]


# --------------------------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------------------------


def _entry(spec: dict, step: int, s: HandState, holes) -> dict:
    if is_terminal(s):
        return {
            "step": step,
            "kind": "terminal",
            "fp": fingerprint(s),
            "settle": list(settle(s, holes)),
        }
    kind, branch = branch_key(s)
    e = {"step": step, "kind": kind, "branch": branch, "fp": fingerprint(s)}
    if kind == "dist":
        e["dist"], e["digest"] = dist_record(spec["profile"], s)
    else:
        e["options"] = options_record(s)
    return e


def generate() -> tuple[list[dict], Counter]:
    hands: list[dict] = []
    counts: Counter = Counter()

    def add(spec: dict, only_last: bool, cap: int | None, terminal: bool) -> None:
        states = list(replay(spec))
        entries = []
        for step, s, holes in states[-1:] if only_last else states:
            if is_terminal(s):
                if terminal:
                    entries.append(_entry(spec, step, s, holes))
                continue
            key = branch_key(s)
            if cap is not None and counts[key] >= cap:
                continue
            counts[key] += 1
            entries.append(_entry(spec, step, s, holes))
        if entries:
            hands.append({**spec, "entries": entries})

    for name in DIRECTED:
        for button in (0, 1):
            for stack in DIRECTED_STACKS:
                for profile in PROFILE_NAMES:
                    add(_spec_directed(name, button, stack, profile), True, None, True)
    i = 0
    while i < TERMINALS or any(counts[k] < MIN_PER_BRANCH for k in REQUIRED):
        if i >= MAX_RANDOM_HANDS:
            missing = [k for k in REQUIRED if counts[k] < MIN_PER_BRANCH]
            raise RuntimeError(f"branches not reached by random or directed play: {missing}")
        add(_spec_random(i), False, CAP_PER_BRANCH, i < TERMINALS)
        i += 1
    return hands, counts


def _document(hands: list[dict], counts: Counter) -> dict:
    digests = " ".join(e.get("digest", "-") for h in hands for e in h["entries"])
    return {
        "branch_counts": {f"{k}|{b}": n for (k, b), n in sorted(counts.items())},
        "combined_sha256": hashlib.sha256(digests.encode()).hexdigest(),
        "hands": hands,
    }


def _dump(doc: dict) -> bytes:
    """One JSON line per hand, so a diff shows which hand moved."""
    head = {k: v for k, v in doc.items() if k != "hands"}
    first = json.dumps(head, sort_keys=True, separators=(",", ":"))[:-1] + ',"hands":['
    rows = [json.dumps(h, sort_keys=True, separators=(",", ":")) for h in doc["hands"]]
    return ("\n".join([first, ",\n".join(rows), "]}"]) + "\n").encode()  # bytes: LF everywhere


def write() -> None:
    hands, counts = generate()
    doc = _document(hands, counts)
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_bytes(_dump(doc))
    for k, n in doc["branch_counts"].items():
        print(f"{n:4d}  {k}", file=sys.stderr)
    n_entries = sum(len(h["entries"]) for h in hands)
    print(f"wrote {DATA}: {len(hands)} hands, {n_entries} entries", file=sys.stderr)


# --------------------------------------------------------------------------------------------
# Checking
# --------------------------------------------------------------------------------------------


def _diff(want: dict, got: dict) -> list[str]:
    out = []
    for k in sorted(set(want) | set(got)):
        w, g = want.get(k), got.get(k)
        if isinstance(w, dict) and isinstance(g, dict):
            out += [f"{k}.{d}" for d in _diff(w, g)]
        elif w != g:
            out.append(f"{k}: pinned {w!r}, now {g!r}")
    return out


def _check_entry(spec: dict, e: dict, s: HandState, holes) -> list[str]:
    where = f"{spec['id']} step {e['step']} ({e['kind']})"
    problems = [f"{where}: fingerprint {d}" for d in _diff(e["fp"], fingerprint(s))]
    if e["kind"] == "terminal":
        if not is_terminal(s):
            problems.append(f"{where}: hand no longer over")
        elif list(settle(s, holes)) != e["settle"]:
            problems.append(f"{where}: settle {list(settle(s, holes))} != pinned {e['settle']}")
    elif is_terminal(s):
        problems.append(f"{where}: hand is over but a decision was pinned")
    elif e["kind"] == "opts":
        if options_record(s) != e["options"]:
            problems.append(f"{where}: options {options_record(s)} != pinned {e['options']}")
    else:
        dist = action_distribution(load_profile(spec["profile"]), s)
        got = {f"{a.seat}:{a.kind.value}:{a.to}": arr for a, arr in dist.items()}
        if sorted(got) != sorted(e["dist"]):
            problems.append(f"{where}: actions {sorted(got)} != pinned {sorted(e['dist'])}")
        else:
            for key, blob in e["dist"].items():
                want = np.frombuffer(zlib.decompress(base64.b64decode(blob)), dtype="<i4") / SCALE
                bad = np.flatnonzero(~np.isclose(got[key], want, rtol=0, atol=TOL))
                if bad.size:
                    d = float(np.max(np.abs(got[key] - want)))
                    problems.append(
                        f"{where}: {key} differs at {bad.size} combos (first {int(bad[0])}), "
                        f"max {d:.2e}"
                    )
    return problems


def check_hands(hands: list[dict]) -> list[str]:
    """Replay each hand once and compare every pinned entry; returns readable problems."""
    problems: list[str] = []
    for h in hands:
        spec = {k: h[k] for k in ("id", "profile", "button", "stacks", "seed", "script")}
        want = {e["step"]: e for e in h["entries"]}
        for step, s, holes in replay(spec):
            if step in want:
                problems += _check_entry(spec, want[step], s, holes)
            if step >= max(want):
                break
    return problems


def _load() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def test_file_is_lf_and_consistent():
    raw = DATA.read_bytes()
    assert b"\r" not in raw
    assert len(raw) < 3_000_000
    doc = json.loads(raw)
    entries = [e for h in doc["hands"] for e in h["entries"]]
    for e in entries:
        if e["kind"] == "dist":
            assert stored_digest(e["dist"]) == e["digest"]
    combined = hashlib.sha256(" ".join(e.get("digest", "-") for e in entries).encode()).hexdigest()
    assert combined == doc["combined_sha256"]
    for kind, b in REQUIRED:
        assert doc["branch_counts"].get(f"{kind}|{b}", 0) >= MIN_PER_BRANCH, (kind, b)
    jam4 = {
        h["profile"]
        for h in doc["hands"]
        for e in h["entries"]
        if e.get("branch") == "pre:n3:jam:bb" and e["kind"] == "dist"
    }
    assert jam4 == set(PROFILE_NAMES)


def _fast_subset(hands: list[dict]) -> list[dict]:
    """Every script at 200 chips for two profiles, the 4-bet jam for all, and 40 random hands."""
    directed = [
        h
        for h in hands
        if h["script"]
        and (
            h["stacks"][0] == 200
            and h["profile"] in ("tag", "sticky")
            or h["script"] == DIRECTED["4bet_jam"]
        )
    ]
    return directed + [h for h in hands if not h["script"]][:40]


def _assert_pins(hands: list[dict]) -> None:
    problems = check_hands(hands)
    assert not problems, "heads-up pins changed:\n" + "\n".join(problems[:40])


def test_hu_pins_fast_subset():
    _assert_pins(_fast_subset(_load()["hands"]))


@pytest.mark.slow
def test_hu_pins_all_states():
    """Every pinned state (about 25 s)."""
    _assert_pins(_load()["hands"])


@pytest.mark.slow
def test_hu_pins_regenerate():
    """Regenerating from scratch gives the stored file byte for byte."""
    hands, counts = generate()
    assert _dump(_document(hands, counts)) == DATA.read_bytes()


if __name__ == "__main__":
    write()
