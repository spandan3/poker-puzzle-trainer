# M10 Play vs Bots (heads-up) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Play page where the user plays full heads-up hands against one bot (the Villain policy) in a saved cash-game session, and can click Analyse on any hand to get every Hero decision graded in the M6 results-view style.

**Architecture:**
- A new pure package `poker_trainer/play/` holds the hand engine (deal, bot acts, settle, session stack rules) and the analysis adapter. It has no database and no web code; a hand is a small record (`deck`, `bot_seed`, `actions`) that is replayed to get its state, so a resumed hand continues identically.
- The API gets `/api/play/...` routes backed by `api/play_service.py` and `api/play_views.py`, and two new tables (`play_sessions`, `play_hands`, migration 0004). The bot always acts on the server; the client never receives the bot's cards before a showdown or an analysis.
- Analysis builds one puzzle-shaped `Spot` per Hero decision and grades it with the existing `solve` and grader, always passing the session's profile snapshot. The result view is the guess-free core of `attempt_result`, shared by both.
- The frontend adds a third page (`/play`) that reuses the M5 table and the M6 `DecisionDetails`.

**Tech Stack:** as today (FastAPI, SQLAlchemy, Alembic, React 19, Vite, Vitest, Playwright). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-12-play-vs-bots-design.md` (§4 is M10). Main spec: `docs/superpowers/specs/2026-11-10-poker-puzzle-trainer-design.md`. Hand-over items: "Open items for M10 and later" in `2026-11-13-m9-signoff.md`.

**Branch:** `adarsh` (the user's ruling; this session may only push there). Commits are authored as the repo's configured git user (Adarsh), with no trailers. Tell subagents: no `--author`, no trailers. Both depart from CLAUDE.md (milestone branch, commits as spandan3) by the user's ruling on 2026-11-14; say so in the PR.

**Plan review:** an Opus review against the code (2026-11-14) is folded in. It confirmed by simulation (6,000 hands, Hero 10–600 chips, bot 80–300) that the strategy, `hero_options` and the solver need no change for short or uneven stacks, that every showdown pot is even, and that a decision solves in about 0.17 s.

## Global Constraints

- **The bot is the Villain policy.** Its action is `sample_action(profile, state, bot_hole, rng)` and nothing else; no new bot logic. One random profile per session from `PROFILE_NAMES`; the puzzles' Villain select does not apply.
- **Hero's menu is the trainer's option set:** `hero_options(state)` plus, post-flop, `custom_action(state, to)`. No limps, no small 4-bets.
- **Chips:** blinds 1/2 chips (bb = 2), start stack 200 chips. The API works in chips; the UI shows bb.
- **Stack rules, applied at the start of each hand:** bot below 80 chips → 200; bot above 300 chips → 200; Hero below 10 chips must rebuy to 200; Hero may top up to 200 whenever below it. Every Hero rebuy or top-up adds to `hero_bought_chips`, and the tally is `hero_stack − hero_bought_chips`.
- **Seats:** Hero is seat 0 for the whole session (`HERO_SEAT = 0`); the button alternates every hand, starting at a random seat.
- **Each hand's randomness is fixed when it starts:** `deck` (a 52-card order; Hero `deck[0:2]`, bot `deck[2:4]`, board `deck[4:9]`, as in `generate_spot`) and `bot_seed` are stored with the hand.
- **No guesses during play:** no equity guess, range read or intent. Analysis shows no guess scores.
- **Analysis only on click**, computed once per decision and stored. It never grades on the result of the hand.
- **The analysis range is the narrowing of the bot's real actions** (`RangeTracker` over the hand's own history with the session's profile snapshot).
- **No number from an LLM.** Per-decision explanations use the M8 template, facts and guardrail unchanged.
- **Puzzle grading must not change:** `tests/puzzle/test_golden.py` and the frontend attempt fixtures stay byte-identical (fixtures are not regenerated except for new play fixtures).
- **Play results stay out of puzzle stats:** nothing in `stats/` or `attempts` changes.
- **Versions:** `STRATEGY_VERSION` (new, in `villain/strategy.py`, value 1), `load_thresholds().version` and `load_config().version` are stored with each hand. If any differs when an analysis is shown, the response says so (`model_changed`).
- **Cross-platform:** LF line endings for generated files, no OS-specific scripts. `random.Random(str)` seeding only (stable across platforms and processes; never `hash()`).
- **Checks before each commit:** backend `uv run pytest -m "not slow"`, `uv run ruff check`, `uv run ruff format --check`; frontend tasks also `npm test`, `npm run lint`, `npm run typecheck`, `npm run format:check`, `npm run check:api`, `npm run build`. UI tasks also `npm run e2e` and screenshots at 1280×800 and 1024×768 for the reviewer. The top bar must stay one row at 1280 wide.
- One commit per task, conventional message as listed. Never squash. Review fixes are new commits.

## Decisions made in this plan

### Hand record and replay
- `play/hand.py` defines the frozen dataclass `HandRecord(button: int, start_stacks: tuple[int, int], deck: tuple[int, ...], bot_seed: int, actions: tuple[Action, ...], abandoned: bool = False)`. `actions` holds both players' actions in order. The state is never stored; `replay(record) -> HandState` rebuilds it with `new_hand(button, start_stacks)`, `apply` and `deal` (board cards from `deck[4:9]`, dealt whenever `needs_board`, including the run-out after an all-in).
- **Bot sampling is a pure function of the record:** the bot's k-th action in the hand history (index `i = len(state.history)`) uses `random.Random(f"{bot_seed}:{i}")`. No RNG state is stored, so a resumed hand continues identically.
- `advance(record, profile) -> HandRecord` appends bot actions until Hero is to act or the hand is over. `hero_act(record, profile, action) -> HandRecord` validates `action` against `hero_options` / `custom_action`, applies it and advances. Both raise `ValueError` for an illegal action or a finished hand.
- `HERO_SEAT = 0`, `BOT_SEAT = 1`.

### Settlement
- `game/settle.py` (new file; `game/state.py` is not changed): `settle(s: HandState, holes: tuple[tuple[int, int], tuple[int, int]]) -> tuple[int, int]` returns the final stacks of a terminal state. Fold: the other seat takes `total_pot(s)`. Showdown (river, board complete): `evaluate` both hands; the winner takes the pot, a tie splits it evenly (the pot is always even heads-up under the effective-stack cap; assert it). It raises `ValueError` when the state is not terminal.
- `HandOutcome(ended_by: Literal["fold", "showdown", "abandoned"], winner: Literal["hero", "villain", "split"], stacks: tuple[int, int], hero_delta: int)` and `outcome(record) -> HandOutcome | None` (None while the hand is running) live in `play/hand.py`.
- **End session during a hand** sets `abandoned=True`: Hero keeps only the chips still in the stack, and the bot takes the whole pot. The outcome is `ended_by="abandoned"`, `winner="villain"`. The bot's cards stay hidden at the table.

### Session rules
- `play/session.py`: `next_stacks(hero: int, bot: int, *, top_up: bool) -> tuple[int, int, int]` returns `(hero_stack, bot_stack, hero_bought)` under the stack rules in Global Constraints (`hero_bought` is the chips added to Hero now). `must_rebuy(hero: int) -> bool` is `hero < 10`. Constants: `START = 200`, `BOT_MIN = 80`, `BOT_MAX = 300`, `HERO_MIN = 10`.
- `new_record(button, stacks, rng: random.Random) -> HandRecord` shuffles a deck and draws `bot_seed = rng.getrandbits(62)`. The service passes `random.Random(secrets.randbits(64))`; tests pass a seeded one.

### Villain and grader prep
- `villain/profiles.py`: `profile_from_dict(name, raw)` becomes public (the private name stays as an alias for existing callers), and `profile_data(name) -> dict` returns the profile file's parsed JSON (a fresh dict). A session stores `profile_data(name)` and rebuilds the profile with `profile_from_dict`; it never calls `load_profile` after the session starts.
- `villain/strategy.py`: `STRATEGY_VERSION = 1`, with a comment: bump by hand whenever the policy's behaviour changes. Add it to `handoff.md` §4 in the docs commit.
- `puzzle/model.py`: `Spot` gains `start_stacks: tuple[int, int] = (START_STACK, START_STACK)` (last field). `_spot_to_dict` writes it **only when it differs from the default**, and `_spot_from_dict` reads it with that default, so every existing puzzle blob and fixture stays byte-identical and `FORMAT` stays 1. `api/views._replay` uses `new_hand(spot.state.button, spot.start_stacks)`.
- `puzzle/grade.py`: split the action part out of `grade()` as `grade_action(p: Puzzle, action: Action, *, intent: Intent | None = None, respond: Respond | None = None) -> ActionGrade`, where `ActionGrade` has `verdict`, `ev_loss_chips`, `chosen`, `best`, `intent_truth`, `intent_flag`, `bluff_check`, `best_is_chosen` (and `ev_loss_bb`). `grade()` calls it and adds the guess scores; its results don't change.
- M9 open item, taken here because the adapter leans on it: `grade._resolve`'s default-`respond` path also refuses a custom size when `load_config().version != p.spot.config_version` (same error style as the profile check).

### Analysis adapter
- `play/analyse.py`:
  - `hero_decisions(record) -> tuple[int, ...]`: the indices into `record.actions` of Hero's actions.
  - `decision_spot(record, profile, n) -> tuple[Spot, Action]`: the spot as it stood at Hero's n-th decision and the action Hero took. The `Spot` has `seed=record.bot_seed`, `attempt=n`, `hero_seat=HERO_SEAT`, `villain_hole=bot_cards(record)`, `runout=deck[4:9]`, `start_stacks`, the profile's name and version, the live categories and config versions, and `steps` from a `RangeTracker(profile, BOT_SEAT)` fed the bot's actions before that point (ranges through `visible_range`, as `generate_spot` does).
  - `analyse_decision(record, profile, n, *, samples: int | None = None) -> DecisionAnalysis`, where `DecisionAnalysis(puzzle: Puzzle | None, grade: ActionGrade | None, not_graded: str | None)`. It solves with `respond=villain_respond(profile)` and `rng=random.Random(f"{record.bot_seed}:analysis:{n}")`, then `grade_action(puzzle, action, respond=respond)`. `UnsupportedSpot` or `ValueError` from `decision_spot` (e.g. the range tracker after a category-threshold change), the solver or the grader becomes `not_graded` with the message; it never raises for a legal hand. `samples` defaults to `load_config().samples`.
- A custom-size action that isn't a listed option is graded by `grade_action`'s custom path (the injected `respond`), as in puzzles.

### Storage (migration `0004_play`)
- `play_sessions`: `id`, `user_id` (FK, index), `created_at`, `ended_at` (null while open), `profile` String(16), `profile_version` Integer, `profile_data` JSON, `hero_stack` Integer, `bot_stack` Integer (stacks after the last finished hand), `hero_bought_chips` Integer (starts at 200), `next_button` Integer, `hands_played` Integer (finished hands). **A partial unique index on `user_id` where `ended_at IS NULL`** enforces one open session; the service turns its `IntegrityError` into 409.
- `play_hands`: `id`, `user_id` (FK, index), `session_id` (FK, index), `hand_no` Integer (1-based; unique with `session_id`, so a doubled "Next hand" hits the constraint → 409), `created_at`, `button` Integer, `start_stacks` JSON, `deck` JSON, `bot_seed` BigInteger, `actions` JSON (list of the `_action_dict` shape), `action_count` Integer, `abandoned` Boolean, `status` String(12) (`in_progress` / `complete`), `ended_by` String(12) null, `winner` String(8) null, `hero_delta_chips` Integer null, `decision_count` Integer (Hero's decisions so far), `strategy_version`, `categories_version`, `config_version` Integer, `ev_loss_chips` Float null (the total, set when every decision is stored).
- **Writes to a hand are compare-and-set:** `UPDATE play_hands SET actions=…, action_count=… WHERE id=:id AND action_count=:expected AND status='in_progress'`; zero rows updated means another request got there first → 409.
- `play_decisions` (one row per analysed Hero decision; unique `(hand_id, n)`): `id`, `user_id` (FK, index), `hand_id` (FK, index), `n` Integer, `created_at`, `status` String(12) (`graded` / `not_graded`), `reason` Text null, `puzzle` LargeBinary null (`db.blob.encode_puzzle`, 5–7 KB), `chosen` JSON null (OptionEV dict), `custom_to` Integer null, `verdict` String(8) null, `ev_loss_chips` Float null, `best_label` String(64) null, `best_ev_chips` Float null, `intent_truth` String(16) null, `bluff_required` / `bluff_actual` Float null, `strategy_version`, `categories_version`, `config_version` Integer (live values when it was analysed). A concurrent second insert hits the unique constraint; the service then returns the stored row.
- The migration's indexes and constraints must match the models exactly (`test_models_match_migrations`). `tests/db/test_migrations.py` hard-codes the head `0003_attempt_stats` in two places (the head assertion and the batch probe's `down_revision`); Task 4 moves both to `0004_play`.

### API (all under `/api/play`, JSON, same error shape as today)
| Route | Does |
|---|---|
| `POST /sessions` → 201 `PlaySessionView` | Start a session: random profile, snapshot, first hand dealt and advanced to Hero's turn. 409 if one is open. |
| `GET /sessions/current` → `PlaySessionView` | The open session with its latest hand (running or finished), or 404. |
| `POST /sessions/{id}/end` → `PlaySessionView` | End it; a running hand is abandoned. Idempotent. |
| `POST /sessions/{id}/hands` body `{"top_up": bool}` → 201 `PlaySessionView` | Deal the next hand (stack rules applied). 409 while a hand is running or the session is ended. |
| `POST /hands/{id}/actions` body `{"expected_actions": int}` plus `{"option": int}` or `{"custom_to": int}` → `PlaySessionView` | Hero acts, then the bot acts until Hero's turn or the end. `expected_actions` is the `action_count` the client saw: 409 if it isn't the hand's current count (a stale or doubled click) or the hand is over; 422 for a bad option or size. |
| `GET /sessions` → `list[PlaySessionSummary]` | Newest first: id, times, profile label, hands, net bb, open flag. |
| `GET /sessions/{id}/hands` → `list[PlayHandSummary]` | hand_no, id, hero position, result bb, ended_by, decision_count, analysed, ev_loss_bb. |
| `GET /hands/{id}` → `PlayHandView` | One hand as it stands (a finished hand of any session). |
| `GET /hands/{id}/analysis` → `HandAnalysis` | What is stored so far: one entry per Hero decision (`null` until computed), the summary when all are done, the reveal, `model_changed`. 409 while the hand is running. |
| `POST /hands/{id}/analysis/{n}` → `DecisionReview` | Compute decision `n` if it isn't stored, store it, return it (the database session is released while solving). 404 for a bad `n`, 409 while the hand is running. |
| `GET /hands/{id}/analysis/{n}/explanation` → `Explanation` | As `GET /attempts/{id}/explanation`, for a stored, graded decision. |

- `PlaySessionView`: `id`, `open`, `profile` (`ProfileInfo`), `hero_stack`, `bot_stack`, `hero_bought_chips`, `net_chips`, `net_bb`, `hands_played`, `must_rebuy`, `can_top_up`, `hand: PlayHandView | None`.
- `PlayHandView`: `id`, `hand_no`, `session_id`, `status`, `action_count`, `decision_count`, `table: TableView`, `frames: list[TableFrame]`, `options: list[OptionBrief]` and `custom: CustomSizes` (empty / not allowed unless Hero is to act; bounds come from `legal_actions`, not `views.custom_allowed`, which needs a `Puzzle`), `outcome: PlayOutcome | None`.
- `TableFrame`: `stacks`, `street_bets`, `pot`, `board_len`, `to_act` (`"hero"` / `"villain"` / null). `frames[k]` is the table after the first `k` history entries (`frames[0]` is after the blinds), so there are `len(history) + 1` frames and the client shows the table at any point of the reveal by lookup. `ActionLogEntry` is not changed (it is shared with puzzles and their fixtures).
- `TableView` is `PuzzleView` without `id`, `options`, `custom`, `range_read_asked` and `attempts_so_far` (`street`, `hero_seat`, positions, `hero_cards`, `board`, `stacks`, `street_bets`, `pot`, `to_call`, `pot_odds`, `history`, `villain_profile`). In a finished hand `stacks` are the settled stacks, `street_bets` are zero and `pot` is the pot that was awarded. `villain_profile` label and description come from the session's snapshot, never `profile_meta` (the live file).
- `PlayOutcome`: `ended_by`, `winner`, `hero_delta_chips`, `hero_delta_bb`, `villain_cards: list[str] | None` (set only for a showdown), `showdown: Showdown | None`.
- `DecisionReview`: `index`, `status` (`graded` / `not_graded`), `reason: str | None`, `view: TableView | None` (the spot as it stood), `grade: DecisionGrade | None` (`GradeView` without the guess fields), `options`, `simplifications`, `categories`, `range_steps`, `chosen_label` (custom sizes keep the server label; the frontend relabels in bb), `explanation`.
- `HandAnalysis`: `hand_id`, `decisions: list[DecisionReview | None]`, `summary: {ev_loss_bb, worst_index} | None` (`worst_index` null when nothing was graded or nothing lost EV), `reveal: PlayReveal` (bot cards, the board as far as it was dealt, profile with version, `showdown: Showdown | None`; the existing `Reveal` requires a showdown and a 5-card run-out, so it is not reused), `model_changed: bool`, `judged_on_range_note`. A hand with no Hero decision (the bot folded the button) has `decisions: []`; the UI offers no Analyse for it.
- Every new response model goes into `tests/api/test_contract.py` (`ROUTES`, the forbid list, the exact-keys test).
- **Shared decision core:** `api/views.decision_core(puzzle, chosen, *, verdict, ev_loss_chips, best_label, best_ev_chips, intent, intent_truth, intent_flag, bluff) -> dict` builds `options`, `simplifications`, `categories`, `range_steps`, the non-guess grade fields and the custom-best rule. `attempt_result` is rewritten to call it and add `attempt`, `answer`, the guess fields and `reveal`; its output must not change (the existing fixture and view tests are the proof).
- `explain()` and `build_facts()` need no change. They read, from the result dict: `grade.{pot_odds, equity, ahead_now, verdict, ev_loss_bb}`, `options[*]` (the full `option_view` shape), `categories`, `range_steps[*].label`, `answer.{custom_to, action.kind, action.to, chosen_label}` and `reveal.profile.{label, description}`; and the `Puzzle` plus `action_log(spot)`. `play_views` builds a dict with exactly those keys from the stored decision row (profile label and description from the snapshot).
- `Explainer.explanation_for`'s first parameter becomes a hashable cache key (`int | tuple`); decisions use `("play", hand_id, n)`. `_cache` / `_in_flight` keys become `tuple[Hashable, str]`, and the four log calls in `_run` that format the id with `%d` switch to `%s`.
- `create_app` gains `play_rng: Callable[[], random.Random] | None` (default: `random.Random(secrets.randbits(64))` per call) and `play_samples: int | None` (default: the config's). The profile draw, the first button and each deck come from `play_rng`; timestamps come from `service.utcnow` (the clock `dev_fixtures` already replaces), so seeded tests and fixtures are deterministic.
- Timing: the route handlers are plain `def` (threadpool) like the rest; the session is closed before solving, as `new_puzzle` does with `db.rollback()`.

### Frontend
- `lib/page.ts`: `Page` gains `'play'` at `/play`; `TopBar` nav gets "Play" between Puzzles and Progress. On Play the bar shows the session tally (`+12.5 bb · 14 hands`) and "End session" in place of the street select, the profile select and "New puzzle". The pot-odds, show-profile and Shortcuts toggles and the `?` help stay on Play (the Play page passes `show_profile` and `show_pot_odds` to `seatsFromView` and `TableCentre`). Shortcuts are scoped to the page on show. The bar must stay one row at 1280 on Puzzles (now wider by one link) and on Play.
- `app/usePlayFlow.ts`: the hook that owns the play state (`loading` / `idle` / `playing` / `handOver` / `error`), with an injectable API like `usePuzzleFlow`. After each response it reveals new `history` entries one at a time, 600 ms apart (`BOT_PAUSE_MS = 600`), and Hero's controls are enabled only when the reveal has caught up. The board, stacks, bets and pot shown come from `frames[shownCount]`.
- `components/AnswerPanel/AnswerPanel.tsx` gains `guesses?: boolean` (default true), `draftKey?: string | number` (default `view.id`; play passes `` `${hand.id}:${hand.action_count}` `` so the draft resets at each decision) and `onAct?: (body: PlayActionChoice) => void`. With `guesses={false}` it renders only the action and size controls and Submit, never reads `attempts_so_far` or `range_read_asked`, and calls `onAct` with `{option}` or `{custom_to}`. `lib/answer.ts` gains `validateAction(view, state) -> {ok: true, body: PlayActionChoice} | {ok: false, errors}`; `validateAnswer` is unchanged. The panel's `view` type becomes `ActionView` (`TableView` fields plus `options` and `custom`, with `id`, `attempts_so_far` and `range_read_asked` optional), which `PuzzleView` satisfies.
- `seatsFromView` and `HistoryPanel` take `TableView`. `groupHistory(view, answer?, toAct?)` gains `toAct: 'hero' | 'villain' | null` (default `'hero'`, today's behaviour): `'villain'` ends the last section with "Villain to act", `null` with nothing (a finished hand).
- `app/useExplanation.ts` is generalised to `useExplanation(key, template, fetcher, settings)`; the puzzle call site passes the attempt id and `client.getExplanation`.
- `components/Play/PlayPage.tsx`: the table (M5 components), the action history panel, and under the table one of: the action panel, the hand-over panel, or the start panel.
  - Start panel (no open session): "Start session", a past-sessions list (net bb, hands, date), and the help note below.
  - Hand-over panel: the result line ("You won 6.5 bb", "Villain won 12 bb at showdown", "Split pot"), "Next hand" (shortcut `N`), "Analyse this hand" (only when `decision_count > 0`), and "Top up to 100 bb" (a checkbox, shown when `can_top_up`); when `must_rebuy`, the button reads "Rebuy and deal".
  - Help note (exact copy): "Pre-flop, the bot responds the same way to a 2.5x and a 3x open or 3-bet, and treats an all-in as a jam. There is no limping and no small 4-bet."
- `components/Play/HandAnalysis.tsx`: loads `GET analysis`, then posts each missing decision in order and shows "Analysing decision 2 of 5…". It renders the summary (total EV lost, worst decision marked), a step list (street and Hero's action, verdict, EV lost), and for the selected step `DecisionDetails` with the Why tab (`ExplanationPanel`) and a Hand tab (bot cards, profile, run-out, showdown line). A `not_graded` step shows "Not graded: {reason}". `model_changed` shows "Villain model has changed since this hand". The "judged on range" note is shown.
- `components/Play/SessionHands.tsx`: the session's hands (number, position, result, EV lost when analysed) with an Analyse / Review button each; used on the Play page and for a past session opened from the start panel.
- `lib/decision.ts`: `decisionFromReview(review) -> DecisionData` (`intent: null`, no guess fields).
- Fixtures: `api/dev_fixtures.py` gains `write_play_fixtures(out)` (called from `main`), writing `play_session_hero_to_act.json`, `play_session_hand_over_fold.json`, `play_session_hand_over_showdown.json`, `play_hand_analysis.json`, `play_sessions.json`, `play_hands.json` from a seeded scripted session. Gallery entry `src/dev/entries/play.tsx`.

## Review Focus

1. **Short and uneven stacks** (the strategy has only ever seen 200/200): a hand started with Hero at 10–600 chips and the bot at 80–300 never raises `UnsupportedSpot` or an illegal-action error, whatever Hero picks from the menu. (Task 2 property test.)
2. **Resume mid-hand:** loading the session again in the middle of a hand, any number of times, gives the same bot actions and the same board as an uninterrupted hand. (Task 2 test; Task 5 API test; Task 8 e2e reload.)
3. **Chips are conserved across a session:** after every hand `hero_stack + bot_stack` equals the start-of-hand total, and `net_chips` equals Hero's stack minus everything Hero bought, through rebuys, top-ups, bot top-ups, bot resets and an abandoned hand. (Task 2 and Task 5 tests.)
4. **The bot's cards never leak:** no API response for a running hand or a hand that ended in a fold contains the bot's hole cards, or undealt board cards; they appear only at a showdown and in the analysis. (Task 4 test that scans the JSON for quoted card tokens.)
5. **Double submit and stale clicks:** two `POST actions` for the same decision, an action on a finished hand, "Next hand" twice, and Analyse clicked twice apply once or answer 409 and never corrupt the hand. (Task 5 and Task 6 tests.)

---

### Task 1: Settlement and model prep (Opus)

**Files:**
- Create: `backend/src/poker_trainer/game/settle.py`, `backend/tests/game/test_settle.py`
- Modify: `backend/src/poker_trainer/villain/profiles.py`, `backend/src/poker_trainer/villain/strategy.py`, `backend/src/poker_trainer/puzzle/model.py`, `backend/src/poker_trainer/puzzle/grade.py`, `backend/src/poker_trainer/api/views.py`
- Test: `backend/tests/villain/test_profiles.py`, `backend/tests/puzzle/test_model.py`, `backend/tests/puzzle/test_grade.py`, `backend/tests/api/test_views.py`

**Interfaces — produces:**
- `settle(s: HandState, holes: tuple[tuple[int, int], tuple[int, int]]) -> tuple[int, int]`
- `profile_from_dict(name: str, raw: Any) -> Profile`, `profile_data(name: str) -> dict[str, Any]`, `STRATEGY_VERSION: int`
- `Spot.start_stacks: tuple[int, int]`
- `grade_action(p, action, *, intent=None, respond=None) -> ActionGrade`

- [ ] **Step 1: Failing tests.**
  - `test_settle.py`: a fold gives the pot to the other seat (pre-flop fold of the button: stacks `(199, 201)` when seat 0 is the button); a river showdown with a named winner; a tie on a board that plays (e.g. board `As Ks Qs Js Ts`) splits evenly; an all-in pre-flop state run out with `deal` settles; `sum(settle(...)) == s.total_chips` in each; a non-terminal state raises `ValueError`. Start stacks `(120, 340)` in at least one case.
  - `test_profiles.py`: `profile_from_dict("tag", profile_data("tag")) == load_profile("tag")` on `version`, `label` and one table; mutating the dict from `profile_data` does not change a second call's result.
  - `test_model.py`: a `Spot` with default `start_stacks` serialises without the key (the dict equals the old shape); `(120, 340)` round-trips; a dict without the key decodes to the tuple `(200, 200)`; `sum(start_stacks) == state.total_chips` is asserted when a `Spot` is built from a dict.
  - `test_grade.py`: `grade_action` equals `grade` on `verdict`, `ev_loss_chips`, `chosen`, `best`, `intent_truth`, `bluff_check` for a listed option and a custom size; a custom size on a puzzle whose `config_version` differs from the live one raises `ValueError` on the default-`respond` path and not when `respond` is injected.
  - `test_views.py`: `action_log` of a spot with `start_stacks=(120, 340)` reports `all_in` and `amount` from those stacks.
- [ ] **Step 2:** Run them; they fail for the missing names.
- [ ] **Step 3:** Implement as in Decisions ("Settlement", "Villain and grader prep").
- [ ] **Step 4:** All backend checks; `tests/puzzle/test_golden.py` passes unchanged; `git status` shows no change under `frontend/src/test/fixtures`.
- [ ] **Step 5: Commit** `feat(game): hand settlement, start stacks in spots, profile snapshots, STRATEGY_VERSION`

### Task 2: Hand engine and session rules (Opus)

**Files:**
- Create: `backend/src/poker_trainer/play/__init__.py`, `play/hand.py`, `play/session.py`, `backend/tests/play/test_hand.py`, `tests/play/test_session.py`, `tests/play/test_properties.py`

**Interfaces — consumes:** `settle`, `profile_from_dict`. **Produces:**
- `HandRecord`, `HandOutcome`, `HERO_SEAT`, `BOT_SEAT`
- `replay(record) -> HandState`, `advance(record, profile) -> HandRecord`, `hero_act(record, profile, action) -> HandRecord`, `outcome(record) -> HandOutcome | None`, `abandon(record) -> HandRecord`
- `hero_cards(record)`, `bot_cards(record)`, `board(record) -> tuple[int, ...]` (dealt so far)
- `next_stacks`, `must_rebuy`, `new_record`, and the constants

- [ ] **Step 1: Failing tests.**
  - `test_hand.py`: a new record with the bot on the button is advanced to Hero's turn or to the end (bot folded); the bot's action at history index `i` equals `sample_action(profile, state, bot_hole, random.Random(f"{seed}:{i}"))`; `advance` is idempotent; replaying a record after every prefix of its actions and advancing again gives the same full record (resume); `hero_act` with an action not in the menu raises `ValueError`; a custom post-flop size inside the legal range is accepted and one outside is refused; an all-in and call pre-flop yields a 5-card board and a showdown outcome; `abandon` gives `ended_by == "abandoned"`, `winner == "villain"` and Hero's stack unchanged from the moment of abandoning; `outcome` is `None` while running.
  - `test_session.py`: `next_stacks` table: `(200, 200) → (200, 200, 0)`; bot `79 → 200`; bot `80` stays; bot `301 → 200`; bot `300` stays; Hero `9 → 200` with bought `191` whatever `top_up` is; Hero `150` with `top_up=True → 200`, bought `50`; Hero `150` without stays; Hero `450` with `top_up=True` stays.
  - `test_properties.py` (hypothesis, 200 examples in the fast suite; a `slow` variant with 3,000): for a random profile, button, Hero stack in [10, 600], bot stack in [80, 300] and a seeded Hero who picks uniformly from `hero_options` (and, post-flop, sometimes a random legal custom size), every hand ends with an outcome, `sum(outcome.stacks) == sum(start_stacks)`, and no `UnsupportedSpot` or `ValueError` escapes. A second property: over 2,000 sampled bot decisions at one fixed state, the action frequencies match `action_distribution` for the bot's combo within a 5-sigma binomial bound.
- [ ] **Step 2:** Run; they fail.
- [ ] **Step 3:** Implement as in Decisions ("Hand record and replay", "Session rules"). The plan review's simulation found no short-stack spot the strategy can't play. If the property test finds one anyway, stop and report it; don't change `villain/strategy.py` in this task.
- [ ] **Step 4:** All backend checks, plus `uv run pytest -m slow tests/play tests/villain`.
- [ ] **Step 5: Commit** `feat(play): hand engine — bot acts from the policy, deterministic resume, session stack rules`

### Task 3: Analysis adapter (Opus)

**Files:**
- Create: `backend/src/poker_trainer/play/analyse.py`, `backend/tests/play/test_analyse.py`

**Interfaces — consumes:** Task 2's record functions, `grade_action`, `Spot.start_stacks`. **Produces:** `hero_decisions`, `decision_spot`, `analyse_decision`, `DecisionAnalysis`.

- [ ] **Step 1: Failing tests** (use `samples=2_000` to keep them fast; build records by scripting `hero_act` on seeded hands):
  - `hero_decisions` counts Hero's actions, in order, for a hand that goes to the river.
  - For every decision of 30 seeded hands: `decision_spot`'s state has Hero to act; its history is the record's prefix; `steps[-1].range` equals an independent `RangeTracker` replay of the bot's earlier actions passed through `visible_range`; the bot's actual combo has weight > 0 in it; `start_stacks` is the record's.
  - `analyse_decision` returns a puzzle and a grade whose `chosen.option.action` is Hero's action; calling it twice gives identical `ev_chips` for every option (seeded MC).
  - It grades with the snapshot: analysing with a profile built from an edited snapshot (e.g. `btn_call_threebet` emptied) changes a 3-bet option's EV, while the live profile file is untouched.
  - A custom post-flop size not in the listed options is graded (the appended option), with no `load_profile` call (monkeypatch it to raise).
  - Forcing `solve` to raise `UnsupportedSpot`, and separately forcing `RangeTracker.observe` to raise `ValueError` (monkeypatch), each yields `not_graded` with the message and no exception.
  - `villain_hole` is the bot's cards and `runout` is `deck[4:9]`, so `views.showdown(spot)` works for any decision.
  - A `slow` test: a 6-decision hand at the default sample count is analysed in under 10 s; print the time.
- [ ] **Step 2:** Run; they fail.
- [ ] **Step 3:** Implement as in Decisions ("Analysis adapter").
- [ ] **Step 4:** All backend checks, plus `uv run pytest -m slow tests/play`.
- [ ] **Step 5: Commit** `feat(play): per-decision analysis with the puzzle grader and the session's profile snapshot`

### Task 4: Storage and play views (Sonnet)

**Files:**
- Create: `backend/src/poker_trainer/db/migrations/versions/0004_play.py`, `backend/src/poker_trainer/api/play_views.py`, `backend/tests/api/test_play_views.py`
- Modify: `backend/src/poker_trainer/db/models.py`, `backend/src/poker_trainer/api/schemas.py`
- Test: `backend/tests/db/test_migrations.py`, `backend/tests/db/test_models.py`

**Interfaces — consumes:** Tasks 1–2. **Produces:** `PlaySessionRow`, `PlayHandRow`, `PlayDecisionRow`; the schemas `TableView`, `TableFrame`, `PlayOutcome`, `PlayHandView`, `PlaySessionView`, `PlaySessionSummary`, `PlayHandSummary`, `PlayActionIn`, `NextHandIn`; `play_views.table_view(record, profile) -> dict`, `play_views.frames(record) -> list[dict]`, `play_views.hand_view(hand_id, hand_no, session_id, record, profile, *, decision_count) -> dict`, `play_views.session_view(session_fields, hand_view | None) -> dict`.

- [ ] **Step 1: Failing tests.**
  - Migration: upgrade from 0003 creates the three tables with the partial unique index and both unique constraints; downgrade drops them; the head assertion and the batch probe's `down_revision` in `test_migrations.py` move to `0004_play`; `test_models_match_migrations` passes.
  - `test_models.py`: a second open session for one user raises `IntegrityError`, and is allowed once the first has `ended_at`; a second `(session_id, hand_no)` and a second `(hand_id, n)` raise.
  - `test_play_views.py`:
    - `table_view` of a running hand: positions, `to_call`, `pot_odds`, `stacks`, `street_bets`, `pot`, `board` and `history` equal `puzzle_view`'s for the equivalent `Spot` (solve it with `samples=500` to get a `Puzzle`); the profile label comes from the profile object passed in (pass one whose label was edited).
    - `frames` has `len(history) + 1` entries; `frames[0]` is the blinds (`street_bets` 1 and 2, `board_len` 0); the last frame equals the table; `board_len` steps 0 → 3 → 4 → 5; chips are conserved in every frame (`sum(stacks) + pot == sum(start_stacks)` with `pot` including bets in front, matching `TableView.pot`).
    - **No leak (Review Focus 4):** over 200 seeded hands at every action prefix, the serialised `hand_view` contains neither of the bot's cards as a quoted token (search for `'"Th"'`, not `Th`) unless the hand ended in a showdown, no undealt board card, and no `deck` or `bot_seed` key.
    - A finished hand: `stacks` are the settled stacks, `street_bets` zero, `pot` the awarded pot, `options` empty, `custom.allowed` false; a showdown outcome has `villain_cards` and `showdown`; a fold or an abandoned hand has neither.
    - Every new model validates the views' output and forbids extra keys.
- [ ] **Step 2:** Run; they fail.
- [ ] **Step 3:** Implement models, the migration, the schemas and the pure views as in Decisions ("Storage", the view models under "API").
- [ ] **Step 4:** All backend checks.
- [ ] **Step 5: Commit** `feat(db): play sessions, hands and decisions tables; table and hand views`

### Task 5: Play service and routes (Sonnet)

**Files:**
- Create: `backend/src/poker_trainer/api/play_service.py`, `backend/tests/api/test_play_api.py`
- Modify: `backend/src/poker_trainer/api/app.py`, `backend/tests/api/conftest.py`, `backend/tests/api/test_contract.py`, `backend/tests/api/test_isolation.py`, `frontend/openapi.json`, `frontend/src/api/schema.d.ts` (regenerated: `npm run gen:openapi && npm run gen:api`)
- Test: `backend/tests/api/test_openapi_snapshot.py`

**Interfaces — consumes:** Tasks 1, 2, 4. **Produces:** every route in the API table except the three analysis routes; `create_app(..., play_rng=None, play_samples=None)`; `play_service.load_hand(db, user_id, hand_id) -> tuple[PlayHandRow, PlaySessionRow, HandRecord, Profile]`; the `play_client` test fixture (an app with a seeded `play_rng` and `play_samples=500`).

- [ ] **Step 1: Failing tests** (`test_play_api.py`, seeded through `play_rng`):
  - start → 201 with a hand (Hero to act, or already finished when the bot folded the button); a second start → 409; `GET current` returns the same session; after `end`, `GET current` → 404 and `end` again → 200.
  - Play a scripted hand to the end by posting option indices with the right `expected_actions`: each response's `history` extends the previous one; the final `outcome` equals `outcome(record)`; `hands_played` is 1; `hero_stack + bot_stack == 400`.
  - **Resume (Review Focus 2):** `GET current` between every action equals the action's response.
  - **Stale and double clicks (Review Focus 5):** repeating a POST with the same `expected_actions` → 409 and the hand is unchanged; an action on a finished hand → 409; an out-of-range option → 422; a custom size pre-flop → 422; `POST hands` while a hand runs → 409; `POST hands` twice after a hand ends → one 201 and one 409 (or the same new hand; never two); `POST hands` after `end` → 409.
  - Stack rules: a session row forced to `hero_stack=6` reports `must_rebuy`, and the next hand starts Hero at 200 with `hero_bought_chips` up by 194; `top_up` at 150 adds 50; a bot at 60 is topped up; a bot at 320 is reset.
  - **Tally (Review Focus 3):** over a 30-hand seeded session with rebuys forced, `net_chips == hero_stack − hero_bought_chips` after every hand; ending mid-hand leaves the pot with the bot and counts the hand.
  - The profile is the snapshot: after the session starts, monkeypatching `load_profile` to raise breaks nothing.
  - `GET sessions` and `GET sessions/{id}/hands` list what was played (`decision_count`, `analysed: false`); another user's session and hand ids → 404 (extend `test_isolation.py`).
  - `test_contract.py`: the new routes and models are in `ROUTES`, the forbid list and the exact-keys test. OpenAPI snapshot updated.
- [ ] **Step 2:** Run; they fail.
- [ ] **Step 3:** Implement the service and routes as in Decisions ("Storage", "API"). The session stores `profile_data(name)`; every later read builds the profile with `profile_from_dict`. Finishing a hand updates the hand row and its session row in one transaction.
- [ ] **Step 4:** All backend checks; regenerate `openapi.json` and `schema.d.ts`; `npm run check:api`, `npm run typecheck`.
- [ ] **Step 5: Commit** `feat(api): play sessions — start, act, next hand, end, lists`

### Task 6: Analysis API and fixtures (Sonnet)

**Files:**
- Modify: `backend/src/poker_trainer/api/views.py`, `api/play_service.py`, `api/play_views.py`, `api/schemas.py`, `api/app.py`, `api/dev_fixtures.py`, `backend/src/poker_trainer/explain/service.py`, `backend/tests/api/test_contract.py`, `frontend/openapi.json`, `frontend/src/api/schema.d.ts`
- Create: `backend/tests/api/test_play_analysis.py`, the six `frontend/src/test/fixtures/play_*.json`
- Test: `backend/tests/api/test_views.py`, `tests/api/test_dev_fixtures.py`, `tests/explain/test_explainer.py`

**Interfaces — consumes:** Tasks 3–5. **Produces:** the three analysis routes; the schemas `DecisionGrade`, `DecisionReview`, `PlayReveal`, `AnalysisSummary`, `HandAnalysis`; `views.decision_core(...)`; `play_views.decision_review(row, record, profile) -> dict`; `play_views.hand_analysis(...) -> dict`; `dev_fixtures.write_play_fixtures(out)` and a `--play-only` flag on its CLI.

- [ ] **Step 1: Failing tests.**
  - `test_views.py`: before refactoring, save `attempt_result`'s output for the cached puzzles (one listed-option answer and one custom-size answer per street) under `backend/tests/api/data/attempt_results.json`; the test asserts the refactored function returns exactly that.
  - `test_play_analysis.py` (the `play_client` fixture):
    - `GET analysis` on a running hand → 409; on a finished hand before any POST → every decision `null`, `summary` null, the reveal present with the bot's cards; a hand with no Hero decision → `decisions: []`.
    - `POST analysis/0` returns a graded `DecisionReview` whose `view` is the table as it stood (board length, pot and `to_call` checked against the record) and whose `options` has exactly one `is_chosen` and one `is_best`; a second POST returns the identical body without solving again (count calls to `analyse_decision`).
    - After every decision is posted, `summary.ev_loss_bb` is the sum of the graded decisions' `ev_loss_bb` and `worst_index` is the largest; the hand list shows `analysed: true` and the same EV lost.
    - A hand that ended in a fold reveals the bot's cards in the analysis, the board only as far as it was dealt, and `showdown: null`.
    - A `not_graded` decision (monkeypatched) is stored and returned with `status: "not_graded"` and a reason, is left out of the summary, and does not block the others.
    - `model_changed` is false normally and true when `STRATEGY_VERSION` is monkeypatched up.
    - A hand from an ended session can be analysed. `n` out of range → 404; another user's hand → 404.
    - The explanation route returns the template with `fallback: "off"` when no provider is set; for a `not_graded` or not-yet-analysed decision → 404.
    - For every graded decision of 10 seeded hands, the template explanation passes the M8 guardrail's number check against its facts (reuse the helper the explain tests use).
  - `test_explainer.py`: a tuple cache key caches and logs like an int one.
  - `test_dev_fixtures.py`: the play fixtures are written, deterministic across two runs, LF-terminated and validate against the response models.
- [ ] **Step 2:** Run; they fail.
- [ ] **Step 3:** Implement as in Decisions ("API", the shared decision core, fixtures). Generate fixtures with `--play-only`, so no existing fixture is rewritten.
- [ ] **Step 4:** All backend checks, plus `uv run pytest -m slow tests/api`; regenerate `openapi.json` and `schema.d.ts`; `npm run check:api`, `npm test`.
- [ ] **Step 5: Commit** `feat(api): hand analysis per decision, stored once, with explanations; play fixtures`

### Task 7: Table components take a play hand (Sonnet)

**Files:**
- Modify: `frontend/src/api/types.ts`, `frontend/src/lib/seats.ts`, `lib/history.ts`, `lib/answer.ts`, `components/AnswerPanel/AnswerPanel.tsx`, `components/HistoryPanel/HistoryPanel.tsx`, `app/useExplanation.ts`, `app/App.tsx` (call sites only), and their tests
- Modify: `frontend/src/dev/entries/answer.tsx` (a `guesses={false}` example)

**Interfaces — consumes:** Task 6's `schema.d.ts` and fixtures. **Produces:** the types `TableView`, `ActionView`, `PlayHandView`, `PlaySessionView`, `PlayActionChoice` (`{option: number} | {custom_to: number}`), `DecisionReview`, `HandAnalysis`; `AnswerPanel` props `guesses`, `draftKey`, `onAct`; `validateAction`; `groupHistory(view, answer?, toAct?)`; `HistoryPanel` prop `toAct`; `useExplanation(key, template, fetcher, settings)`.

- [ ] **Step 1: Failing tests.**
  - `AnswerPanel.test.tsx`: with `guesses={false}` and the play fixture there is no Equity box, no range read, no intent group and no attempts note; picking an action (and a size) enables Submit and calls `onAct` with `{option}` or `{custom_to}`; a custom size outside the bounds shows the existing error; the shortcuts for fold / check / call / bet-raise, the size digits and submit still work; changing `draftKey` resets the draft. The puzzle path's existing tests pass unchanged.
  - `answer.test.ts`: `validateAction` needs an action, and a size for a bet or raise; it returns the option index or the custom chips.
  - `history.test.ts`: `groupHistory` with `toAct` `'villain'` ends with "Villain to act", with `null` ends with no to-act line, and by default behaves as today.
  - `seats.test.ts` and `HistoryPanel.test.tsx`: both accept a play `table`.
  - `useExplanation.test.tsx`: the existing cases pass through the new signature; a string key with a custom fetcher fetches once per key.
- [ ] **Step 2:** Run; they fail.
- [ ] **Step 3:** Implement as in Decisions ("Frontend"). No visual change to the Puzzles page.
- [ ] **Step 4:** All frontend checks and `npm run e2e` (the existing smoke tests prove Puzzles is unchanged).
- [ ] **Step 5: Commit** `refactor(ui): answer panel, seats, history and explanations accept a play hand`

### Task 8: Play page (Sonnet)

**Files:**
- Create: `frontend/src/app/usePlayFlow.ts`, `frontend/src/components/Play/PlayPage.tsx`, `HandOverPanel.tsx`, `StartPanel.tsx`, `Play.module.css`, `frontend/src/lib/play.ts`, `frontend/src/dev/entries/play.tsx`, `frontend/e2e/play.spec.ts`, and tests for each
- Modify: `frontend/src/api/client.ts`, `lib/page.ts`, `lib/shortcuts.ts`, `app/App.tsx`, `components/TopBar/TopBar.tsx`, `components/ShortcutsOverlay/ShortcutsOverlay.tsx`, `frontend/e2e/smoke.spec.ts` (only if a selector needs it), and their tests

**Interfaces — consumes:** Task 5's routes, Task 6's fixtures, Task 7's components. **Produces:** `usePlayFlow(api?, {enabled}) -> PlayFlow` (`state`, `session`, `shownCount`, `revealing`, `start`, `act`, `nextHand(topUp)`, `end`, `retry`); `PlayApi`; `lib/play.ts`: `resultLine(outcome) -> string`, `tallyText(session) -> string`, `tableAt(hand, shownCount) -> TableView`, `toActAt(hand, shownCount)`; `PlayPage` props `{flow, settings, shortcutsOn, onAnalyse(handId)}`.

- [ ] **Step 1: Failing tests.**
  - `play.test.ts`: `resultLine` for a Hero win by fold ("You won 1.5 bb"), a loss at showdown ("Villain won 12 bb at showdown"), a split ("Split pot"), an abandoned hand ("Hand ended: you gave up the pot"); `tallyText` ("+12.5 bb · 14 hands", "−3 bb · 1 hand", "0 bb · 0 hands"); `tableAt` with a smaller `shownCount` takes stacks, bets, pot and the board length from that frame and cuts the history.
  - `usePlayFlow.test.tsx` (fake API, fake timers): no session → `idle`; `start` → `playing`; after `act`, the bot's new entries appear one per 600 ms and `revealing` is true until they have; `act` is ignored while revealing or while a request is in flight, and sends the hand's `action_count` as `expected_actions`; a 409 reloads the current session; a response that ends the hand → `handOver` once the reveal is done; `nextHand` → `playing`; an API error → `error` with `retry`; `end` → `idle`; a session loaded mid-hand shows its whole history at once.
  - `PlayPage.test.tsx` (fixtures): Hero to act shows the table, face-down bot cards and the action panel; during the bot's reveal the panel is disabled and the history ends with "Villain to act"; hand over by fold keeps the bot's cards face down and shows the result line, "Next hand" and "Analyse this hand"; hand over by showdown shows the bot's cards; a hand with `decision_count` 0 has no Analyse button; `must_rebuy` reads "Rebuy and deal"; "Top up to 100 bb" shows only when `can_top_up`; the profile shows only when `show_profile` is on; the start panel shows the help note and the past sessions.
  - `TopBar.test.tsx`: a "Play" link; on Play the tally and "End session" show, the street and profile selects and "New puzzle" don't, and the toggles and help do. `App.test.tsx`: `/play` renders the Play page, the tab title is "Play · Poker Puzzle Trainer", Puzzles' half-entered answer survives a visit, and puzzle shortcuts don't fire on Play. `shortcuts.test.ts`: `N` is "Next hand" on Play.
  - `e2e/play.spec.ts`: open `/play`, start a session, play hands by clicking the first enabled action (and first size) until one is over, check the result line and the tally, press `N` for the next hand, reload mid-hand and see the same cards and history, end the session and see the start panel with the session listed. The top bar is one row at 1280 on Play and still on Puzzles (the existing check).
- [ ] **Step 2:** Run; they fail.
- [ ] **Step 3:** Implement as in Decisions ("Frontend"). The Play page stays mounted but hidden on other pages, like Puzzles.
- [ ] **Step 4:** All frontend checks and `npm run e2e`. Screenshots (Hero to act, hand over by showdown, start panel) at 1280×800 and 1024×768 for the reviewer.
- [ ] **Step 5: Commit** `feat(ui): Play page — sessions, full hands against the bot, tally, resume`

### Task 9: Hand analysis view and session hands (Sonnet)

**Files:**
- Create: `frontend/src/components/Play/HandAnalysis.tsx`, `SessionHands.tsx`, `frontend/src/app/useHandAnalysis.ts`, and tests for each
- Modify: `frontend/src/lib/decision.ts`, `lib/result.ts`, `components/Play/PlayPage.tsx`, `components/Play/StartPanel.tsx`, `components/Play/Play.module.css`, `api/client.ts`, `app/App.tsx`, `src/dev/entries/play.tsx`, `e2e/play.spec.ts`, and their tests

**Interfaces — consumes:** Task 6's routes and fixtures, Tasks 7–8. **Produces:** `useHandAnalysis(handId, api?) -> {analysis, progress: {done, total}, error, retry}`; `decisionFromReview(review) -> DecisionData`.

- [ ] **Step 1: Failing tests.**
  - `decision.test.ts`: `decisionFromReview` of the fixture gives a `DecisionData` that `OptionsTable`, `MathsPanel` and `RangePanel` render; a custom chosen label is shown in bb; `intent` is null.
  - `useHandAnalysis.test.tsx`: it GETs, then POSTs each `null` decision in order and reports progress; stored decisions are not posted again; a failed POST stops with `error` and `retry` continues from that decision; unmounting or a new `handId` stops the loop and drops late responses.
  - `HandAnalysis.test.tsx`: while loading it shows "Analysing decision 2 of 5…"; when done, the summary shows the total EV lost and marks the worst step; clicking a step shows its verdict line and `DecisionDetails` with Why, Options, Maths, Range and Hand tabs; the Hand tab shows the bot's cards and profile for a hand that ended in a fold; a `not_graded` step reads "Not graded: …" and has no details; `model_changed` shows "Villain model has changed since this hand"; the "judged on range" note is present; no equity-guess or range-read score appears; the Why tab asks the play explanation route when a model is on.
  - `SessionHands.test.tsx`: rows show hand number, position, result and, when analysed, EV lost; the button reads "Analyse" or "Review" and is absent for a hand with no decision; clicking calls `onOpen(handId)`.
  - `PlayPage.test.tsx`: "Analyse this hand" opens the analysis of the hand just played; closing it returns to the hand-over panel with "Next hand" still available; a past session's hands open from the start panel.
  - `e2e/play.spec.ts` (extended): play until a hand with at least one Hero decision is over, click Analyse, wait for the summary, open each tab of the first decision, close, play the next hand; then open the analysed hand again from the session's hand list and see it without a loading state.
- [ ] **Step 2:** Run; they fail.
- [ ] **Step 3:** Implement as in Decisions ("Frontend").
- [ ] **Step 4:** All frontend checks and `npm run e2e`. Screenshots (the summary with steps, each details tab, the session hands list) at 1280×800 and 1024×768.
- [ ] **Step 5: Commit** `feat(ui): hand analysis — graded decisions step by step, session hand list`

## Finish

Final whole-branch review (Opus), one fix wave, scoped re-review. Run every check in CLAUDE.md yourself, plus `uv run pytest -m slow tests/play tests/api tests/puzzle tests/villain`. Then a docs commit: follow-ups, rulings and open items for M11 and later at the end of this plan; the roadmap's M10 section (what was built, in how many commits); `handoff.md` (§4 `STRATEGY_VERSION`, §5 status); CLAUDE.md status line; a "Play vs Bots" paragraph in the README. Push `adarsh` and open a PR into `main` listing the rulings.

## Not in M10 (recorded for later)

- UI polish of the Play page and the analysis (M11).
- Per-session EV-lost statistics beyond the hand list; play stats on the Progress page.
- Hero choosing the bot's profile; limps and small 4-bets (a Villain-model task).
- The M9 open items not listed under "Villain and grader prep" (explainer fact pair for "X beats Y", guardrail rejection reasons, the Villain tuning list, code minors).

## Follow-up after the final M10 review

The final whole-branch review (Opus) found nothing Critical or Important. It checked the spec's anti-goals and the five Review Focus items end to end, and probed abandoned hands. The fix wave (commit "fix(play): final review fixes") did these:

- `tableAt` no longer computes `to_call` and `pot_odds` in the browser for a partial frame (0 and null; the server's table at the full count), so no shown number can disagree with the API.
- Escape on Play no longer cancels a skip that is pending on Puzzles.
- `next_hand` writes the session only while it is still open (`WHERE ended_at IS NULL`), so a "Next hand" racing "End session" in two tabs answers 409 instead of leaving a running hand in an ended session.
- The analysis' Hand tab says "No showdown." (it said "ended with a fold" for an abandoned hand too).
- The analysis summary says "No decision could be graded." when nothing was graded, instead of "No decision lost EV."
- The hand's EV-lost total is repaired on the next GET if a crash came between storing the last decision and writing the total; its UPDATE also filters by `user_id`.

Rulings made during M10, with what each costs if wrong:

1. Branch `adarsh`, commits authored as the configured git user (Adarsh) with no trailers: the user's ruling, against CLAUDE.md's milestone branch and spandan3 author. Cost if wrong: history authorship.
2. Frames describe the table during play: a finished hand's last frame is the pre-award table, while `table` holds the settled stacks. Cost if wrong: a small view change.
3. The property tests are in `tests/play/test_play_properties.py`, because `tests/puzzle/test_properties.py` owns the basename. Cost: none.
4. `advance()` on a finished hand returns it unchanged and raises only on an abandoned hand. Cost: none; callers check `outcome()`.
5. `abandon()` on a finished hand raises; on an abandoned hand it returns it unchanged. Cost: small.
6. The decision index `n` is 0-based in the API and 1-based only in UI copy. Cost: none.
7. A custom size in an analysis is graded at the config's sample count, not the adapter's override (the grader's existing behaviour). Cost: test speed only.
8. `NextHandIn` gained `expected_hands`; `POST hands` answers 409 when it differs from the session's `hands_played`. It was needed for "never two hands" when a hand ends at the deal. Cost: one request field.
9. `act` refuses with 409 once the session has ended, and the 30-hand tally test forces a rebuy. Cost: none.
10. `DecisionGrade` has no `intent` and no `intent_flag` (no intent in play), and a `not_graded` review still carries its table `view`. Cost: none.
11. `validateAction`'s signature is `(state, view, opts)`, matching `validateAnswer`. Cost: none.
12. `shownTally`: the top-bar tally counts a finished hand only once its reveal is done, so it never gives away the result early. Cost: none.
13. "End session" has no confirmation in M10 (polish for M11). Cost: a misclick abandons a hand.
14. `PlayPage` owns the open analysis; the planned `onAnalyse` prop was dropped. Cost: none.
15. The final fix wave also took four cheap items beyond the two marked "fix now". Cost: a slightly larger fix wave.
16. Every other deferred minor became an open item below. Cost: follow-up work in M11/M12.

## Open items for M11 and later

- **UI (M11):**
  - "End session" has no confirmation, and it is silently ignored while a request is in flight.
  - The shortcuts overlay files "Next hand" under the group "Puzzle".
  - The options table scrolls sideways inside its panel at 1024.
  - The analysis sits under the table, so the page scrolls at 1280×800.
  - A finished hand's table shows the settled stacks plus the awarded pot; show pot 0 or "won X".
  - The past-session hand list goes stale after analysing a hand; give StartPanel a `refreshKey`.
  - Analysis retry gives no feedback while it reloads.
  - The hand list's load error has no retry.
  - StartPanel converts `net_bb` back to chips to format it.
  - The dev gallery's Play entries nest `<main>`.
- **Explainer:** play explanations say "the range this puzzle was graded on"; thread a "hand" noun through the facts and template, keeping the guardrail checks.
- **Backend:**
  - `end` racing `act` answers 409 rather than an idempotent 200.
  - `start_session` flushes before dealing.
  - `list_sessions` computes `net_bb` inline and builds a `Profile` per row just for its label.
  - The `IntegrityError` path in `analyse` asserts its re-read.
  - `play_service` calls `service._check_finite`, and `play_views` calls `views._street_name` and `_cards`; make them public.
  - `models.py` has `hero_bought_chips` default `200` as a literal.
  - `frames` replays each prefix (O(n²)).
- **Engine:**
  - The showdown winner comes from the sign of Hero's delta; assert the equal-contribution invariant.
  - `Grade` repeats `ActionGrade`'s fields; add a field-subset test.
  - `Spot.start_stacks`' sum check runs only when a spot is decoded from a dict.
- **Types:** `AnswerPanel`'s `onSubmit` and `onAct` are optional with no type link to `guesses`, and a missing callback locks the panel. The HistoryPanel doc comment is stale.
- **Tests:**
  - The migration test doesn't assert that the open-session index is partial.
  - `attempt_results.json` has no non-best custom case and no `bluff_check: null` case.
  - The abandoned-hand analysis test branch depends on the seed.
  - The custom-size picker in `test_analyse` can raise `StopIteration`.
  - A SessionHands test name claims a failure case it doesn't test.
  - `HandAnalysis.test` has dead setup.
  - `test_contract`'s forbid list omits `ProfileInfo`, `OptionBrief` and `CustomSizes` (covered by exact keys).
- **M12 (5-max):** `HERO_SEAT`/`BOT_SEAT`, two-element stacks, `1 - seat` and `TableFrame` are heads-up only; the record, the frames and the views need generalising.
- Still open from M9: the items under "Open items for M10 and later" in `2026-11-13-m9-signoff.md`, except the grader's `config_version` check, which M10 did.
