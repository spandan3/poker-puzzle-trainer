import json
import zlib

import pytest

from poker_trainer.db.blob import decode_puzzle, encode_puzzle
from poker_trainer.game.state import Street
from poker_trainer.puzzle.generate import generate_puzzle
from poker_trainer.puzzle.model import puzzle_to_dict

STREETS = [Street.PREFLOP, Street.FLOP, Street.TURN, Street.RIVER]


@pytest.fixture(scope="module")
def puzzles():
    """One generated puzzle per street, fixed seeds."""
    return [generate_puzzle(11, street=street) for street in STREETS]


def _dump(p) -> str:
    return json.dumps(puzzle_to_dict(p), ensure_ascii=False, separators=(",", ":"))


def test_blob_round_trip_every_street(puzzles):
    for p, street in zip(puzzles, STREETS, strict=True):
        assert p.spot.state.street == street
        blob = encode_puzzle(p)
        assert isinstance(blob, bytes)
        back = decode_puzzle(blob)
        assert _dump(back) == _dump(p)
        assert len(blob) < 0.25 * len(_dump(p).encode("utf-8"))


def test_blob_rejects_bad_format(puzzles):
    d = puzzle_to_dict(puzzles[0])
    d["format"] = 2
    blob = zlib.compress(json.dumps(d).encode("utf-8"))
    with pytest.raises(ValueError, match="unsupported puzzle format"):
        decode_puzzle(blob)


def test_blob_utf8(puzzles):
    labels = [
        b.label for p in puzzles for o in p.solution.options for b in o.branches if "—" in b.label
    ]
    assert labels, "expected an em dash in some branch label"
    for p in puzzles:
        blob = encode_puzzle(p)
        raw = zlib.decompress(blob)
        back = decode_puzzle(blob)
        before = [b.label for o in p.solution.options for b in o.branches]
        after = [b.label for o in back.solution.options for b in o.branches]
        assert after == before
        if any("—" in label for label in before):
            assert "—".encode() in raw  # stored as UTF-8, not \u escapes
