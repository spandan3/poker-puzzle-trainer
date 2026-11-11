"""Puzzle blobs: zlib-compressed UTF-8 JSON of ``puzzle_to_dict`` (exact float round-trip)."""

from __future__ import annotations

import json
import zlib

from poker_trainer.puzzle.model import Puzzle, puzzle_from_dict, puzzle_to_dict


def encode_puzzle(p: Puzzle) -> bytes:
    text = json.dumps(puzzle_to_dict(p), ensure_ascii=False, separators=(",", ":"))
    return zlib.compress(text.encode("utf-8"), 6)


def decode_puzzle(b: bytes) -> Puzzle:
    """Raises ``ValueError("unsupported puzzle format: ...")`` for a format other than 1."""
    return puzzle_from_dict(json.loads(zlib.decompress(b).decode("utf-8")))
