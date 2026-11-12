# M6 Results View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a submit, the user sees the full results of main spec §8: verdict and EV lost, guesses against the truth, every option's EV, step-by-step maths, Villain's range (how it narrowed, and Hero against it), Villain's hand and the run-out, and the "judged on range" note, then moves to the next puzzle. M6 replaces M5's `ResultStrip`.

**Architecture:**
- No new API endpoints. `POST /api/puzzles/{id}/attempts` already returns everything (`AttemptResult`: `grade`, `options` with `branches` and `continue_grid`, `simplifications`, `categories`, `range_steps`, `reveal`, `judged_on_range_note`). The only backend changes are the intent-flag wording and more attempt fixtures (Task 1).
- **Reusable per-decision components** (Play vs Bots spec §6, `docs/superpowers/specs/2026-11-12-play-vs-bots-design.md`): every results component below the summary takes a `DecisionData` (one graded decision plus its spot context), never an `AttemptResult` or a `PuzzleView`. M10 will build `DecisionData` from a played hand. Puzzle-only parts (guess scores, Next puzzle, reveal) live outside `components/Decision/`.
- Layout in the result state: the table (Villain's cards flip, run-out deals) and the history panel stay where they are. The answer slot shows `ResultSummary`. Under the play area, a full-width `DecisionDetails` region with four tabs: **Options**, **Maths**, **Range**, **Hand**. The page may scroll vertically in the result state only. The answering state still fits 1280×800 (M5's e2e test stays).

**Tech Stack:** unchanged from M5: Vite, React 19, TypeScript strict, CSS Modules plus tokens, Vitest and Testing Library, Playwright. Backend: Python 3.13, FastAPI, pytest. **No new dependencies** (no chart, table or UI library; the range grid is CSS grid).

**Spec:** `docs/superpowers/specs/2026-11-10-poker-puzzle-trainer-design.md` (§8 results view, §11 UI, §12 accuracy) and `docs/superpowers/specs/2026-11-12-play-vs-bots-design.md` (§6 reuse). Roadmap: `docs/superpowers/plans/2026-11-10-roadmap.md` (M6). Hand-over items: "Open items for M6 and M7" at the end of `2026-11-11-m5-table-ui.md`, "Open items for M5, M6 and M7" in `2026-11-11-m4-api-and-storage.md`, "Deferred to M6" in `2026-11-10-m3-puzzle-and-grader.md`.

## Global Constraints

- **Every number comes from the API.** The UI never computes an EV, equity, frequency or range weight. It may only rearrange API numbers into the formulas they came from (Task 3), and shows a plugged-in formula only when it reproduces the API's value (see Task 3).
- **Display in big blinds:** chips / 2 via `formatBb` (M5). EV in bb uses the API's `*_bb` fields, two decimals with trailing zeros dropped (`formatEvBb`, moved from `lib/result.ts` to `lib/format.ts` in Task 2). Percentages via `formatPct`. Server labels that contain chips ("bet 14", "Villain raises to 40 — Hero folds") are relabelled in bb.
- **Options are matched by `is_chosen` / `is_best`, never by position.** A custom choice is appended at the end of `options` (M4).
- **`reveal.runout` holds all 5 cards,** including the board already shown. Slice by board length to deal the rest (M4, done in M5).
- **Types come from the API contract:** `src/api/schema.d.ts` is generated; regenerate (`npm run gen:openapi && npm run gen:api`) only if Task 1 changes a response model (it should not).
- **Accessibility:** the tabs follow the WAI-ARIA tabs pattern (`role="tablist"`, arrow keys, `aria-selected`, `aria-controls`). Tables are real `<table>`s with `<th scope>`. Range-grid cells carry an accessible name ("AKs, 75% of combos"). Colour is never the only signal (Best / You badges are text). Animations stop under `prefers-reduced-motion: reduce`. The app-level `role="status"` verdict announcer in `App` stays as it is.
- **Focus:** when a result arrives, focus moves to "Next puzzle" (M5 behaviour, kept).
- **Layout:** answering state fits 1280×800 (unchanged). Result state: no horizontal scroll at 1024 wide and up; the range grid stays square and legible at 1024 (cells at least 22 px).
- **Cross-platform, dependencies, original art, commit hygiene:** as in the M5 plan's Global Constraints.
- Commands run from `frontend/` unless stated; backend commands from `backend/`.

## Decisions made in this plan

- **`DecisionData`** (`src/lib/decision.ts`):
  ```ts
  import type { AttemptResult, PuzzleView, StreetName } from '../api/types'
  type R = AttemptResult
  export interface DecisionContext {
    street: StreetName
    potChips: number            // total pot at the decision, including bets in front (PuzzleView.pot)
    heroStreetBetChips: number  // street_bets[hero_seat]
    villainStreetBetChips: number
    potOdds: number | null
    heroCards: string[]
    board: string[]             // the board at the decision, not the run-out
  }
  export interface DecisionData {
    context: DecisionContext
    grade: Pick<R['grade'], 'verdict' | 'ev_loss_bb' | 'chosen_label' | 'best_label' | 'equity'
      | 'equity_std_error' | 'equity_exact' | 'ahead_now' | 'intent' | 'intent_truth'
      | 'intent_flag' | 'bluff_check'>
    chosenLabel: string          // display label, custom sizes in bb (from chosenLabel())
    options: R['options']
    simplifications: R['simplifications']
    categories: R['categories']
    rangeSteps: R['range_steps']
  }
  export function decisionFromAttempt(view: PuzzleView, result: AttemptResult): DecisionData
  ```
- **Results layout:** `ResultSummary` in the answer slot; `DecisionDetails` (tabs Options / Maths / Range / Hand) full width under the play area. Default tab: Options. The selected tab is remembered in `localStorage` key `ppt.resultTab` (try/catch). `ResultSummary` has a "Details" button that scrolls `DecisionDetails` into view and focuses its selected tab.
- **The Hand tab is not a Decision component:** it renders `reveal` (puzzle-specific), so it lives in `components/HandReveal/`. M10 will render its own hand summary.
- **Hero folds (any street): no run-out** (M5 open item, Claude's call). Villain's cards still flip; the board stays as it was at the decision; the Hand tab says "You folded, so there's no showdown." in place of the showdown line. The sampled run-out only makes sense when Hero stays in.
- **Intent flag wording is fixed in the grader** (M5 open item), so the stored text is right for M7's history too. Old stored attempts keep their old text (accepted). New forms (exact copy):
  - intent text by action kind: bet → "a value bet" / "a bluff" / "a semi-bluff"; raise → "a value raise" / "a bluff raise" / "a semi-bluff raise".
  - normal: `"You labelled this {intent_text(chosen)}, but {reason}, so it's {intent_text(truth)}."`
  - Villain never continues: `"You labelled this {intent_text(chosen)}, but {never_reason}."` (the reason already names the truth; its "this bet" becomes "this raise" for a raise).
  - The raw enum in parentheses is gone.
- **Option sizes show both** (M5 open item): the options table's size column reads "1.5 bb · 30% pot" for bets (share = `put / potChips`, rounded) and "to 7.5 bb" for raises; the label column keeps the nominal label ("Bet 33%").
- **Options table order:** EV descending; ties keep API order. Fold is always shown (EV 0, the baseline).
- **Profile notes deferred** (M3 "Deferred to M6"): per-profile behaviour notes need new profile data owned by the Villain branch. They go to M8 (explanations). The `preflop_size` simplification text is shown whenever its code is present, which covers "say so when 2.5x vs 3x decides the best option".
- **Plain-English explanation** (spec §8 item 8) is M8; M6 leaves no placeholder for it.
- **Live profile text on old puzzles** (M4 open item: a renamed profile makes the result a 500) stays open; no profile has been renamed. Recorded again for M9.

## Review Focus

1. **A custom size chosen:** it is the appended last option, not best; it shows in the table with a bb label ("Bet 7 bb", not "bet 14") and a "You" badge, and the maths tab can show it.
2. **Villain never continues** (one branch, "Villain folds" 100%, `equity_vs_continue` null): the table shows "—" for equity when called, maths shows EV = pot, no division by zero, no "NaN".
3. **River and pre-flop results:** `ahead_now` and `range_read_guess` null on the river, `categories` possibly null; every component hides the missing part without an empty heading.
4. **Re-raise branch labels in chips** ("Villain raises to 40 — Hero folds") are shown in bb ("Villain raises to 20 bb — you fold").
5. **1024 px wide result page:** no horizontal scroll with the widest options table and the range grid; checked by an e2e test.

---

### Task 1: Grader intent wording and attempt fixtures (backend)

**Files:**
- Modify: `backend/src/poker_trainer/puzzle/grade.py` (`_INTENT_TEXT`, the flag f-string near line 162)
- Modify: `backend/src/poker_trainer/api/dev_fixtures.py` (`write_fixtures`)
- Test: `backend/tests/puzzle/test_grade.py` (add), `backend/tests/api/test_dev_fixtures.py` (new)
- Regenerate: `frontend/src/test/fixtures/*.json`

**Interfaces:**
- Produces: `intent_text(intent: Intent, kind: ActionKind) -> str` in `puzzle/grade.py`; fixtures `attempt_call.json`, `attempt_raise_preflop.json`, `attempt_fold_preflop.json`, `attempt_check_river.json`, `attempt_custom.json`, `attempt_never_continues.json` next to the existing `attempt_bet.json` and `attempt_fold.json`.

- [ ] **Step 1: Write failing tests** in `tests/puzzle/test_grade.py`:
  - `test_intent_text_by_kind`: `intent_text("value", ActionKind.RAISE) == "a value raise"`, `intent_text("semi_bluff", ActionKind.BET) == "a semi-bluff"`, `intent_text("bluff", ActionKind.RAISE) == "a bluff raise"`.
  - `test_intent_flag_has_no_raw_enum`: grade a fixed puzzle (build it as `tests/puzzle/test_golden.py` does) with an intent that mismatches; assert the flag ends with `", so it's a bluff."` (or the matching truth), and `"(" not in flag`.
  - `test_intent_flag_never_continues`: grade with an injected always-fold `respond` (the `facing_respond` / `arr` helpers in `tests/puzzle/test_solve.py`); the flag has no "so it's" and says "raise" for a raise.
  - `test_verdicts_unchanged`: the existing golden tests still pass (no code change needed; run them).
- [ ] **Step 2: Run** `uv run pytest tests/puzzle/test_grade.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** `intent_text` and the new flag forms (copy in "Decisions made in this plan"). Only the text changes; `intent_truth`, verdicts and EVs must not.
- [ ] **Step 4: Run** `uv run pytest -m "not slow"`. Expected: PASS.
- [ ] **Step 5: Extend `write_fixtures`** to also write these attempts (search the fixture puzzles for the needed option, as the existing loop does; raise `RuntimeError` if none fits):
  - `attempt_call.json`: call on `facing_postflop_raise`.
  - `attempt_raise_preflop.json`: the first raise option on `preflop_bb_facing_open` (carries `preflop_size`), intent "value".
  - `attempt_fold_preflop.json`: fold on `preflop_btn_first_in`.
  - `attempt_check_river.json`: check on `river` (river check look-ahead branches), or the first river puzzle with a check option.
  - `attempt_custom.json`: `custom_to = min_to` on `custom_allowed`.
  - `attempt_never_continues.json`: search seeds (as `search()` does) for a puzzle whose `p.solution.options` has a bet or raise with `fold_freq == 1.0`, and submit that option's index. If none is found within 200 seeds, raise `RuntimeError` and skip the file; the frontend tests then use a clearly labelled synthetic case built from `attempt_bet` in `src/test/synthetic.ts` (never a wrong real option).
  - `attempt_custom`: assert `min_to` differs from every stored option's `to` (otherwise no custom row is appended).
  - Note: `attempt_call` and `attempt_fold` share a puzzle, so the second has `attempt_no` 2; harmless.
  Test: `test_write_fixtures_writes_all_attempts` asserts each file exists and `attempt_custom.json` has an option with `is_chosen` true and `is_best` false at the end of `options`.
- [ ] **Step 6: Regenerate** fixtures: from `backend/`, `uv run python -m poker_trainer.api.dev_fixtures ../frontend/src/test/fixtures`. Run frontend `npm test` (existing tests must still pass with the regenerated fixtures).
- [ ] **Step 7: Commit** `fix(grader): plain-English intent flag, more attempt fixtures for the results view`

### Task 2: Verdict, guesses and options EV table

**Files:**
- Create: `frontend/src/lib/decision.ts` (+ `.test.ts`)
- Modify: `frontend/src/lib/format.ts` (move `formatEvBb` here, add `bbLabel`), `frontend/src/lib/result.ts` (its private `formatEvBb` moves to `format.ts`; import it)
- Create: `frontend/src/components/ResultSummary/ResultSummary.tsx` (+ `.module.css`, `.test.tsx`)
- Create: `frontend/src/components/Decision/DecisionDetails.tsx`, `OptionsTable.tsx`, `MathsPanel.tsx` (stub), `RangePanel.tsx` (stub), plus `.module.css` and tests for `DecisionDetails` and `OptionsTable`
- Create: `frontend/src/components/HandReveal/HandReveal.tsx` (stub)
- Create: `frontend/src/styles/tokens.results.css` (imported from `global.css`) with every results token up front: `--range-fill`, `--range-blocked-hatch`, `--badge-best`, `--badge-you`, `--maths-formula-bg`. Tasks 3–5 use only these or module-local variables; they don't edit this file.
- Create: `frontend/src/dev/entries/results.tsx`
- Modify: `frontend/src/app/App.tsx`, `App.module.css`, `App.test.tsx`
- Delete: `frontend/src/components/ResultStrip/*`, `frontend/src/dev/entries/result.tsx`

**Interfaces:**
- Consumes: `AttemptResult`, `PuzzleView` (`api/types`); `chosenLabel`, `verdictLine`, `guessLines`, `VERDICT_LABELS`, `SCORE_LABELS`, `optionLabel` (`lib/result`).
- Produces:
  - `DecisionData`, `DecisionContext`, `decisionFromAttempt` (see Decisions).
  - `formatEvBb(bb: number): string` and `bbLabel(label: string): string` in `lib/format.ts`. `bbLabel` rewrites chip amounts matched by `/\b(to|bets?) (\d+)/` in server labels into bb, and "Hero folds/calls" into "you fold/call" (`"Villain raises to 40 — Hero folds"` → `"Villain raises to 20 bb — you fold"`; `"Villain bets 14 — Hero calls"` → `"Villain bets 7 bb — you call"`).
  - `sizeText(option: OptionResult, ctx: DecisionContext): string` in `lib/decision.ts` ("1.5 bb · 30% pot", "to 7.5 bb", "" for fold/check/call).
  - `sortedOptions(options): OptionResult[]` (EV desc, stable).
  - `<DecisionDetails decision={DecisionData} handTab?: ReactNode />`: tabs Options, Maths, Range, and Hand only when `handTab` is given. Renders `<OptionsTable>`, `<MathsPanel>`, `<RangePanel>` with `decision`.
  - `<MathsPanel decision />`, `<RangePanel decision />`: stubs rendering "Coming soon" (replaced in Tasks 3 and 4, same props).
  - `<HandReveal view={PuzzleView} result={AttemptResult} />`: stub (Task 5).
  - `<ResultSummary ref result onNext loading shortcutsOn onDetails />`: a `<section aria-label="Result">` (the M5 e2e relies on it) with verdict badge, `verdictLine`, guess lines with score badges, intent flag (when present), the judged-on-range note in small text (as `ResultStrip` has it), "Next puzzle" (exact name; `N` hint, forwarded ref for focus), "Details" button. Same props as `ResultStrip` plus `onDetails`.
  - Tab ids via `useId`. A stored `ppt.resultTab` naming a tab that isn't present (e.g. "hand" without `handTab`) falls back to Options.
  - The `is_chosen` row's label is `decision.chosenLabel` (the server label for a custom size is in chips).

- [ ] **Step 1: Write failing tests**
  - `decision.test.ts`: `decisionFromAttempt(puzzle_flop_unopened, attempt_bet)` has `context.potChips === view.pot`, `context.board` equal to `view.board` (not the run-out), `chosenLabel` equal to `chosenLabel(result)`; for `attempt_custom` the chosen label is in bb. `sizeText` for a bet option on the flop fixture gives `"{x} bb · {y}% pot"` with y = round(100·put/pot). `sortedOptions` is EV-descending and keeps ties in API order.
  - `format.test.ts`: `bbLabel("Villain raises to 40 — Hero folds") === "Villain raises to 20 bb — you fold"`; `bbLabel("Villain bets 14 — Hero folds") === "Villain bets 7 bb — you fold"`; `bbLabel("Villain calls") === "Villain calls"`.
  - `OptionsTable.test.tsx`: with `attempt_bet`, one row per option; the best row has a "Best" badge, the chosen row a "You" badge (both when the same); EV cells match `formatEvBb(o.ev_bb)`; "vs best" (`best.ev_bb − o.ev_bb`, an allowed rearrangement of API numbers) shows `−x bb` for worse options, `+x bb` if a custom size beats the best, and nothing for the best; fold-freq and equity-when-called show "—" when null (`attempt_never_continues`). `attempt_custom`: the last-by-API custom row shows "You" and a bb label.
  - `DecisionDetails.test.tsx`: tabs are `role="tab"`; ArrowRight moves selection; without `handTab` there are three tabs; the selected tab is restored from `localStorage` and still renders when storage throws.
  - `ResultSummary.test.tsx`: port the `ResultStrip` tests; add: the intent flag shows when present; "Details" calls `onDetails`.
  - `App.test.tsx`: after a submit, "Next puzzle" has focus, the announcer text is unchanged from M5, and the Options tab is visible.
- [ ] **Step 2: Run** `npm test`. Expected: new tests FAIL.
- [ ] **Step 3: Implement** the files above. `App.tsx`: replace `ResultStrip` with `ResultSummary`; render `<DecisionDetails decision={decisionFromAttempt(view, result)} handTab={<HandReveal view result />} />` as a child of `.main` with `grid-column: 1 / -1`, only when `result` is not null. It is outside `.play`, so give it its own `data-pending` dimming (kept, dimmed, while the next puzzle loads, like the table). `onDetails` scrolls the details region into view (`scrollIntoView({ block: 'start' })`, instant under reduced motion) and focuses its selected tab.
- [ ] **Step 4: Gallery:** `dev/entries/results.tsx` shows `ResultSummary` and `DecisionDetails` for every attempt fixture.
- [ ] **Step 5: Run** `npm test && npm run lint && npm run typecheck && npm run format:check`. Expected: PASS.
- [ ] **Step 6: Commit** `feat(ui): verdict, equity/range-read comparison, options EV table`

### Task 3: Step-by-step maths panel

**Files:**
- Create: `frontend/src/lib/maths.ts` (+ `.test.ts`)
- Replace: `frontend/src/components/Decision/MathsPanel.tsx` (+ `.module.css`, `.test.tsx`)
- Create: `frontend/src/dev/entries/maths.tsx`

**Interfaces:**
- Consumes: `DecisionData`, `formatEvBb`, `bbLabel`, `formatPct`.
- Produces:
  ```ts
  export interface MathsLine { text: string; result?: string }   // "Pot odds = 2 / (8 + 2)", "20%"
  export interface OptionMaths {
    label: string; isBest: boolean; isChosen: boolean
    potOdds: MathsLine[]        // empty when no call
    foldEquity: MathsLine[]     // empty unless bet/raise
    ev: MathsLine[]             // the EV derivation, last line = the option's ev_bb
    branches: { label: string; share: string; equity: string | null; value: string; formula: string | null }[]
    notes: string[]             // simplification texts for this option's codes
  }
  export function optionMaths(o: OptionResult, d: DecisionData): OptionMaths
  ```

**The formulas the solver uses** (`backend/src/poker_trainer/puzzle/solve.py`; P = `potChips`, put = `o.put`, e = equity, all chips, shown in bb):
- Fold: EV = 0 (the baseline).
- Call: EV = e × (P + put) − put, with e = `grade.equity`.
- Check with no branches: EV = e × P.
- Check on the river (`_river_check_lookahead`): EV = Σ share × value. Branch "Villain checks back": value = e_b × P. Branch "Villain bets {b} — Hero calls|folds": value = max(e_b × (P + 2b) − b, 0), with b = the bet in chips (street bets are 0 after the check); "folds" is the 0 case.
- Bet/raise: EV = Σ share × value. Branch "Villain folds": value = P. Branch "Villain calls": value = e_b × (P + put + vcall) − put, where vcall = `o.to − villainStreetBetChips`. Re-raise branches: show the value only.
- Pot odds (when `potOdds` is not null): call / (P + call) with call = the call option's `put`; compare with `grade.equity`.
- Fold equity (bet/raise): required = put / (P + put) (equals `o.required_fold_equity`); actual = `o.fold_freq`.

**Rule:** a plugged-in formula line is emitted only if recomputing it from the raw API values (not the rounded display) matches the API value within 0.01 bb (EV) or 0.001 (fractions). Otherwise the line shows the API value without the formula. This keeps "displayed maths ≡ graded maths". Equities in formulas are displayed to one decimal ("41.3%").

- [ ] **Step 1: Write failing tests** in `maths.test.ts`, for every attempt fixture and every option in it: the last `ev` line's `result` equals `formatEvBb(o.ev_bb)`; whenever a branch `formula` is non-null, recomputing it matches `value_bb` within 0.01. Specific cases: `attempt_check_river` produces non-null formulas for both branch kinds; `attempt_call` call option has a formula line "EV = e × (pot + call) − call" with real numbers; `attempt_never_continues` has one branch, "Villain folds", share "100%", and no NaN anywhere in the output (`JSON.stringify` has no "NaN"); `attempt_fold_preflop` fold option gives `ev` = ["EV = 0 (folding is the baseline)"]; `attempt_raise_preflop` notes include the `preflop_size` text.
- [ ] **Step 2: Run** `npx vitest run src/lib/maths.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement** `optionMaths`.
- [ ] **Step 4: Implement `MathsPanel`:** two columns, "Your play" and "Best play" (one column when they are the same option). Each shows the pot-odds, fold-equity and EV sections, the branch table, then the notes. Under the columns, "EV lost = best − yours = x bb". The EV-lost line always uses `grade.ev_loss_bb` (never a subtraction, which can go negative for a custom size). Test (`MathsPanel.test.tsx`): with `attempt_fold` (chosen fold, best call) there are two columns headed by the two labels and the EV-lost line equals `formatEvBb(grade.ev_loss_bb)`; with `attempt_bet` (chosen = best) there is one column.
- [ ] **Step 5: Run** `npm test && npm run lint && npm run typecheck`. Expected: PASS.
- [ ] **Step 6: Commit** `feat(ui): step-by-step maths panel`

### Task 4: Range grid, narrowing steps, Hero vs range

**Files:**
- Create: `frontend/src/lib/grid.ts` (+ `.test.ts`)
- Create: `frontend/src/components/Decision/RangeGrid.tsx`, `CategoryTable.tsx` (+ `.module.css`, tests)
- Replace: `frontend/src/components/Decision/RangePanel.tsx` (+ test)
- Create: `frontend/src/dev/entries/range.tsx`

**Interfaces:**
- Consumes: `DecisionData` (`rangeSteps`, `options[].continue_grid`, `categories`, `grade.ahead_now`, `grade.equity`).
- Produces:
  - `cellLabel(row: number, col: number): string` (13×13; ranks A..2 on both axes; pairs on the diagonal; suited and offsuit sides as in `backend/src/poker_trainer/engine/combos.py` `grid_position`, verified by a test that `cellLabel` inverts `grid_position` for "AA", "AKs", "AKo", "72o").
  - `<RangeGrid grid={Grid} label: string />`: weight 0–1 as fill (`--range-fill` with opacity = weight), None as a hatched "blocked" cell; each cell has an accessible name "AKs, 75% weight" or "AKs, blocked" (the API value is the mean weight over unblocked combos).
  - `<CategoryTable categories hero />`: columns Category, Share of range, You're ahead, Your equity, Win / Tie / Lose.
  - `<RangePanel decision />`:
    - a step selector (`role="radiogroup"`) with one button per `rangeSteps[i].label`, default the last step, showing that step's grid and its combo count (`combos.length`) and weighted size (Σ weights);
    - a "Continues vs" selector over options that have a `continue_grid` (default: the best option if it has one, else the chosen one, else the first), showing the continuing range and "Folds: x%" from `fold_freq`; hidden when no option has a grid (e.g. facing an all-in);
    - headline: "You're ahead of {ahead_now} of this range; your equity is {equity}." (first clause omitted on the river, when `ahead_now` is null);
    - the category table when `categories` is not null.

- [ ] **Step 1: Write failing tests:** `grid.test.ts` as above; `RangeGrid.test.tsx`: 169 cells, a None cell is named "…, blocked"; a weighted cell "…, x% weight"; `RangePanel.test.tsx` with `attempt_bet`: the step buttons equal the fixture labels in order, the last is selected; selecting the first changes the grid; the continue selector defaults to the best option when it has a grid, and is absent when no option has one; with `attempt_check_river` the headline has no "ahead" clause; with `categories: null` no category heading renders.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement.** Grid cells at least 22 px at 1024 wide; the grid is a CSS grid with row/column headers (A…2).
- [ ] **Step 4: Run** `npm test && npm run lint && npm run typecheck`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(ui): range grid with narrowing steps and hero-vs-range breakdown`

### Task 5: Villain reveal, run-out, judged-on-range note, next puzzle

**Files:**
- Replace: `frontend/src/components/HandReveal/HandReveal.tsx` (+ `.module.css`, `.test.tsx`)
- Modify: `frontend/src/app/App.tsx` (fold rule for the run-out), `App.test.tsx`
- Modify: `frontend/src/lib/result.ts` (`showdownLine` handles a fold)
- Modify: `frontend/e2e/smoke.spec.ts`
- Create: `frontend/src/dev/entries/hand.tsx`

**Interfaces:**
- Consumes: `PuzzleView`, `AttemptResult`, `Card` component, `showdownLine`.
- Produces: `heroFolded(result: AttemptResult): boolean` in `lib/result.ts` (`answer.action.kind === 'fold'`); `<HandReveal view result />`.

- [ ] **Step 1: Write failing tests**
  - `result.test.ts`: `showdownLine(attempt_fold)` is "You folded, so there's no showdown."; `heroFolded` true for `attempt_fold` and `attempt_fold_preflop`, false for `attempt_bet`.
  - `HandReveal.test.tsx`: shows Villain's two cards (accessible names), the profile label and description from `reveal.profile`, the run-out (all five cards) when Hero didn't fold and only the decision board when Hero folded, the showdown line, the `judged_on_range_note` text verbatim, and the simplification texts as a "Simplifications" list.
  - `App.test.tsx`: after submitting a fold, the table board shows `view.board.length` cards (no run-out); after a bet it shows 5.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement.** In `App.tsx`, the table centre's `board` is `result && !heroFolded(result) ? result.reveal.runout : view.board`. (The judged-on-range note is already in `ResultSummary` from Task 2; `HandReveal` shows it too.)
- [ ] **Step 4: E2E** (`e2e/smoke.spec.ts`): extend "a puzzle end to end" to open each tab (Options, Maths, Range, Hand) and check one landmark in each; add "result page: no horizontal scroll at 1024×768 and 1280×800" (`document.documentElement.scrollWidth <= clientWidth`), using route-fulfilled `puzzle_custom_allowed` / `attempt_custom` fixtures for the widest options table, as the M5 layout test does; keep the M5 answering-state 800 px test unchanged.
- [ ] **Step 5: Run** `npm test && npm run lint && npm run typecheck && npm run build && npm run e2e`. Expected: PASS.
- [ ] **Step 6: Commit** `feat(ui): Villain reveal, run-out, "judged on range" note, next puzzle`

## Execution notes

- Order: Task 1, then Task 2. Tasks 3, 4 and 5 can run in parallel after Task 2: they replace different stub files and add separate gallery entries; only Task 5 touches `App.tsx`. Commits land in roadmap order (3, 4, 5).
- Every task's reviewer gets this plan, the task's diff, the test output and, for UI tasks, screenshots of the gallery entry and of the app at 1280×800 and 1024×768. The reviewer checks spec compliance, then code quality, and does a mutation check on the most important test (break the code, see it fail, restore).
- Models: Sonnet implementers for Tasks 2, 4 and 5; Opus for Task 1 (grader) and Task 3 (maths ≡ graded maths); Opus for all reviews.
- After Task 5: a whole-branch review on Opus, then a PR `m6-results-view` → `main` (no squash). Check CI on Windows and macOS.

## Follow-up after the final M6 review

Decisions made while building (controller rulings):
- No Villain-always-folds spot exists in seeds 1–200, so `attempt_never_continues.json` isn't written; tests use a labelled synthetic case in `frontend/src/test/synthetic.ts`.
- Tasks 3, 4 and 5 ran one after another, not in parallel.
- The Villain profile and the run-out showdown line moved from the summary into the Hand tab, so a fold never shows a run-out result.
- All-in options show "all-in x bb" with no pot share.
- On the river the Range headline reads "Your equity against this range is x."
- After a fold the summary hides the judged-on-range note, and the Hand tab says "Graded against Villain's whole range." (the server note mentions a run-out that isn't dealt).

Fixed after the final review: all-in size label, fold-aware range note, empty Board section on a pre-flop fold, one minus sign (U+2212) everywhere, a hidden h2 so the tab headings nest, table roles for the range grid (column headers line up), and a focusable tab panel.

## Open items for M7 and later (from the M6 reviews)

- **M9, grader:** a custom size can have a higher EV than the option marked best, while the verdict says best with 0 bb lost (the grader picks best from the preset options only). The table shows "+x bb" honestly.
- **M9, fixtures:** regenerating fixtures on Windows vs macOS changes floats in the last digit. Round floats in `_dump`, or accept the churn.
- **M9, profile text:** a renamed profile still turns old results into a 500 (from M4).
- **M8:** per-profile behaviour notes and the plain-English explanation.
- **M11 polish:** range-grid cell text is 9 px and faint at mid weights; no hover tooltip with the exact weight; tie wording "x is above x" when equity equals pot odds; the judged-on-range note appears in both the summary and the Hand tab.
- **Tests to tighten:** the maths tests don't pin the Villain-calls formula or the Σ line (a regression would fall back to plain values silently); the Range "Continues vs" default test can't tell best from chosen; the Details button and `dealFrom` on a fold are untested; the e2e focuses Next before pressing N.
- **Code tidy:** `MINUS` is defined in both `OptionsTable.tsx` and `maths.ts`; all-in is detected by the server label `'all-in'`; `grade.py` has a line over 100 characters; the never-continues fixture write path has never run.
