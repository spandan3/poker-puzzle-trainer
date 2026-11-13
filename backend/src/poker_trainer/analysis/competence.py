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
    bets Hero happened to make. A defence probe counts toward ``samples`` only when that
    weight is at least MIN_PROBE_WEIGHT; lighter probes still enter the mean.
  - The fold/call checks use every probe. The Villain tables only bet 33% / 75% and
    raise 3x, so a pot-size bet is almost never faced in self-play; the 100% probe (a
    Hero size shortcut in the trainer) gives ``strong_fold_max`` its spots. These are
    max-over-spots checks, so every probe counts as a sample whatever Hero's frequency.
  - ``defence_overbet``: at every Hero unopened decision (any street), Villain's
    continue / MDF facing a Hero probe of 2.5x pot (``bet_to`` may clamp it to all-in).
    Each probe has weight 1 and counts as a sample. This probe feeds no other check.
  - ``raise_dominated`` (river, 33% / 75% probes): of Villain's raising weight, the share
    that is value (category >= MEDIUM) with equity below 0.4 against the Hero combos
    that made the probe bet and then continue (call or raise) facing the raise. Bluff
    raises count in the denominator only. Probes are weighted by Hero's bet frequency,
    as the defence probes are; a probe counts as a sample when it has a raise and its
    weight is at least MIN_PROBE_WEIGHT. With fewer than MIN_SAMPLES samples the check
    is reported as info (``CheckResult.info``), not pass/fail: raises are rare.
* ``cbet_flop``: Villain's whole-range bet frequency (any size) at each flop decision
  in the c-bettor role, averaged over spots.
* ``preflop_defence_3bet`` (no simulation, ``samples`` = 1326): BTN continue (call or
  jam) facing a 3x 3-bet, weighted by BTN's opening range, over MDF (0.50 for a 3-bet to
  15). Fixed band for every profile: BTN is in position, so continuing above MDF is
  right; the post-flop ``defence_ratio`` bands don't apply.
* INFO_NAMES are printed for review but are not checks: ``river_stab`` (whole-range
  river stab frequency), ``air_continue_max`` (AIR call+raise facing river bets of
  75% pot or more; ``air_call_max`` counts calls only) and ``preflop_defence_open``
  (BB continue, call or 3-bet, over all 1,326 combos facing a 2.5x open, over MDF 4/7;
  heads-up the BB closes the action at a price, so defending well above MDF is right).

MDF convention everywhere: ``prior / (prior + call)``, where ``prior`` is the pot before
the bet faced (``total_pot - call``).

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
    OPEN_MULT,
    THREEBET_MULT,
    UnsupportedSpot,
    action_distribution,
    bet_to,
    raise_to,
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
    "cbet_flop",
    "defence_overbet",
    "raise_dominated",
    "preflop_defence_3bet",
)
# Printed for information only; never pass/fail.
INFO_NAMES = ("river_stab", "air_continue_max", "preflop_defence_open")
# Checks reported as info (not pass/fail) when they have fewer than MIN_SAMPLES samples.
SPARSE_INFO = ("raise_dominated",)
MIN_SAMPLES = 30
# A defence probe counts toward ``samples`` only if Hero makes that bet at least this
# often there; rarer probes still enter the weighted mean.
MIN_PROBE_WEIGHT = 0.05
VILLAIN_SEAT, HERO_SEAT = 0, 1

_BET_SIZES = {"33": 0.33, "75": 0.75}
_PROBE_SIZES = (0.33, 0.75, 1.0)
_OVERBET = 2.5
_BLUFF_EQUITY = 0.5
_DOMINATED_EQUITY = 0.4
_FIXED_BANDS = {
    "nuts_fold_max": (0.0, 0.0),
    "strong_fold_max": (0.0, 0.10),
    "air_call_max": (0.0, 0.10),
    "thin_value_dominated": (0.0, 0.10),
    "cbet_flop": (0.45, 0.70),
    "raise_dominated": (0.0, 0.10),
    "preflop_defence_3bet": (0.90, 1.40),
}
_MAX_CHECKS = ("nuts_fold_max", "strong_fold_max", "air_call_max", "air_continue_max")
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
    # True when a SPARSE_INFO check has too few samples: shown, but neither pass nor fail.
    info: bool = False


# One record per spot: (check name, numerator, denominator, counts toward samples). A
# check's value is sum(numerators) / sum(denominators), except the *_max checks, which
# take the largest numerator (their denominators are 1).
Record = tuple[str, float, float, bool]


def break_even_bluff_share(frac: float) -> float:
    """Bluff share that makes a caller indifferent to a bet of ``frac`` pot: f / (1 + 2f)."""
    return frac / (1.0 + 2.0 * frac)


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


def mdf(s: HandState) -> float:
    """Minimum defence frequency for the seat to act facing a bet: prior / (prior + call)."""
    call = legal_actions(s).call
    prior = total_pot(s) - call  # pot before the bet faced
    return prior / (prior + call)  # 1 / (1 + f)


def _defence_ratio(s: HandState, dist: dict[Action, np.ndarray], range_: np.ndarray) -> float:
    """Whole-range continue (call + raise) frequency over MDF, for the seat to act."""
    cont = _sum_kind(dist, ActionKind.CALL, ActionKind.RAISE)
    return float(range_ @ cont) / float(range_.sum()) / mdf(s)


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
        name = f"defence_{_STREET_NAMES[s.street]}"
        counted = defence_weight >= MIN_PROBE_WEIGHT
        ratio = _defence_ratio(s, dist, villain)
        out.append((name, defence_weight * ratio, defence_weight, counted))

    nuts = _share(villain, cats == HandCategory.NUTS, fold)
    if nuts is not None:
        out.append(("nuts_fold_max", nuts, 1.0, True))
    # Half a chip of slack: bet_to rounds the nominal size to whole chips. Bets only:
    # folding a STRONG hand to a pot-plus all-in check-raise can be correct, and the
    # facing_raise tables deliberately fold more than facing_bet.
    if call + 0.5 >= prior and role(s) == "facing_bet":
        strong = _share(villain, cats == HandCategory.STRONG, fold)
        if strong is not None:
            out.append(("strong_fold_max", strong, 1.0, True))
    if s.street == Street.RIVER and call + 0.5 >= 0.75 * prior:
        air = _share(villain, cats == HandCategory.AIR, calls)
        air_cont = _share(villain, cats == HandCategory.AIR, cont)
        if air is not None and air_cont is not None:
            out.append(("air_call_max", air, 1.0, True))
            out.append(("air_continue_max", air_cont, 1.0, True))


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
        out.append((f"bluff_share_{name}", bluffs / range_total, bet_total / range_total, True))
        value_total = float(value.sum())
        if value_total > 0.0:
            out.append(
                ("thin_value_dominated", dominated / range_total, value_total / range_total, True)
            )


def _bet_frequency(dist: dict[Action, np.ndarray], villain: np.ndarray) -> float:
    """Whole-range probability of betting (any size)."""
    return float(villain @ _sum_kind(dist, ActionKind.BET)) / float(villain.sum())


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

    Defence and raise records are weighted by how often Hero's range makes that bet here
    (zero for the 100% probe, which is not a Hero policy size). The 2.5x-pot probe feeds
    ``defence_overbet`` only, with weight 1.
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
        if s.street == Street.RIVER and weight > 0.0:
            bettors = hero * hero_dist[bet]
            _raise_records(out, probe, dist, hero_profile, villain, bettors, cats, weight)
    over = apply(s, bet_to(s, _OVERBET))
    dist = action_distribution(villain_profile, over)
    out.append(("defence_overbet", _defence_ratio(over, dist, villain), 1.0, True))


def _raise_records(
    out: list[Record],
    probe: HandState,
    dist: dict[Action, np.ndarray],
    hero_profile: Profile,
    villain: np.ndarray,
    bettors: np.ndarray,
    cats: np.ndarray,
    weight: float,
) -> None:
    """``raise_dominated`` record for Villain raising a Hero river probe bet.

    ``bettors`` is Hero's range times its probability of making the probe bet. Equity is
    against the bettors that continue (call or raise) facing Villain's raise. Numerator:
    value raises (category >= MEDIUM) with equity below 0.4; denominator: all raises.
    Both are shares of Villain's range, scaled by ``weight`` (Hero's bet frequency).
    If no bettor continues, nothing is dominated (the raise wins the pot).
    """
    range_total = float(villain.sum())
    value_mask = cats >= HandCategory.MEDIUM
    raised = dominated = 0.0
    for a, arr in dist.items():
        if a.kind != ActionKind.RAISE:
            continue
        raising = villain * arr
        if float(raising.sum()) <= 0.0:
            continue
        raised += float(raising.sum())
        response = action_distribution(hero_profile, apply(probe, a))
        callers = bettors * _sum_kind(response, ActionKind.CALL, ActionKind.RAISE)
        if float(callers.sum()) <= 0.0:
            continue
        eq = river_equity(probe.board, callers)
        with np.errstate(invalid="ignore"):
            dominated += float((raising * value_mask)[eq < _DOMINATED_EQUITY].sum())
    if raised > 0.0:
        counted = weight >= MIN_PROBE_WEIGHT
        out.append(
            (
                "raise_dominated",
                weight * dominated / range_total,
                weight * raised / range_total,
                counted,
            )
        )


# ---------------------------------------------------------------------------
# Pre-flop defence (deterministic)
# ---------------------------------------------------------------------------


def preflop_defence(profile: Profile) -> tuple[float, float]:
    """``(open, 3bet)`` continue / MDF ratios from the profile's pre-flop policy.

    ``open``: BB facing a 2.5x open (to 5 chips; MDF 4/7), call + 3-bet, over all 1,326
    combos. ``3bet``: BTN facing a 3x 3-bet (to 15; MDF 0.50), call + jam, weighted by
    BTN's opening range.
    """
    s = new_hand(VILLAIN_SEAT)
    open_ = raise_to(s, OPEN_MULT)
    opened = action_distribution(profile, s)[open_]
    facing_open = apply(s, open_)
    bb = action_distribution(profile, facing_open)
    open_ratio = _defence_ratio(facing_open, bb, np.ones(len(COMBOS)))
    facing_3bet = apply(facing_open, raise_to(facing_open, THREEBET_MULT))
    btn = action_distribution(profile, facing_3bet)
    return open_ratio, _defence_ratio(facing_3bet, btn, opened)


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
                can_bet = legal_actions(s).aggressive == ActionKind.BET
                if r.startswith("facing"):
                    _facing_records(out, s, dist, villain, cats, defence_weight=0.0)
                elif can_bet and s.street == Street.FLOP and r == "cbet":
                    out.append(("cbet_flop", _bet_frequency(dist, villain), 1.0, True))
                elif can_bet and s.street == Street.RIVER:
                    if r == "stab":
                        out.append(("river_stab", _bet_frequency(dist, villain), 1.0, True))
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
        base = break_even_bluff_share(_BET_SIZES[name.removeprefix("bluff_share_")])
        lo, hi = profile.bands.bluff_offset
        return round(base + lo, 6), round(base + hi, 6)
    if name.startswith("defence_"):
        return profile.bands.defence_ratio
    return _FIXED_BANDS[name]


def competence_report(profile_name: str, n_hands: int = 400, seed: int = 0) -> list[CheckResult]:
    """Simulate ``n_hands`` hands and score ``profile_name`` on every check in CHECK_NAMES.

    A check with fewer than MIN_SAMPLES spots fails ("insufficient samples"), except a
    SPARSE_INFO check, which is then marked ``info`` (neither pass nor fail); a check
    with none reports nan.
    """
    return competence_details(profile_name, n_hands, seed)[0]


def competence_details(
    profile_name: str, n_hands: int = 400, seed: int = 0
) -> tuple[list[CheckResult], dict[str, float]]:
    """``competence_report`` plus the INFO_NAMES values (printed, never checked)."""
    villain_profile = load_profile(profile_name)
    hero_profile = load_profile(HERO_PROFILE)
    rng = np.random.default_rng(seed)
    records: list[Record] = []
    for i in range(n_hands):
        try:
            records.extend(_play_hand(villain_profile, hero_profile, i % 2, rng))
        except UnsupportedSpot:
            continue  # abandoned hand: its records are dropped

    open_ratio, threebet_ratio = preflop_defence(villain_profile)
    results = []
    for name in CHECK_NAMES:
        if name == "preflop_defence_3bet":
            value, samples = threebet_ratio, len(COMBOS)
        else:
            value, samples = _aggregate(records, name)
        band = _band(villain_profile, name)
        passed = (
            samples >= MIN_SAMPLES
            and not math.isnan(value)
            and band[0] - _TOL <= value <= band[1] + _TOL
        )
        info = name in SPARSE_INFO and samples < MIN_SAMPLES
        results.append(CheckResult(profile_name, name, value, band, passed, samples, info))
    infos = {name: _aggregate(records, name)[0] for name in INFO_NAMES}
    infos["preflop_defence_open"] = open_ratio
    return results, infos


def _aggregate(records: list[Record], name: str) -> tuple[float, int]:
    mine = [(num, den, counted) for n, num, den, counted in records if n == name]
    samples = sum(1 for *_, counted in mine if counted)
    if not mine:
        return math.nan, samples
    if name in _MAX_CHECKS:
        return max(num for num, _, _ in mine), samples
    return sum(num for num, _, _ in mine) / sum(den for _, den, _ in mine), samples


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
        elif r.info:
            verdict = "INFO (insufficient samples, not checked)"
        elif r.samples < MIN_SAMPLES:
            verdict = "FAIL (insufficient samples)"
        else:
            verdict = "FAIL"
        lines.append(
            f"{r.profile:<8} {r.name:<22} {r.value:>7.3f}  {band:<15} {r.samples:>7}  {verdict}"
        )
    return "\n".join(lines)


def format_summary(
    runs: Sequence[tuple[list[CheckResult], dict[str, dict[str, float]]]],
) -> str:
    """Min / max per check over seeds and the number of seeds passing (``info`` counts
    seeds where a sparse check was not checked). INFO_NAMES rows have no band."""
    header = f"{'profile':<8} {'check':<22} {'min':>7} {'max':>7}  {'band':<15} {'pass':>5}  info"
    lines = [header, "-" * len(header)]
    n = len(runs)
    first = runs[0][0]
    for i, r0 in enumerate(first):
        rs = [results[i] for results, _ in runs]
        vals = [r.value for r in rs]
        band = f"[{r0.band[0]:.2f}, {r0.band[1]:.2f}]"
        passing = f"{sum(r.passed for r in rs)}/{n}"
        info = sum(r.info for r in rs)
        lines.append(
            f"{r0.profile:<8} {r0.name:<22} {min(vals):>7.3f} {max(vals):>7.3f}  "
            f"{band:<15} {passing:>5}  {info or ''}"
        )
        last_of_profile = i + 1 == len(first) or first[i + 1].profile != r0.profile
        if last_of_profile:
            for name in INFO_NAMES:
                vals = [infos[r0.profile][name] for _, infos in runs]
                lines.append(
                    f"{r0.profile:<8} {name:<22} {min(vals):>7.3f} {max(vals):>7.3f}  "
                    f"{'(info)':<15} {'-':>5}"
                )
    return "\n".join(lines)


def parse_seeds(text: str) -> list[int]:
    """``"0-5"`` -> [0, 1, 2, 3, 4, 5]; ``"0,3"`` -> [0, 3]; ranges and lists combine."""
    seeds: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        lo, sep, hi = part.partition("-")
        if sep:
            a, b = int(lo), int(hi)
            if a > b:
                raise ValueError(f"empty seed range {part!r}")
            seeds.extend(range(a, b + 1))
        else:
            seeds.append(int(part))
    if not seeds:
        raise ValueError("no seeds given")
    return seeds


def _seeds_arg(text: str) -> list[int]:
    try:
        return parse_seeds(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def _print_infos(infos: dict[str, dict[str, float]]) -> None:
    print("info (not checks): river_stab = whole-range river stab bet frequency;")
    print("air_continue_max = AIR call+raise share facing river bets >= 75% pot (max);")
    print("preflop_defence_open = BB call+3-bet share of all combos vs a 2.5x open / MDF 4/7.")
    for n, info in infos.items():
        print(f"{n:<8} " + "  ".join(f"{k}={v:.3f}" for k, v in info.items()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Villain profile competence report.")
    parser.add_argument("--profile", default="all", choices=(*PROFILE_NAMES, "all"))
    parser.add_argument("--hands", type=int, default=400)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--seeds",
        type=_seeds_arg,
        default=None,
        help="several seeds, e.g. 0-5 or 0,3 (overrides --seed): a table per seed and a summary",
    )
    args = parser.parse_args(argv)
    names = PROFILE_NAMES if args.profile == "all" else (args.profile,)
    seeds = args.seeds if args.seeds is not None else [args.seed]
    runs: list[tuple[list[CheckResult], dict[str, dict[str, float]]]] = []
    for seed in seeds:
        results: list[CheckResult] = []
        infos: dict[str, dict[str, float]] = {}
        for n in names:
            checks, infos[n] = competence_details(n, args.hands, seed)
            results.extend(checks)
        runs.append((results, infos))
        if args.seeds is not None:
            print(f"=== seed {seed} ===")
        print(format_table(results))
        print()
        _print_infos(infos)
        print()
    if args.seeds is not None:
        print(f"=== summary over {len(seeds)} seeds, {args.hands} hands each ===")
        print(format_summary(runs))
    ok = all(r.passed or r.info for results, _ in runs for r in results)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
