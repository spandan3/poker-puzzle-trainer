"""``puzzle-sample``: print a few generated puzzles (plain ASCII for Windows consoles)."""

from __future__ import annotations

import argparse

from poker_trainer.engine.cards import card_str
from poker_trainer.engine.ranges import total_weight
from poker_trainer.game.state import Street, apply, deal, needs_board, new_hand, position_name
from poker_trainer.puzzle.generate import generate_puzzle, parse_street
from poker_trainer.puzzle.model import Puzzle, Spot
from poker_trainer.villain.narrowing import describe


def _cards(cs: tuple[int, ...]) -> str:
    return " ".join(card_str(c) for c in cs) if cs else "-"


def describe_line(spot: Spot) -> list[str]:
    """Each action of the hand up to the decision, e.g. "Hero (BTN) Pre-flop: opens to 5"."""
    final = spot.state
    s = new_hand(final.button)
    out: list[str] = []
    for a in final.history:
        while needs_board(s):
            n = 3 if s.street == Street.PREFLOP else 1
            k = len(s.board)
            s = deal(s, spot.runout[k : k + n])
        who = "Hero" if a.seat == spot.hero_seat else "Villain"
        out.append(f"{who} ({position_name(s, a.seat)}) {describe(a, s)}")
        s = apply(s, a)
    return out


def format_puzzle(p: Puzzle) -> str:
    sp, sol = p.spot, p.solution
    s = sp.state
    hero_pos = position_name(s, sp.hero_seat)
    street = s.street.name.lower()
    lines = [
        f"seed {sp.seed} attempt {sp.attempt} | {street} | villain {sp.profile} | hero {hero_pos}",
        "line:  " + ("; ".join(describe_line(sp)) or "(first to act)"),
        f"hero:  {_cards(sp.hero)}    board: {_cards(tuple(s.board))}",
        f"range: {total_weight(sp.range):.1f} combos (weighted)",
        f"equity: {sol.equity:.3f} (+/- {sol.equity_std_error:.3f})   pot odds: {sol.pot_odds:.3f}",
        "options (EV in bb, fold = 0):",
    ]
    for i, o in enumerate(sol.options):
        mark = "  <- best" if i == sol.best else ""
        lines.append(f"  {o.option.label:<12} {o.ev_bb:+8.2f}{mark}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print sample generated puzzles.")
    parser.add_argument("--n", type=int, default=5, help="number of puzzles")
    parser.add_argument("--seed", type=int, default=0, help="first seed")
    parser.add_argument("--street", choices=["preflop", "flop", "turn", "river"], default=None)
    parser.add_argument("--profile", default=None, help="villain profile (default: random)")
    args = parser.parse_args(argv)
    street = None if args.street is None else parse_street(args.street)
    for i in range(args.n):
        if i:
            print()
        print(format_puzzle(generate_puzzle(args.seed + i, street=street, profile=args.profile)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
