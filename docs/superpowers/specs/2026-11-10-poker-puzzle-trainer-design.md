# Poker Puzzle Trainer — Design

Date: 2026-11-10
Status: draft for approval
Replaces: the temporary "Poker Puzzle Trainer – Project Spec.md"

## 1. Intent

A chess.com-puzzles-style trainer for No-Limit Texas Hold'em. Each puzzle drops the user into a hand at a decision point, shows everything a player at the table would see, and asks for an equity estimate and an action. Code grades the decision against Villain's range and teaches *why*.

The user plays home games and low-stakes live games, dabbling online. Their honest weak spot is **range reading**: they have a rough idea of what opponents hold, but not a good one, and so their equity and odds estimates are shaky too.

**Success** = the user's decision-making improves and they get better at estimating EV in real spots. The headline metric is **EV lost per decision, in big blinds**, trending toward zero over time.

## 2. Goals, non-goals, anti-goals

**Goals**
- Train all three linked skills — range reading, equity estimation, pot odds / EV — and report on all three after every puzzle, with the deepest breakdown on ranges.
- Grade by EV loss, not just right/wrong, so small and big mistakes are distinguished.
- Show the maths step by step, so the user learns to do the calculation, not just see the answer.
- A polished, real-feeling poker table UI from the first usable version.
- Progress tracking from day one.
- Works on Windows and macOS for development.
- Hostable later without a rewrite.

**Non-goals (for now)**
- GTO / solver-accurate answers. The engine is rule-based and approximate; it says so where it approximates.
- User accounts, auth, payments, multi-tenant hosting.
- Mobile-first layout (desktop browser is primary; should not break on a laptop screen).
- Hand-history import from real sites.

**Anti-goals (would make it a failure even if it "works")**
- Any equity, pot odds or EV number produced by an LLM.
- Villain's revealed hand inconsistent with the line it took.
- The displayed range disagreeing with the range actually used for grading.
- Grading on the result (who won the run-out) instead of the decision against the range.
- An endless stream of trivial puzzles (holding the nuts, obvious folds).

## 3. Constraints and decisions

### Tech stack (Claude's call, the user delegated it)
- **Backend:** Python 3.13, FastAPI, Pydantic models.
- **Hand evaluation:** `phevaluator` (perfect-hash evaluator, native wheels for Windows and Apple-silicon macOS on 3.13; pure-Python fallback elsewhere). `eval7` was rejected: no wheels for 3.13 and stale.
- **Reference/cross-check:** `pokerkit` (maintained, has equity calculation and full game-rule engine). Used in tests to cross-check our equity numbers; may be used for betting-rule validation in Phase 2.
- **Equity engine:** our own, because we need *weighted* ranges (combos with frequencies 0–1), which none of the libraries support well. See §6.
- **Frontend:** React + TypeScript, built with Vite. Charts via a standard React chart library (builder's choice, e.g. Recharts).
- **Storage:** SQLite via SQLAlchemy (+ Alembic migrations), so Postgres is a config change for hosting.
- **Packaging:** `uv` with `pyproject.toml` and a single cross-platform `uv.lock` (Windows + macOS). If a dependency ever differs by OS, use PEP 508 platform markers in `pyproject.toml` rather than separate requirements files. Frontend uses `npm` with `package-lock.json`.
- **Cross-platform hygiene:** no bash- or PowerShell-only dev scripts; dev commands live in `package.json` scripts / Python entry points. `.gitattributes` normalises line endings.
- **Repo:** private GitHub repo `spandan3/poker-puzzle-trainer` (created).

### Hosting readiness
- All config via environment variables (`.env` for local), nothing hard-wired to the developer's machine.
- Every stored row has a `user_id` (a single default local user in the MVP), so multi-user later doesn't need a data migration of meaning.
- Production build: FastAPI serves the built frontend as static files; one process to deploy. A Dockerfile can come later.
- LLM is optional everywhere (see §9).

### Table format
- **Phase 1: heads-up.** Blinds 1/2, 100bb effective stacks. Hero and Villain alternate button.
- **Phase 2: five-handed** (UTG, CO, BTN, SB, BB), Hero in any seat. Starts with pots that end heads-up or three-way after pre-flop folds; larger multiway pots later. Same engine, approximations accepted and labelled.

## 4. The puzzle experience

1. The user sees a table: their hole cards, board so far, full action history by street, pot, stacks, amount to call, pot odds (toggleable), Villain's position, Villain profile (toggleable).
2. The user enters:
   - equity estimate (slider + number input), against Villain's *range*;
   - **range read** (optional, quick): "% of Villain's range I'm ahead of right now" — one number. Hidden on the river, where it equals equity. Scored like the equity guess (within 5 = great, 10 = good). This is how range reading is exercised without slowing puzzles down; the user explicitly did not want a detailed range input such as painting a grid;
   - action: fold / check / call / bet / raise (only legal ones enabled);
   - size if betting/raising: shortcuts 33%, 50%, 75%, pot (bets) or 2.5x / 3x / all-in (raises), plus custom;
   - intent: value / bluff / semi-bluff.
3. Submit → results view (§8) → next puzzle. Keyboard shortcuts for every action.
4. Endless stream; trivial puzzles are filtered out (§7).

**Later harder mode:** the user also guesses the EV of their chosen action. Not in the first release; the results view's step-by-step maths prepares for it.

## 5. Villain model and ranges (the core)

### Profiles
Villains are **competent, thinking players** — they value bet, bluff with sensible frequencies, and fold when beaten. Profiles vary style, not competence. Initial set (Claude's call, tunable):
- **TAG** — solid tight-aggressive regular.
- **LAG** — wider ranges, more aggression and bluffs.
- **Tight / nitty-solid** — narrower ranges, fewer bluffs, value-heavy.
- **Sticky** — competent but defends and calls down wider.

Profile is a data file (pre-flop ranges per position/action, per-street action frequencies by hand category, sizing preferences), not code.

### One policy, used three ways — the key consistency rule
Villain has a **strategy**: given a game state and a hand, it returns a probability for each action (and size). That single strategy is used to:
1. **Generate the line** — sample Villain's actual actions from its actual hand.
2. **Build the range** — start from the profile's pre-flop range and, at each Villain action, multiply each combo's weight by the probability the strategy would have taken that action with that combo. The range is exactly the posterior of Villain's own strategy.
3. **Predict responses** — fold/call/raise frequencies to a Hero bet come from the same strategy applied to every combo in the range.

Because all three come from one place, the revealed hand is always consistent with the line, and the range shown is the range graded against. This must be enforced by tests.

### Hand categorisation
The strategy acts on hand categories, computed by code per combo per board: e.g. nuts/near-nuts, strong value, medium made hand, weak made hand, strong draw (combo draw, flush draw + overs), weak draw, air (with/without blockers). Exact category list and thresholds are the builder's, kept in the profile data where tunable.

### What "competent" means, and how it's checked (Claude's call)
The strategy may use board texture and stack-to-pot ratio as well as hand category. Before Phase 1 is done, an analysis script runs the strategy across many random spots per profile and checks, per bet size:
- bluff share of the betting range is near the pot-odds break-even (`b / (pot + 2b)`), within a profile-specific band (LAG higher, Tight lower);
- fold rate facing bets sits near minimum defence frequency, within a profile band (Sticky folds less);
- no dominated lines (e.g. folding the nuts, value-betting hands that only worse hands never call).
Bands live in profile data. The script's report is then reviewed by the user as a manual sign-off.

### Hero's earlier actions
Hero's own actions on earlier streets (e.g. a pre-flop open) are generated by a sensible default Hero policy, so the spot is realistic. Hero's earlier line is shown, not graded.

### Representation
- A range is 1326 combos with weights 0–1, with combos blocked by Hero's cards and the board removed.
- Displayed on a 13×13 grid (169 hand classes), each cell shaded by aggregate weight, with per-combo detail on hover.

## 6. Equity engine

- Hero's equity vs a weighted range = weighted average over Villain combos of Hero's share of the pot over all run-outs (ties split).
- **River:** exact. **Turn:** exact (≤ 44 rivers per combo). **Flop:** exact enumeration if fast enough, otherwise Monte Carlo with a stated error bound ≤ 0.5 percentage points (builder benchmarks and picks). **Pre-flop:** precomputed 169×169 hand-class equity table (generated once by a script, committed as data), weighted by combos with blockers handled correctly or approximated and labelled.
- Performance target: equity for a puzzle returns in under ~1 s on a laptop.
- **Accuracy tests:** known reference values (e.g. AA vs KK ≈ 81.9%, AKs vs QQ ≈ 46%, coin-flip pairs vs overs), cross-checks against `pokerkit` on random spots within tolerance, and invariants (equities sum to 1, symmetry).

## 7. Puzzle generation

1. Shuffle; deal Hero and Villain hole cards.
2. Pick decision street (pre-flop / flop / turn / river), with weights (builder's call; roughly even, maybe fewer pre-flop).
3. Pick Villain profile (or use the user's setting).
4. Play the hand forward to the decision point: Hero default policy and Villain strategy act from their actual hands; Villain's range is updated at each Villain action (§5).
5. Hand must reach the decision street with Hero to act and a non-trivial decision; otherwise regenerate.
6. Track pot, stacks, current bet, legal actions.
7. **Trivial filter** (Claude's call, thresholds tunable): reject if Hero equity vs range > 92% or < 4%, or if every option's EV is within a negligible margin of the best (nothing to learn), or if the best option beats the second-best by a huge margin *and* the spot is a textbook auto-play.
8. Every puzzle stores its RNG seed and its **full frozen state** (cards, line, range at each step, computed results) plus the profile-data version. Replays use the frozen state, never regenerate from the seed, so tuning profiles later never changes an old puzzle (Claude's call).
9. **Puzzles and attempts are separate records.** "Replay" from history means answering the same puzzle again as practice. Only the first attempt counts toward headline stats, streaks and the daily goal; retries are tracked separately (Claude's call).

## 8. Grading and results

### Computations (all code)
- **True equity** vs range (§6).
- **Pot odds:** call / (pot + call), where pot includes Villain's bet.
- **EV of every legal option**, relative to folding (fold = 0):
  - Call: `equity × (pot + call) − call` on the river. On earlier streets the same formula with full equity realisation — a labelled simplification.
  - Bet/raise of size b: `F × pot + (1 − F) × (equity_vs_continuing_range × (pot + 2b) − b)`, where F is the fraction of Villain's range that folds to b (from Villain's strategy), and the continuing range is the range re-weighted by call/raise probabilities. In the MVP Villain's response to a Hero bet is fold or call; Villain re-raises are folded into "call" or ignored and labelled as a simplification (builder decides which, states it).
  - Candidate sizes evaluated: 33/50/75/100% pot for bets; 2.5x/3x/all-in for raises.
  - Check: on the river, equity vs Villain's checking-back range × pot; earlier streets, equity × pot (simplification, labelled). If Villain can bet behind, builder may model it simply.
- **Bluff check:** required fold equity `b / (pot + b)` vs F.
- **Verdict** from EV loss vs the best option, in bb (Claude's call, thresholds in config): **Best** (≤ 0.25bb or ≤ 2% of pot), **Fine** (≤ 10% of pot), **Mistake** (≤ 25% of pot), **Blunder** (worse).
- **Equity guess score:** within 5 points = great, within 10 = good, otherwise off.
- **Intent check:** flag mismatches (e.g. "value bet" when only worse hands call is fine; "value" when only better hands call is a mistake in labelling).

### Results view
1. Verdict and EV lost in bb.
2. Equity guess vs true equity; range-read guess vs true "% ahead now".
3. **Options table:** every option's EV, recommended option and size highlighted.
4. **Step-by-step maths** for the user's action and the best action (pot odds, fold equity, the EV formula with real numbers plugged in).
5. **Range breakdown (the deep part):**
   - 13×13 grid of Villain's range now;
   - how it narrowed: a step per Villain action ("pre-flop range → after flop c-bet → after turn call") with the grid at each step;
   - Hero vs range by category: % of range Hero beats, loses to, and draws vs; which hands fold/call to the recommended bet.
6. Villain's actual hand revealed, board run out, winner shown.
7. A clear note: judged against the range, not this result.
8. Plain-English explanation (LLM if available, template otherwise).
9. Next puzzle.

## 9. LLM layer (optional)

- Uses only: rewrite the action history as a short narrative; explain the verdict in plain English from computed numbers.
- Provider interface: `none` (template text, the default) / `ollama` (local, 3B–8B model) / hosted API later. Configured by env vars.
- The LLM is given computed numbers and hand details only and asked to explain, never compute.
- Guardrail (Claude's call): if the LLM output contains a number not present in its input, discard it and fall back to the template.
- A hosted deployment can run with `none`.

## 10. Progress tracking

Every submitted answer is saved (user_id, puzzle seed + state, inputs, computed results, timestamps). Progress tab shows:
- **Headline:** average EV lost per decision (bb), rolling last 50, as a line chart.
- Average equity-estimate error, also trended.
- Average range-read error ("% ahead now" guess vs truth), trended — the range-reading progress line.
- Decision accuracy by street, by action type, by Villain profile.
- Common leaks, detected by rules (e.g. calling too often on the river, over-bluffing, under-value-betting, equity over-estimation with draws).
- Current and best streak; puzzles per day vs a daily goal.
- History table: street, action, verdict, EV lost, equity error; click to replay the puzzle.

## 11. UI

- Dark theme, oval felt table, real card graphics, smooth deal animations, keyboard shortcuts. Visual polish is a requirement.
- Seats show name, position, stack, current bet, dealer button. Villain's cards face down until results.
- Each opponent seat shows its profile label (TAG / LAG / Tight / Sticky) by default, with a one-line tendency description on hover. A setting hides it for a harder "unknown player" mode; the profile is always revealed in the results.
- Centre: board, pot, pot odds (toggle).
- Side panel: action history by street (optionally the LLM narrative).
- Answer panel as in §4.
- Results view as in §8.
- Progress tab as in §10.
- Settings: pot-odds display, show Villain profile, Villain profile selection / random, daily goal, LLM provider status.
- Layout must accommodate 5 seats (Phase 2) without redesign.

## 12. Accuracy strategy

Two different kinds of accuracy, held to different standards:

**A. The maths must be exact given its inputs** (equity, pot odds, EV formulas, accounting). Verified by:
- **Evaluator ground truth:** enumerate all 2,598,960 five-card hands and match the known count per hand class (e.g. 40 straight flushes, 624 quads, 3,744 full houses); seven-card spot checks.
- **Equity references:** published matchups (AA vs KK, pair vs overcards, dominated hands) to within 0.1 points when exact.
- **Independent cross-checks:** pokerkit on thousands of random hand-vs-range spots; a slow brute-force reference implementation on small cases. Monte Carlo results must fall within their stated error bound.
- **Golden spots:** ~20 hand-worked puzzles (pot, range, sizes, expected equity/pot odds/EV per option written into the test).
- **Accounting invariants:** chips conserved, pot = sum of contributions, only legal actions offered.
- **Consistency invariants** (property tests over many random puzzles): revealed hand has non-zero weight in the final range; displayed range ≡ graded range; narrowing never increases a weight.

**B. The Villain model is an approximation**, and is honest about it:
- Competence checks in §5 (bluff share and defence frequency vs theory per size), plus user sign-off.
- Every simplification (equity realisation before the river, re-raise handling) is labelled in the results.
- Future: optional solver comparison to measure the gap.

## 13. Testing

- `pytest` for the engine: evaluator wrapper, equity reference values, pokerkit cross-checks, range-narrowing invariants (range weights never increase on narrowing; revealed hand always has non-zero weight in final range), pot/stack accounting, EV formula unit tests with hand-worked examples.
- Property-based tests (`hypothesis`) for consistency rules across many random puzzles.
- Frontend: component tests (Vitest) for the answer panel and results maths display; a smoke end-to-end test is nice-to-have.
- CI on GitHub Actions running on both `windows-latest` and `macos-latest`.

## 14. Phases

- **Phase 1 (MVP, heads-up):** everything above except the harder EV-guess mode.
- **Phase 1.5:** EV-guess harder mode; difficulty presets (hide pot odds, hide profile, tighter scoring).
- **Phase 2:** five-handed table.
- **Later:** spaced repetition of missed puzzles, daily puzzle challenge, hosted deployment with accounts, optional real solver integration.

## 15. Left to the builder

- Exact hand-category definitions and profile frequency numbers (must make Villains feel competent).
- Flop equity: exact vs Monte Carlo, based on a benchmark.
- How Villain re-raises are handled in Hero-bet EV (state the simplification in the results).
- Street selection weights, trivial-filter thresholds (tunable in config).
- Chart library, animation approach, card graphics source (must be freely licensed).
- Commit breakdown and order — produced next in the implementation plan, in sensibly-sized commits.
