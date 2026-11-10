# M1 Engine Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A tested Python poker maths core: cards, hand evaluation, combos, weighted ranges, and equity vs a weighted range.

**Architecture:** A `poker_trainer.engine` package with one module per concept. Cards are ints 0–51; ranges are numpy arrays of 1326 combo weights; equity is exact on turn/river and Monte Carlo on flop/pre-flop with a reported standard error. `phevaluator` does 7-card evaluation behind our own wrapper.

**Tech Stack:** Python 3.13, uv, phevaluator 0.6, numpy, pytest, hypothesis, ruff, pokerkit (dev-only, cross-check).

**Spec:** `docs/superpowers/specs/2026-11-10-poker-puzzle-trainer-design.md` (§3, §6, §12). Roadmap: `docs/superpowers/plans/2026-11-10-roadmap.md`.

## Global Constraints

- Python `>=3.13`; dependencies managed by `uv` with `backend/pyproject.toml` and one `backend/uv.lock` valid for Windows and macOS. Per-OS differences use PEP 508 markers, never separate requirements files.
- No bash- or PowerShell-only scripts; every command below is runnable as written on both OSes from `backend/`.
- Hand evaluator: `phevaluator`. `eval7` must not be used.
- `pokerkit` is a dev dependency only (tests), never imported by `poker_trainer`.
- No LLM involvement anywhere in this milestone.
- Equity error: exact on turn and river; Monte Carlo standard error ≤ 0.25 percentage points (so ±0.5pt at ~95%).
- Performance: one equity call on any street returns in < 1 s on a laptop.
- CI: GitHub Actions on `windows-latest` and `macos-latest`.

## Decisions made in this plan (deviations/details beyond the spec)

- **Pre-flop equity uses Monte Carlo at runtime**, not a precomputed 169×169 table: exact blocker handling, meets the ±0.5pt bound, no data file. (Spec §6 allowed approximating; this is more accurate.)
- **Flop equity uses Monte Carlo** (exact flop enumeration is ~2M evaluations in Python, too slow).
- **"Ahead now" definition:** post-flop = weighted fraction of Villain combos Hero's current best hand beats (ties count half). Pre-flop = the same idea with hole cards only (pair beats unpaired, then high cards), so "22 vs AK" counts as ahead and "AK vs QQ" as behind. Not computed on the river (spec hides it there).
- **pokerkit cross-check scale:** 50 single-combo flop spots + 4 pre-flop references, not "thousands of hand-vs-range spots" (spec §12). pokerkit has no weighted ranges; weighted-range logic is checked exactly against the independent brute force on turn spots.
- **Pre-flop reference values** replaced by pokerkit-confirmed values (0.814 / 0.461 / 0.525 / 0.739).
- **Slow cross-checks run on ubuntu** on main/schedule/dispatch only (CI cost on a private repo); fast tests run on windows + macos for every PR.
- **Open item for M3:** `class_grid` averages over all combos in a class, so a class partly blocked by Hero's cards shows a lower weight; M3 decides whether the display averages over unblocked combos only.

## Review Focus

1. Duplicate cards (hero card also on board, villain combo overlapping) → `ValueError`, never silently wrong maths. Tests in Tasks 2 and 6.
2. Range fully blocked by dead cards (all weight removed) → `ValueError("range is empty after removing blocked combos")`, never NaN. Test in Task 6.
3. Range strings with odd spacing/case or invalid tokens (`"qq+ , aks"`, `"AKx"`) → parse correctly / raise `ValueError` naming the token. Tests in Task 5.
4. Split pots → count half to each player. Test in Task 6.
5. Board of illegal length (1, 2 or 6 cards) → `ValueError`. Test in Task 6.

---

### Task 1: Scaffold backend package and CI

**Files:**
- Create: `.gitignore`, `.gitattributes`, `backend/pyproject.toml`, `backend/src/poker_trainer/__init__.py`, `backend/src/poker_trainer/engine/__init__.py`, `backend/tests/test_smoke.py`, `.github/workflows/ci.yml`

**Interfaces:**
- Produces: importable package `poker_trainer` with `__version__ = "0.1.0"`; `uv run pytest` and `uv run ruff check` work from `backend/`.

- [ ] **Step 1: Install uv if missing** — Windows: `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`; macOS: `curl -LsSf https://astral.sh/uv/install.sh | sh`. Verify `uv --version`.
- [ ] **Step 2: Write `backend/pyproject.toml`** — src layout, `requires-python = ">=3.13"`, deps `phevaluator>=0.6,<0.7`, `numpy>=2`; dev group `pytest`, `hypothesis`, `ruff`, `pokerkit>=0.7,<0.8`; pytest config `markers = ["slow: long-running ground-truth tests"]`, `testpaths = ["tests"]`; ruff line-length 100.
- [ ] **Step 3: `.gitattributes`** — `* text=auto eol=lf`, plus `*.ps1 text eol=crlf`. `.gitignore` — Python (`.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`), Node (`node_modules/`, `dist/`), `.env`, `*.db`.
- [ ] **Step 4: Write the smoke test**

```python
import poker_trainer

def test_package_imports():
    assert poker_trainer.__version__ == "0.1.0"
```

- [ ] **Step 5: Run** `uv sync` then `uv run pytest` → 1 passed; `uv run ruff check` → no errors. Confirm `uv.lock` is created.
- [ ] **Step 6: CI workflow** — matrix `os: [windows-latest, macos-latest]`, `astral-sh/setup-uv`, working-directory `backend`, run `uv sync --locked`, `uv run ruff check`, `uv run pytest -m "not slow"`, and a second step `uv run pytest -m slow`.
- [ ] **Step 7: Commit**

```bash
git add .gitignore .gitattributes .github backend
git commit -m "chore: scaffold backend package, uv, ruff, pytest, CI (windows + macos)"
```

### Task 2: Cards and deck

**Files:**
- Create: `backend/src/poker_trainer/engine/cards.py`
- Test: `backend/tests/engine/test_cards.py`

**Interfaces:**
- Produces:
  - `RANKS = "23456789TJQKA"`, `SUITS = "cdhs"`; card id `= rank_index * 4 + suit_index` (matches phevaluator's encoding — verified in Task 3).
  - `parse_card(s: str) -> int` (case-insensitive rank and suit: `"ah"`, `"Ah"` → same id)
  - `card_str(c: int) -> str` (`"Ah"` form)
  - `parse_cards(s: str) -> tuple[int, ...]` (accepts `"AhKs"`, `"Ah Ks"`, `"ah,ks"`); raises `ValueError` on duplicates.
  - `rank_of(c: int) -> int`, `suit_of(c: int) -> int`
  - `class Deck: __init__(self, rng: random.Random, dead: Iterable[int] = ()); deal(self, n: int) -> tuple[int, ...]; remaining(self) -> list[int]`
  - `ensure_distinct(*groups: Iterable[int]) -> None` — raises `ValueError("duplicate card: Xx")`.

- [ ] **Step 1: Write failing tests** — `test_roundtrip_all_52` (every id 0..51 round-trips through `card_str`/`parse_card`, all 52 strings distinct); `test_parse_card_ids` (`parse_card("2c") == 0`, `parse_card("As") == 51`, `parse_card("ah") == parse_card("Ah") == 50`); `test_parse_cards_separators` (`parse_cards("Ah Ks") == parse_cards("ah,ks") == parse_cards("AhKs")`); `test_parse_invalid` (`"1h"`, `"Ax"`, `"A"` raise `ValueError`); `test_parse_cards_duplicate_raises` (`"AhAh"`); `test_deck_respects_dead` (deck with dead `AhKs` never deals them across 100 seeds; `len(remaining()) == 50`); `test_deck_deterministic` (same seed → same deal); `test_ensure_distinct` (`ensure_distinct((50,), (50, 1))` raises with message containing `"Ah"`).
- [ ] **Step 2: Run** `uv run pytest tests/engine/test_cards.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement `cards.py`** to the interfaces above.
- [ ] **Step 4: Run** same command → all PASS.
- [ ] **Step 5: Commit** `feat(engine): card encoding, parsing and deck`

### Task 3: Evaluator wrapper and ground-truth census

**Files:**
- Create: `backend/src/poker_trainer/engine/evaluator.py`
- Create: `backend/tests/reference/naive_eval.py` (independent slow evaluator, tests only)
- Test: `backend/tests/engine/test_evaluator.py`

**Interfaces:**
- Consumes: card ids from Task 2.
- Produces:
  - `evaluate(cards: Sequence[int]) -> int` — 5, 6 or 7 cards; **lower is stronger**, 1 = royal flush, 7462 = worst high card (phevaluator scale). If phevaluator 0.6 returns a rank object, unwrap to `int` here.
  - `class HandClass(IntEnum): STRAIGHT_FLUSH=8, FOUR_OF_A_KIND=7, FULL_HOUSE=6, FLUSH=5, STRAIGHT=4, THREE_OF_A_KIND=3, TWO_PAIR=2, PAIR=1, HIGH_CARD=0`
  - `hand_class(rank: int) -> HandClass` — boundaries: ≤10 SF, ≤166 quads, ≤322 FH, ≤1599 flush, ≤1609 straight, ≤2467 trips, ≤3325 two pair, ≤6185 pair, else high card.
  - tests-only `naive_eval.best_hand_key(cards: Sequence[int]) -> tuple` — larger is stronger; best of all 5-card subsets, written from scratch (category, then kickers; wheel A-2-3-4-5 handled).

- [ ] **Step 1: Write failing tests**
  - `test_encoding_matches_phevaluator`: `evaluate(parse_cards("AhKhQhJhTh")) == 1`; `hand_class(evaluate(parse_cards("5c4d3h2sAs"))) == HandClass.STRAIGHT`; `evaluate(parse_cards("7c5d4h3s2c")) == 7462`.
  - `test_lower_is_stronger`: quads AAAA K < full house.
  - `@pytest.mark.slow test_five_card_census`: over all `itertools.combinations(range(52), 5)` count `hand_class(evaluate(h))`; assert exactly `{SF: 40, QUADS: 624, FH: 3744, FLUSH: 5108, STRAIGHT: 10200, TRIPS: 54912, TWO_PAIR: 123552, PAIR: 1098240, HIGH: 1302540}`.
  - `test_matches_naive_on_random_7card`: 20,000 random pairs of 7-card hands (seeded) — `sign(evaluate(b) - evaluate(a)) == sign(cmp(naive(a), naive(b)))`.
- [ ] **Step 2: Run** `uv run pytest tests/engine/test_evaluator.py -v` → FAIL.
- [ ] **Step 3: Implement `evaluator.py`** (thin wrapper; check phevaluator 0.6's API — `from phevaluator import evaluate_cards`) **and `naive_eval.py`**.
- [ ] **Step 4: Run** `uv run pytest tests/engine/test_evaluator.py -v -m "slow or not slow"` → all PASS (census may take ~10–30 s).
- [ ] **Step 5: Commit** `feat(engine): phevaluator wrapper with hand classes and ground-truth census`

### Task 4: Combos and 169 hand classes

**Files:**
- Create: `backend/src/poker_trainer/engine/combos.py`
- Test: `backend/tests/engine/test_combos.py`

**Interfaces:**
- Produces:
  - `COMBOS: tuple[tuple[int, int], ...]` — all 1326 `(hi, lo)` with `hi > lo`, fixed order.
  - `combo_index(a: int, b: int) -> int` (order-insensitive)
  - `HAND_CLASSES: tuple[str, ...]` — 169 labels (`"AA"`, `"AKs"`, `"AKo"`, …) in grid order: row = first rank, col = second rank, A high at index 0; suited above the diagonal, offsuit below.
  - `class_of_combo(i: int) -> str`; `combos_of_class(label: str) -> tuple[int, ...]` (pairs 6, suited 4, offsuit 12).
  - `grid_position(label: str) -> tuple[int, int]` (row, col) in the 13×13 grid.

- [ ] **Step 1: Write failing tests** — `len(COMBOS) == 1326` and unique; `combo_index` round-trips all 1326 and is order-insensitive; `len(HAND_CLASSES) == 169`; class combo counts 6/4/12 summing to 1326; `grid_position("AA") == (0, 0)`, `grid_position("AKs") == (0, 1)`, `grid_position("AKo") == (1, 0)`, `grid_position("22") == (12, 12)`.
- [ ] **Step 2: Run** `uv run pytest tests/engine/test_combos.py -v` → FAIL.
- [ ] **Step 3: Implement `combos.py`.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(engine): 1326 combos and 169 hand classes`

### Task 5: Weighted ranges

**Files:**
- Create: `backend/src/poker_trainer/engine/ranges.py`
- Test: `backend/tests/engine/test_ranges.py`

**Interfaces:**
- Consumes: `COMBOS`, `combos_of_class`, `grid_position` (Task 4).
- Produces:
  - `Range = numpy.ndarray` (shape `(1326,)`, float64, values in [0, 1]) — documented alias.
  - `empty_range() -> Range`, `full_range() -> Range`
  - `parse_range(text: str) -> Range` — comma-separated tokens; supports `QQ`, `QQ+`, `22-55`, `AKs`, `AKo`, `AK` (both), `ATs+` (ATs..AKs), `A2s-A5s`, specific combos `AhKh`, and a weight suffix `:0.5` (e.g. `"AKo:0.5"`). Case- and whitespace-insensitive in ranks; suits lower-case. Unknown token → `ValueError` containing the token.
  - `remove_blocked(r: Range, dead: Iterable[int]) -> Range` — zero combos containing a dead card (returns a copy).
  - `total_weight(r: Range) -> float` — sum of weights.
  - `class_grid(r: Range) -> numpy.ndarray` — shape `(13, 13)`, each cell = mean weight of that class's combos.

- [ ] **Step 1: Write failing tests**
  - `test_parse_pairs_plus`: `QQ+` has weight 1 on exactly 18 combos.
  - `test_parse_suited_plus`: `ATs+` → 16 combos (ATs, AJs, AQs, AKs).
  - `test_parse_dash`: `A2s-A5s` → 16; `22-44` → 18.
  - `test_parse_specific_and_weight`: `"AhKh, AKo:0.5"` → weight 1.0 at `combo_index(AhKh)`, 0.5 on all 12 AKo combos, `total_weight == 7.0`.
  - `test_parse_whitespace_case`: `parse_range(" qq+ , aks ")` equals `parse_range("QQ+,AKs")`.
  - `test_parse_invalid_token`: `"AKx"` → `ValueError` with `"AKx"` in message; weight `":1.5"` → `ValueError`.
  - `test_remove_blocked`: `remove_blocked(parse_range("AA"), parse_cards("Ah"))` → total weight 3.
  - `test_class_grid`: `class_grid(parse_range("AKs"))[0, 1] == 1.0`, `[1, 0] == 0.0`; with `"AhKh"` only → `[0, 1] == 0.25`.
- [ ] **Step 2: Run** `uv run pytest tests/engine/test_ranges.py -v` → FAIL.
- [ ] **Step 3: Implement `ranges.py`.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(engine): weighted ranges — parsing, blockers, 13x13 grid`

### Task 6: Equity vs weighted range and ahead-now

**Files:**
- Create: `backend/src/poker_trainer/engine/equity.py`
- Test: `backend/tests/engine/test_equity.py`

**Interfaces:**
- Consumes: `evaluate` (Task 3), `COMBOS`/`combo_index` (Task 4), `Range`, `remove_blocked`, `total_weight` (Task 5), `ensure_distinct` (Task 2).
- Produces:
  - `@dataclass(frozen=True) class EquityResult: equity: float; win: float; tie: float; exact: bool; std_error: float` — fractions in [0, 1]; `equity = win + tie / 2`; `std_error == 0.0` when exact.
  - `equity_vs_range(hero: tuple[int, int], board: Sequence[int], villain: Range, *, rng: random.Random | None = None, samples: int = 40_000) -> EquityResult` — board length 0, 3, 4 or 5, otherwise `ValueError`. River/turn exact (weighted over unblocked combos and all remaining cards). Pre-flop/flop Monte Carlo: sample a villain combo ∝ weight among unblocked combos, then the remaining board cards uniformly from the rest.
  - `equity_by_combo(hero, board, villain) -> numpy.ndarray` — per-combo equity (exact; only for turn/river, `ValueError` otherwise). Used later for range breakdowns.
  - `ahead_now(hero: tuple[int, int], board: Sequence[int], villain: Range) -> float` — weighted fraction of unblocked combos where Hero's current hand beats the combo's current hand, ties = half. Post-flop (3 or 4 board cards): compare best hands made with the board. Pre-flop: compare the two hole cards as a 2-card hand (pair beats unpaired; then higher pair or higher cards in order). River: `ValueError("ahead_now is not used on the river")`.
  - Errors: duplicates between hero and board → `ValueError`; range empty after blockers → `ValueError("range is empty after removing blocked combos")`.

- [ ] **Step 1: Write failing tests**
  - `test_river_exact_simple`: hero `AhAd`, board `AsKd7c3h2s`, villain `parse_range("KK")` → `equity == 1.0`, `exact is True`.
  - `test_river_split`: hero `2c3d`, board `AhKhQhJhTh`, villain `"44"` → `equity == 0.5`, `tie == 1.0`.
  - `test_turn_exact_outs`: hero `AhKh`, board `QhJh2c3d`, villain `parse_range("3c3s")` (set of threes). Hero's outs: hearts `Th 9h 8h 7h 6h 5h 4h` (7; `2h` and `3h` are excluded because they give Villain a full house or quads) plus `Tc Td Ts` for the straight (3) → 10 outs of 44 unseen cards. Assert `abs(equity - 10/44) < 1e-9` and `exact is True`.
  - `test_monte_carlo_reports_error`: pre-flop `AhAd` vs `"KK"` → `exact is False`, `std_error <= 0.0025`, `0.80 < equity < 0.84`.
  - `test_deterministic_with_seed`: same `random.Random(1)` → identical results.
  - `test_duplicate_cards_raise`: hero card on board → `ValueError`.
  - `test_blocked_range_raises`: hero `AhAd`, board `AsAcKd`, villain `"AA"` → `ValueError` with `"range is empty"`.
  - `test_bad_board_length`: boards of length 1, 2, 6 → `ValueError`.
  - `test_ahead_now_flop`: hero `AhKd`, board `Ac7s2d`, villain `parse_range("QQ, 77")` → ahead of QQ (6 combos), behind 77 (3 combos unblocked) → `abs(result - 6/9) < 1e-9`.
  - `test_ahead_now_preflop`: hero `2c2d` vs `parse_range("AKo, 33")` → ahead of 12 AKo, behind 6 of 33 → `abs(result - 12/18) < 1e-9`; hero `AhKd` vs `"AsKc"` → `0.5` (tie).
  - `test_ahead_now_river_raises`.
  - `test_equity_weights_respected`: villain `"KK, QQ:0.5"` equity equals the weight-averaged exact equities from `equity_by_combo` on a turn board.
- [ ] **Step 2: Run** `uv run pytest tests/engine/test_equity.py -v` → FAIL.
- [ ] **Step 3: Implement `equity.py`.** For turn/river, evaluate Hero once per runout and reuse across villain combos. MC `std_error = sqrt(p(1-p)/n)` using per-sample showdown share.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(engine): equity vs weighted range and ahead-now fraction`

### Task 7: Equity cross-checks and benchmark

**Files:**
- Create: `backend/tests/engine/test_equity_crosscheck.py`
- Create: `backend/tests/reference/naive_equity.py` (brute-force equity using `naive_eval`)

**Interfaces:**
- Consumes: `equity_vs_range` (Task 6), `naive_eval.best_hand_key` (Task 3), `pokerkit` (dev).
- Produces: no runtime code.

- [ ] **Step 1: Write tests**
  - `test_reference_preflop_matchups` (MC, seeded, tolerance ±1.0pt): `AhAs` vs `KdKc` ≈ 0.82; `AhKh` vs `QQ` ≈ 0.46; `2c2d` vs `AKo` ≈ 0.52; `AhKd` vs `AsQc` ≈ 0.74 (implementer: confirm each reference value with pokerkit in the same test file and record the pokerkit number in a comment).
  - `test_matches_naive_bruteforce`: 30 random turn spots (seeded) with 3–10 combo ranges → `equity_vs_range` equals `naive_equity` within 1e-9.
  - `@pytest.mark.slow test_matches_pokerkit_random_flops`: 50 random flop spots (hero hand vs a single random villain combo) — our MC equity within 1.0pt of pokerkit `calculate_equities` (check pokerkit 0.7 docs, "Statistical Analysis" page, for the call signature and use ≥ 20,000 samples there).
  - `test_mc_error_bound_honest`: run 20 seeded pre-flop MC estimates of `AhAs` vs `KdKc`; ≥ 18 fall within `2 * std_error` of their mean.
  - `test_benchmark_under_one_second`: flop equity vs a 200-combo range (`parse_range("22+, A2s+, KTs+, QTs+, JTs, ATo+, KJo+")`) and pre-flop vs the same range each complete in < 1.0 s (`time.perf_counter`). Mark `slow` if it flakes on CI runners; keep the assertion.
- [ ] **Step 2: Run** `uv run pytest tests/engine/test_equity_crosscheck.py -v -m "slow or not slow"` → PASS. If any reference value fails, fix the engine, not the tolerance.
- [ ] **Step 3: Run the full suite** `uv run pytest -m "slow or not slow"` and `uv run ruff check` → all green.
- [ ] **Step 4: Commit** `test(engine): equity reference values, brute-force and pokerkit cross-checks, benchmark`
- [ ] **Step 5: Push and confirm CI is green on both OSes** — `git push`, then `gh run watch`.
