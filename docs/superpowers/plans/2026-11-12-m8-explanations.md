# M8 Explanations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The plain-English explanation of main spec §8 item 8 and the optional LLM layer of §9: every result gets a short narrative of the hand and an explanation of the verdict, written by code from the numbers the grader computed. With `PPT_LLM_PROVIDER=ollama`, a local model may rewrite that text in plainer words, but its output is thrown away (and the template shown) if it contains any number that is not in its input. The LLM provider's status is visible in the app.

**Architecture:**
- **Backend:** a new package `poker_trainer.explain`:
  - `facts.py`: `Facts`, every number the explanation may use, already formatted as text by code, built from the stored result dict and the frozen puzzle;
  - `template.py`: the template explanation (headline, hand narrative, verdict, Villain);
  - `guardrail.py`: number extraction and the "no new numbers" check;
  - `ollama.py`: the Ollama client (stdlib `urllib`, no new dependency) and the status probe;
  - `service.py`: provider selection, the LLM call with fallback, an in-memory cache.
  - The template explanation is part of every `AttemptResult` (new field `explanation`). The LLM version comes from a new endpoint `GET /api/attempts/{id}/explanation`, so a slow model never delays a submit.
- **Frontend:** a new **Why** tab, first in `DecisionDetails`, shows the explanation. When the provider is on, it shows the template at once and swaps in the model's text when it arrives. The tab's footer shows the provider status (from `GET /api/settings`).
- **Spec:** `docs/superpowers/specs/2026-11-10-poker-puzzle-trainer-design.md` §2 (anti-goal: no LLM numbers), §8 item 8, §9, §11 (LLM provider status). Roadmap M8. Hand-over: "Open items for M8 and later" at the end of `2026-11-12-m7-progress.md`, M6 "Profile notes deferred", M4 "`llm_status` has an `"on"` branch that can't be reached".

## Global Constraints

- **No number ever comes from an LLM.** Every number in the template is computed by the grader (or is a plain count or label such as a card rank, a position or a street) and formatted by code. The LLM gets only the template text and the facts; its output passes the guardrail or is discarded.
- **The template states only stored or frozen values.** It never regrades. A number in the explanation equals the number the Options, Maths or summary views show for the same quantity, in the same format (see "Number formats").
- **Grade against the range:** the explanation talks about Villain's range and the EV of the options, never about the sampled run-out or Villain's actual cards (those are in the Hand tab). It must not say "you won" or "you lost".
- **The LLM is optional everywhere.** With `PPT_LLM_PROVIDER=none` (the default) nothing calls a network, and every test runs without Ollama. A missing, slow or broken Ollama gives the template, never an error page.
- **Display in bb**, as everywhere (chips / 2).
- **Cross-platform:** no new dependency, backend or frontend. Tests that exercise the Ollama client run a local fake server (`http.server` in a thread on `127.0.0.1`, port 0), which works on Windows and macOS.
- **Accessibility:** the Why tab is a normal WAI-ARIA tab like the others. The "rewriting" status uses `role="status"` (polite). Headings: the tab's sections are `h3` (DecisionDetails has a hidden `h2`).
- **Commit hygiene:** as in CLAUDE.md (author spandan3, no trailers, new commits for fixes once pushed).

## Decisions made in this plan

### Number formats (backend, `explain/format.py`; same output as the frontend helpers)

- `bb(chips: int) -> str`: chips as bb like `formatBb`: `5` → `"2.5 bb"`, `200` → `"100 bb"`.
- `ev_bb(x: float) -> str`: like `formatEvBb`: two decimals, trailing zeros dropped, U+2212 for negatives, `"0 bb"` for |x| < 0.005.
- `pct(x: float, digits: int = 0) -> str`: like `formatPct` (`toFixed`). The UI formats some quantities differently in different views, so each quantity follows one named view:
  | Quantity | Digits | Matches |
  |---|---|---|
  | equity vs the whole range, `ahead_now` | 1 | the summary (`guessLines`) |
  | pot odds | 1 | Maths (`maths.ts`) |
  | fold frequency of an option | 0 | Options table |
  | required fold equity (bluff check) | 1 | Maths |
  | equity vs the continuing range | 1 | Options table |
  | category share | 1 | `CategoryTable` |
  | Hero's equity against a category | 0 | `CategoryTable` |
  | EV, EV lost | `ev_bb` | Options / summary (`formatEvBb`) | JS `toFixed` rounds the float's exact binary value and breaks exact ties away from zero, while Python's `format` breaks them to even. So: compute the same float JS formats (`y = x * 100` for percentages, `y = bb` for EVs), then `decimal.Decimal(y).quantize(Decimal(10) ** -digits, ROUND_HALF_UP)` (the exact value, **not** `Decimal(repr(y))`: `0.15.toFixed(1)` is `"0.1"`). Test against a table of values the frontend helpers give (the test lists the JS outputs as literals, produced once with `node -e`).
- Cards: rank + suit symbol (`"K♠"`, `"T♦"`). Tens stay `"T"`, as in the API's card strings, so a card never puts a "10" into the text.
- Labels: option labels through the same rule as the frontend's `optionLabel` ("bet 100%" → "Bet pot", capitalised); custom sizes in bb ("Bet 7 bb", "Raise to 20 bb") as `chosenLabel` does.

### `Explanation` (API, `api/schemas.py`)

```python
ExplanationSource = Literal["template", "llm"]
FallbackReason = Literal["off", "unavailable", "timeout", "error", "invalid", "guardrail"]

class ExplanationSection(_Out):
    id: Literal["hand", "verdict", "villain"]
    title: str
    paragraphs: list[str]

class Explanation(_Out):
    source: ExplanationSource
    headline: str                       # one sentence
    sections: list[ExplanationSection]  # always in the order hand, verdict, villain
    model: str | None                   # the model name when source == "llm"
    fallback: FallbackReason | None     # why the template is shown when the LLM was asked
```

- `AttemptResult.explanation: Explanation` — always the template (`source="template"`, `model=None`, `fallback=None`).
- `GET /api/attempts/{attempt_id}/explanation` → `Explanation`. Provider `none`: the template with `fallback="off"`. Provider `ollama`: the model's version, or the template with the reason it was not used. Same 404 rules as `GET /api/attempts/{id}`. Never 5xx because of the model.

### Template content (`explain/template.py`)

All three sections are built from `Facts`. Exact wording is the implementer's, inside these rules; golden tests pin it for the fixture spots.

1. **Headline** (one sentence), with the same three cases and the same `EV_EPSILON = 0.005` as the frontend's `verdictLine` (`lib/result.ts`): loss < 0.005 → the user found the top play ("Bet 33% was the top play, and you found it."); verdict best or fine with a loss → "within X of the top play (Y)" in words ("Call was close: within 0.11 bb of the top play, Bet 75%."); otherwise the top play and the bb lost ("Fold was the top play; calling loses 2.25 bb against Villain's range.").
2. **The hand** (`id="hand"`, title "The hand"): a narrative of the action log up to the decision: positions, the profile label, each street's board, each action with amounts in bb ("You opened to 2.5 bb on the button and Villain, a TAG, called from the big blind. The flop came K♠ 7♦ 2♣ …"), ending with the decision ("You faced 4 bb more to call, with 16 bb in the pot." / "It was your turn to act with 14 bb in the pot."). Built from `views.action_log(spot)` entries (`actor`, `kind`, `to`, `amount`, `all_in`, `street`) and the board at each street (`spot.state.board[:3]`, `[:4]`, `[:5]`); **never from the entries' `text`** (it is in chips); never from the run-out after the decision. Sources: pot = `total_pot(spot.state)` (includes Villain's bet, as `PuzzleView.pot`), to call = `amount_to_call(spot.state)`, positions from `position_name` ("BTN", "BB").
3. **The verdict** (`id="verdict"`, title "Why"): 2–4 short paragraphs:
   - what the user chose and the verdict: chosen label, the top option, EV lost in bb (when > 0), the verdict word;
   - the key number for the spot type:
     - **every** template states equity vs the whole range (1 digit, as the summary) and, when `ev_loss_bb >= 0.005`, the EV lost (as the summary), so the Why text always contains the summary's strings;
     - facing a bet (a call option exists): equity against the pot odds, using the Maths tab's formula `call / (pot + call)` with pot = `total_pot` (Villain's bet included): "calling 4 bb into a pot of 16 bb needs 4 / (16 + 4) = 20.0%". The formula is printed only when it reproduces `pot_odds` within 0.001 (as Maths' `matchesFraction`), else the number alone. The same rule for the bluff check's `b / (pot + b)`;
     - a bet or raise option is best or chosen: its fold frequency, Hero's equity against the continuing range, and (when the grade has a bluff check) the fold equity a bluff of that size needs against what Villain folds;
     - check best: why betting does worse (the best bet's EV against the check's EV, both from `options`);
   - the range: the share of the range Hero is ahead of now (`ahead_now`, when not null), and the two largest categories by share with Hero's equity against each (from `categories`, when not null);
   - the simplification codes are **not** repeated (they are in the Maths tab).
4. **Villain** (`id="villain"`, title "Villain"): the profile label and description, then how the range narrowed: the range-step labels in order, without the first `Start` step, converted to bb with a Python port of the frontend's `bbLabel` (`lib/format.ts`; the labels come from `villain/narrowing.describe` and are in chips: `"Pre-flop: opens to 5"` → `"Pre-flop: opens to 2.5 bb"`, `"Turn: bets 8 (80% pot)"` → `"Turn: bets 4 bb (80% pot)"`), as the Range tab shows them; the converted labels are facts. Ending "The range in the Range tab is the range this puzzle was graded on." This covers the M6/M7 "per-profile behaviour notes" item with existing data only; richer per-profile notes need Villain-branch data (left open).

The intent flag and the "judged on range" note stay where they are (ResultSummary) and are not repeated.

### `Facts` (`explain/facts.py`)

`build_facts(result: dict, puzzle: Puzzle, log: list[dict]) -> Facts`, where `result` is the dict `views.attempt_result` builds (before `explanation` is added) and `log` is `views.action_log(puzzle.spot)` (passed in, so the explain package never imports `views`). `Facts` is a frozen dataclass of strings (and string lists) plus a few flags (`facing_bet`, `hero_folded`, `best_is_chosen`, …). It also has `as_lines() -> list[str]`: `"Name: value"` lines, the facts block given to the LLM. Every number the template prints must appear in `as_lines()` (a test asserts it for every fixture spot: the template itself passes the guardrail against its own facts).

`views.attempt_result` calls `explain.template.explain(result_dict, puzzle, action_log(spot))` last and adds `explanation`. It stays pure (no DB, no network).

### Guardrail (`explain/guardrail.py`)

- `numbers(text) -> set[str]`: every number token: digit runs with an optional decimal part (`\d+(?:[.,]\d+)?`, a comma between digits read as a decimal point only when followed by 1–2 digits; thousands separators are not expected since amounts are in bb), normalised (`Decimal`, trailing zeros removed: "12.50" = "12.5", "4.0" = "4"). A minus sign or "−" is ignored (the sign is words' business).
- Number words: `zero, two … twenty, thirty, forty, fifty, sixty, seventy, eighty, ninety, hundred, thousand, million, dozen, half, halves, third, quarter, twice, double, triple` (whole words, plural `s` allowed, case-insensitive) count as numbers too; "one" does not (too common in plain English). A number word is allowed only if the same word appears in the input.
- Also counted as numbers: any character with `unicodedata.numeric(ch, None) is not None` that the ASCII digit regex (`re.ASCII`) did not capture (½, ², Roman numeral characters, non-ASCII digits): such a character is always rejected unless it appears in the input.
- `check(output: str, allowed_text: str) -> bool`: true when every number and number word in `output` appears in `allowed_text`. **`allowed_text` is the facts' values only** (`facts.values_text()`, the right-hand sides of `as_lines()`), never the instructions or the fact names; a test asserts the LLM instructions contain no number token or number word.
- Known limit (stated in the module docstring and in the PR): a number swapped for another number from the facts, or a flipped sign, passes. Tokens are compared with their unit when one follows ("25%" ≠ "25 bb"): a number followed by `%` must appear followed by `%` in the input, a number followed by `bb` must appear followed by `bb`.
- The LLM output passes only if every field passes. One failing field discards the whole output (spec §9: "discard it and fall back to the template").

### Ollama (`explain/ollama.py`)

- Settings (`settings.py`): `llm_provider: Literal["none", "ollama"] = "none"`, `ollama_url: str = "http://127.0.0.1:11434"`, `ollama_model: str = "llama3.2:3b"`, `llm_timeout: float = 60.0` (seconds, > 0; a 3B model on CPU with a cold load is slow), requests send `"keep_alive": "10m"`. Env vars `PPT_LLM_PROVIDER`, `PPT_OLLAMA_URL`, `PPT_OLLAMA_MODEL`, `PPT_LLM_TIMEOUT`, added to `backend/.env.example`.
- `generate(url, model, system, prompt, schema, timeout) -> str`: `POST {url}/api/chat` with `{"model", "messages": [system, user], "stream": false, "format": <JSON schema>, "options": {"temperature": 0.2}}`, returns `message.content`. Raises `LlmUnavailable` (connection refused, DNS, HTTP 404 model not found), `LlmTimeout` (a bare `TimeoutError` on read, or `URLError` whose `reason` is a `TimeoutError` on connect), `LlmError` (other HTTP errors including 400 from an Ollama older than 0.5 that has no JSON-schema `format`, `ConnectionResetError`, `RemoteDisconnected`, bad JSON). `HTTPError` is caught before `URLError` (it is a subclass). The opener is built with `urllib.request.build_opener(ProxyHandler({}))` so no environment or system proxy is used (this container sets `HTTPS_PROXY`; Windows and macOS have system proxies).
- The model is asked for JSON `{"headline": str, "hand": str, "verdict": str}` (`hand` and `verdict` may hold paragraphs separated by blank lines). The prompt: the facts block and the template text; instructions to rewrite in plain English for a recreational player, keep it short, use only numbers that appear in the input, never compute or estimate a number, keep card names as written, talk about the range not the result. Parse failures, empty fields, or a field over 1,200 characters → `invalid`.
- The Villain section is always the template's (it is a description, not a narrative).
- `probe(url, model, timeout=1.5) -> (status, detail)`: `GET {url}/api/tags`; `ready` when the model is listed (a model given without a tag matches `name:latest`), else `unavailable` with a detail ("Ollama is running but the model llama3.2:3b isn't pulled: run `ollama pull llama3.2:3b`." / "Ollama isn't answering at http://127.0.0.1:11434."). Cached for 30 s (`time.monotonic`).

### Service (`explain/service.py`)

- `Explainer(settings, *, generate=ollama.generate, probe=ollama.probe, clock=time.monotonic)` lives on `app.state` (created in `create_app`, injectable for tests like the puzzle factory).
- `explanation_for(attempt_id, template: Explanation, facts: Facts) -> Explanation`: provider `none` → template with `fallback="off"`. Else: a cached result for `(attempt_id, model)` if any; else call the model, apply the guardrail, build the `Explanation` (`source="llm"`, `model=<name>`, headline and the `hand` / `verdict` sections from the model, paragraphs split on blank lines, the template's Villain section). Cache successes and guardrail rejections (LRU, 256 entries, guarded by a `threading.Lock`, since sync endpoints run in a thread pool); do not cache `unavailable`, `timeout` or `error`. A per-key in-flight `threading.Event`: a second request for the same key while the first runs waits for its result instead of queueing a second generation in Ollama (an aborted browser fetch does not stop the server-side call). A guardrail rejection is logged at INFO with the offending numbers (not the whole text).
- `status() -> (llm_status, detail)` for settings: `none` → `("off", None)`; else the cached probe. Only `GET /api/settings` probes. `PATCH /api/settings` also returns a `SettingsView`, but it reports the last cached probe without probing again (`status(probe=False)`; with no cached probe yet it reports `unavailable` with the detail "Not checked yet.").

### Settings view

`SettingsView` changes: `llm_status: Literal["off", "ready", "unavailable"]` (the unreachable `"on"` goes), new `llm_model: str | None` (the model name when the provider is not `none`), `llm_detail: str | None`. `llm_provider` stays a string.

### Frontend

- **Why tab:** `DecisionDetails` gets an optional `whyTab?: ReactNode` (like `handTab`). Tab order: Why, Options, Maths, Range, Hand. When no tab is stored, the default is Why when present, else Options. The e2e tab checks iterate the new tab too; `App.test.tsx` (expects Options selected with a table after a submit) is updated; `ResultSummary.tsx` comments listing the tabs are updated.
- **`components/Explanation/ExplanationPanel.tsx`** (puzzle-agnostic, takes an `Explanation`, an optional `pending` flag and an optional `status` line): the headline (bold paragraph), then each section (`h3` title + paragraphs). Plain text only (no `dangerouslySetInnerHTML`; the text is rendered as text).
- **`useExplanation(result, llm)`** (Task 4): returns the explanation to show. With `llm_status === "off"` it is `result.explanation`, no request. With `unavailable` it shows the template and the settings' `llm_detail`, no request. With `ready` it shows `result.explanation` with "Rewriting in plain English with {model}…" (`role="status"`), requests `GET /api/attempts/{id}/explanation` with an `AbortController` (aborted when the result changes or unmounts), and swaps in the response. A failed request keeps the template, with a muted note.
- **Footer of the Why tab** (always): the source. Template: "Written by the trainer from the graded numbers." LLM: "Reworded by {model}, a local model. Every number in it was checked against the grader's numbers." Template after a fallback: one muted line for the reason ("The local model's text used a number the grader didn't compute, so the trainer's own text is shown." / "The local model didn't answer in time." / "The local model isn't available: {detail}."). Off: "Explanations come from templates. A local model (Ollama) can reword them: see backend/.env.example." The settings `llm_detail` is shown when the status is `unavailable`.
- **No top-bar change** (it must stay one row at 1280). The LLM status lives in the Why tab footer; a settings page is M11's.

### Fixtures

- Task 1 regenerates the `attempt_*.json` fixtures (they gain `explanation`), restoring unrelated last-digit changes with `git checkout` (CLAUDE.md). Task 3 regenerates `settings.json` (new fields) and adds `explanation_llm.json` (an `Explanation` with `source="llm"`, written by the fixture script from a fake generator that rewords the template (e.g. prefixes "In short: " and joins sentences) without adding numbers, so tests can tell the swap happened). `test/synthetic.ts`'s `neverContinuesAttempt` spreads `attempt_bet`, so its `explanation` is stale: Review Focus 2's test skips it.

## Review Focus

1. **No LLM numbers:** an LLM output with a number not in its input (including a number word, and "12.50" vs "12.5" normalisation) is discarded; the frontend shows the template and the reason.
2. **Template numbers equal the UI's numbers** for the same quantity (equity, pot odds, fold frequency, EV lost) on every attempt fixture: a frontend test compares the Why text against the Options / summary formatting of the same fixture.
3. **The template passes the guardrail against its own facts** on every fixture and on 50 generated puzzles (all streets, all action kinds).
4. **Never 5xx from the model:** unavailable, timeout, HTTP 500, bad JSON, empty output: each gives the template with the right `fallback`.
5. **No network with provider `none`:** a test patches `ollama.generate` and `ollama.probe` to raise and runs submit, result, explanation and settings.
6. **The Why tab** at 1024×768 and 1280×800: no horizontal scroll, readable text width (max ~70ch), keyboard navigation between tabs still works.

---

### Task 1: Template explanations and narrative (backend) — Opus

**Files:**
- Create: `backend/src/poker_trainer/explain/__init__.py`, `explain/format.py`, `explain/facts.py`, `explain/template.py`
- Modify: `backend/src/poker_trainer/api/views.py` (`attempt_result` adds `explanation`), `api/schemas.py` (`Explanation`, `ExplanationSection`, `AttemptResult.explanation`)
- Modify: `frontend/openapi.json`, `frontend/src/api/schema.d.ts` (`npm run gen:openapi && npm run gen:api`), `frontend/src/api/types.ts` (export `Explanation`, `ExplanationSection`), `frontend/src/test/fixtures/attempt_*.json` (regenerated)
- Test: `backend/tests/explain/test_format.py`, `test_facts.py`, `test_template.py`, `test_guardrail.py` (new), `tests/api/test_views.py` (`explanation` present, `source == "template"`); `test_contract.py` and `test_openapi_snapshot.py` follow the schema and the regenerated `openapi.json`

- [ ] **Step 1: Tests first.** `format`: a table of `pct` / `ev_bb` / `bb` cases including exact halves, negatives and `−0`; the JS outputs written as literals. `facts`: for a hand-built facing-bet river puzzle (reuse the golden-spot helpers in `tests/puzzle/` if they build `Puzzle`s, else `generate_puzzle(seed, street=...)`), `as_lines()` holds the pot odds, equity, EV lost and every option's EV as the UI formats them. `template`: golden texts for at least four spots (river call facing a bet, flop bet best and chosen, pre-flop fold, river check best with a bet chosen); "the template passes `guardrail.check` against `facts.as_lines()`" for 50 generated puzzles across streets with every legal option chosen once (**Task 1 adds `guardrail.numbers`/`check` too**, as the test needs them; Task 3 extends them with the LLM wiring); no section mentions the run-out or Villain's cards (assert Villain's hole-card strings don't appear).
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** `format`, `guardrail` (numbers and check only), `facts`, `template`; wire into `views.attempt_result` and the schemas.
- [ ] **Step 4: Regenerate** `openapi.json`, `schema.d.ts`, and the attempt fixtures (restore unrelated float changes). Frontend `npm run typecheck` and `npm test` still pass (the new field is unused yet).
- [ ] **Step 5: Run** the backend checks (`uv run pytest -m "not slow"`, `ruff check`, `ruff format --check`) and `npm run check:api`. Expected: PASS.
- [ ] **Step 6: Commit** `feat(explainer): template explanations and narrative (default provider "none")`

### Task 2: Why tab (frontend) — Sonnet

**Files:**
- Create: `frontend/src/components/Explanation/ExplanationPanel.tsx`, `ExplanationPanel.module.css`, `ExplanationPanel.test.tsx`
- Modify: `frontend/src/components/Decision/DecisionDetails.tsx` (+ test: `whyTab`, order, default), `frontend/src/app/App.tsx` (pass `whyTab`) and `App.test.tsx` (default tab after a submit is Why), `components/ResultSummary/ResultSummary.tsx` (comments), `frontend/src/dev/entries/results.tsx` (gallery entry for the Why tab), `frontend/e2e/smoke.spec.ts` (tabs include Why)

- [ ] **Step 1: Tests first.** The panel renders headline, three `h3` sections and paragraphs in order, as text (a `<b>` in the text is shown literally). DecisionDetails: Why is first and the default when nothing is stored; a stored `options` still opens Options; arrow keys cycle five tabs. Numbers agree (Review Focus 2): for each attempt fixture, the equity and EV-lost strings the summary shows appear verbatim in the Why tab text.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.** Footer as in "Frontend" with the template source line only (Task 4 adds the LLM states). Text width max 70ch.
- [ ] **Step 4: E2E:** the result flow test clicks the Why tab and sees the headline; the no-horizontal-scroll test covers Why.
- [ ] **Step 5: Run** every frontend check. Screenshots of the Why tab at 1280×800 and 1024×768 for the reviewer. Expected: PASS.
- [ ] **Step 6: Commit** `feat(ui): Why tab with the plain-English explanation`

### Task 3: Ollama provider, number guardrail, settings status (backend) — Opus

**Files:**
- Create: `backend/src/poker_trainer/explain/ollama.py`, `explain/service.py`
- Modify: `explain/guardrail.py` (number words, field checks), `settings.py`, `.env.example`, `api/app.py` (`Explainer` on `app.state`, `GET /api/attempts/{id}/explanation`), `api/service.py` (`settings_view` status), `api/schemas.py` (`SettingsView`), `api/dev_fixtures.py` (`explanation_llm.json`, settings)
- Modify: `frontend/openapi.json`, `schema.d.ts`, `types.ts`, `src/test/fixtures/settings.json`, new `src/test/fixtures/explanation_llm.json`
- Test: `backend/tests/explain/test_guardrail.py`, `test_ollama.py` (fake server), `test_service.py`; `tests/api/test_explanation_api.py`; `tests/api/test_settings_api.py`, `tests/db/test_app_settings.py` (new fields, `"on"` gone)

- [ ] **Step 1: Tests first.** Guardrail: a table of (output, input, pass?) including "12.50" vs "12.5", "1,5" vs "1.5", "−2.25 bb", "half", "halves", "twice", "two pair" (rejected: facts never hold showdown hand classes, which come from the run-out), "½", "²", "25%" vs an input "25 bb", a card "T♠"; and "the LLM instructions contain no number token". Ollama client against a fake server: success, model 404 → unavailable, 500 → error, slow reply → timeout (timeout 0.2 s), non-JSON content → invalid; the request body has `stream: false`, `format`, the model, and the facts in the prompt. Service: provider none → `fallback="off"` and no call; a guardrail failure → template with `fallback="guardrail"`, cached; unavailable not cached (a second call retries); LRU bound. Probe: ready, model missing, server down, the 30 s cache with an injected clock. API: the endpoint with an injected `Explainer` (fake `generate`), 404 for another user's or a missing attempt, provider none needs no network (Review Focus 5). Settings: `llm_status` off / ready / unavailable with detail; tests build `AppSettings(...)` explicitly with every LLM field (an env var on a dev machine would otherwise apply); `llm_model` is null with provider `none` even when `PPT_OLLAMA_MODEL` is set.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Regenerate** `openapi.json`, `schema.d.ts`, `settings.json`, `explanation_llm.json` (only those; restore the rest).
- [ ] **Step 5: Manual check** (not in CI): if `ollama` can be installed in the container, run a real model once and note the outcome in the task report; otherwise say so.
- [ ] **Step 6: Run** the backend checks and `npm run check:api`, `npm run typecheck`. Expected: PASS.
- [ ] **Step 7: Commit** `feat(explainer): Ollama provider + number guardrail + settings status`

### Task 4: Local-model explanations and LLM status in the UI (frontend) — Sonnet

**Files:**
- Create: `frontend/src/app/useExplanation.ts` (+ test)
- Modify: `frontend/src/api/client.ts` (`getExplanation(attemptId, signal)` + test), `components/Explanation/ExplanationPanel.tsx` (pending status, source footer, fallback notes, settings status), `app/App.tsx` (pass settings' LLM fields), `dev/entries/results.tsx` (LLM, pending and fallback states), `e2e/smoke.spec.ts`, `docs/superpowers/plans/2026-11-10-roadmap.md` (M8 bullets marked as built in 4 commits)

- [ ] **Step 1: Tests first.** Hook: off → no fetch; on → template first, then the LLM version; result change aborts the old request (no stale swap); a failed request keeps the template and sets a note. Panel: each footer text; `llm_detail` shown when unavailable; the pending status is `role="status"`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: E2E** with `page.route`: settings fulfilled with `llm_status: "ready"`, the explanation endpoint fulfilled from `explanation_llm.json` after a short delay; the Why tab shows the pending line, then the LLM text and the "Reworded by" footer.
- [ ] **Step 5: Run** every frontend check. Screenshots (LLM, pending, fallback) at 1280×800 and 1024×768. Expected: PASS.
- [ ] **Step 6: Commit** `feat(ui): local-model explanations and LLM status`

## Execution notes

- Order: 1 → 2 → 3 → 4. Task 2 needs Task 1's fixtures; Task 4 needs Task 3's schema and fixtures.
- Models: Opus implementers for Tasks 1 and 3 (numbers must match the grader's; the guardrail is the anti-goal's only defence); Sonnet for Tasks 2 and 4; Opus for every review and the final whole-branch review.
- Every reviewer gets this plan, the task's diff and test output and, for UI tasks, screenshots. Spec compliance first, then code quality, then a mutation check on the most important test (Task 1: break a format rule; Task 3: let one new number through the guardrail).
- After Task 4: whole-branch review, one fix wave, scoped re-review, all checks, follow-ups and open items recorded at the end of this plan, then push and open a PR into `main` (no squash).

## Rulings from the plan review (folded in above)

- Range-step labels and action-log `text` are in chips and contain numbers: the narrative uses `kind`/`to`/`amount`, the Villain section converts the labels with a port of `bbLabel` and puts them in the facts.
- Each quantity has one named UI view whose format it copies (table under "Number formats").
- Every template states whole-range equity and, when lost, the EV lost, so the Why text contains the summary's strings.
- The headline follows `verdictLine`'s three cases and `EV_EPSILON`.
- Formulas (pot odds, bluff check) are printed only when they reproduce the API number within 0.001.
- The guardrail checks against the facts' values only; Unicode numerals, plural number words and number+unit pairs are covered; swapped numbers and flipped signs are a stated known limit.
- urllib ignores system proxies, maps both timeout forms, orders `HTTPError` before `URLError`; the cache is locked and duplicate requests wait for the in-flight one.
- Timeout 60 s with `keep_alive`. PATCH settings does not probe.

