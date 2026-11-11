"""Reject puzzles whose answer is obvious (the "Trivial filter" rules in the M3 plan)."""

from __future__ import annotations

from poker_trainer.puzzle.model import PuzzleConfig, Solution, best_margin

_EPS = 1e-9


def is_trivial(sol: Solution, pot: int, cfg: PuzzleConfig) -> str | None:
    """The reason ``sol`` is a trivial spot at total pot ``pot``, or None if it is not."""
    t = cfg.trivial
    eq = sol.equity
    if eq > t.eq_hi or eq < t.eq_lo:
        return f"equity {eq:.3f} outside [{t.eq_lo}, {t.eq_hi}]"

    evs = sorted((o.ev_chips for o in sol.options), reverse=True)
    best = evs[0]
    margin = best_margin(pot, cfg.verdict) + _EPS
    if all(best - ev <= margin for ev in evs):
        return "every option is within the Best margin"

    if len(evs) > 1 and best - evs[1] > t.gap_pot * pot and (eq > t.gap_eq_hi or eq < t.gap_eq_lo):
        return f"best option clear by {best - evs[1]:.1f} chips with equity {eq:.3f}"
    return None
