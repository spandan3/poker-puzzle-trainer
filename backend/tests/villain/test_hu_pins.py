"""Pins the heads-up Villain strategy and Hero's options before the M12 (5-max) engine work.

Each pinned state is reached by playing seeded heads-up hands with the M10 hand engine: Hero
(seat 0) picks a seeded random option from ``hero_options``, the bot (seat 1) plays
``sample_action``. Every state where the bot is to act pins ``sha256`` of its
``action_distribution`` (arrays rounded to 9 decimals; keys are kind/to/seat in sorted order);
every state where Hero is to act pins ``sha256`` of its ``hero_options`` (labels + actions).
250 of each, split evenly pre-flop / post-flop, over varied stacks (10 to 300 chips) and all
four profiles. Only ``random.Random(str)`` seeding is used.

To rebuild the digests (only for an intended behaviour change, with a version bump):

    cd backend && uv run python tests/villain/test_hu_pins.py
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

import numpy as np
import pytest

from poker_trainer.game.state import HandState, Street, apply, is_terminal, new_hand
from poker_trainer.play.hand import BOT_SEAT, HERO_SEAT, _deal_board
from poker_trainer.play.session import new_record
from poker_trainer.puzzle.options import hero_options
from poker_trainer.villain.profiles import PROFILE_NAMES, load_profile
from poker_trainer.villain.strategy import action_distribution, sample_action

DATA = Path(__file__).resolve().parent.parent / "data" / "hu_strategy_digests.json"
PER_KIND_STREET = 125  # per (distribution | options) x (pre-flop | post-flop)
FAST_SUBSET = 100  # states kept in the non-slow test
STACKS = (10, 12, 15, 20, 25, 40, 60, 80, 100, 150, 200, 250, 300)

_Entry = tuple[str, str, str, str]  # (id, kind, street, digest)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _action_key(a) -> str:
    return f"{a.seat}:{a.kind.value}:{a.to}:{int(a.street)}"


def distribution_digest(profile_name: str, s: HandState) -> str:
    dist = action_distribution(load_profile(profile_name), s)
    h = hashlib.sha256()
    for a in sorted(dist, key=lambda a: (a.seat, a.kind.value, a.to)):
        arr = np.round(np.asarray(dist[a], dtype="<f8"), 9) + 0.0  # + 0.0 turns -0.0 into 0.0
        h.update(f"{a.seat}:{a.kind.value}:{a.to}|".encode())
        h.update(arr.tobytes())
    return h.hexdigest()


def options_digest(s: HandState) -> str:
    lines = [f"{o.label}|{_action_key(o.action)}" for o in hero_options(s)]
    return _sha("\n".join(lines).encode())


def generate() -> list[_Entry]:
    """Play seeded hands until every (kind, street) quota is full; entries in discovery order."""
    quota = {(k, st): 0 for k in ("dist", "opts") for st in ("pre", "post")}
    entries: list[_Entry] = []
    i = 0
    while any(n < PER_KIND_STREET for n in quota.values()):
        rng = random.Random(f"hu-pin:{i}")
        name = PROFILE_NAMES[i % len(PROFILE_NAMES)]
        profile = load_profile(name)
        stacks = (rng.choice(STACKS), rng.choice(STACKS))
        r = new_record(rng.randint(0, 1), stacks, rng)
        s = _deal_board(new_hand(r.button, r.start_stacks), r.deck)
        step = 0
        while not is_terminal(s):
            kind = "opts" if s.to_act == HERO_SEAT else "dist"
            street = "pre" if s.street == Street.PREFLOP else "post"
            if quota[(kind, street)] < PER_KIND_STREET:
                quota[(kind, street)] += 1
                digest = options_digest(s) if kind == "opts" else distribution_digest(name, s)
                entries.append((f"{i}.{step}.{name}", kind, street, digest))
            if s.to_act == HERO_SEAT:
                opts = hero_options(s)
                a = opts[rng.randrange(len(opts))].action
            else:
                assert s.to_act == BOT_SEAT
                hole = (r.deck[2], r.deck[3])
                a = sample_action(profile, s, hole, random.Random(f"{r.bot_seed}:{len(s.history)}"))
            s = _deal_board(apply(s, a), r.deck)
            step += 1
        i += 1
    return entries


def _document(entries: list[_Entry]) -> dict:
    states = [{"id": e[0], "kind": e[1], "street": e[2], "sha256": e[3]} for e in entries]
    combined = _sha("\n".join(f"{e[0]} {e[3]}" for e in entries).encode())
    return {"combined_sha256": combined, "count": len(states), "states": states}


def write() -> None:
    DATA.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_document(generate()), indent=1, sort_keys=True) + "\n"
    DATA.write_bytes(text.encode())  # bytes: LF on every platform


def _check(states: list[dict]) -> None:
    """Recompute the digest of each pinned state by regenerating it from its id."""
    for st in states:
        hand, step, name = st["id"].split(".", 2)
        rng = random.Random(f"hu-pin:{hand}")
        profile = load_profile(name)
        stacks = (rng.choice(STACKS), rng.choice(STACKS))
        r = new_record(rng.randint(0, 1), stacks, rng)
        s = _deal_board(new_hand(r.button, r.start_stacks), r.deck)
        for _ in range(int(step)):
            if s.to_act == HERO_SEAT:
                opts = hero_options(s)
                a = opts[rng.randrange(len(opts))].action
            else:
                hole = (r.deck[2], r.deck[3])
                a = sample_action(profile, s, hole, random.Random(f"{r.bot_seed}:{len(s.history)}"))
            s = _deal_board(apply(s, a), r.deck)
        got = options_digest(s) if st["kind"] == "opts" else distribution_digest(name, s)
        assert got == st["sha256"], f"heads-up pin changed at state {st['id']} ({st['kind']})"


def _load() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def _fast_subset(states: list[dict]) -> list[dict]:
    pick = [s for s in states if s["kind"] == "dist"][: FAST_SUBSET // 2]
    pick += [s for s in states if s["kind"] == "opts"][: FAST_SUBSET // 2]
    return pick


def test_file_is_lf_and_consistent():
    raw = DATA.read_bytes()
    assert b"\r" not in raw
    doc = json.loads(raw)
    assert doc["count"] == len(doc["states"]) == 4 * PER_KIND_STREET
    combined = _sha("\n".join(f"{s['id']} {s['sha256']}" for s in doc["states"]).encode())
    assert combined == doc["combined_sha256"]


def test_hu_pins_fast_subset():
    _check(_fast_subset(_load()["states"]))


@pytest.mark.slow
def test_hu_pins_all():
    doc = _load()
    _check(doc["states"])
    assert _document(generate())["combined_sha256"] == doc["combined_sha256"]


if __name__ == "__main__":
    write()
    print(f"wrote {DATA}", file=sys.stderr)
