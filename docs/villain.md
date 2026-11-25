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

## 5-max

Heads-up play is unchanged by M12. Five-seat bots (Play mode, `table_size` 5) use the same post-flop tables with a multiway damping step, and a separate pre-flop policy driven by two data files in `villain/`.

### Hand ranking (`villain/hand_ranking.json`)

`{"version": 1, "classes": [...169 labels, strongest first...]}`. It is generated by `poker_trainer.analysis.hand_ranking` (`cd backend && uv run python -m poker_trainer.analysis.hand_ranking`, or `--check` to compare only). Strength is all-in equity against one random hand: 50,000 samples per class (a random villain hand and board), seeded `random.Random("hand-ranking:<label>")`, ties broken by label. The output depends on CPython's `random.sample`, so it is stable with one uv lock. Buckets are slices of the 1326 combos in this order; a class that straddles a bucket boundary gets a **fractional weight**, so a profile's percentages are exact.

### Per-profile percentages (`villain/fivemax.json`)

`{"version", "bb_call_mult", "damping": {"bluff", "thin", "call"}, "profiles": {...}}`. Each of `tight`, `tag`, `lag`, `sticky` has `open` (UTG, CO, BTN, SB), `vs_open` (`threebet`, `call`), `vs_threebet` (`jam`, `call`) and `vs_jam` (`call`), all percentages of the 1326 combos. "3-bet t%, call c%" means the top t% 3-bet and the next c% call. The big blind's call % is `call × bb_call_mult` (1.6), capped so that the 3-bet and call buckets together are at most 100%. Loading is strict: exact keys at every level, type checks, profile names from `PROFILE_NAMES`, a block for every profile.

### Pre-flop routing (`villain/preflop5.py`)

`action_distribution` sends pre-flop states with exactly five seats to `preflop5` (3, 4 and 6 seats raise `UnsupportedSpot`). The spot depends on `r`, the number of `RAISE`s pre-flop:

- **Facing a jam** (checked first): no raise is legal, a pre-flop raiser is all-in, or `r >= 3`. Fold or call with `vs_jam.call`. This holds for bots and Hero, and it makes every later spot fold/call.
- `r == 0`: fold or open (2.5 bb, or 3 bb from the SB), by position.
- `r == 1`: fold, call, or 3-bet to `(3 + callers) × the open`.
- `r == 2`: fold, call or jam.

No limps and no small 4-bets: every 4-bet is all-in (invariant 6 still holds). A limped pot (a call before any raise) raises `UnsupportedSpot`, and so does a big blind "open" raise (the BB cannot open: no position row for it).

### Multiway damping (`villain/strategy.py`)

`k` is the number of live opponents minus one, **counting all-in opponents** (a bluff must still get through an all-in player's main pot). Heads-up `k = 0`, and damping is then a no-op by construction. The constants come from `fivemax.json` `damping`.

- Damping is applied to the **category matrix** inside `_unopened` and `_facing`, **before** the "no raise legal: raise moves to call" merge. A test pins this order (facing a jam, a bluff category calls `(call0 + raise0 × bluff^k) × call^k`; moving the damping after the merge fails it).
- `_unopened`, after the river override and the draw boost: the bet columns of `AIR`, `WEAK_DRAW`, `WEAK` are multiplied by `bluff^k` and those of `MEDIUM` by `thin^k`; the removed mass goes to check. `STRONG_DRAW`, `STRONG` and `NUTS` are untouched.
- `_facing`, after the continue curve: `MEDIUM`'s raise moves to call; the raise column of `AIR`, `WEAK_DRAW`, `WEAK` is multiplied by `bluff^k`; then the call and raise of every row below `STRONG` (`AIR`, `WEAK_DRAW`, `WEAK`, `MEDIUM`, `STRONG_DRAW`) are multiplied by `call^k`; the removed mass goes to fold. When `street_spr <= 1` the `_COMMITTED` rows (`MEDIUM`, `STRONG_DRAW`, `STRONG`, `NUTS`) are skipped, `MEDIUM`'s raise-to-call step included (the low-SPR step then handles them as heads-up).
- `action_distribution` and `sample_action` take keyword `fivemax` and `damping` (None reads the live file; `k = 0` never reads it). When `fivemax` is passed, `damping` defaults to `fivemax.damping`; play passes each seat's snapshot.

### Per-seat snapshots

Each bot seat is stored in `play_sessions.seats` as `SeatBot.to_dict()`: its profile, the profile data and a one-profile slice of `fivemax.json` (`version`, `bb_call_mult`, `damping`, the profile's block). Every `advance_seats` / `hero_act_seats` call rebuilds it with `SeatBot.from_dict` (strict validation; the rebuilds happen in `play_service._seat_bots`), so editing a data file never changes a stored hand's replay. `hand_ranking.json` is not snapshotted; it is only version-stamped in `play_hands.bot_versions` (`hand_ranking` is the live version; `fivemax` is the version of the seat snapshots the hand was played with, not of the live file).

### Version rules

- A change to 5-max behaviour bumps `version` in `fivemax.json` or `hand_ranking.json`. **`STRATEGY_VERSION` stays 1**: heads-up is unchanged, and a bump would flag every stored heads-up analysis as "model changed".
- Regenerate `hand_ranking.json` only with its script, and bump its `version` if the order changes: the version is `VERSION` in `analysis/hand_ranking.py` (the script writes it into the file).
- Heads-up must stay byte-identical: the pins in `tests/villain/test_hu_pins.py` (a fast subset runs by default; the all-states and regenerate tests are slow) and the replay digest `test_heads_up_hands_replay_exactly_as_before_m12` guard it.

## Backlog

**Known weaknesses**
1. **Per-street tables.** Flop and turn share one unopened table; only the river has overrides (`river_unopened`, `river_facing`). Add `turn_unopened` or generalise to per-street overrides (e.g. double-barrel frequencies).
2. **MEDIUM raises a bet too often.** River raises are still about 2% of the range because STRONG is a broad category.
3. **Board texture is barely used.** The only rule is a 1.25× bet boost for draws on wet boards. Ideas: c-bet small more on dry boards, slow down on monotone boards, range advantage.
4. **Blockers.** AIR is one bucket; the spec mentions bluffing with and without blockers.
5. **Pre-flop ignores raise size.** BB defends the same range against a 2.5× and a 3× open, which is partly why Hero's pre-flop sizes are limited to 2.5×, 3× and all-in.
6. **Pre-flop tree.** No limps or small 4-bets (invariant 6). Widening it would widen Play mode too.
7. **Thin margins** listed in the sign-off report §9: LAG defence trending down past 2× pot, Sticky at 1.375 against the 1.40 pre-flop ceiling, over-defence against an uncapped BTN lead at pot or less.
8. **5-max has no analysis yet** (M13). `RangeTracker` and the grader are still heads-up.

**5-max (M14)**
9. **The ranking ignores playability.** Equity against a random hand ranks small pairs and offsuit broadway-ish hands above suited connectors (TAG opens J9o and K8o on the BTN but not 22 or 76s), and close neighbours are in sampling-noise order (±0.2%).
10. **Few multiway flops.** BB defence (`vs_open.call` × 1.6 = 11 to 29%) and overcalls are narrow: about 5% of hands (bots only) and about 14% of flops (random Hero) are multiway.
11. **Hero's 3-bet sizes** are 2.5x / 3x of the open, while bots squeeze to (3 + callers) × the open. Add the bot size to Hero's menu.
12. **No limps and no small 4-bets** for Hero or bots (every 4-bet is a jam).
13. **Tuned multiway tables** should replace the damping factors (`bluff`, `thin`, `call`), which are a first approximation.

**Ideas**
- **Modelling Hero:** track Hero's range with `RangeTracker(load_profile(HERO_PROFILE), hero_seat)` and adjust to it, respecting invariant 4. A real "adapt to the user" model would use the stored attempt history (`GET /api/stats`, `GET /api/history`).
- **Exploitative profiles** (maniac, calling station): need new bands and a decision against the spec's "competent; profiles vary style, not competence".
- **Solver comparison:** the best way to prove an improvement helps; listed as future work in the spec.

**Small tidy-ups**
- `_can_reraise` in `state.py` is effectively dead code under the effective-stack cap.
- `_rest` clips silently.
- `strong_fold_max` counts bets only, not raises; `air_call_max` counts calls only, not raises.
