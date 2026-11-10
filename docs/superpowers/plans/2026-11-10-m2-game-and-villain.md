# M2 Game State and Villain Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A heads-up hand engine plus a rule-based Villain whose single strategy generates lines, narrows ranges and predicts responses, with a competence report proving the four profiles play sensibly.

**Architecture:** `poker_trainer.game` holds an immutable heads-up hand state with chip accounting and legal actions. `poker_trainer.villain` computes per-combo hand features for a board, maps them to categories with versioned thresholds, loads versioned JSON profiles, and turns profile + state into a probability for every concrete legal action per combo (one function, used for sampling, narrowing and response prediction). `poker_trainer.analysis.competence` simulates lines and checks bluff share, defence frequency and dominated lines per profile.

**Tech Stack:** Python 3.13, numpy, pytest, hypothesis (property tests), uv. Builds on M1 `poker_trainer.engine`.

**Spec:** `docs/superpowers/specs/2026-11-10-poker-puzzle-trainer-design.md` (§3 table format, §4 Hero options, §5 Villain model, §7 generation, §8 grading inputs, §12 accuracy). Roadmap: `docs/superpowers/plans/2026-11-10-roadmap.md`.

## Global Constraints

- Heads-up, blinds 1/2, 100bb effective stacks → **chips are ints, SB = 1, BB = 2, starting stack = 200**. Button = small blind, acts first pre-flop and last post-flop.
- **One policy, used three ways** (spec §5): line generation, range narrowing and response prediction all go through `action_distribution` (Task 4). No second copy of frequencies anywhere.
- Villains are competent, thinking players; profiles vary style, not competence (spec §5).
- Profiles and category thresholds are versioned data files, not code (spec §5, §7.8).
- Narrowing never increases a weight; the revealed hand always has non-zero weight in the final range (spec §12).
- Chips are conserved: `sum(stacks) + pot + sum(street_bets)` equals the starting total in every state (spec §12).
- No LLM anywhere. pokerkit stays test-only. Works on Windows and macOS; commands run from `backend/`.
- M1 interfaces used as-is: card ids `rank*4+suit`; `evaluate()` lower-is-stronger; `Range` = float64 `(1326,)` over `COMBOS`; `parse_range`, `remove_blocked`, `full_range`, `total_weight`, `combo_index`, `COMBOS`, `hand_class`, `HandClass`, `equity_by_combo`.

## Decisions made in this plan

- **Pre-flop tree.** BTN opens (any non-all-in raise) or folds; competent HU players don't limp. BB facing a non-all-in open: fold / call / 3-bet; BB facing an open-jam: fold / call. BTN facing a non-all-in 3-bet: fold / call / jam; BTN facing a 3-bet jam: fold / call. BB facing a jam 4-bet: fold / call. Spot detection: any non-all-in raise counts as the open/3-bet of that level; an all-in raise is the jam spot. A BTN limp or a non-all-in 4-bet raises `UnsupportedSpot`; M3 offers Hero only all-in as a pre-flop 4-bet and no limp. Range weights for later spots are conditional on reaching that spot.
- **Sizing (shared with M3):** `bet_to(s, frac)` and `raise_to(s, mult)` are the only sizing code. Villain bets 33% / 75% pot and raises 3× the bet faced; pre-flop open is `raise_to(s, 2.5)` (to 5) and 3-bet `raise_to(s, 3)` (to 15). Amounts round to whole chips, clamp to `[min_to, max_to]`, and become all-in when `to >= 0.6 * max_to`.
- **Policy over concrete actions.** Keys (`bet_33`, `bet_75`, …) are resolved to `Action`s and keys resolving to the same `Action` are merged (probabilities summed) — narrowing and sampling use the merged distribution, so the posterior is correct when two sizes clamp to the same amount.
- **Roles.** Post-flop unopened spots use a role: `cbet` (seat was the last aggressor on the previous street), `lead` (not the aggressor, first to act), `stab` (not the aggressor, acting after a check). Facing spots: `facing_bet` (first bet of the street) and `facing_raise` (any raise). Tables are per role, not per street.
- **Facing-bet size scaling** is order-preserving: `continue(f) = base_continue ** ((1 + f) / 1.5)` (identity at half pot; 1 stays 1, 0 stays 0), `f = amount_to_call / (total_pot - amount_to_call)`. Call/raise keep their base ratio inside continue.
- **SPR** is measured at the start of the street: `min(stack_i + street_bet_i) / pot` (post-flop only). If ≤ 1.0 and category ≥ MEDIUM (or STRONG_DRAW), fold → 0.
- **Categories** come from strength percentile, "beaten-by" share and draw outs, with thresholds in versioned `categories.json` (tunable in Task 6).
- **Hero's earlier actions** use the same `action_distribution` with `HERO_PROFILE = "tag"` — no separate Hero policy module (roadmap commit "default Hero policy" folds into Task 4).
- **Display/grading blockers:** `RangeTracker` stores Villain's range from Villain's own perspective (board blockers removed when post-flop features apply, Hero's cards never removed). M3 applies `remove_blocked(hero + board)` to every displayed and graded step so displayed ≡ graded.

## Review Focus

1. All-in states: once a player is all-in and the bet is matched, no one is asked to act, `legal_actions` raises, and the hand only needs board cards. Test in Task 1.
2. Short all-in below a min-raise: allowed for the shover; the opponent can then only fold or call. Test in Task 1.
3. Bet sizing on tiny pots or short stacks: amounts never below the legal minimum or above the stack; two sizes that clamp to the same chips merge. Tests in Task 4.
4. Boards where the board itself makes a straight/flush: a card that only improves the board is not an out. Test in Task 2.
5. Facing a big jam with a medium hand: Villain can fold (the SPR rule uses start-of-street SPR). Test in Task 4.

---

### Task 1: Heads-up hand state

**Files:**
- Create: `backend/src/poker_trainer/game/__init__.py`, `backend/src/poker_trainer/game/state.py`
- Test: `backend/tests/game/test_state.py`

**Interfaces:**
- Consumes: `ensure_distinct` (engine.cards).
- Produces (all in `poker_trainer.game.state`):
  - `class Street(IntEnum): PREFLOP=0, FLOP=1, TURN=2, RIVER=3`
  - `class ActionKind(StrEnum): FOLD="fold", CHECK="check", CALL="call", BET="bet", RAISE="raise"`
  - `@dataclass(frozen=True) class Action: seat: int; kind: ActionKind; street: Street; to: int = 0` — `to` = the seat's total street contribution after a BET/RAISE/CALL (filled in for CALL by `apply`); 0 for FOLD/CHECK. Hashable and comparable by value.
  - `@dataclass(frozen=True) class Legal: fold: bool; check: bool; call: int; aggressive: ActionKind | None; min_to: int | None; max_to: int | None` — `fold` is True only when `call > 0`; `aggressive` is BET when nothing is bet this street, RAISE otherwise, None when no bet/raise is allowed; when the stack can't make a full min-raise, `min_to == max_to` (all-in).
  - `@dataclass(frozen=True) class HandState: button: int; stacks: tuple[int, int]; street_bets: tuple[int, int]; pot: int; street: Street; board: tuple[int, ...]; to_act: int | None; history: tuple[Action, ...]; last_raise: int; folded: int | None; total_chips: int`
  - `SB = 1; BB = 2; START_STACK = 200`
  - `new_hand(button: int, stacks: tuple[int, int] = (START_STACK, START_STACK)) -> HandState` — posts blinds (button posts SB; a stack smaller than its blind posts all-in), `to_act = button`.
  - `legal_actions(s) -> Legal` — `ValueError` if `s.to_act is None`.
  - `apply(s, a) -> HandState` — `ValueError("illegal action: ...")` for wrong seat or illegal kind/amount.
  - `needs_board(s) -> bool`, `deal(s, cards) -> HandState` (3 cards for flop, 1 otherwise; moves street bets into `pot`; `last_raise = BB`; `to_act` = non-button seat, or `None` if a player is all-in; duplicates → `ValueError`), `is_terminal(s) -> bool`.
  - `total_pot(s) -> int`, `amount_to_call(s) -> int`, `pot_odds(s) -> float` (= `call / (total_pot + call)`, 0.0 when nothing to call), `position_name(s, seat) -> str` (`"BTN"` / `"BB"`).
  - `last_aggressor(s, street: Street) -> int | None` — seat of the last BET/RAISE on that street.
- Rules: min bet = BB; min raise-to = current bet + `last_raise`; max = all-in. A full raise sets `last_raise = to - previous bet`. Re-raise rights are derived from `history`: a seat may raise unless the only aggression since its own last action is an all-in smaller than a full raise. Pre-flop the BB gets an option after the button calls.

- [ ] **Step 1: Write failing tests**
  - `test_new_hand_blinds`: `new_hand(0)` → stacks `(199, 198)`, street_bets `(1, 2)`, `to_act == 0`, `pot_odds == 1/4`, `legal.aggressive == RAISE`, `legal.min_to == 4`.
  - `test_chips_conserved_property` (hypothesis): random starting stacks in `[1, 300]`, random legal actions (amounts uniform in `[min_to, max_to]`), random distinct cards when `needs_board`, until terminal — every state has `sum(stacks) + pot + sum(street_bets) == total_chips`, stacks ≥ 0.
  - `test_preflop_bb_option`: button calls → `to_act == 1`, `check` True, `fold` False; BB checks → `needs_board`.
  - `test_min_raise`: button raises to 6 → BB `min_to == 10`, `max_to == 200`.
  - `test_short_allin_does_not_reopen`: `new_hand(0, stacks=(200, 9))`; button raises to 6; BB all-in to 9 (below full raise 10) → button `Legal.aggressive is None`, `call == 3`.
  - `test_short_stack_min_equals_max`: `new_hand(0, stacks=(200, 9))`; button raises to 6 → BB `min_to == max_to == 9`.
  - `test_allin_called_needs_only_board`: jam pre-flop, call → `to_act is None`, `needs_board`; after flop/turn/river deals, `is_terminal`; `legal_actions` raises `ValueError`.
  - `test_fold_terminal`, `test_postflop_order` (after flop deal `to_act == 1`), `test_last_aggressor` (button opens, BB calls → `last_aggressor(s, PREFLOP) == 0`).
  - `test_illegal_actions_raise`: wrong seat, check facing a bet, bet below BB, raise above stack, fold with nothing to call → `ValueError`.
  - `test_deal_rejects_duplicates`.
- [ ] **Step 2: Run** `uv run pytest tests/game -v` → FAIL (module missing).
- [ ] **Step 3: Implement `state.py`.**
- [ ] **Step 4: Run** → PASS; `uv run pytest -m "not slow"`, `uv run ruff check`, `uv run ruff format --check` green.
- [ ] **Step 5: Commit** `feat(game): heads-up hand state — blinds, pot/stack accounting, legal actions, street progression`

### Task 2: Hand features — strength, outs, categories, texture, SPR

**Files:**
- Create: `backend/src/poker_trainer/villain/__init__.py`, `backend/src/poker_trainer/villain/features.py`, `backend/src/poker_trainer/villain/categories.json`
- Test: `backend/tests/villain/test_features.py`

**Interfaces:**
- Consumes: `COMBOS`, `combo_index`; `evaluate`, `hand_class`, `HandClass`; `HandState`, `Street` (Task 1).
- Produces (in `poker_trainer.villain.features`):
  - `class HandCategory(IntEnum): AIR=0, WEAK_DRAW=1, WEAK=2, MEDIUM=3, STRONG_DRAW=4, STRONG=5, NUTS=6` (ordered by how the strategy treats them).
  - `@dataclass(frozen=True) class RangeFeatures: board: tuple[int, ...]; strength: np.ndarray; beaten_by: np.ndarray; outs: np.ndarray` — `(1326,)` each; board-blocked combos: `strength = beaten_by = nan`, `outs = -1`.
  - `range_features(board: Sequence[int]) -> RangeFeatures` — board length 3, 4 or 5 else `ValueError`; cached with `functools.lru_cache(maxsize=256)` on `tuple(board)`.
  - `@dataclass(frozen=True) class CategoryThresholds: version: int; nuts_max_beaten: float; strong_min: float; strong_draw_outs: int; medium_min: float; weak_draw_outs: int; weak_min: float`
  - `load_thresholds() -> CategoryThresholds` (from `categories.json`, starting values: version 1, `nuts_max_beaten 0.005`, `strong_min 0.80`, `strong_draw_outs 8`, `medium_min 0.60`, `weak_draw_outs 4`, `weak_min 0.35`).
  - `categorize(f: RangeFeatures, t: CategoryThresholds) -> np.ndarray` — int8 `(1326,)`, -1 for blocked. Order of tests: NUTS if `beaten_by <= nuts_max_beaten`; STRONG if `strength >= strong_min`; STRONG_DRAW if `outs >= strong_draw_outs`; MEDIUM if `strength >= medium_min`; WEAK_DRAW if `outs >= weak_draw_outs`; WEAK if `strength >= weak_min`; else AIR.
  - `@dataclass(frozen=True) class BoardTexture: paired: bool; monotone: bool; two_tone: bool; connected: bool; wet: bool`; `board_texture(board) -> BoardTexture` — `monotone`: some suit has ≥ 3 board cards; `two_tone`: not monotone and some suit has exactly 2; `connected`: some 3 distinct ranks with `max - min <= 4` (ace also counts as low); `wet = monotone or two_tone or connected`.
  - `street_spr(s: HandState) -> float` — `min(stacks[i] + street_bets[i]) / s.pot`; `ValueError` pre-flop.
- Definitions: `strength[c]` = fraction of other live combos (board-blocked removed; mutual blocking ignored) whose current best hand is strictly worse, plus half of ties; `beaten_by[c]` = fraction strictly better. `outs[c]` = unseen cards x (not board, not in c) where `hand_class(evaluate(c+board+x)) >= STRAIGHT`, the current hand is below STRAIGHT, and — when board+x has ≥ 5 cards — `evaluate(c+board+x) < evaluate(best 5 of board+x)`. River: outs = 0.

- [ ] **Step 1: Write failing tests**
  - `test_blocked_combos_marked`: board `AhKd7c`, combo `AhAs` → nan strength/beaten_by, outs -1, category -1.
  - `test_flush_draw_overs_is_strong_draw`: board `Kh7h2c`, combo `AhQh` → outs 9, category `STRONG_DRAW`.
  - `test_pair_plus_flush_draw_is_strong_draw`: board `Kh7h2c`, combo `7h6h` → category `STRONG_DRAW`.
  - `test_gutshot_weak_draw`: board `Kh9d2c`, combo `QsJc` → outs 4, category `WEAK_DRAW`.
  - `test_top_set_is_nuts`: board `Kd7s2c`, combo `KhKc` → `NUTS`.
  - `test_overpair_not_nuts`: board `Kd7s2c`, combo `AsAc` → not NUTS (STRONG).
  - `test_tptk_not_nuts`: board `Kd7s2c`, combo `KsQc` → not NUTS.
  - `test_board_straight_not_out`: board `9c8d7h6s`, combo `2c2d` → outs 0.
  - `test_river_has_no_outs`; `test_strength_bounds` (in [0,1], mean ≈ 0.5 ± 0.01); `test_beaten_by_plus_strength_le_one`.
  - `test_texture`: `Kh7h2c` two_tone & wet; `Kd7s2c` dry; `9c8d7h` connected; `KhKd2c` paired; `Ah5h3h` monotone; `Ah5c4d3s` connected (ace low).
  - `test_street_spr`: after open to 5, call, flop dealt → `street_spr == 195 / 10`.
  - `test_features_fast`: `range_features` on a fresh flop < 0.5 s (cache cleared).
- [ ] **Step 2: Run** `uv run pytest tests/villain/test_features.py -v` → FAIL.
- [ ] **Step 3: Implement `features.py` and `categories.json`** (evaluate each live combo once, rank with numpy for strength/beaten_by; outs by evaluating each combo with each unseen card).
- [ ] **Step 4: Run** → PASS; fast suite + ruff green.
- [ ] **Step 5: Commit** `feat(villain): hand features — strength, outs, versioned categories, texture, SPR`

### Task 3: Profile data schema and the four profiles

**Files:**
- Create: `backend/src/poker_trainer/villain/profiles.py`, `backend/src/poker_trainer/villain/profiles/{tag,lag,tight,sticky}.json`
- Test: `backend/tests/villain/test_profiles.py`

**Interfaces:**
- Consumes: `parse_range`, `Range`, `total_weight`; `HandCategory` (Task 2).
- Produces (in `poker_trainer.villain.profiles`):
  - `PROFILE_NAMES = ("tag", "lag", "tight", "sticky")`
  - `@dataclass(frozen=True) class PreflopRanges: open: Range; bb_call: Range; bb_threebet: Range; bb_call_open_jam: Range; btn_call_threebet: Range; btn_jam: Range; btn_call_jam: Range; bb_call_jam: Range`
  - `@dataclass(frozen=True) class Bands: bluff_offset: tuple[float, float]; defence_ratio: tuple[float, float]`
  - `Table = dict[HandCategory, dict[str, float]]`
  - `@dataclass(frozen=True) class Profile: name: str; label: str; description: str; version: int; preflop: PreflopRanges; unopened: dict[str, Table]; facing: dict[str, Table]; bands: Bands` — `unopened` keyed by role `"cbet"`, `"lead"`, `"stab"` with action keys `check`, `bet_33`, `bet_75`; `facing` keyed `"facing_bet"`, `"facing_raise"` with keys `fold`, `call`, `raise` (written for a half-pot bet / a 3× raise).
  - `load_profile(name: str) -> Profile` (cached); unknown name → `ValueError`.
- JSON shape: `{"name", "label", "version", "description", "preflop": {8 range strings}, "unopened": {"cbet": {...7 categories}, "lead": {...}, "stab": {...}}, "facing": {"facing_bet": {...}, "facing_raise": {...}}, "bands": {"bluff_offset": [lo, hi], "defence_ratio": [lo, hi]}}`; every row sums to 1; all seven category names present.
- Descriptions (exact, shown on hover in the UI): TAG "Solid tight-aggressive regular: value-heavy, bluffs in balance." · LAG "Loose-aggressive: wide ranges, frequent pressure, more bluffs." · Tight "Tight and solid: narrow ranges, value-heavy, rarely bluffs." · Sticky "Competent, but defends wide and calls down lighter than most."
- Bands (starting values; Task 6 may tune, never just to pass): TAG bluff_offset `[-0.08, 0.08]`, defence `[0.85, 1.15]`; LAG `[-0.04, 0.12]`, `[0.85, 1.20]`; Tight `[-0.15, 0.02]`, `[0.70, 1.00]`; Sticky `[-0.10, 0.06]`, `[1.00, 1.35]`.
- Content guidance: realistic heads-up ranges for competent players (e.g. BTN opens ~70% TAG, ~85% LAG, ~55% Tight, ~70% Sticky; Sticky has the widest `bb_call`). Leads (`lead`) are rare for every profile; `facing_raise` folds most of MEDIUM and below and re-raises only STRONG/NUTS. Weights of later pre-flop spots are conditional on reaching the spot.

- [ ] **Step 1: Write failing tests**
  - `test_all_profiles_load` (label, description, `version >= 1`); `test_rows_sum_to_one` (every role/table row, all seven categories).
  - `test_nuts_never_fold`: every `facing` table has `NUTS.fold == 0`.
  - `test_leads_rare`: for every profile, mean over categories of `1 - lead.check` < mean of `1 - cbet.check`.
  - `test_facing_raise_tighter`: for each category ≤ MEDIUM, `facing_raise.fold >= facing_bet.fold`.
  - `test_range_widths_ordered`: open widths tight < tag < lag; sticky has the largest `bb_call`.
  - `test_preflop_ranges_consistent`: per combo `bb_call + bb_threebet <= 1`, `btn_call_threebet + btn_jam <= 1`.
  - `test_unknown_profile_raises`; `test_profiles_ship_as_package_data` (`importlib.resources.files("poker_trainer.villain") / "profiles"`).
- [ ] **Step 2: Run** `uv run pytest tests/villain/test_profiles.py -v` → FAIL.
- [ ] **Step 3: Implement `profiles.py` and the four JSON files.**
- [ ] **Step 4: Run** → PASS; fast suite + ruff green.
- [ ] **Step 5: Commit** `feat(villain): versioned profile data — TAG, LAG, Tight, Sticky`

### Task 4: Strategy — sizing, per-combo action distribution, sampling

**Files:**
- Create: `backend/src/poker_trainer/villain/strategy.py`
- Test: `backend/tests/villain/test_strategy.py`

**Interfaces:**
- Consumes: Task 1 API; `range_features`, `categorize`, `load_thresholds`, `board_texture`, `street_spr`, `HandCategory` (Task 2); `Profile`, `load_profile` (Task 3); `combo_index`.
- Produces (in `poker_trainer.villain.strategy`):
  - `ALLIN_FRACTION = 0.6`, `OPEN_MULT = 2.5`, `THREEBET_MULT = 3.0`, `RAISE_MULT = 3.0`, `HERO_PROFILE = "tag"`
  - `class UnsupportedSpot(ValueError)`
  - `bet_to(s: HandState, frac: float) -> Action` — `to = street_bet + round(frac * total_pot)`, clamped to `[min_to, max_to]`, all-in if `to >= ALLIN_FRACTION * max_to`; `ValueError` if betting isn't legal.
  - `raise_to(s: HandState, mult: float) -> Action` — `to = round(mult * current bet faced)`, same clamping/all-in rule; `ValueError` if raising isn't legal.
  - `allin(s) -> Action`.
  - `role(s: HandState) -> str` — post-flop: `"facing_raise"` if the street has ≥ 2 BET/RAISE actions, `"facing_bet"` if 1, else `"cbet"` / `"lead"` / `"stab"` per the Decisions.
  - `action_distribution(profile: Profile, s: HandState) -> dict[Action, np.ndarray]` — for `s.to_act`; keys are concrete legal Actions (keys that resolve to the same Action merged by summing); arrays `(1326,)`; for every combo not blocked by the board the values sum to 1; blocked combos all 0.
  - `sample_action(profile: Profile, s: HandState, hole: tuple[int, int], rng: random.Random) -> Action`.
- Pre-flop mapping (Decisions tree): BTN first → `raise_to(s, OPEN_MULT)` with `open`, fold rest. BB facing non-all-in open → `raise_to(s, THREEBET_MULT)` with `bb_threebet`, call with `bb_call`, fold rest; facing open-jam → call `bb_call_open_jam`. BTN facing non-all-in 3-bet → `allin` with `btn_jam`, call `btn_call_threebet`; facing 3-bet jam → call `btn_call_jam`. BB facing jam 4-bet → call `bb_call_jam`. Other pre-flop spots → `UnsupportedSpot`.
- Post-flop: category per combo via `categorize`; unopened roles → `check` / `bet_to(0.33)` / `bet_to(0.75)` from `profile.unopened[role]`; on a `wet` board STRONG_DRAW and WEAK_DRAW bet probabilities ×1.25 then renormalised. Facing → `fold` / `call` / `raise_to(RAISE_MULT)` from `profile.facing[role]`, scaled by `continue(f) = base ** ((1 + f) / 1.5)` for every category (NUTS rows have base continue 1); raise mass goes to call when raising isn't legal. SPR rule: `street_spr(s) <= 1.0` and category ∈ {MEDIUM, STRONG_DRAW, STRONG, NUTS} → fold mass moved to call.

- [ ] **Step 1: Write failing tests**
  - `test_distribution_sums_to_one`: every profile, on pre-flop BTN-first, BB-facing-open, a flop `cbet` spot, a flop `facing_bet` spot: unblocked combos sum to 1 (±1e-9), blocked all 0.
  - `test_preflop_open_matches_range`: TAG on `new_hand(0)`: the array for `Action(0, RAISE, PREFLOP, 5)` equals `tag.preflop.open`.
  - `test_unsupported_spots`: BTN limp → BB `UnsupportedSpot`; a non-all-in 4-bet → `UnsupportedSpot`.
  - `test_bet_to_values`: flop pot 10, stacks 195 → `bet_to(s, 0.33).to == 3`, `bet_to(s, 0.75).to == 8`; pot 4 → `bet_to(s, 0.33).to == 2` (min bet).
  - `test_allin_threshold`: hand-built flop state with pot 30 and the bettor 30 behind → `bet_to(s, 0.75).to == 30` (22 ≥ 18 → all-in).
  - `test_sizes_merge`: a state where 33% and 75% both clamp to the same `to` → the distribution has one bet Action whose array equals the sum of both table entries.
  - `test_bigger_bet_folds_more`: same flop spot facing 25% vs 100% pot — total fold weight over `tag.preflop.bb_call` is higher at 100%.
  - `test_strong_rarely_folds`: facing pot-size bet, max fold prob of STRONG combos ≤ 0.10 for every profile.
  - `test_nuts_never_fold_any_size`: facing 33/75/150% pot → NUTS fold 0.
  - `test_jam_into_small_pot_medium_can_fold`: flop pot 10, stacks 195/195, bettor jams → some MEDIUM combo has fold > 0.
  - `test_low_spr_commits_medium`: flop with start-of-street SPR ≤ 1 → MEDIUM fold 0.
  - `test_role_detection`: BTN opens, BB calls, flop: BB to act → `"lead"`; BB checks → BTN `"cbet"`; BTN checks back; turn: BB → `"lead"`; BB checks → BTN `"stab"` (BTN was not the flop aggressor); BTN bets → BB `"facing_bet"`; BB raises → BTN `"facing_raise"`.
  - `test_sample_action_deterministic_and_legal`: same seed → same Action; `apply` accepts it; a combo with `open == 0` never samples the open across 200 seeds.
- [ ] **Step 2: Run** `uv run pytest tests/villain/test_strategy.py -v` → FAIL.
- [ ] **Step 3: Implement `strategy.py`.**
- [ ] **Step 4: Run** → PASS; fast suite + ruff green.
- [ ] **Step 5: Commit** `feat(villain): strategy — shared sizing, per-combo action distribution, sampling`

### Task 5: Range narrowing from the same strategy

**Files:**
- Create: `backend/src/poker_trainer/villain/narrowing.py`
- Test: `backend/tests/villain/test_narrowing.py`

**Interfaces:**
- Consumes: `action_distribution`, `sample_action` (Task 4); `full_range`, `remove_blocked`, `total_weight`, `Range`; Task 1 API.
- Produces (in `poker_trainer.villain.narrowing`):
  - `narrow(r: Range, dist: dict[Action, np.ndarray], action: Action) -> Range` — `r * dist[action]` (new array); `KeyError`-free: an action not in `dist` → `ValueError("action not available")`; zero total weight → `ValueError("action has zero probability for every combo in range")`.
  - `describe(action: Action, s: HandState) -> str` — `"Pre-flop: opens to 5"`, `"Pre-flop: 3-bets to 15"`, `"Pre-flop: calls"`, `"Flop: bets 8 (75% pot)"`, `"Turn: checks"`, `"River: raises to 60"`, `"Flop: goes all-in"`; percent = `(to - street_bet) / total_pot` rounded to whole %.
  - `@dataclass(frozen=True) class RangeStep: label: str; street: Street; action: Action | None; range: Range`
  - `class RangeTracker: __init__(self, profile: Profile, seat: int)`; `observe(self, s: HandState, action: Action) -> RangeStep` (state *before* the action; `ValueError` if `s.to_act != seat`); `steps: list[RangeStep]` (first: label `"Start"`, `full_range()`); `current: Range`.

- [ ] **Step 1: Write failing tests**
  - `test_narrow_never_increases` (hypothesis): element-wise `narrowed <= original`.
  - `test_narrow_zero_raises`; `test_narrow_unknown_action_raises`.
  - `test_tracker_matches_strategy`: BTN open tracked → `current == tag.preflop.open`.
  - `test_revealed_hand_in_range_property` (hypothesis, ≤ 50 examples, seeded): random hands, both seats play via `sample_action` (profiles random), tracking seat 1, until terminal or `UnsupportedSpot`; the actual seat-1 combo's final weight `> 0` and equals the product of `action_distribution(...)[action][combo]` over its actions (rel. tol 1e-9).
  - `test_labels`: BTN open → BB call → flop BB check → BTN `bet_to(0.75)` tracked for seat 0 → labels `["Start", "Pre-flop: opens to 5", "Flop: bets 8 (75% pot)"]`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS; fast suite + ruff green.
- [ ] **Step 5: Commit** `feat(villain): range narrowing from the same strategy`

### Task 6: Competence report and tuning

**Files:**
- Create: `backend/src/poker_trainer/analysis/__init__.py`, `backend/src/poker_trainer/analysis/competence.py`
- Modify (tuning only, bump `version` on change): the four profile JSONs, `categories.json`
- Test: `backend/tests/analysis/test_competence.py`

**Interfaces:**
- Consumes: Tasks 1–5; `equity_by_combo` not required — river equity vs a range is computed from per-combo hand ranks.
- Produces (in `poker_trainer.analysis.competence`):
  - `@dataclass(frozen=True) class CheckResult: profile: str; name: str; value: float; band: tuple[float, float]; passed: bool; samples: int`
  - `competence_report(profile_name: str, n_hands: int = 400, seed: int = 0) -> list[CheckResult]`
  - `main(argv: list[str] | None = None) -> int` — CLI `uv run python -m poker_trainer.analysis.competence [--profile NAME|all] [--hands N]`; prints a table; returns 1 if any check fails.
- Method: simulate `n_hands` hands, profile under test as Villain vs `HERO_PROFILE` on the other seat (alternate seats), both via `sample_action`, tracking both ranges. At each Villain decision on flop/turn/river collect: Villain's tracked range, Hero's tracked range, the distribution. Checks:
  - `bluff_share_33`, `bluff_share_75` (river, unopened): within the weight betting that size, the share whose equity vs the opponent's *calling* range (opponent's tracked range × its call+raise probabilities facing that bet, from `action_distribution` on the resulting state) is < 0.5. Band = `f/(1+2f)` (0.20 / 0.30) + `bands.bluff_offset`.
  - `defence_flop`, `defence_turn`, `defence_river` (facing a bet): continue weight / range weight divided by MDF `1/(1+f)`, averaged over spots. Band = `bands.defence_ratio`.
  - `nuts_fold_max` band `(0, 0)`; `strong_fold_max` facing ≥ pot-size bets band `(0, 0.10)`; `air_call_max` river facing ≥ 75% band `(0, 0.10)`.
  - `thin_value_dominated` (river): share of value bets (strength ≥ medium) whose equity vs the calling range < 0.4; band `(0, 0.10)`.
  - Every check reports `samples`; a check with < 30 samples is reported as failed ("insufficient samples").

- [ ] **Step 1: Write failing tests**
  - `test_report_shape`: `competence_report("tag", n_hands=40)` returns the 10 named checks with `profile == "tag"`.
  - `@pytest.mark.slow test_all_profiles_competent`: every profile at `n_hands=400` passes every check.
  - `test_cli_header`: `main(["--profile", "tag", "--hands", "40"])` returns 0 or 1 and prints `bluff_share_75`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement `competence.py`.**
- [ ] **Step 4: Tune.** Run `uv run python -m poker_trainer.analysis.competence --profile all --hands 400`; adjust profile/category JSON until every check passes. Never widen bands just to pass — if a band looks wrong, report it. Bump versions of changed files. Paste the final table into the task report.
- [ ] **Step 5: Run** `uv run pytest -m "slow or not slow" tests/analysis tests/villain` → PASS; fast suite + ruff green.
- [ ] **Step 6: Commit** `feat(analysis): competence report and tuned profiles`
- [ ] **Step 7:** Controller hands the final table to the user for sign-off at the end of the milestone.

## Open items for M3 (from the M2 final review)

- **Blocked combos:** one helper applies `remove_blocked(range, board + hero_hole)` to the tracked range. Use it for both the displayed range and the graded range so they stay identical. `RangeTracker.current` is never filtered by Hero's cards.
- **Pot accounting:** use `total_pot` at showdown and for fold wins. When grading a bet that Villain folds to, the money won is the pot before the bet. `amount_to_call` and `pot_odds` return 0 when nobody is to act.
- **Pre-flop sizes:** Hero pre-flop sizes are limited to opening 2.5x or 3x, 3-betting, calling, folding and going all-in. `UnsupportedSpot` means the puzzle is regenerated.
- **Canonical actions:** pass the canonical `Action` objects (the keys of `action_distribution`, or `history[-1]`) to narrowing and response prediction. `apply` now rejects calls, folds and checks whose `to` amount isn't the canonical one.
- **Persist puzzles, not seeds:** store the full frozen puzzle (cards, actions, profile and its version, categories version), not just the seed. Floating-point maths can differ slightly between Windows and macOS.
- **Simplifications to show the learner:**
  - pre-flop responses ignore the raise size;
  - STRONG folds about 34% to oversized jams;
  - MEDIUM raises a bet fairly often;
  - Villain bets only 19–25% when checked to on the river (pending user sign-off).
- **Command entry point:** add `[project.scripts]` for the competence CLI when M3 touches `pyproject.toml`.
- **Possible future check:** whether MEDIUM raises are dominated.
