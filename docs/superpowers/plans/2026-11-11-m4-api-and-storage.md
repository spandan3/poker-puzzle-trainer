# M4 API and Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist puzzles and attempts for a default local user, and serve them over a FastAPI JSON API. The API must hide everything Villain-side until the user submits an answer. After a submit, it returns the full frozen result, with the grade stored so it is never silently recomputed.

**Architecture:**
- `poker_trainer.settings` reads environment config (with an optional `.env`).
- `poker_trainer.db` holds the SQLAlchemy 2.0 models, the engine and session helpers, the default local user and Alembic migrations. The migrations ship inside the package, so the app can upgrade the database on startup.
- `poker_trainer.api` holds four modules:
  - `views`: pure functions that turn a frozen `Puzzle` / `Grade` into JSON-safe dicts. It has no DB and no FastAPI.
  - `text`: maps codes to display text.
  - `service`: DB plus puzzle logic.
  - `app`: the FastAPI routes, Pydantic request/response schemas and static frontend serving.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2.0, Alembic, uvicorn, SQLite (Postgres via config), pytest, httpx (`TestClient`), uv. Builds on M3 `puzzle` (`generate_puzzle`, `grade`, `puzzle_to_dict` / `puzzle_from_dict`).

**Spec:** `docs/superpowers/specs/2026-11-10-poker-puzzle-trainer-design.md` (§3 storage and hosting readiness, §4 puzzle experience, §7.8–7.9 frozen puzzles and separate attempts, §8 results, §10 what every attempt saves, §11 settings). Roadmap: `docs/superpowers/plans/2026-11-10-roadmap.md`. M3 hand-over items: the "Open items for M4" section of `docs/superpowers/plans/2026-11-10-m3-puzzle-and-grader.md`.

## Global Constraints

- **Villain is hidden until a submit.** No response before an attempt may contain any of these:
  - Villain's hole cards;
  - board cards not yet dealt at the decision;
  - any range or range step;
  - any part of `Solution` (equity, `ahead_now`, option EVs, `best`, the category breakdown);
  - the seed or the generation `attempt` (with the code, the seed reproduces the hand on the same platform).
- **Store puzzles, not seeds.** Puzzles are stored frozen and are never regenerated. A replay reads the stored puzzle. Load it with `puzzle_from_dict`; a `format` other than 1 raises, and the API maps that to HTTP 500 with the message `"unsupported puzzle format"`.
- **Grades are stored, never recomputed on read.** An attempt stores its inputs and its full grade, including the chosen `OptionEV` and the best option's label and EV, plus `config_version` = the live `load_config().version` at grading time (verdict bands come from the live config). Puzzle-time versions stay on the puzzle row. `GET` of an attempt returns what was stored.
- **Canonical actions only.** The client never sends an `Action`. It sends either `option` (an index into the puzzle's stored options) or `custom_to` (post-flop bet/raise total), which the server turns into an action through `custom_action(state, to)`. Exactly one of the two.
- **Every row has a `user_id`.** One default local user (`id = 1`, `name = "local"`) is created idempotently at startup. Every query filters by the current user (`current_user` dependency). Another user's rows return 404, never 403, so their existence isn't revealed.
- **All config via environment variables**, each with a safe default; `.env` is read if present and never committed. Prefix `PPT_`.
- **UTF-8 end to end.** Branch labels contain an em dash. JSON responses are UTF-8; puzzle blobs are UTF-8 JSON, zlib-compressed.
- **No NaN or infinity in any response.** Floats come from finite stored values. Request floats are validated as finite and in range.
- **Dependencies** must have wheels (or be pure Python) for Windows and macOS on Python 3.13. Use plain `uvicorn`, not `uvicorn[standard]` (uvloop has no Windows wheels). Update the single `uv.lock`.
- **No LLM.** M4 does not change behaviour in `engine/**`, `puzzle/**`, `game/**` or `villain/**`. The only edit there is the public alias in Task 2A. The handoff gives Villain tuning to a separate `villain/*` branch.
- **Test basenames are unique across `tests/`** (the test dirs have no `__init__.py`, so pytest fails on duplicate basenames).
- **Timestamps are always UTC-aware** in Python and in every response (ISO strings ending `+00:00`), including on SQLite, which drops the tzinfo on read.
- Chips are ints; the API reports bb as `chips / 2` alongside chips where the M6 maths display needs both. Commands run from `backend/`. Works on Windows and macOS.

## Decisions made in this plan

- **Environment config** (`poker_trainer.settings.AppSettings`, pydantic-settings, `env_prefix="PPT_"`, `env_file=".env"`):

  | Variable | Default | Meaning |
  |---|---|---|
  | `PPT_DATABASE_URL` | `sqlite:///./poker_trainer.db` | Any SQLAlchemy URL. Relative to the working directory (`backend/`). `*.db` is already git-ignored. |
  | `PPT_FRONTEND_DIST` | `../frontend/dist` | The built frontend. Served only if the directory contains `index.html`. |
  | `PPT_HOST` / `PPT_PORT` | `127.0.0.1` / `8000` | Used by the `serve` script. |
  | `PPT_LLM_PROVIDER` | `none` | Reported read-only in settings. Only `none` is valid until M8. |

  `get_settings()` is `lru_cache`d; tests build `AppSettings(_env_file=None, ...)` directly, so a developer's `.env` never leaks into tests, and pass it to `create_app`. A committed `backend/.env.example` lists every variable with its default.
- **Tables** (SQLAlchemy 2.0 typed `Mapped[...]`):
  - Timestamps use a `UTCDateTime` TypeDecorator over `DateTime(timezone=True)`. It requires aware values on write, converts them to UTC, and attaches UTC on read.
  - `Base.metadata` has a naming convention (`ix`, `uq`, `ck`, `fk`, `pk`), so SQLite batch migrations can alter named constraints later.
  - `users`: `id` (int pk), `name` (str 64, unique), `created_at`.
  - `user_settings`: `user_id` (pk, fk users), `show_pot_odds` (bool, default True), `show_profile` (bool, default True), `profile` (str 16, nullable; null = random), `daily_goal` (int, default 10), `updated_at`.
  - `puzzles`: `id` (int pk), `user_id` (fk, indexed), `created_at`, `seed` (BigInteger), `street` (str 8: `preflop` / `flop` / `turn` / `river`), `profile` (str 16), `profile_version`, `categories_version`, `config_version`, `format` (int), `data` (LargeBinary: zlib-compressed UTF-8 `puzzle_to_dict` JSON).
  - `attempts`: `id` (int pk), `user_id` (fk, indexed), `puzzle_id` (fk, indexed), `attempt_no` (int; 1 is the first), `is_first` (bool, `attempt_no == 1`), `created_at`. Inputs: `option_index` (int, nullable), `custom_to` (int, nullable), `action` (JSON: seat/kind/street/to), `equity_guess` (float), `range_read_guess` (float, nullable), `intent` (str, nullable). Grade: `verdict` (str 8, indexed), `action_kind` (str 8, indexed: the chosen action's kind), `best_kind` (str 8: the best option's kind), `ev_loss_chips`, `equity_error`, `equity_score`, `range_read_error` (nullable), `range_read_score` (nullable), `intent_truth` (nullable), `intent_flag` (Text, nullable), `bluff_required` and `bluff_actual` (nullable floats), `chosen` (JSON: the chosen `OptionEV` dict in the same shape as `puzzle_to_dict` options), `best_label` (str), `best_ev_chips` (float), `config_version` (live at grading; see above).
  - Unique constraint `(puzzle_id, attempt_no)`, so two concurrent submits can't both be first. The service computes `attempt_no = max + 1` inside the transaction and retries once on `IntegrityError`.
- **Puzzle blob:** `encode_puzzle(p) -> bytes` = `zlib.compress(json.dumps(puzzle_to_dict(p), ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 6)`, and `decode_puzzle(b) -> Puzzle` reverses it. Python's `json` writes floats with `repr`, so the round-trip is bit-exact. A typical puzzle is about 133 KB as JSON and about 7 KB compressed. No float32 or sparse encoding: exact beats smaller here.
- **Migrations:** Alembic, with `script_location = poker_trainer.db:migrations` so the scripts ship as package data. `backend/alembic.ini` exists for the CLI (`uv run alembic upgrade head`, `uv run alembic revision --autogenerate`). `db.migrate(url)` runs `upgrade head` programmatically and passes the URL through `cfg.attributes["url"]`, never `set_main_option`, because a `%` in a Postgres password breaks configparser. `env.py` uses `config.attributes["url"]` when present and falls back to `get_settings().database_url` for the CLI. It calls `fileConfig(config.config_file_name, disable_existing_loggers=False)` only when `config_file_name` is set, so running migrations in the app lifespan never silences uvicorn's loggers. Revision `0001_initial` creates all four tables. SQLite migrations use `render_as_batch=True`. A test checks that autogenerate against the head schema finds no differences, so the models and migrations can't drift.
- **Engine and sessions:** `make_engine(url)` (SQLite: `check_same_thread=False`, and `PRAGMA foreign_keys=ON` on connect). `make_sessionmaker(engine)`. `ensure_default_user(session) -> User` is idempotent and also creates the default `user_settings` row.
- **App factory:** `create_app(settings: AppSettings | None = None, *, puzzle_factory: PuzzleFactory | None = None) -> FastAPI`.
  - On startup (lifespan) it migrates the database and ensures the default user; on shutdown it disposes the engine, so Windows can delete a tmp DB file. Tests must use `with TestClient(app) as client:`; without the context manager the lifespan never runs.
  - `PuzzleFactory = Callable[[int, Street | None, str | None], Puzzle]` defaults to `lambda seed, street, profile: generate_puzzle(seed, street=street, profile=profile)`. Tests inject a factory that returns cached puzzles, so the API suite never pays for generation per test.
  - Seeds come from `secrets.randbelow(2**62)`. If the factory raises `RuntimeError` (no non-trivial puzzle), the service retries with a fresh seed up to 3 times, then returns 503 `"could not generate a puzzle, try again"`.
- **Route handlers are plain `def`**, so FastAPI runs them in its threadpool. Generation is CPU-bound (about 0.2–3 s) and must not block the event loop.
- **Endpoints** (all JSON, all under `/api`). Roadmap commit 2:
  - `GET /api/health` → `{"status": "ok", "version": poker_trainer.__version__}`.
  - `POST /api/puzzles` with body `{"street": "flop" | null, "profile": "tag" | null}` (both optional) → 201 `PuzzleView`. A null profile falls back to the user's settings `profile`, and then to random. An unknown street or profile → 422.
  - `POST /api/puzzles/{id}/attempts` with body `AttemptIn` → 201 `AttemptResult`.
  - `GET /api/attempts/{id}` → `AttemptResult`.

  Roadmap commit 3:
  - `GET /api/puzzles/{id}` → `PuzzleView` (the hidden view, used for replay).
  - `GET /api/puzzles/current` → the newest unanswered puzzle's `PuzzleView`, or 404 if there is none. The UI uses it to resume after a reload. `POST /api/puzzles` always creates a new puzzle; an unanswered one is a skip, visible as a puzzle with no attempts. Register this route before `/{id}`.
  - `GET /api/puzzles/{id}/attempts` → list of `AttemptSummary`, oldest first.
  - `GET /api/history?limit=50&offset=0&first_only=false` → `{"items": [AttemptSummary...], "total": n}`, newest first, `limit` 1–200.
  - `GET /api/settings` and `PATCH /api/settings` (partial update) → `SettingsView`.
  - Static frontend serving.
- **`AttemptIn`:**
  - `option: int | None` and `custom_to: int | None`; exactly one is required.
  - `equity_guess: float` in [0, 1].
  - `range_read_guess: float | None` in [0, 1]; it is ignored on the river (the grader already does this).
  - `intent: "value" | "bluff" | "semi_bluff" | None`.
  - Errors:
    - out-of-range `option`, or both / neither given → 422;
    - `custom_to` pre-flop, or a custom size that `custom_action` rejects → 422 with the `ValueError` message;
    - `custom_to` is first matched against the listed options (same `Action` → graded as that option, as `grade._resolve` does).
  - Otherwise, when `load_profile(spot.profile).version != spot.profile_version` **or** `load_thresholds().version != spot.categories_version` → 409 `"Villain model changed since this puzzle was generated; custom sizes are disabled for this puzzle"`. The grader's custom path uses the live profile and the live category thresholds.

  Listed options always grade from the stored `OptionEV`s, so stale puzzles still accept them.
- **`PuzzleView`** (`views.puzzle_view(puzzle_id, p, *, custom_sizes_allowed)`), every field visible at the table:
  - `id`, `street`, `hero_seat`, `hero_position` (`BTN` / `BB`), `villain_position`, `hero_cards` (e.g. `["Ah","Kd"]`), `board` (only the decision board).
  - `stacks`, `street_bets`, `pot` (= `total_pot`), `to_call` (= `amount_to_call`), `pot_odds` (= `solution.pot_odds` when a call option exists, otherwise null, so it matches the results view; pot odds are table-visible, not hidden).
  - `history`: one entry per action with `street`, `actor` (`"hero"` / `"villain"`), `kind`, `to`, `text`. The text comes from `villain.narrowing.describe(action, state_before)`. The states before each action are rebuilt by replaying `spot.state.history` from `new_hand(spot.state.button)`, dealing board cards from `spot.runout` (3 cards for the flop, then 1) whenever `needs_board`: before each action, and once more after the last action until the board has the decision board's length. A test asserts the replay ends equal to `spot.state` field by field.
  - `villain_profile`: `{"name", "label", "description"}`, always sent. The settings toggle only hides it in the UI.
  - `options`: `[{"index", "label", "kind", "to"}]`.
  - `custom`: `{"allowed": bool, "min_to": int | null, "max_to": int | null}`. Allowed only post-flop, when a bet or raise is legal and both the profile version and the categories version are current.
  - `range_read_asked` (False on the river), `attempts_so_far` (int).
- **`AttemptResult`** (`views.attempt_result(...)`), built from the stored attempt row plus the decoded puzzle:
  - `attempt`: `{"id", "puzzle_id", "attempt_no", "is_first", "created_at"}`.
  - `answer`: the stored inputs and the chosen label.
  - `grade`: `verdict`, `ev_loss_chips`, `ev_loss_bb`, `chosen_label`, `best_label`, `equity` (true), `equity_std_error`, `equity_exact`, `equity_guess`, `equity_error`, `equity_score`, `ahead_now`, `range_read_guess`, `range_read_error`, `range_read_score`, `intent`, `intent_truth`, `intent_flag`, `bluff_check` (`{"required", "actual"}` or null), `pot_odds`.
  - `options`: every stored option, plus the chosen one if it was a custom size. Each has `label`, `kind`, `to`, `ev_chips`, `ev_bb`, `fold_freq`, `equity_vs_continue`, `equity_vs_continue_se`, `ahead_vs_continue`, `required_fold_equity`, `put`, `branches` (`label`, `share`, `equity`, `value_chips`, `value_bb`), `simplifications` (codes), `continue_grid` (13×13 or null), `is_best`, `is_chosen`.
  - `simplifications`: `[{"code", "text"}]` from `SIMPLIFICATIONS`, covering the solution's codes plus the chosen option's.
  - `categories`: the breakdown rows with `category` (code), `name` (display text), `share`, `ahead`, `equity`, `win`, `tie`, `lose`; null pre-flop.
  - `range_steps`: `[{"label", "street", "grid", "combos"}]`. `grid` is 13×13 (rows and columns in `class_grid` order). `combos` is `[[combo_str, weight], ...]` for weight > 0, with combos named by `card_str` (e.g. `"AsKd"`).
  - `reveal`: `villain_cards`, `runout` (all 5 cards), `profile` (`name` / `label` / `description` / `version`), and `showdown`: `{"hero_hand", "villain_hand", "winner": "hero" | "villain" | "split"}`. The showdown is computed from the frozen hole cards and the full 5-card runout (always dealt at generation) with `evaluate`, plus `HAND_CLASS_NAMES` display text. It is always shown, including when Hero's answer was a fold: spec §8.6 shows the run-out and winner, and §8.7 says the grade is on the range.
  - `judged_on_range_note`: fixed text, "Graded against Villain's whole range, not this run-out."
- **Range grid display** (M1 open item): the grid averages **over unblocked combos only**, i.e. the combos that are live in the step's range array after `visible_range` (blocked = Hero's cards or the decision board). A cell whose combos are all blocked is `null`. Implement it in `views.range_grid(r, dead)`, not by changing `engine.class_grid`.
- **Display text** (`api/text.py`):
  - `CATEGORY_NAMES`: `NUTS` "Nuts / near-nuts", `STRONG` "Strong value", `STRONG_DRAW` "Strong draw", `MEDIUM` "Medium made hand", `WEAK_DRAW` "Weak draw", `WEAK` "Weak made hand", `AIR` "Air".
  - `simplification_text(code)`, which delegates to `SIMPLIFICATIONS`.
  - `CATEGORY_NAMES` is keyed by the lower-case codes that `CategoryRow.category` actually holds (`HandCategory.X.name.lower()`, e.g. `"strong_draw"`; see `solve.py`).
  - `HAND_CLASS_NAMES`, keyed by `HandClass` member: e.g. `TWO_PAIR` "Two pair".
  - `JUDGED_ON_RANGE`.
  - A test asserts that every `HandCategory` member, every `HandClass` member and every `SIMPLIFICATIONS` key has text.
- **History** `AttemptSummary`: `attempt_id`, `puzzle_id`, `attempt_no`, `is_first`, `created_at`, `street`, `profile`, `chosen_label`, `verdict`, `ev_loss_bb`, `equity_error`, `range_read_error`. Read from columns only, never by decoding blobs.
- **Settings:** `SettingsView` = `show_pot_odds`, `show_profile`, `profile` (null or a `PROFILE_NAMES` member), `daily_goal` (1–500), plus read-only `llm_provider` (from env), `llm_status` (`"off"` for `none`) and `profiles` (`[{name, label, description}]` for every `PROFILE_NAMES` member, so M5 doesn't hard-code them). `PATCH` validates every field and updates `updated_at`. The request model uses `extra="forbid"`, so read-only or unknown fields → 422. Only fields in `model_fields_set` are applied: `profile: null` resets to random, and an omitted field is left unchanged.
- **Static frontend:** if `PPT_FRONTEND_DIST/index.html` exists, the app serves the built frontend.
  - `/assets/*` and other files are served with `StaticFiles`.
  - Any other non-`/api` GET falls back to `index.html` (SPA routing). Files are only ever served through `StaticFiles` or a path check that the resolved path is inside the dist directory, so no traversal outside it is possible.
  - Unknown `/api/*` paths still return a JSON 404.

  If `index.html` doesn't exist, `GET /` returns a small JSON `{"detail": "frontend not built"}` with 404. The frontend arrives in M5; tests use a temp dist directory.
- **`serve` script:** `[project.scripts] serve = "poker_trainer.api.app:main"` runs `uvicorn.run(create_app(), host, port)` from `AppSettings`.
- **Postgres note:** the default user is inserted with explicit `id = 1`, which doesn't advance a Postgres id sequence. That's harmless while there is one user; fix it when accounts arrive.
- **Not in M4** (recorded for later): the daily-goal and streak day boundary (M7 decides the timezone; M4 stores UTC timestamps). The profile toggle is UI-only by design: `villain_profile` is always sent, and the setting hides it in the UI.
- **Errors:** every error body is FastAPI's standard `{"detail": ...}`. A missing puzzle or attempt (or another user's) → 404.

## Review Focus

1. **Leaks before submit.** Serialise `PuzzleView` for many puzzles: none of Villain's two card strings as quoted JSON strings (e.g. `'"Ah"'`), no undealt runout card, no key named `range` / `steps` / `solution` / `seed` / `villain_hole` / `runout`, and none of the solution's option EVs. Tests in Task 2.
2. **First-attempt semantics.** Only `attempt_no == 1` has `is_first`. Replays get 2, 3 and so on. The unique constraint holds. Tests in Tasks 2 and 3.
3. **Stale profiles.** With a monkeypatched profile version, a custom size → 409 and `custom.allowed` is False, while listed options still grade. Test in Task 2.
4. **Stored grade is authoritative.** Change the stored attempt's `verdict` column directly, then check that `GET /api/attempts/{id}` returns the changed value, proving no regrade on read. Test in Task 2.
5. **Exact blob round-trip** on real generated puzzles for every street, and the format check. Test in Task 1.
6. **Migrations equal models** (autogenerate shows no diff); `migrate` is idempotent; `ensure_default_user` is idempotent. Tests in Task 1.
7. **User isolation:** rows of user 2, inserted directly, are 404 / invisible to the default user in every endpoint. Test in Task 3.

---

### Task 1: Settings, database models, Alembic, default local user — Opus

**Files:**
- Create: `backend/src/poker_trainer/settings.py`, `backend/src/poker_trainer/db/__init__.py`, `db/models.py`, `db/session.py`, `db/blob.py`, `db/migrations/env.py`, `db/migrations/script.py.mako`, `db/migrations/versions/0001_initial.py`, `backend/alembic.ini`, `backend/.env.example`.
- Modify: `backend/pyproject.toml` (deps `sqlalchemy>=2.0,<3`, `alembic>=1.13`, `pydantic-settings>=2.4`; make sure the migrations, including `script.py.mako`, ship in the wheel) and `uv.lock`.
- Tests: `backend/tests/db/test_app_settings.py`, `test_models.py`, `test_blob.py`, `test_migrations.py`.

**Interfaces:**
- `poker_trainer.settings`: `AppSettings` and `get_settings()`.
- `poker_trainer.db.models`: `Base`, `User`, `UserSettings`, `PuzzleRow`, `AttemptRow`, and `DEFAULT_USER_ID = 1`.
- `poker_trainer.db.session`: `make_engine(url)`, `make_sessionmaker(engine)`, `migrate(url)`, `ensure_default_user(session) -> User`.
- `poker_trainer.db.blob`: `encode_puzzle(p) -> bytes`, `decode_puzzle(b) -> Puzzle`.
- `poker_trainer.db` re-exports the above.

- [ ] **Step 1: Failing tests**
  - `test_settings_defaults_and_env` (with `_env_file=None`): the defaults match the table above; `monkeypatch.setenv("PPT_DATABASE_URL", ...)` overrides the URL.
  - `test_blob_round_trip_every_street`: generate one puzzle per street (seeds fixed, module-scoped fixture). `decode_puzzle(encode_puzzle(p))` gives `puzzle_to_dict` equal to the original's, `json.dumps` byte for byte. The compressed size is < 25% of the JSON size.
  - `test_blob_rejects_bad_format`: a blob with `format: 2` → `ValueError("unsupported puzzle format...")`.
  - `test_blob_utf8`: a branch label with an em dash survives the round-trip.
  - `test_migrate_creates_tables` (tmp-path SQLite file): the four tables exist, and `alembic_version` is at head.
  - `test_migrate_idempotent`: `migrate` twice gives no error.
  - `test_models_match_migrations`: `alembic.autogenerate.compare_metadata(MigrationContext.configure(conn), Base.metadata)` returns `[]`.
  - `test_default_user_idempotent`: two calls give one user with id 1 and one settings row with the defaults.
  - `test_attempt_unique_constraint`: two attempts with the same `(puzzle_id, attempt_no)` → `IntegrityError`.
  - `test_foreign_keys_enforced` (SQLite pragma): an attempt with an unknown `puzzle_id` → `IntegrityError`.
  - `test_migrate_uses_given_url`: with `PPT_DATABASE_URL` pointing at a second tmp file, `migrate(url_a)` creates tables only in `url_a`.
  - `test_utc_round_trip`: a stored aware timestamp reads back aware, in UTC.
- [ ] **Steps 2–4:** fail → implement → pass. Run `uv run pytest -m "not slow" -q`, `uv run ruff check .` and `uv run ruff format --check .`. Check the CLI path: `uv run alembic -c alembic.ini upgrade head` with `PPT_DATABASE_URL=sqlite:///<tmp>/cli.db` creates the tables there. Run the same with `alembic check` to confirm no pending autogenerate diff.
- [ ] **Step 5:** Task 1 runs in parallel with Task 2A in the same tree. The controller stages only Task 1's paths (never `git add -A`) and commits `feat(db): SQLAlchemy models (users, puzzles, attempts) + Alembic, default local user, env config`.

### Task 2A: Pure API views and display text — Sonnet (in parallel with Task 1: no DB, no FastAPI, no new dependencies)

**Files:**
- Create: `backend/src/poker_trainer/api/__init__.py` (empty for now), `api/text.py`, `api/views.py`.
- Test: `backend/tests/api/test_views.py`, `test_text.py`.

**Interfaces** (`poker_trainer.api.views`):
- `action_log(spot) -> list[dict]`: history entries with `street`, `actor`, `kind`, `to` and `text`.
- `range_grid(r, dead) -> list[list[float | None]]` and `range_combos(r) -> list[list]`.
- `showdown(spot) -> dict`.
- `option_view(o: OptionEV, *, best: bool, chosen: bool, dead) -> dict`.
- `puzzle_view(puzzle_id: int, p: Puzzle, *, custom_sizes_allowed: bool, attempts_so_far: int) -> dict`.
- `attempt_result(*, attempt: dict, puzzle: Puzzle, chosen: OptionEV) -> dict`. `attempt` holds the stored row fields as a plain dict (id, puzzle_id, attempt_no, is_first, created_at ISO string, inputs, grade fields, best_label), so views stay independent of the ORM.
- `option_ev_to_dict(o)` and `option_ev_from_dict(d)`, for the attempt's `chosen` JSON. These call the existing private `model._option_ev_to_dict` / `_option_ev_from_dict`. Re-export them publicly from `puzzle/model.py` as `option_ev_to_dict` / `option_ev_from_dict`; this one-line alias is the only `puzzle/**` change and doesn't change behaviour.
- `custom_allowed(p: Puzzle) -> bool` and `custom_bounds(p) -> tuple[int | None, int | None]`.

Every value returned is a plain JSON type (no numpy scalars, no NaN).

- [ ] **Step 1: Failing tests** (module-scoped fixture: one generated puzzle per street, fixed seeds; plus a river fixture with a known outcome built like M3's `river_spot`):
  - `test_puzzle_view_hides_villain`: for each street, `json.dumps(puzzle_view(...))` contains neither Villain card as a quoted JSON string, no undealt runout card as a quoted JSON string, and none of the keys `range`, `steps`, `solution`, `seed`, `villain_hole`, `runout`, `combo_equity`.
  - `test_action_log_replays_to_state`: the rebuilt final state equals `spot.state`. Actors match seats. The texts match `describe`.
  - `test_puzzle_view_numbers`: `pot` and `to_call` equal `total_pot` and `amount_to_call` of `spot.state`. `pot_odds` equals `solution.pot_odds` when a call option exists, otherwise None (BTN first in pre-flop → None). The options' labels, kinds and `to`s equal the stored ones. `range_read_asked` is False on the river.
  - `test_range_grid_unblocked_mean`: with Hero `AhAs`, the `AA` cell is the mean over the 1 unblocked AA combo only (hand-built range); an all-blocked cell is None.
  - `test_attempt_result_shape`: `is_best` on exactly one option, `is_chosen` on exactly one, and a custom chosen option is appended. `simplifications` carry text. Categories are None pre-flop. `json.dumps(..., allow_nan=False)` succeeds.
  - `test_showdown_known_river`: a fixture with known hands gives the expected winner and class names; a split is reported as `"split"`.
  - `test_text_covers_all_codes`.
- [ ] **Steps 2–4:** fail → implement → pass; ruff clean.
- [ ] No separate commit: this ships in Task 2B's commit (roadmap item 2).

### Task 2B: FastAPI app — new puzzle, submit attempt, get result — Opus (after Tasks 1 and 2A)

**Files:**
- Create: `backend/src/poker_trainer/api/schemas.py` (Pydantic request/response models), `api/service.py`, `api/app.py`.
- Modify: `backend/pyproject.toml` (deps `fastapi>=0.115`, `uvicorn>=0.30`; dev `httpx`; script `serve`) and `uv.lock`.
- Tests: `backend/tests/api/conftest.py` (an app built over a tmp-path SQLite file with an injected cached `puzzle_factory`, plus a `TestClient` fixture) and `backend/tests/api/test_puzzles.py`.

**Interfaces:**
- `service.new_puzzle(db, user_id, factory, *, street, profile) -> tuple[int, Puzzle]`.
- `service.load_puzzle(db, user_id, puzzle_id) -> tuple[PuzzleRow, Puzzle]` (raises `NotFound`).
- `service.submit_attempt(db, user_id, puzzle_id, inp: AttemptIn) -> AttemptRow`.
- `service.load_attempt(db, user_id, attempt_id) -> AttemptRow`.
- `app.create_app(settings=None, *, puzzle_factory=None) -> FastAPI`, `app.main()`.
- `current_user` and `get_db` are FastAPI dependencies.

- [ ] **Step 1: Failing tests**
  - `test_health`.
  - `test_new_puzzle_201_hidden`: the leak checks from Task 2A on the HTTP response. A row exists in `puzzles` with `user_id == 1`.
  - `test_new_puzzle_uses_settings_profile`: with the settings profile set directly in the DB to `"sticky"`, a POST without a profile passes `"sticky"` to the factory.
  - `test_new_puzzle_bad_street_422`.
  - `test_generation_failure_retries_then_503`: a factory that raises `RuntimeError` 3 times → 503; one that raises twice then succeeds → 201.
  - `test_submit_listed_option`: 201. The verdict and EV loss equal `grade(p, Answer(...))` called directly. `is_first` True, `attempt_no` 1. The reveal contains Villain's cards.
  - `test_submit_second_attempt_not_first`.
  - `test_submit_validation`: both or neither of `option` / `custom_to`, an out-of-range option index, `equity_guess` 1.5 or NaN → 422.
  - `test_custom_size_postflop`: graded through `evaluate_action`, and the chosen option is appended to `options`.
  - `test_custom_size_preflop_422`.
  - `test_custom_size_stale_profile_409`: monkeypatch `load_profile` to return a different version. `custom.allowed` is False in the view, and a listed option still returns 201. A `custom_to` equal to a listed option's `to` also returns 201.
  - `test_custom_size_stale_categories_409`: the same with `load_thresholds` returning a different version.
  - `test_attempt_kinds_stored`: `action_kind` and `best_kind` are stored, and `config_version` equals the live `load_config().version`.
  - `test_created_at_utc`: `created_at` ends in `+00:00` on both POST and GET.
  - `test_get_attempt_returns_stored_grade`: Review Focus 4.
  - `test_unknown_ids_404`.
  - `test_responses_utf8`: an em dash appears in some branch label, and the content type is JSON.
- [ ] **Steps 2–4:** fail → implement → pass. Run the full fast suite and ruff. Start `uv run serve` briefly and `curl` (or `httpx`) `/api/health` and `POST /api/puzzles` against it.
- [ ] **Step 5:** Commit `feat(api): FastAPI app — new puzzle, submit attempt, get result (Villain hidden until submitted)`.

### Task 3: Settings, history, replay, static frontend — Sonnet (after Task 2B)

**Files:**
- Modify: `api/app.py`, `api/service.py`, `api/schemas.py`.
- Tests: `backend/tests/api/test_settings_api.py`, `test_history.py`, `test_replay.py`, `test_static.py`, `test_isolation.py`.

- [ ] **Step 1: Failing tests**
  - `test_settings_get_defaults`: the defaults, with `llm_provider` `"none"`, `llm_status` `"off"` and 4 `profiles`.
  - `test_settings_patch_partial`: only the given fields change, and `updated_at` moves.
  - `test_settings_validation`: an unknown profile, `daily_goal` 0 or 501, or a read-only field → 422. `profile: null` resets to random.
  - `test_history_newest_first_and_paging`: `limit` and `offset` work, `total` is right, and `first_only=true` filters. Bounds on `limit` → 422.
  - `test_history_never_decodes_blobs`: corrupt a puzzle blob in the DB, and history still returns.
  - `test_replay_get_puzzle_hidden`: `GET /api/puzzles/{id}` after an attempt still hides Villain, and `attempts_so_far` counts. Submitting again gives `attempt_no` 2.
  - `test_puzzle_attempts_list`: oldest first.
  - `test_static_serves_index_and_assets` (tmp dist with `index.html` and `assets/app.js`): `/` and `/progress` return index.html, `/assets/app.js` returns the file, and `/api/nope` is a JSON 404.
  - `test_static_no_traversal`: `/..%2f..%2fpyproject.toml` and `/assets/../../secret.txt` (a file next to the dist dir) never return that file's contents.
  - `test_current_puzzle`: 404 when there is none. After POST it returns that puzzle; after a submit it returns 404 again; with two unanswered puzzles it returns the newer one.
  - `test_static_absent`: `GET /` → 404 `"frontend not built"`, and the API still works.
  - `test_user_isolation`: Review Focus 7, across `GET` puzzle, attempts, history and submit.
- [ ] **Steps 2–4:** fail → implement → pass; full fast suite plus ruff.
- [ ] **Step 5:** Commit `feat(api): settings, history, replay endpoints; serve built frontend as static`.

## How M3's open items are handled

| M3 open item | Where |
|---|---|
| Size: compress puzzle JSON | Task 1, `db/blob.py` (zlib, exact) |
| Persist the grade with each attempt, with config version | Task 1 columns, Task 2B `submit_attempt` |
| Custom sizes need the live profile | Task 2A `custom_allowed`, Task 2B 409 |
| Canonical actions | `AttemptIn.option` / `custom_to` → stored `Option.action` or `custom_action` |
| Display text for categories and simplification codes | Task 2A `api/text.py` |
| UTF-8 end to end | Task 1 blob, Task 2B response test |
| Format check, never regenerate | Task 1 `decode_puzzle`, Global Constraints |
| Showdown winner | Task 2A `views.showdown` from frozen cards |
| (M1) grid over unblocked combos | Task 2A `views.range_grid` |

## Deviations from this plan (recorded after the M4 final review)

- **Service helpers:**
  - `submit_attempt` returns `(AttemptRow, Puzzle)`, so the blob is decoded once per submit.
  - Added `attempt_result_for`, `count_attempts`, `settings_profile`, `current_puzzle`, `puzzle_attempts`, `history`, `settings_view` and `patch_settings`.
  - `views.villain_model_current` is the single stale-model check, used by both the view's `custom.allowed` and the 409.
  - `db.alembic_config(url)` is exported.
- **Extra error cases:**
  - When the single retry also collides, `ConcurrentSubmit` → 409 `"concurrent submit, try again"`.
  - Ids ≤ 0 or above 2^63−1 → 404 (avoids a SQLite overflow).
  - Non-finite floats in a 422 body are echoed as strings.
  - Unexpected exceptions → JSON 500 `{"detail": "internal server error"}`.
- **Stricter inputs:** `AttemptIn.option` / `custom_to` and `SettingsPatch` booleans and `daily_goal` are strict (no `"1"`, `true` or `1.0` coercion).
- **Responses** are built as plain dicts in `api/views.py` and validated by Pydantic response models in `api/schemas.py` (`extra="forbid"`, so a view key without a model field fails the tests). See the follow-up below.
- **Static files** are served by one `GET`/`HEAD` catch-all route with a resolve plus `is_relative_to` check, not by `StaticFiles`. `.js`, `.mjs` and `.css` MIME types are forced, because the Windows registry can map `.js` to `text/plain`.
- **Migrations** run on their own `create_engine(NullPool)`, with SQLite foreign keys off, so later batch table rebuilds work. The app engine keeps foreign keys on. This is tested.
- **`answer.action.street`** is stored as an int and returned as the lower-case street name, like every other street in the API.
- **`llm_status`** has an `"on"` branch that can't be reached while `llm_provider` is `Literal["none"]` (M8).

## Follow-up after the M4 PR review

Fixed on this branch:
- **`GET /api/puzzles/current`** returns the newest puzzle only if it is unanswered. Previously it returned the newest *unanswered* puzzle, so a skipped puzzle came back once a newer one was answered.
- **Migration `0002_chosen_label`**: a `chosen_label` column, backfilled from `chosen`. History and per-puzzle summaries read it, never the `chosen` JSON (about 20 KB per bet option, because of `continue_range`).
- **History summaries** add `action_kind`, `best_label` and `best_kind`. `GET /api/history` takes optional `street`, `verdict`, `action_kind` and `profile` filters (AND-ed, `total` counts the filtered rows; `profile` accepts any stored name, so removed profiles stay filterable).
- **Response models** for every route (`PuzzleView`, `AttemptResult`, `AttemptSummary`, `HistoryPage`, `SettingsView`), so `/openapi.json` carries every response shape for M5's TypeScript types. `tests/api/test_contract.py` pins them.
- **Stale settings profile:** a stored profile no longer in `PROFILE_NAMES` reads as null (random) in settings and generation, instead of a 500.
- **`POST /api/puzzles` `profile: "random"`** is random whatever the settings profile is (null still means "use the settings").
- **Stored inputs:** a river `range_read_guess` and an `intent` on a fold, check or call are stored (and echoed) as null, because the grader ignores them.
- **Strict probabilities:** `equity_guess` and `range_read_guess` reject `"0.5"` and `true`, like the other strict inputs (ints such as 0 and 1 are still accepted).
- **`HEAD /api/health`** returns 200 (it fell through to the SPA catch-all's JSON 404).
- **`GZipMiddleware`** (minimum 1 KB): an attempt result of about 55–75 KB goes over the wire as about 9 KB.

## Open items for M5, M6 and M7 (from the M4 final review)

- **M5, contract:** done (see the follow-up above). Generate the TypeScript types from `/openapi.json`.
- **M5, bb vs chips:**
  - The puzzle view gives chips only: `stacks`, `pot`, `to_call`, `street_bets` and option `to`.
  - History texts use chips ("opens to 5").
  - Results give `ev_*_bb` next to chips; history items give only `ev_loss_bb`.
  - Divide by 2 in the UI, or add bb fields to the API. Be consistent.
- **M5, pot odds:** pre-flop BTN first in has `to_call` 1 but `pot_odds` null, because there is no call option. Never compute pot odds in the UI from `to_call`.
- **M5, working directory:** the `PPT_DATABASE_URL` and `PPT_FRONTEND_DIST` defaults, and `.env`, are relative to the working directory. Run `serve` from `backend/`, or resolve the defaults against the backend directory. Document this in the M9 README.
- **M5, routing:** the SPA catch-all makes `GET` on a POST-only API route (e.g. `GET /api/puzzles`) return 404, not 405. `/docs`, `/redoc` and `/openapi.json` stay reachable and shadow SPA routes with those names.
- **M5, river range read:** done; the server stores None. The UI still shouldn't ask when `range_read_asked` is false.
- **M6, options:** results `options` carry no `index`, and a custom choice is appended at the end. Match on `is_chosen` / `is_best`, not on position.
- **M6, run-out:** `reveal.runout` holds all 5 cards, including the board already shown. Slice by board length to animate the run-out.
- **M6, profile text:** `villain_profile` and `reveal.profile` use the *live* profile's label and description. If a profile is renamed or removed, `load_profile` raises and the result is a 500. Store the display text on the puzzle, or handle the missing profile.
- **M7, history filters:** done (street, verdict, action kind, profile; summaries carry `action_kind`, `best_kind`, `best_label`). Aggregate stats (averages by street, profile and kind) are still M7's, ideally in SQL.
- **M7, day boundary:** decide the daily-goal and streak day boundary (timezone); timestamps are stored in UTC. (The stale settings profile is fixed: it falls back to random.)
- **Dependencies:** Starlette 1.10 warns that `httpx` with `TestClient` is deprecated in favour of `httpx2`. Switch before an upgrade breaks the tests.
- **Unchanged since M3:** Villain tuning (TAG calls river jams too wide; BTN over-folds to 3-bets) is still for the `villain/*` branch in `handoff.md`.
