# Handoff: improving the Villain "poker bot"

This is for working on the Villain model while the main line of work (M9, Phase 1 sign-off) continues on its own branch.

Repo: `spandan3/poker-puzzle-trainer` (private). The state described here is `main` after the M8 merge (2026-11-12). M3 (the puzzle generator and grader), M4 (API and storage), M5 (table UI), M6 (results view), M7 (progress) and M8 (explanations) are done. M9 (Phase 1 sign-off) is next.

## 1. What the project is

It's a puzzle trainer in the style of chess.com puzzles, for heads-up No-Limit Hold'em.
- Each puzzle drops Hero (the user) into a hand at a decision point.
- The user estimates equity, estimates what share of Villain's range they're ahead of, and picks an action.
- Code grades the action by EV against Villain's range.

The full design is in `docs/superpowers/specs/2026-11-10-poker-puzzle-trainer-design.md`. §5 covers the Villain and is the part that matters for you.

The **Villain** is a rule-based, probabilistic player, not a solver:
1. It sorts every one of the 1,326 possible hands into a **category** on the current board: AIR, WEAK_DRAW, WEAK, MEDIUM, STRONG_DRAW, STRONG, NUTS.
2. A **profile** (TAG, LAG, Tight, Sticky) gives each category a probability for each action in each spot. Example: a STRONG hand as c-bettor checks 12%, bets 33% pot 38% of the time, and bets 75% pot 50% of the time.
3. Adjustments are layered on top: a draw boost on wet boards, bet-size scaling when facing a bet, and the low-SPR "committed" rule.

### The key rule: one policy, used three ways

Everything goes through **one function**, `action_distribution(profile, state)` in `villain/strategy.py`. It does three jobs:
1. **Plays the hand.** Villain's real action is sampled from its real hand's probabilities.
2. **Builds the range.** At each Villain action, every combo's weight is multiplied by the probability that combo would have taken that action. The range shown to the user is exactly what the line implies.
3. **Predicts responses.** When Hero bets, the fold/call/raise frequencies come from the same function, applied to every combo in the range.

So any improvement you make to that function automatically improves all three. It also means **breaking its contract (§4) breaks the trainer**.

## 2. Setup (Windows or macOS)

```bash
# install uv first: https://docs.astral.sh/uv/
cd backend
uv sync
uv run pytest -m "not slow"            # fast suite, about 60 s, 636 tests
uv run pytest -m slow                  # slow cross-checks, about 10 min
uv run ruff check . && uv run ruff format --check .
uv run python -m poker_trainer.analysis.competence --profile all --hands 400   # about 2 min
```

## 3. Scope: what's yours, what's shared, what's off-limits

### Yours: edit freely

| Path (under `backend/`) | What it is |
|---|---|
| `src/poker_trainer/villain/profiles/{tag,lag,tight,sticky}.json` | Profile data: pre-flop ranges, unopened tables per role (`cbet` / `lead` / `stab`), facing tables (`facing_bet` / `facing_raise`), `river_unopened` overrides, competence `bands`. **Bump `version` on any change.** |
| `src/poker_trainer/villain/categories.json` | Category thresholds. **Bump `version` on any change.** |
| `src/poker_trainer/villain/strategy.py` | The policy. You may change its internals freely. Its public API is in §4. |
| `src/poker_trainer/villain/features.py` | Per-combo strength, beaten-by, outs, `categorize`, `board_texture`, `street_spr`. |
| `src/poker_trainer/villain/profiles.py` | The profile loader and validator. Extend the schema here, for example per-street tables. |
| `src/poker_trainer/analysis/competence.py` | The competence report. Add checks here. |
| `tests/villain/*`, `tests/analysis/*` | Their tests. |

### Shared: coordinate first, because M3 depends on these

| Path | Why |
|---|---|
| `src/poker_trainer/villain/narrowing.py` | Puzzles store the `RangeTracker` steps and the `describe` labels. |
| `src/poker_trainer/game/state.py` | The hand engine everything uses. Avoid changing it. If you must, keep every existing test passing. |
| `backend/pyproject.toml`, `uv.lock` | M4 added FastAPI, uvicorn, SQLAlchemy, Alembic and pydantic-settings. If you add a dependency, tell us. It must have wheels for Windows and macOS on Python 3.13. |

### Off-limits: the main line owns these

- `src/poker_trainer/engine/**` (equity engine)
- `src/poker_trainer/puzzle/**` (generator, solver, grader, `config.json`)
- the API, the database and migrations (`src/poker_trainer/api/**`, `db/**`, `settings.py`, `tests/api/**`, `tests/db/**`)
- the stats and leak rules (`src/poker_trainer/stats/**`, `tests/stats/**`, M7)
- the explanations and the LLM guardrail (`src/poker_trainer/explain/**`, `tests/explain/**`, M8). The template quotes the range-step labels from `narrowing.describe` and the profile `label` and `description`, so a change to those changes the Why text (the guardrail tests run on generated puzzles and catch numbers that aren't facts).
- `tests/engine/**`, `tests/puzzle/**`
- the frontend (`frontend/**`, at the repo root)
- `docs/superpowers/**` (plans and spec)

You can still *use* the puzzle code to see your changes in action (§6).

## 4. The contract you must keep

M3 calls these names. Their signatures and meaning must not change:

```python
# villain/strategy.py
action_distribution(profile: Profile, s: HandState) -> dict[Action, np.ndarray]
sample_action(profile, s, hole: tuple[int, int], rng) -> Action
bet_to(s, frac) -> Action;  raise_to(s, mult) -> Action;  allin(s) -> Action   # Hero sizing uses these too
role(s) -> str;  UnsupportedSpot;  HERO_PROFILE = "tag"
# villain/profiles.py
load_profile(name) -> Profile;  PROFILE_NAMES;  Profile.version
# villain/features.py
HandCategory;  range_features(board);  categorize(features, thresholds);  load_thresholds() (.version)
# villain/narrowing.py
RangeTracker(profile, seat).observe(s, action) / .steps / .current;  describe(action, s)
```

Invariants that tests enforce. Keep all of them true:
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

   Anything else raises `UnsupportedSpot`, and the generator retries the hand. Extending the tree is welcome; just keep that behaviour for whatever stays unsupported.
7. **Jams are value-only.**
8. **No profile may fold NUTS.** STRONG must continue at least 0.93 facing a bet (the `facing_bet` row).

Old puzzles are frozen with the `profile_version` they were generated under. That's why every data change needs a version bump.

## 5. Current status

M1 (equity engine), M2 (game state plus Villain), M3 (puzzles and grader), M4 (API and storage), M5 (table UI), M6 (results view), M7 (progress) and M8 (explanations) are done and reviewed.

Roadmap (2026-11-12, M1–M8 done): M9 Phase 1 sign-off → M10 Play vs Bots heads-up → M11 UI polish → M12 Play vs Bots 5-max (play) → M13 5-max analysis. See `docs/superpowers/plans/2026-11-10-roadmap.md`.

**Play vs Bots (M10) matters for Villain work:** the bot in that mode *is* the Villain policy (`action_distribution`, sampled for the bot's real cards), so every tuning change shows up in live play too (spec: `docs/superpowers/specs/2026-11-12-play-vs-bots-design.md`). M10 will add `STRATEGY_VERSION` to `strategy.py`: once it exists, bump it by hand whenever the policy's behaviour changes, as you already do for profile and `categories.json` versions. Play mode only offers the supported pre-flop tree (no limps, no small 4-bets); widening that tree is a welcome future Villain task, listed under "Later" in the roadmap.

M4 note for Villain work: custom bet sizes on a stored puzzle are refused (409) once its profile or `categories.json` version changes, so version bumps are still the right way to change data.

M7 note for Villain work: each attempt now stores Hero's own hand category (`stats/hero.py`, via `categorize` and `categories.json`). It is stored only when the puzzle's `categories_version` equals the live one, so after a `categories.json` bump, answers to older puzzles store no category (they drop out of the "draws" leak rule). Keep `categorize`'s signature and the category names (`HandCategory`) stable; the stats and the API's `CategoryCode` rely on them.

The competence report checks 10 things per profile over 400 simulated hands against the TAG Hero (seed 0). All 40 checks pass:

| Check | TAG | LAG | Tight | Sticky | Meaning |
|---|---|---|---|---|---|
| bluff_share_33 | 0.258 | 0.248 | 0.172 | 0.229 | Share of 33% river bets that are bluffs. Target is near f/(1+2f) ≈ 0.20, plus a profile offset. |
| bluff_share_75 | 0.297 | 0.328 | 0.184 | 0.266 | The same for 75% bets. Target is near 0.30. |
| defence_flop / turn / river | 0.92 / 1.03 / 0.90 | 0.95 / 1.07 / 0.96 | 0.86 / 0.96 / 0.89 | 1.05 / 1.18 / 1.06 | How often Villain continues facing a bet, divided by minimum defence frequency 1/(1+f). |
| nuts_fold_max | 0 | 0 | 0 | 0 | Must be 0. |
| strong_fold_max | 0.041 | 0.028 | 0.071 | 0.028 | Facing a bet of pot size or more. Must be ≤ 0.10. |
| air_call_max | 0.071 | 0.049 | 0.023 | 0.058 | Calls with air facing a river bet of 75% pot or more. Must be ≤ 0.10. |
| thin_value_dominated | 0.060 | 0.061 | 0.028 | 0.071 | Value bets that only better hands call. Must be ≤ 0.10. |
| cbet_flop | 0.566 | 0.635 | 0.513 | 0.541 | Whole-range flop c-bet frequency, in [0.45, 0.70]. |
| river_stab (info only) | 0.319 | 0.381 | 0.286 | 0.333 | How often Villain bets the river when checked to. |

The bands live in each profile's `bands` block. **Don't widen a band just to make a check pass.** If a band looks wrong, argue the case from the theory.

## 6. What to improve, with the highest value first

**How to see the effect of a change on real puzzles:** the generator and grader are built now. `uv run puzzle-sample --n 10 --profile tag` prints puzzles: Villain's line, Hero's cards, the board, the range size, Hero's equity, and the EV of every Hero option in bb. Each option's EV comes from your strategy's fold, call and raise responses. If a ridiculous option grades as best, the cause is usually a Villain frequency.

**Found by the M3 review (fix these first). They make the grader teach the wrong lesson:**
1. **TAG calls huge river jams too wide.** On a monotone river, TAG called a 2.5×-pot jam with about 55% of its range, so Hero jamming two pair graded as best. To fix it, have `facing_bet` continue less against big sizes for MEDIUM and WEAK hands: tighten their base rows, or steepen the size curve in `_facing`. Then add a competence check on the continue rate against bets of 2× pot or more.
2. **BTN over-folds to 3-bets.** From the BB, 3-betting trash like 23o, 35o and 75o grades as best by 0.6–1.3bb, so Villain BTN's `btn_call_threebet` + `btn_jam` is too narrow against a 3-bet. Check it against the minimum defence frequency, MDF = 1/(1+f), where f = call ÷ (pot before the call − call):
   - A 3-bet to 15 against BTN's open to 5: BTN calls 10 into 10, so f = 1 and BTN should continue about 50% of its opening range.
   - A 3-bet to 12: f = 0.7, so BTN should continue about 59%.

   Consider adding a pre-flop defence check to `competence.py`.

**Known weaknesses:**
1. **Per-street tables.** Flop and turn share one unopened table. Only the river has overrides, through `river_unopened`. Real players play turns differently, for example double-barrel frequencies. You could add `turn_unopened`, or generalise to per-street overrides.
2. **MEDIUM raises a bet too often** in the `facing_bet` tables. No check measures this yet. Add a "raises are dominated" check, like `thin_value_dominated` but for raises, then tune.
3. **STRONG folds about 34% to huge over-jams** of about 20× pot. That falls out of the size-scaling formula `continue = base ** ((1+f)/1.5)` in `_facing`. Consider a floor for STRONG, or a different curve.
4. **Board texture is barely used.** The only texture rule is a 1.25× bet boost for draws on wet boards. Ideas:
   - on dry boards, c-bet small more often;
   - on monotone boards, slow down;
   - adjust for how the board connects with each player's range (range advantage).
5. **Blockers.** The spec mentions "air with/without blockers". AIR is one bucket today. Bluffing with nut-flush blockers, for example, would be more realistic.
6. **Pre-flop ignores raise size.** For example, BB defends the same range against a 2.5× open and a 3× open. Hero's pre-flop sizes are limited to 2.5×, 3× and all-in partly for this reason.
7. **Thin margins.** Some checks are close to their band edges:
   - TAG `bluff_share_33` is 0.258 against an upper edge of 0.28;
   - Tight `cbet_flop` is about 0.50 against a lower edge of 0.45;
   - Sticky `thin_value_dominated` reaches 0.077 at seed 1.

   Making these robust across seeds 0–5 would be good.

**New factors you suggested:**
- **Modelling Hero.** Villain could track Hero's range with `RangeTracker(load_profile(HERO_PROFILE), hero_seat)` and adjust to it, for example calling wider when Hero's line is bluff-heavy, or using range-versus-range equity. This must respect invariant 4: Hero's range, never Hero's cards.
  - Caveat: the trainer's Hero policy is always TAG today. A real "adapt to the user" model needs the user's history: since M7 every first attempt is stored with its verdict, action, street, profile and guesses (`GET /api/stats`, `GET /api/history`), but Hero's puzzle actions are still generated by the TAG policy.
- **Exploitative profiles**, such as a maniac or a calling station. These need new bands and, if they're meant to be bad on purpose, a decision on whether they fit the spec. The spec says "competent, profiles vary style, not competence".
- **Solver comparison.** This is the best way to prove an improvement helps. The spec lists it as future work.

**Smaller tidy-ups** found in reviews and parked:
- `_can_reraise` in `state.py` is effectively dead code under the effective-stack cap.
- `street_spr` hard-codes heads-up seats.
- `_rest` clips silently.
- `strong_fold_max` counts bets only, not raises.
- `air_call_max` counts calls only, not raises.

## 7. How to work in parallel

1. Branch from `main`: `git checkout main && git pull && git checkout -b villain/<topic>`. Example: `villain/per-street-tables`.
2. Make small, focused commits. **We never squash: every commit is preserved on merge.**
3. Before you push, run all of these:
   - `uv run pytest -m "not slow"`
   - `uv run pytest -m slow tests/villain tests/analysis`
   - `ruff check` and `ruff format --check`
   - the competence report for all profiles
4. Paste the before and after competence tables into the PR description.
5. Open a PR into `main`. CI runs the fast suite on Windows and macOS. The slow suite runs on `main` after merge.
6. If you change behaviour the puzzle code relies on (§4), say so in the PR so the main line can rebase on it deliberately.
7. Profile version bumps: saved puzzles keep their old `profile_version`. Grading a custom bet size on an older puzzle raises "profile changed since this puzzle was generated". This is intended. Just bump the version on every data change.

**Rule of thumb:** data and tuning changes plus new checks never conflict with the main line. Changing a public signature does.
