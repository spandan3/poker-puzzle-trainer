"""Generate ``villain/hand_ranking.json``: the 169 hand classes, strongest first.

Strength is all-in equity against one random hand: for each class, 50,000 samples of a random
villain hand and a random five-card board from the 50 cards left, seeded with
``random.Random("hand-ranking:<label>")`` per class. Every combo of a class has the same exact
equity (suit symmetry), so each class is sampled with its first combo. Classes are sorted by
equity, highest first; equal equities are ordered by label, so the order is stable.

The samples come from ``random.Random(str).sample``: CPython seeds a string through SHA-512 and
documents the sequence it draws for a seed only loosely, so a new Python release could in
principle change the numbers. Run ``--check`` after a Python upgrade; to change the file on
purpose, bump ``VERSION`` below and rewrite it.

The 5-max pre-flop bots (``villain/preflop5.py``) take their buckets as slices of this order.

    cd backend && uv run python -m poker_trainer.analysis.hand_ranking            # rewrite the file
    cd backend && uv run python -m poker_trainer.analysis.hand_ranking --check    # compare only
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from importlib.resources import files
from pathlib import Path

from phevaluator import evaluate_cards

from poker_trainer.engine.combos import COMBOS, HAND_CLASSES, combos_of_class

VERSION = 1
SAMPLES = 50_000


def class_equity(label: str, samples: int = SAMPLES) -> float:
    """Monte Carlo all-in equity (win + tie / 2) of ``label`` against a random hand."""
    a, b = COMBOS[combos_of_class(label)[0]]
    rest = [c for c in range(52) if c not in (a, b)]
    rng = random.Random(f"hand-ranking:{label}")
    sample = rng.sample
    score = 0.0
    for _ in range(samples):
        v1, v2, b1, b2, b3, b4, b5 = sample(rest, 7)
        h = evaluate_cards(a, b, b1, b2, b3, b4, b5)
        v = evaluate_cards(v1, v2, b1, b2, b3, b4, b5)
        if h < v:  # lower rank is stronger
            score += 1.0
        elif h == v:
            score += 0.5
    return score / samples


def ranking(samples: int = SAMPLES) -> list[str]:
    eq = {label: class_equity(label, samples) for label in HAND_CLASSES}
    return sorted(HAND_CLASSES, key=lambda lab: (-eq[lab], lab))


def render(classes: list[str]) -> str:
    """The file's exact text: one label per line, LF line endings."""
    body = ",\n".join(f'    "{c}"' for c in classes)
    return f'{{\n  "version": {VERSION},\n  "classes": [\n{body}\n  ]\n}}\n'


def data_path() -> Path:
    return Path(str(files("poker_trainer.villain").joinpath("hand_ranking.json")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the 169-class hand ranking.")
    parser.add_argument("--check", action="store_true", help="compare with the file, write nothing")
    args = parser.parse_args(argv)
    text = render(ranking())
    json.loads(text)  # well-formed
    path = data_path()
    if args.check:
        same = path.read_bytes() == text.encode("utf-8")
        print("hand_ranking.json is up to date" if same else "hand_ranking.json differs")
        return 0 if same else 1
    path.write_bytes(text.encode("utf-8"))  # bytes: LF on every platform
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
