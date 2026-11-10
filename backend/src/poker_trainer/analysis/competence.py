"""Competence report: does each Villain profile play sensibly?

The profile under test plays Villain (seat 0) against ``HERO_PROFILE`` (seat 1); the
button alternates every hand. Both seats act through ``sample_action`` and both ranges
are tracked with ``RangeTracker``, so every check runs on the same posteriors that the
trainer shows and grades. Checks are computed over whole ranges (every combo weighted by
its tracked weight and its action probability), not over the one sampled hand.

Where the data comes from:

* Villain flop/turn/river decisions: the role, Villain's range, Hero's range and the
  action distribution. Unopened river spots feed the bluff-share and thin-value checks;
  facing spots (bets and raises) feed the fold/call checks.
* Hero flop/turn/river unopened decisions ("probes"): Villain's predicted response to a
  Hero bet of 33%, 75% and 100% pot. Villain's range at a Hero decision does not depend
  on what Hero then does, so a probe is the same spot a real bet would create.
  - Defence ratios use the 33% / 75% probes, each weighted by how often Hero's tracked
    range makes that bet there. This estimates the average over the facing-a-bet spots
    self-play reaches without the noise (and the thin river sample) of using only the
    bets Hero happened to make.
  - The fold/call checks use every probe. The Villain tables only bet 33% / 75% and
    raise 3x, so a pot-size bet is almost never faced in self-play; the 100% probe (a
    Hero size shortcut in the trainer) gives ``strong_fold_max`` its spots.

River equity is exact: per-combo hand ranks on the river board, each Villain combo
against the weighted calling range, skipping Hero combos that share a card with it.
"""

from __future__ import annotations

import argparse
import math
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from poker_trainer.engine.combos import COMBOS
from poker_trainer.engine.evaluator import evaluate
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
    total_pot,
)
from poker_trainer.villain.features import (
    HandCategory,
    categorize,
    load_thresholds,
    range_features,
)
from poker_trainer.villain.narrowing import RangeTracker
from poker_trainer.villain.profiles import PROFILE_NAMES, Profile, load_profile
from poker_trainer.villain.strategy import (
    HERO_PROFILE,
    UnsupportedSpot,
    action_distribution,
    bet_to,
    role,
    sample_action,
)

CHECK_NAMES = (
    "bluff_share_33",
    "bluff_share_75",
    "defence_flop",
    "defence_turn",
    "defence_river",
    "nuts_fold_max",
    "strong_fold_max",
    "air_call_max",
    "thin_value_dominated",
)
MIN_SAMPLES = 30
VILLAIN_SEAT, HERO_SEAT = 0, 1

# Break-even bluff share f / (1 + 2f) of a bet of f pot, at the nominal sizes.
_BET_SIZES = {"33": 0.33, "75": 0.75}
_BREAK_EVEN = {"33": 0.20, "75": 0.30}
_PROBE_SIZES = (0.33, 0.75, 1.0)
_BLUFF_EQUITY = 0.5
_DOMINATED_EQUITY = 0.4
_FIXED_BANDS = {
    "nuts_fold_max": (0.0, 0.0),
    "strong_fold_max": (0.0, 0.10),
    "air_call_max": (0.0, 0.10),
    "thin_value_dominated": (0.0, 0.10),
}
_MAX_CHECKS = ("nuts_fold_max", "strong_fold_max", "air_call_max")
_STREET_NAMES = {Street.FLOP: "flop", Street.TURN: "turn", Street.RIVER: "river"}
_TOL = 1e-9


@dataclass(frozen=True)
class CheckResult:
    profile: str
    name: str
    value: float
    band: tuple[float, float]
    passed: bool
    samples: int


# One record per spot: (check name, numerator, denominator). A check's value is
# sum(numerators) / sum(denominators), except the *_max checks, which take the largest
# numerator (their denominators are 1).
Record = tuple[str, float, float]


# ---------------------------------------------------------------------------
# Per-board caches
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _thresholds():
    return load_thresholds()


@lru_cache(maxsize=1024)
def _board_info(board: tuple[int, ...]) -> tuple[np.ndarray, np.ndarray]:
    """(live mask as 0/1 floats, category per combo; -1 for board-blocked)."""
    cats = categorize(range_features(board), _thresholds())
    live = (cats >= 0).astype(np.float64)
    live.flags.writeable = False
    return live, cats


@lru_cache(maxsize=1)
def _no_conflict() -> np.ndarray:
    """(1326, 1326) float32: 1 where two combos share no card."""
    onehot = np.zeros((len(COMBOS), 52), dtype=np.float32)
    for i, (a, b) in enumerate(COMBOS):
        onehot[i, a] = onehot[i, b] = 1.0
    out = (onehot @ onehot.T == 0).astype(np.float32)
    out.flags.writeable = False
    return out


@lru_cache(maxsize=4)
def _showdown(board: tuple[int, ...]) -> np.ndarray:
    """(1326, 1326) float32: 1 if row combo beats column combo, 0.5 on a tie, 0 if it loses
    or the two combos share a card. Board-blocked combos get rank 0 (callers' weights are
    zero there, so it never matters)."""
    on_board = set(board)
    ranks = np.array(
        [0 if a in on_board or b in on_board else evaluate((a, b, *board)) for a, b in COMBOS]
    )
    score = (ranks[:, None] < ranks[None, :]).astype(np.float32)
    score += 0.5 * (ranks[:, None] == ranks[None, :])
    score *= _no_conflict()
    score.flags.writeable = False
    return score


def river_equity(board: Sequence[int], opponent: np.ndarray) -> np.ndarray:
    """Showdown equity of every combo against a weighted range on a 5-card board.

    nan where no opponent combo is compatible with the combo.
    """
    b = tuple(int(c) for c in board)
    if len(b) != 5:
        raise ValueError("river equity needs a 5-card board")
    num = _showdown(b) @ opponent
    den = _no_conflict() @ opponent
    return np.divide(num, den, out=np.full(len(COMBOS), np.nan), where=den > 0)


# ---------------------------------------------------------------------------
# Spot records
# ---------------------------------------------------------------------------


def _sum_kind(dist: dict[Action, np.ndarray], *kinds: ActionKind) -> np.ndarray:
    out = np.zeros(len(COMBOS))
    for a, arr in dist.items():
        if a.kind in kinds:
            out += arr
    return out


def _share(weights: np.ndarray, mask: np.ndarray, probs: np.ndarray) -> float | None:
    w = weights * mask
    total = float(w.sum())
    return None if total <= 0.0 else float(w @ probs) / total


def _facing_records(
    out: list[Record],
    s: HandState,
    dist: dict[Action, np.ndarray],
    villain: np.ndarray,
    cats: np.ndarray,
    defence_weight: float,
) -> None:
    """Records for Villain facing a bet or raise in state ``s``.

    ``defence_weight`` > 0 adds a defence record with that weight.
    """
    call = legal_actions(s).call
    prior = total_pot(s) - call  # pot before the bet faced
    fold = _sum_kind(dist, ActionKind.FOLD)
    cont = _sum_kind(dist, ActionKind.CALL, ActionKind.RAISE)
    calls = _sum_kind(dist, ActionKind.CALL)
    if defence_weight > 0.0:
        mdf = prior / (prior + call)  # 1 / (1 + f)
        rate = float(villain @ cont) / float(villain.sum())
        name = f"defence_{_STREET_NAMES[s.street]}"
        out.append((name, defence_weight * rate / mdf, defence_weight))

    nuts = _share(villain, cats == HandCategory.NUTS, fold)
    if nuts is not None:
        out.append(("nuts_fold_max", nuts, 1.0))
    # Half a chip of slack: bet_to rounds the nominal size to whole chips. Bets only:
    # folding a STRONG hand to a pot-plus all-in check-raise can be correct, and the
    # facing_raise tables deliberately fold more than facing_bet.
    if call + 0.5 >= prior and role(s) == "facing_bet":
        strong = _share(villain, cats == HandCategory.STRONG, fold)
        if strong is not None:
            out.append(("strong_fold_max", strong, 1.0))
    if s.street == Street.RIVER and call + 0.5 >= 0.75 * prior:
        air = _share(villain, cats == HandCategory.AIR, calls)
        if air is not None:
            out.append(("air_call_max", air, 1.0))


def _river_bet_records(
    out: list[Record],
    s: HandState,
    dist: dict[Action, np.ndarray],
    hero_profile: Profile,
    villain: np.ndarray,
    hero: np.ndarray,
    cats: np.ndarray,
) -> None:
    """Bluff-share and thin-value records for Villain's river betting range."""
    bets = {name: bet_to(s, frac) for name, frac in _BET_SIZES.items()}
    if bets["33"] == bets["75"]:
        return  # both sizes resolve to the same chips: no per-size answer
    range_total = float(villain.sum())
    value_mask = cats >= HandCategory.MEDIUM
    for name, bet in bets.items():
        betting = villain * dist[bet]
        bet_total = float(betting.sum())
        if bet_total <= 0.0:
            continue
        response = action_distribution(hero_profile, apply(s, bet))
        callers = hero * _sum_kind(response, ActionKind.CALL, ActionKind.RAISE)
        if float(callers.sum()) <= 0.0:
            continue
        eq = river_equity(s.board, callers)
        with np.errstate(invalid="ignore"):
            bluffs = float(betting[eq < _BLUFF_EQUITY].sum())
            value = betting * value_mask
            dominated = float(value[eq < _DOMINATED_EQUITY].sum())
        out.append((f"bluff_share_{name}", bluffs / range_total, bet_total / range_total))
        value_total = float(value.sum())
        if value_total > 0.0:
            out.append(("thin_value_dominated", dominated / range_total, value_total / range_total))


def _probe_records(
    out: list[Record],
    s: HandState,
    villain_profile: Profile,
    hero_profile: Profile,
    villain: np.ndarray,
    hero: np.ndarray,
    cats: np.ndarray,
) -> None:
    """Villain's predicted response to each probe bet at a Hero unopened decision.

    Defence records are weighted by how often Hero's range makes that bet here (zero for
    the 100% probe, which is not a Hero policy size).
    """
    hero_dist = action_distribution(hero_profile, s)
    hero_total = float(hero.sum())
    seen: set[Action] = set()
    for frac in _PROBE_SIZES:
        bet = bet_to(s, frac)
        if bet in seen:
            continue
        seen.add(bet)
        weight = float(hero @ hero_dist[bet]) / hero_total if bet in hero_dist else 0.0
        probe = apply(s, bet)
        dist = action_distribution(villain_profile, probe)
        _facing_records(out, probe, dist, villain, cats, defence_weight=weight)


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


def _play_hand(
    villain_profile: Profile,
    hero_profile: Profile,
    button: int,
    rng: np.random.Generator,
) -> list[Record]:
    cards = [int(c) for c in rng.permutation(52)[:9]]
    holes = ((cards[0], cards[1]), (cards[2], cards[3]))
    board = cards[4:]
    profiles = (villain_profile, hero_profile)
    trackers = (
        RangeTracker(villain_profile, VILLAIN_SEAT),
        RangeTracker(hero_profile, HERO_SEAT),
    )
    out: list[Record] = []
    s = new_hand(button)
    while not is_terminal(s):
        if needs_board(s):
            n = len(s.board)
            s = deal(s, tuple(board[n : n + (3 if n == 0 else 1)]))
            continue
        seat = s.to_act
        assert seat is not None
        if s.street != Street.PREFLOP:
            live, cats = _board_info(s.board)
            villain = trackers[VILLAIN_SEAT].current * live
            r = role(s)
            if seat == VILLAIN_SEAT:
                dist = action_distribution(villain_profile, s)
                if r.startswith("facing"):
                    _facing_records(out, s, dist, villain, cats, defence_weight=0.0)
                elif s.street == Street.RIVER and legal_actions(s).aggressive == ActionKind.BET:
                    hero = trackers[HERO_SEAT].current * live
                    _river_bet_records(out, s, dist, hero_profile, villain, hero, cats)
            elif not r.startswith("facing") and legal_actions(s).aggressive == ActionKind.BET:
                hero = trackers[HERO_SEAT].current * live
                _probe_records(out, s, villain_profile, hero_profile, villain, hero, cats)
        action = sample_action(profiles[seat], s, holes[seat], rng)  # type: ignore[arg-type]
        trackers[seat].observe(s, action)
        s = apply(s, action)
    return out


def _band(profile: Profile, name: str) -> tuple[float, float]:
    if name.startswith("bluff_share_"):
        base = _BREAK_EVEN[name.removeprefix("bluff_share_")]
        lo, hi = profile.bands.bluff_offset
        return round(base + lo, 6), round(base + hi, 6)
    if name.startswith("defence_"):
        return profile.bands.defence_ratio
    return _FIXED_BANDS[name]


def competence_report(profile_name: str, n_hands: int = 400, seed: int = 0) -> list[CheckResult]:
    """Simulate ``n_hands`` hands and score ``profile_name`` on every check in CHECK_NAMES.

    A check with fewer than MIN_SAMPLES spots fails ("insufficient samples"); a check with
    none reports nan.
    """
    villain_profile = load_profile(profile_name)
    hero_profile = load_profile(HERO_PROFILE)
    rng = np.random.default_rng(seed)
    records: list[Record] = []
    for i in range(n_hands):
        try:
            records.extend(_play_hand(villain_profile, hero_profile, i % 2, rng))
        except UnsupportedSpot:
            continue  # abandoned hand: its records are dropped

    results = []
    for name in CHECK_NAMES:
        mine = [(num, den) for n, num, den in records if n == name]
        if not mine:
            value = math.nan
        elif name in _MAX_CHECKS:
            value = max(num for num, _ in mine)
        else:
            value = sum(num for num, _ in mine) / sum(den for _, den in mine)
        band = _band(villain_profile, name)
        passed = (
            len(mine) >= MIN_SAMPLES
            and not math.isnan(value)
            and band[0] - _TOL <= value <= band[1] + _TOL
        )
        results.append(CheckResult(profile_name, name, value, band, passed, len(mine)))
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def format_table(results: Sequence[CheckResult]) -> str:
    header = f"{'profile':<8} {'check':<22} {'value':>7}  {'band':<15} {'samples':>7}  result"
    lines = [header, "-" * len(header)]
    for r in results:
        band = f"[{r.band[0]:.2f}, {r.band[1]:.2f}]"
        if r.passed:
            verdict = "PASS"
        elif r.samples < MIN_SAMPLES:
            verdict = "FAIL (insufficient samples)"
        else:
            verdict = "FAIL"
        lines.append(
            f"{r.profile:<8} {r.name:<22} {r.value:>7.3f}  {band:<15} {r.samples:>7}  {verdict}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Villain profile competence report.")
    parser.add_argument("--profile", default="all", choices=(*PROFILE_NAMES, "all"))
    parser.add_argument("--hands", type=int, default=400)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    names = PROFILE_NAMES if args.profile == "all" else (args.profile,)
    results = [r for n in names for r in competence_report(n, args.hands, args.seed)]
    print(format_table(results))
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
