# The Villain model

Villain is the opponent in every puzzle and the bot in Play vs Bots. This page holds its contract, the rules for changing it, how its competence is checked, and the open backlog. Design: `docs/superpowers/specs/2026-11-10-poker-puzzle-trainer-design.md` §5. Code: `backend/src/poker_trainer/villain/`.

## How it works

Villain is a rule-based, probabilistic player, not a solver:
1. It sorts every one of the 1,326 possible hands into a **category** on the current board: AIR, WEAK_DRAW, WEAK, MEDIUM, STRONG_DRAW, STRONG, NUTS (`features.py`, thresholds in `categories.json`).
2. A **profile** (TAG, LAG, Tight, Sticky; `profiles/*.json`) gives each category a probability for each action in each spot.
3. Adjustments are layered on top in `strategy.py`: a draw boost on wet boards, bet-size scaling when facing a bet (MDF-scaled past pot size, with a STRONG floor), and the low-SPR "committed" rule.

### One policy, used four ways

Everything goes through `action_distribution(profile, state)` in `villain/strategy.py`:
1. **Plays the puzzle hand.** Villain's real action is sampled from its real hand's probabilities.
2. **Builds the range.** At each Villain action, every combo's weight is multiplied by the probability that combo would have taken that action, so the range shown is exactly what the line implies.
3. **Predicts responses.** When Hero bets, the fold/call/raise frequencies come from the same function, applied to every combo in the range.
4. **Is the Play vs Bots bot**, sampled for the bot's real cards.

An improvement to that function improves all four; breaking its contract breaks the trainer.

## Contract

These names are used by the puzzle generator, grader, Play engine and stats. Their signatures and meaning must not change:

```python
# villain/strategy.py
action_distribution(profile: Profile, s: HandState) -> dict[Action, np.ndarray]
sample_action(profile, s, hole: tuple[int, int], rng) -> Action
bet_to(s, frac) -> Action;  raise_to(s, mult) -> Action;  allin(s) -> Action   # Hero sizing uses these too
role(s) -> str;  UnsupportedSpot;  HERO_PROFILE = "tag";  STRATEGY_VERSION
# villain/profiles.py
load_profile(name) -> Profile;  PROFILE_NAMES;  Profile.version
profile_data(name) -> dict;  profile_from_dict(name, raw) -> Profile   # Play sessions snapshot a profile
# villain/features.py
HandCategory;  range_features(board);  categorize(features, thresholds);  load_thresholds() (.version)
# villain/narrowing.py
RangeTracker(profile, seat).observe(s, action) / .steps / .current;  describe(action, s)
```

### Invariants (enforced by tests)

1. **The keys are canonical legal `Action`s**, the same objects `apply()` records. Keys that resolve to the same chips are merged, with their probabilities summed. `apply` rejects a CALL, FOLD or CHECK whose `to` amount isn't canonical.
2. **Each array is `(1326,)`.** For every combo not blocked by the board, the probabilities sum to 1. Board-blocked combos are 0 everywhere.
3. **Deterministic and pure.** The output depends only on `(profile, state)`: no hidden randomness, no global mutable state.
4. **Only use what Villain could know:** the betting line, the board, stacks and pot. **Never Hero's actual cards.** Hero's *range*, as implied by the line, is fine.
5. **Vectorised over all 1,326 combos.** The generator calls this function many times per puzzle. Cache per-board work, as `_row_index` and `range_features` already do.
6. **The pre-flop tree** supports only:
   - BTN opens or folds (no limps);
   - BB folds, calls or 3-bets, or calls/folds facing an open-jam;
   - BTN folds, calls or jams facing a 3-bet;
   - BB calls or folds facing a 4-bet jam.

   Anything else raises `UnsupportedSpot`, and the generator retries the hand. Play mode offers only this tree too.
7. **Jams are value-only.**
8. **No profile may fold NUTS.** STRONG must continue at least 0.93 facing a bet (the `facing_bet` row), and the loader refuses any STRONG facing row below `STRONG_CONTINUE_MIN` (0.75), because the overbet curve's STRONG floor assumes it.

The template explanations (M8) quote `narrowing.describe` labels and each profile's `label` and `description`, so changing those changes the Why text.

## Changing Villain

### Versions

- **Bump a profile's `version`** on any change to its JSON, and **`categories.json`'s `version`** on any threshold change. Stored puzzles keep the versions they were generated under; a custom bet size on an older puzzle is refused (409) once its versions differ. That is intended.
- **Bump `STRATEGY_VERSION`** in `strategy.py` by hand whenever the policy's behaviour changes. Each played hand stores it, and its analysis is labelled "Villain model has changed since this hand" when it differs.
- Play sessions store a snapshot of their profile's data and keep playing and analysing with it, so a profile change does not affect sessions already started.
- Attempts store Hero's hand category only when the puzzle's `categories_version` equals the live one. Keep `categorize`'s signature and the `HandCategory` names stable: the stats and the API's `CategoryCode` rely on them.

### Seeing the effect

- `uv run puzzle-sample --n 10 --profile tag` (in `backend/`) prints puzzles with Villain's line, the range size, Hero's equity and the EV of every Hero option in bb. If a ridiculous option grades as best, the cause is usually a Villain frequency. The grader discounts Hero's equity out of position before the river (puzzle `config.json`: 0.80 pre-flop, 0.88 flop, 0.94 turn), so judge tuning on the current config.
- The competence report (below).

### Checks to run

```bash
cd backend
uv run pytest -m "not slow"
uv run pytest -m slow tests/villain tests/analysis tests/puzzle   # includes test_bb_trash_3bet_not_best
uv run ruff check . && uv run ruff format --check .
uv run competence --profile all --hands 400 --seeds 0-5          # about 11 min
```

Paste the before and after competence tables into the PR.

## Competence report

`analysis/competence.py` checks 13 things per profile (plus 3 info lines) over 400 simulated hands against the TAG Hero. Since M9, all 52 checks pass on all six seeds 0–5 (312/312 check-seeds). Full tables: `docs/superpowers/reports/2026-11-13-m9-competence-signoff.md`.

| Check | Band | Meaning |
|---|---|---|
| bluff_share_33 / _75 | per profile | Share of 33% / 75% river bets that are bluffs. |
| defence_flop / turn / river | per profile | Continue rate facing a bet, divided by MDF = prior / (prior + call). |
| defence_overbet | per profile | The same, averaged over bets of 1.5×, 2× and 2.5× pot. |
| nuts_fold_max | 0 | Must be 0. |
| strong_fold_max | ≤ 0.10 | STRONG folds facing a bet of pot size or more. |
| air_call_max | ≤ 0.10 | Calls with air facing a river bet of 75% pot or more. |
| thin_value_dominated | ≤ 0.10 | Value bets that only better hands call. |
| raise_dominated | ≤ 0.10 | River value raises that only better hands continue against (ratio of sums). |
| cbet_flop | [0.45, 0.70] | Whole-range flop c-bet frequency. |
| preflop_defence_3bet | [0.90, 1.40], all profiles | BTN continue vs a 3-bet to 15, divided by MDF 0.50. Above 1 is expected: BTN is in position. |
| river_stab, air_continue_max, preflop_defence_open (info only) | — | River stab rate; air continuing; BB defence vs an open divided by MDF 4/7. |

`tests/puzzle/test_solve.py::test_bb_trash_3bet_not_best` (slow) checks that BB 3-betting trash (whole-range equity < 0.40) never beats the better of call/fold by more than 0.25 bb against any profile's BTN opens.

Bands live in each profile's `bands` block. **Don't widen a band just to make a check pass**; if a band looks wrong, argue it from the theory.

## Backlog

**Known weaknesses**
1. **Per-street tables.** Flop and turn share one unopened table; only the river has overrides (`river_unopened`, `river_facing`). Add `turn_unopened` or generalise to per-street overrides (e.g. double-barrel frequencies).
2. **MEDIUM raises a bet too often.** River raises are still about 2% of the range because STRONG is a broad category.
3. **Board texture is barely used.** The only rule is a 1.25× bet boost for draws on wet boards. Ideas: c-bet small more on dry boards, slow down on monotone boards, range advantage.
4. **Blockers.** AIR is one bucket; the spec mentions bluffing with and without blockers.
5. **Pre-flop ignores raise size.** BB defends the same range against a 2.5× and a 3× open, which is partly why Hero's pre-flop sizes are limited to 2.5×, 3× and all-in.
6. **Pre-flop tree.** No limps or small 4-bets (invariant 6). Widening it would widen Play mode too.
7. **Thin margins** listed in the sign-off report §9: LAG defence trending down past 2× pot, Sticky at 1.375 against the 1.40 pre-flop ceiling, over-defence against an uncapped BTN lead at pot or less.
8. **Heads-up only.** `street_spr` hard-codes heads-up seats; M12 (5-max) will need the policy and `RangeTracker` generalised.

**Ideas**
- **Modelling Hero:** track Hero's range with `RangeTracker(load_profile(HERO_PROFILE), hero_seat)` and adjust to it, respecting invariant 4. A real "adapt to the user" model would use the stored attempt history (`GET /api/stats`, `GET /api/history`).
- **Exploitative profiles** (maniac, calling station): need new bands and a decision against the spec's "competent; profiles vary style, not competence".
- **Solver comparison:** the best way to prove an improvement helps; listed as future work in the spec.

**Small tidy-ups**
- `_can_reraise` in `state.py` is effectively dead code under the effective-stack cap.
- `_rest` clips silently.
- `strong_fold_max` counts bets only, not raises; `air_call_max` counts calls only, not raises.
