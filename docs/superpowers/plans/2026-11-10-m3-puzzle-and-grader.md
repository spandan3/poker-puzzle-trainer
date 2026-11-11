# M3 Puzzle Generator and Grader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate realistic, non-trivial heads-up puzzles whose frozen state includes Villain's range at every step. Grade any Hero answer by EV loss against that range, with the maths exposed for the results view.

**Architecture:**
- `poker_trainer.engine.equity` gains `ComboEquity`, a per-combo equity table. It is exact on the turn and river, and comes from one Monte Carlo run pre-flop and on the flop. It can be re-weighted to any sub-range: the calling range, the checking-back range, and so on.
- `poker_trainer.puzzle` holds four modules:
  - `model`: frozen dataclasses and a JSON round-trip.
  - `options`: Hero's legal options.
  - `solve`: the EV of every option.
  - `grade`: verdicts and scores.
- It also holds `generate`, which plays hands forward with the M2 strategy for both seats, freezes the spot, solves it and filters trivial spots.

**Tech Stack:** Python 3.13, numpy, pytest, hypothesis, uv. Builds on M1 `engine`, M2 `game` and `villain`.

**Spec:** `docs/superpowers/specs/2026-11-10-poker-puzzle-trainer-design.md` (§4 options, §5 one policy, §7 generation, §8 grading, §12 accuracy). Roadmap: `docs/superpowers/plans/2026-11-10-roadmap.md`. M2 hand-over items: the "Open items for M3" section of `docs/superpowers/plans/2026-11-10-m2-game-and-villain.md`.

## Global Constraints

- Chips are ints internally (SB 1, BB 2, stacks 200). Every EV is computed in chips. `ev_bb = ev_chips / 2`.
- EVs are relative to folding: fold = 0 (spec §8).
- **Displayed ≡ graded.** Every number in a `Solution` is computed from the `Spot.range` array, and `Spot.range` is exactly what the UI shows. Removing blocked combos happens in one helper only, `visible_range`.
- **One policy.** Villain's responses come only from `action_distribution` on the post-action state. The only exception is tests, which inject `respond` explicitly. There is no second copy of frequencies.
- **Canonical actions only.** Use distribution keys, `history[-1]` after `apply`, or the sizing helpers `bet_to`, `raise_to`, `allin`. `apply` rejects CALL, FOLD and CHECK actions whose `to` is not canonical.
- **Supported pre-flop tree only.**
  - Hero opens 2.5x or 3x, 3-bets 2.5x or 3x, calls, folds or goes all-in.
  - There is no limp and no 4-bet that is not all-in.
  - `UnsupportedSpot` while generating means "try again".
- Store puzzles, not seeds. Replays read the frozen JSON and never regenerate.
- No LLM. Deterministic for a given seed: one `random.Random(seed)` stream drives everything. Works on Windows and macOS. Commands run from `backend/`.

## Decisions made in this plan

- **Equity on sub-ranges.**
  - `ComboEquity` stores three arrays per combo: `wins`, `ties` and `count`.
  - MC (pre-flop and flop) draws combos in proportion to the base range `D`, with `r_c = w_c / D_c`.
  - On the turn and river (exact), `wins` and `ties` are the per-combo fractions, `count = 1` on live combos, and `r_c = w_c`.
  - `vs(w)` computes `win = Σ r·wins / Σ r·count` and `tie` the same way, then `equity = win + tie/2`. With r ≡ 1 this is bit-identical to today's `equity_vs_range`, which becomes `combo_equity(...).vs(villain)`; `rng.choices` over the index list consumes the RNG exactly as it does now.
  - MC: `std_error = sqrt(p(1−p)/n_eff)` with `n_eff = (Σ r·count)² / Σ r²·count` (Kish). This is a self-normalised importance estimate: consistent, not unbiased; fine at 40k samples.
  - A sub-range whose positive-weight combos were never sampled (`Σ r·count == 0`) raises `UnsampledRange` (a `ValueError`). `solve` then falls back to `equity_vs_range(hero, board, w, rng=random.Random(0), samples=samples // 4)`. The seed is fixed, so it stays deterministic.
- **Visible range:** `visible_range(r, hero, board) = remove_blocked(r, hero + board)`. All range steps use the decision-time board and Hero's cards ("what Villain can hold, given what Hero sees now").
- **Option EVs.** `P = total_pot(s)` at the decision. `put = action.to − street_bets[hero]` for a call, bet or raise.
  - Fold: 0.
  - Call: `eq·(P + put) − put`. Before the river this is the full-realisation simplification.
  - Bet/raise: `s2 = apply(s, action)`, Villain distribution `d = respond(s2)`. Let `|x| = Σ x`.
    - `F = |D·fold| / |D|`.
    - Calls: `C = D·call`, `vcall = legal_actions(s2).call`, value `eq(C)·(P + put + vcall) − put`.
    - Each Villain raise key `R`: `s3 = apply(s2, R)`, `c = legal_actions(s3).call`, `final = total_pot(s3) + c`. Hero replies with the better of folding or calling, with no further raise: value `max(−put, eq(D·d_R)·final − (put + c))`.
    - `EV = F·P + Σ_k (|D·d_k| / |D|)·value_k` over the call and raise keys.
    - The continuing range `C_all = D·(1 − fold)`. If `|C_all| = 0`, then `EV = P`.
  - Check, when it closes the action (IP check-back): `eq·P`. Before the river it is labelled.
  - Check out of position on the river: `s2 = apply(s, check)`, `d = respond(s2)`. `EV = Σ_k (|D·d_k| / |D|)·v_k`, where:
    - for the check-back key, `v = eq(D·d)·P`;
    - for each Villain bet key with chips `b = to − 0`, `v = max(0, eq(D·d)·(P + 2b) − b)`. Hero's best response is fold or call.
  - Check out of position before the river: `eq·P` (labelled).
- **Simplification codes**, each a stable string with fixed English text in `model.SIMPLIFICATIONS`:
  - `realisation` — "Before the river, Hero is assumed to realise full equity."
  - `reraise_reply` — "After a Villain re-raise, Hero only folds or calls."
  - `preflop_size` — "Pre-flop, Villain's responses don't depend on Hero's raise size."
- **Profile notes deferred to M6:** STRONG folds about 34% to big jams, MEDIUM raises often, and how often Villain bets the river when checked to. M6 shows these as per-profile notes; they are not per-option codes.
- **Verdict:** the loss is `best_ev − chosen_ev` in chips.
  - **Best** if loss ≤ 0.5 chips (0.25bb) or ≤ 2% of P.
  - **Fine** ≤ 10% of P. **Mistake** ≤ 25% of P. Otherwise **Blunder**.
  - All thresholds live in `puzzle/config.json`.
- **Scores:** equity error (absolute, in fractions): ≤ 0.05 is great, ≤ 0.10 is good, otherwise off. The range read is scored the same way against `ahead_now(hero, board, D)`; there is no range read on the river.
- **Intent** applies only to bets and raises. The truth is decided like this:
  - `value` if Hero's ahead-now share of the continuing range is ≥ 0.5. On the river, ahead-now means equity vs C.
  - Otherwise `semi_bluff` if the street is before the river and eq(C) ≥ 0.30.
  - Otherwise `bluff`.
  - A mismatch is flagged with a message. It never changes the verdict.
- **Bluff check** applies to bets and raises: the required fold equity is `put / (P + put)`, compared with F.
- **Street and profile** are drawn once per `generate_puzzle` call, not per attempt. Otherwise the delivered mix drifts toward the streets and profiles that succeed most often.
- **Decision point.** Play forward with Hero's TAG policy and the Villain profile. At each Hero turn on the target street, stop with probability `stop_prob` (0.6). If the target street ends, or the hand ends, without a stop, retry.
  - Street weights: pre-flop 0.15, flop 0.30, turn 0.30, river 0.25.
  - The profile is uniform over `PROFILE_NAMES` unless one is given.
- **Trivial filter.** Reject the puzzle when any of these holds:
  - equity > 0.92 or < 0.04;
  - every option is within the "Best" margin of the best one;
  - the best option beats the second best by > 50% of P, and equity is > 0.85 or < 0.10.
- **Custom sizes** are allowed only after the flop. `evaluate_action` scores any legal post-flop bet or raise. Before the flop, only the listed options are accepted.
- **Performance:** one MC run per puzzle (40k samples), reused for every option. The reviewer measured about 0.15 s for flop MC and 0.24 s pre-flop. The target is a mean under 3 s per puzzle. The slow test asserts < 6 s, which leaves headroom for CI runners, and prints the mean.
- **Determinism** is per platform: `np.power` in the strategy uses the C maths library. Never pin a cross-platform golden puzzle dict. Test determinism as "same seed twice on the same machine".
- **Hero post-flop options:**
  - Unopened: check, bet 33%, bet 50%, bet 75%, bet 100%, all-in.
  - Facing a bet or raise: fold, call, raise 2.5x, raise 3x, all-in.
  - Duplicates are merged.
- Dataclasses holding ndarrays use `@dataclass(frozen=True, eq=False)`; tests compare them field by field.

## Review Focus

1. **Hero or Villain all-in.** When Hero's bet is all-in, Villain only folds or calls. When Villain is already all-in, Hero has no bet option. Options that resolve to the same chips are merged, and the all-in label wins. Tests in Task 2 and Task 3.
2. **Villain never continues** (C = 0) **or always continues** (F = 0). There must be no NaN, and EV = P or the pure call-down formula. Test in Task 3.
3. **River out-of-position check where Villain always bets, or always checks.** The look-ahead sums correctly, and Hero's response is floored at fold (0). Test in Task 3.
4. **Pre-flop BTN first in** offers no call (limp). **BTN facing a 3-bet** offers only fold, call and all-in. Test in Task 2.
5. **JSON round-trip:** `Range` arrays, the `Street` and `ActionKind` enums and tuples survive `puzzle_to_dict` → `json.dumps` → `json.loads` → `puzzle_from_dict` with equality. Test in Task 2.

---

### Task 1: Per-combo equity table (`ComboEquity`) — Opus

**Files:** Modify `backend/src/poker_trainer/engine/equity.py`. Test: `backend/tests/engine/test_combo_equity.py`.

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True, eq=False) class ComboEquity: hero: tuple[int,int]; board: tuple[int,...]; base: np.ndarray; wins: np.ndarray; ties: np.ndarray; count: np.ndarray; exact: bool`.
  - `class UnsampledRange(ValueError)`.
    - The arrays are `(1326,)` and read-only.
    - The class has `vs(self, weights: Range) -> EquityResult`.
  - `combo_equity(hero, board, villain: Range, *, rng: random.Random | None = None, samples: int = 40_000) -> ComboEquity`.
  - `equity_vs_range` is unchanged in signature and is reimplemented as `combo_equity(...).vs(villain)`.
- `vs` rules:
  - Weights on combos blocked by Hero or the board are ignored.
  - A positive weight on an unblocked combo where `base == 0` raises `ValueError("weights outside base range")`.
  - MC with `Σ r·count == 0` raises `UnsampledRange`.
  - All-zero weights raise `ValueError("empty range")`.
  - Win and tie are reported in the same way as `equity`.
- [ ] **Step 1: Failing tests**
  - `test_vs_base_matches_equity_vs_range`: on a flop, with the same seed, `combo_equity(...).vs(D)` equals the pre-change `equity_vs_range` value exactly, for equity, win and tie. Record the pre-change value in the test first.
  - `test_river_exact_subrange`: on board `Ks7h2c4d9s`, Hero `KhQh`, D = {AsKd: 1, JcTc: 1}. Check that `vs(D).equity == 0.5`, `vs({AsKd}).equity == 0.0`, `vs({JcTc}).equity == 1.0`, and that `exact` is True.
  - `test_turn_exact_matches_equity_by_combo`.
  - `test_flop_subrange_within_4se`: on a flop, check `vs(D·mask)` against the exact flop reference in `tests/reference/exact_flop.py`, for a mask that keeps about half the range, to within 4·`std_error`.
  - `test_outside_base_raises`. `test_unsampled_subrange_raises`: build a ComboEquity with a weight-1e-9 combo, then `vs` on that combo alone. `test_n_eff_shrinks_for_subrange`: the SE for the subrange is greater than the SE for the base.
  - Existing tests `tests/engine/*` pass unchanged.
- [ ] **Step 2:** Run the new tests → FAIL. **Step 3:** Implement. Refactor the MC loop to accumulate per-combo outcomes; don't change the draw order. **Step 4:** `uv run pytest -m "not slow" -q tests/engine` and the slow equity tests → PASS.
- [ ] **Step 5:** Commit `feat(engine): per-combo equity table re-weightable to sub-ranges`.

### Task 2: Puzzle model and Hero options — Sonnet

**Files:** Create `backend/src/poker_trainer/puzzle/__init__.py`, `model.py`, `options.py` and `config.json`. Tests: `backend/tests/puzzle/test_model.py`, `test_options.py`.

**Interfaces** (`poker_trainer.puzzle.model`):
- `SIMPLIFICATIONS: Mapping[str, str]`, using the three codes and texts above.
- `@dataclass(frozen=True) class Option: label: str; action: Action`.
  - Labels: `"fold"`, `"check"`, `"call"`, `"bet 33%"`, `"bet 50%"`, `"bet 75%"`, `"bet 100%"`, `"raise 2.5x"`, `"raise 3x"`, `"all-in"`, or `"bet N"` / `"raise to N"` for custom sizes.
- `@dataclass(frozen=True) class RangeView: label: str; street: Street; range: Range`.
- `@dataclass(frozen=True) class Spot` with these fields:
  - `seed: int`, `attempt: int`, `state: HandState`, `hero_seat: int`, `hero: tuple[int,int]`, `villain_hole: tuple[int,int]`
  - `runout: tuple[int,...]` (all 5 board cards), `profile: str`, `profile_version: int`, `categories_version: int` (from `load_thresholds().version`)
  - `steps: tuple[RangeView, ...]`; the property `range` returns `steps[-1].range`
- `@dataclass(frozen=True) class OptionEV` with these fields:
  - `option: Option`, `ev_chips: float`, `fold_freq: float | None`
  - `equity_vs_continue: float | None`, `ahead_vs_continue: float | None`
  - `equity_vs_continue_se: float | None`, `required_fold_equity: float | None`, `put: int`
  - `continue_range: Range | None` (D·(1 − fold) for bets and raises; the "which hands continue" grid)
  - `branches: tuple[Branch, ...]` — the look-ahead terms for the step-by-step maths
  - `simplifications: tuple[str, ...]`
  - the property `ev_bb`
- `@dataclass(frozen=True) class Branch: label: str; share: float; equity: float | None; value_chips: float`. Labels include "Villain folds", "Villain calls", "Villain raises to N — Hero calls/folds", "Villain checks back" and "Villain bets N — Hero calls/folds".
- `@dataclass(frozen=True) class CategoryRow: category: str; share: float; ahead: float; equity: float` gives, per Villain hand category (post-flop), the share of D, Hero's ahead-now share within that category (equity on the river) and Hero's equity.
- `@dataclass(frozen=True) class Solution` with these fields:
  - `equity: float`, `equity_std_error: float`, `equity_exact: bool`, `ahead_now: float | None`, `pot_odds: float`
  - `options: tuple[OptionEV, ...]`, `best: int`, `combo_equity: ComboEquity`
  - `category_breakdown: tuple[CategoryRow, ...] | None` (None pre-flop), `simplifications: tuple[str, ...]`
- `@dataclass(frozen=True) class Puzzle: spot: Spot; solution: Solution`.
- `puzzle_to_dict(p) -> dict` (JSON-safe; ranges as lists of floats) and `puzzle_from_dict(d) -> Puzzle`. Include `"format": 1`.
- `visible_range(r: Range, hero, board) -> Range` (read-only result).

**Interfaces** (`poker_trainer.puzzle.options`):
- `hero_options(s: HandState) -> tuple[Option, ...]`, in a stable order: fold, check, call, then bets or raises from smallest to largest, then all-in.
  - Merge options that resolve to the same `Action`. The label `"all-in"` wins when `to == legal.max_to`; otherwise the first label is kept.
  - Pre-flop restrictions follow Global Constraints:
    - BTN first in: fold, raise 2.5x, raise 3x, all-in.
    - BB facing an open: fold, call, raise 2.5x, raise 3x, all-in.
    - BTN facing a non-all-in 3-bet: fold, call, all-in.
    - Facing a jam: fold, call.
- `custom_action(s, to: int) -> Action`. Post-flop only. It returns a validated BET or RAISE `Action`, or raises `ValueError`.

**`config.json`:** `version: 1`; `street_weights`; `stop_prob`; `samples: 40000`; `verdict: {best_bb: 0.25, best_pot: 0.02, fine_pot: 0.10, mistake_pot: 0.25}`; `score: {great: 0.05, good: 0.10}`; `trivial: {eq_hi: 0.92, eq_lo: 0.04, gap_pot: 0.5, gap_eq_hi: 0.85, gap_eq_lo: 0.10}`; `max_attempts: 200`. Add a loader `load_config() -> PuzzleConfig` (frozen) in `model.py`.

- [ ] **Step 1: Failing tests**
  - `test_btn_first_in_options`: on `new_hand(0)` the labels are `["fold","raise 2.5x","raise 3x","all-in"]`, the raise `to` values are 5 and 6, and the all-in `to` is 200.
  - `test_bb_vs_open_options` (after BTN raises to 5): the labels are `["fold","call","raise 2.5x","raise 3x","all-in"]`, with `to` values 12 and 15.
  - `test_btn_vs_3bet_options`: `["fold","call","all-in"]`. `test_facing_jam_options`: `["fold","call"]`.
  - `test_postflop_options_merge_allin`: with a short stack, `bet 75%` and `bet 100%` both reach the all-in threshold. Only one `"all-in"` remains, and every option `apply`s cleanly.
  - `test_custom_action_rejected_preflop`.
  - `test_round_trip`: build a `Puzzle` with a 2-step `Spot`, a dummy `Solution` with one `Branch`, a `CategoryRow` and a `continue_range`, and a small `ComboEquity`. Check that `puzzle_from_dict(json.loads(json.dumps(puzzle_to_dict(p))))` equals the original field by field, with arrays compared using `np.array_equal`.
  - `test_visible_range_removes_hero_and_board`.
- [ ] **Steps 2–4:** fail → implement → pass (`uv run pytest -q tests/puzzle`; ruff clean).
- [ ] **Step 5:** Commit `feat(puzzle): frozen puzzle model, JSON round-trip, Hero options`.

### Task 3: Option EVs (`solve`) — Opus

**Files:** Create `backend/src/poker_trainer/puzzle/solve.py`. Test: `backend/tests/puzzle/test_solve.py`.

**Interfaces:**
- `Respond = Callable[[HandState], dict[Action, np.ndarray]]`.
- `evaluate_action(s, hero, D, ce: ComboEquity, action, respond) -> OptionEV` follows the formulas in "Decisions".
  - `fold_freq`, `equity_vs_continue` and `ahead_vs_continue` are set for bets and raises.
  - `required_fold_equity = put / (P + put)` is set for bets and raises.
  - Simplification codes are attached as follows:
    - `realisation` to every non-river call, check, bet or raise;
    - `reraise_reply` when any raise key has positive weight on D;
    - `preflop_size` to any pre-flop raise.
- `solve(s, hero, D, respond, *, rng, samples) -> Solution`.
  - Build `ce = combo_equity(hero, s.board, D, rng=rng, samples=samples)`.
  - Then `equity = ce.vs(D)`, `ahead_now` (None on the river), `pot_odds(s)`, and every `hero_options(s)` evaluated.
  - `best` is the index of the maximum EV. Ties go to the earlier option.
  - `category_breakdown`: post-flop, group D by `categorize(range_features(board), load_thresholds())`, with categories of zero weight omitted. Use `ce.vs(D·mask)` for equity and `ahead_now` for ahead (equity on the river).
  - `simplifications` is the sorted union of the options' codes.
- `villain_respond(profile: Profile) -> Respond` is `lambda s: action_distribution(profile, s)`.

Use this river fixture, `river_spot()`:
- `new_hand(0)`; BTN raises to 5; BB calls.
- Board `Ks7h2c` / `4d` / `9s`, with BB check and BTN check on the flop and on the turn.
- On the river, either BB bets 8 (P = 18; Hero = seat 0, `KhQh`, faces 8), or BB checks (P = 10, Hero to act in position).
- For the out-of-position variant, Hero is seat 1 (BB) and acts first on the river.
- D = {AsKd: 1, JcTc: 1} via `parse_range`. `respond` is injected with explicit arrays.

- [ ] **Step 1: Failing tests**
  - `test_river_call_ev`: facing 8 into P = 18, equity 0.5. `call.ev_chips == 0.5*26 - 8 == 5.0`, `fold == 0`, `pot_odds == 8/26`.
  - `test_river_bet_ev`: checked to, `bet 50%` (to 5). Villain calls with AsKd only. F = 0.5, eq(C) = 0, EV = `0.5*10 + 0.5*(0*20 - 5) == 2.5`. `check.ev == 5.0`. `best` is check. `required_fold_equity == 5/15`.
  - `test_river_oop_check_lookahead`: Hero out of position checks. Villain bets 75% (to 8) with AsKd and checks JcTc. EV = `0.5*(1.0*10) + 0.5*max(0, 0*26 - 8) == 5.0`.
  - `test_no_continue_ev_is_pot`: Villain always folds, so `bet.ev == P` and `equity_vs_continue is None`.
  - `test_always_continue`: F = 0, so EV = `eq·(P+2b) − b`.
  - `test_allin_villain_only_fold_call`: when Hero is all-in, the response distribution has no raise key and the EV is still finite.
  - `test_reraise_lookahead`: Hero bets 50% on the river (to 5). Villain raises to 15 with AsKd and folds JcTc. Hero's reply is fold (−5), since eq = 0 against AK. EV = `0.5*10 + 0.5*(-5) == 2.5`. There are three `branches` and `reraise_reply` is attached.
  - `test_category_breakdown_sums`: the shares sum to 1, and on the river `ahead == equity`.
  - `test_realisation_label_preriver`: a flop call carries `realisation`; a river call does not.
  - `test_solve_with_strategy_smoke`: run a real `villain_respond(load_profile("tag"))` on a flop spot. Every option's EV is finite. `0 ≤ fold_freq ≤ 1`.
- [ ] **Steps 2–4:** fail → implement → pass. **Step 5:** Commit `feat(grader): option EVs from the shared Villain strategy with labelled simplifications`.

### Task 4: Grading — Sonnet

**Files:** Create `backend/src/poker_trainer/puzzle/grade.py`. Test: `backend/tests/puzzle/test_grade.py`.

**Interfaces:**
- `@dataclass(frozen=True) class Answer: action: Action; equity_guess: float; range_read_guess: float | None = None; intent: Literal["value","bluff","semi_bluff"] | None = None`. The guesses are fractions from 0 to 1.
- `@dataclass(frozen=True) class Grade` with these fields:
  - `verdict: Literal["best","fine","mistake","blunder"]`, `ev_loss_chips: float`, `chosen: OptionEV`, `best: OptionEV`
  - `equity_error: float`, `equity_score: Literal["great","good","off"]`
  - `range_read_error: float | None`, `range_read_score: Literal["great","good","off"] | None`
  - `intent_truth: str | None`, `intent_flag: str | None`, `bluff_check: tuple[float, float] | None`, which holds the required and the actual fold frequency
  - the property `ev_loss_bb`
- `grade(p: Puzzle, a: Answer, *, respond: Respond | None = None) -> Grade`.
  - `respond` defaults to `villain_respond(load_profile(p.spot.profile))`. It is needed only for custom sizes. If the loaded profile's version differs from `spot.profile_version`, raise `ValueError("profile changed since this puzzle was generated")`; M4 decides how to present that.
  - If the action matches a listed option, its stored `OptionEV` is used. Otherwise it is a custom post-flop size, scored with `evaluate_action` against `p.solution.combo_equity`. An illegal or pre-flop custom action raises `ValueError`.
  - Verdict, scores, intent and bluff check follow "Decisions", with thresholds from `config.json`.
  - `intent_flag` is set when `a.intent` is given and differs from `intent_truth`. The text names both values, for example `"You called this a value bet, but only better hands continue (bluff)."`.
- [ ] **Step 1: Failing tests** (built on `river_spot` and a hand-built `Solution`):
  - All threshold comparisons use `<= thr + 1e-9`. Verdict boundaries for a loss of exactly 0.5 chips (best), `0.10·P` (fine), `0.10·P + 0.01` (mistake), and `> 0.25·P` (blunder).
  - Equity score boundaries: errors of 0.05, 0.10 and 0.1001.
  - No range read on the river, and a guess there is ignored.
  - Intent value / bluff / semi-bluff truth, with a flag message on mismatch.
  - The bluff check tuple.
  - A custom size scored via `evaluate_action`.
  - `test_preflop_custom_rejected`. `test_profile_version_mismatch_raises`, using a custom size on a spot whose `profile_version` was altered.
- [ ] **Steps 2–4:** fail → implement → pass. **Step 5:** Commit `feat(grader): verdicts, equity and range-read scores, intent and bluff checks`.

### Task 5: Generator, trivial filter, CLI — Opus (the decision-point logic is subtle)

**Files:** Create `backend/src/poker_trainer/puzzle/generate.py`, `trivial.py` and `cli.py`. Modify `backend/pyproject.toml` (`[project.scripts]`). Tests: `backend/tests/puzzle/test_generate.py`, `test_trivial.py`.

**Interfaces:**
- `is_trivial(sol: Solution, pot: int, cfg) -> str | None` returns the reason or None, using the three rules in "Decisions".
- `generate_spot(rng: random.Random, street: Street, profile: str, *, seed: int, attempt: int) -> Spot | None` makes one attempt and returns None on failure.
  - Draw `hero_seat` and `button`.
  - Shuffle a deck with `rng` and deal Hero's 2 cards, Villain's 2 cards and a 5-card runout.
  - Play forward using `sample_action` for both seats, Hero with `load_profile(HERO_PROFILE)`. Use `RangeTracker(villain_profile, villain_seat)` to observe each Villain action. Deal from the runout when `needs_board`.
  - Stop according to `stop_prob`. `UnsupportedSpot`, a terminal state, or passing the target street gives None.
  - The steps are the tracker steps, mapped through `visible_range(·, hero, decision board)`.
- `generate_puzzle(seed: int, *, street=None, profile=None) -> Puzzle`.
  - Use one `random.Random(seed)` for all attempts and for the MC. Draw the street (weights) and the profile (uniform) once, before the loop, unless they are given.
  - Loop up to `max_attempts`: generate the spot → `solve` → skip it if `is_trivial`.
  - If no puzzle is found, raise `RuntimeError`.
- `cli.main(argv) -> int` is `puzzle-sample [--n 5] [--seed 0] [--street flop]`. It prints, for each puzzle, the line, Hero's cards, the board, the range size, equity, pot odds and each option's EV in bb.
- `[project.scripts]`: `competence = "poker_trainer.analysis.competence:main"` and `puzzle-sample = "poker_trainer.puzzle.cli:main"`.
- [ ] **Step 1: Failing tests**
  - `test_trivial_rules`: one case for each rule, plus one non-trivial case.
  - `test_generate_deterministic`: the same seed gives an identical `puzzle_to_dict`.
  - `test_generate_respects_street_and_profile`.
  - `test_hero_to_act_at_decision`.
  - `test_runout_consistent`: the decision board is a prefix of `runout`, and Hero's cards, Villain's cards and the runout are all distinct.
  - `test_steps_start_full_and_end_at_range`.
  - `test_cli_runs`: `main(["--n","2","--seed","1"]) == 0`.
  - `test_street_mix_not_biased`: over 40 seeds with no street given, every street appears, and pre-flop is at most 40%.
  - `@slow test_generation_speed`: 10 seeds, mean < 6 s, and print the mean.
- [ ] **Steps 2–4:** fail → implement → pass. Check that `uv run puzzle-sample --n 3` and `uv run competence --profile tag --hands 40` work. **Step 5:** Commit `feat(puzzle): generator with trivial filter, frozen state, sample CLI`.

### Task 6: Golden hand-worked spots — Opus

**Files:** Test: `backend/tests/puzzle/test_golden.py`. If a test-only helper is needed, put it in `backend/tests/puzzle/spots.py`.

- 20 spots, each built from an explicit `HandState` line, an explicit Villain range (`parse_range`, with weights where useful) and an injected `respond`.
- Coverage:
  - 8 river spots: calls, value bets, bluffs, the out-of-position check look-ahead, and raises facing a bet;
  - 5 turn spots, which are exact;
  - 4 flop spots, with the MC tolerance at 4·SE;
  - 3 pre-flop spots: BTN open, BB vs open call, BTN vs 3-bet jam, all with the MC tolerance.
- Write the expected pot odds, F and EV per option as numbers worked out by hand, with the working shown in a comment for each spot. River and turn equities are worked out by hand and compared to 1e-9.
- Flop equities come from `tests/reference/exact_flop.py`; pre-flop equities come from pokerkit with a fixed seed and 200k samples. Compare with 4·SE combined, and state the source in each comment.
- At least one spot for each Review Focus item 1–3.
- [ ] Write the tests → run → any failure is either a plan bug or a code bug. Report which, and fix the code only with the controller's agreement. Commit `test(grader): golden hand-worked spots`.

### Task 7: Puzzle property tests — Sonnet

**Files:** Test: `backend/tests/puzzle/test_properties.py`.

- Hypothesis over `seed`, with `deadline=None` (`max_examples=15` fast; a `@slow` variant with 150):
  - Villain's revealed hand has positive weight in `spot.range`.
  - `p.solution.equity == p.solution.combo_equity.vs(p.spot.range).equity` (displayed ≡ graded).
  - Re-running `evaluate_action` for every stored option, against the stored `combo_equity` and the profile's `respond`, reproduces its `ev_chips` to 1e-12.
  - Weights never increase from one step to the next.
  - Chips are conserved in `spot.state`.
  - Every option `apply`s cleanly.
  - `grade` of each option's action gives `verdict == "best"` exactly for options within the best margin.
  - The JSON round-trip holds.
- [ ] Write the tests → pass. Commit `test(puzzle): property tests — revealed hand in range, displayed ≡ graded, chips conserved`.

## Open items for M4 (from the M3 final review)

- **Size:** puzzle JSON is 60–160 KB, mostly float lists. Store it compressed (zlib), or use a sparse or float32 encoding, provided the round-trip stays exact where needed.
- **Persist the Grade with each attempt:** store the chosen `OptionEV`, the verdict and `Spot.config_version`. A later config change must not silently regrade history.
- **Custom sizes need the live profile:** `grade` raises if the profile version changed. Disable custom sizes for stale puzzles.
- **Canonical actions:** build `Answer.action` from a stored `Option.action`, or via `custom_action`. Guesses are fractions from 0 to 1.
- **Display text:** map category enum names and simplification codes (`SIMPLIFICATIONS`) to display text in the API layer.
- **Encoding:** branch labels contain an em dash. Use UTF-8 end to end.
- **Format check:** check `format: 1`. Never regenerate a puzzle from its seed, because determinism holds only per platform.
- **Showdown winner:** compute it from the frozen cards (hole cards and runout), or add it to the frozen state.

## Deferred to M6 (results-view profile notes, or Villain tuning on the handoff branch)

- TAG calls a 2.5×-pot river jam with 55% of its range on a monotone board, so jamming two pair grades as best.
- In BB pre-flop spots, 3-betting trash (23o/35o/75o) grades best by 0.6–1.3bb. BTN may over-fold to 3-bets.
- `preflop_size`: 2.5x is never worse than 3x by construction. Say so whenever this decides the best option.
- Profile notes carried over from M3 planning: STRONG folds about 34% to big jams; MEDIUM raises often; the river stab frequency.
