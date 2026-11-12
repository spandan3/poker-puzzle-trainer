# Poker Puzzle Trainer: working notes for Claude

A personal NLHE trainer: a FastAPI backend (`backend/`, uv, Python 3.13) and a Vite + React + TS frontend (`frontend/`). Repo: `spandan3/poker-puzzle-trainer` (private).

## Where things are

- Spec: `docs/superpowers/specs/2026-11-10-poker-puzzle-trainer-design.md`. Play vs Bots: `docs/superpowers/specs/2026-11-12-play-vs-bots-design.md`.
- Roadmap: `docs/superpowers/plans/2026-11-10-roadmap.md`. Order: M6 results → M7 progress → M8 explanations (local LLM) → M9 Phase 1 sign-off → M10 Play vs Bots heads-up → M11 UI polish → M12 5-max play → M13 5-max analysis.
- Each milestone has a plan in `docs/superpowers/plans/`. The end of the latest plan lists the open items for the next milestones. Read it before planning the next one.
- `handoff.md` is for parallel work on the Villain model (`villain/*` branches). It also says which paths the main line owns.

## How each milestone is built

1. **Plan:** write the milestone plan (superpowers:writing-plans) from the roadmap, the spec and the previous plan's open items. Before any code, an Opus subagent reviews the plan against the real code. Fold its findings in, then commit the plan to the milestone branch.
2. **Branch:** one branch per milestone, e.g. `m7-progress`. Never commit code straight to `main`.
3. **Build:** subagent-driven development (superpowers:subagent-driven-development), with one commit per task, in roadmap order.
   - **Implementers:** Sonnet for well-specified tasks. Opus for maths-critical work (equity, Villain strategy and range narrowing, EV grader, anything that must match the grader's numbers).
   - **Reviewers:** Opus for every task review and for the final whole-branch review. Re-reviews of small fix diffs can use Sonnet.
   - UI tasks give the reviewer screenshots at 1280×800 and 1024×768.
4. **Finish:** final whole-branch review, then one fix wave, then a scoped re-review. Run the checks yourself, record the follow-ups and open items at the end of the plan, then push and open a PR into `main`.
5. **Autonomy:** once the plan is committed, run the whole milestone to the PR without check-in questions. Make rulings yourself and list them in the PR summary. Brainstorming and design for new features still involve the user.

## Git rules

- **Never squash.** Every commit is preserved on merge (rebase-merge or merge commit).
- Docs-only commits (handoff, plan follow-ups, roadmap) may go straight to `main`.
- Don't delete branches without asking.

## Checks before any PR

- `backend/`: `uv run pytest -m "not slow"`, `uv run ruff check`, `uv run ruff format --check`
- `frontend/`: `npm test`, `npm run lint`, `npm run typecheck`, `npm run format:check`, `npm run build`, `npm run e2e` (it starts the backend; run `npx playwright install chromium` if the browser is missing)
- CI runs on Windows and macOS. Keep everything cross-platform: no OS-specific scripts, LF line endings for generated files, one uv lock.

## Running the app

Build the frontend (`npm run build` in `frontend/`), then run `uv run serve` in `backend/` and open http://127.0.0.1:8000. For live reload, run `npm run dev` in `frontend/` with the backend running, and open http://localhost:5173.

## Product rules that must not break

- No equity, pot-odds or EV number ever comes from an LLM. The LLM (M8, Ollama, optional) only explains numbers the code computed.
- Grade the decision against Villain's range, never the result of the hand.
- The range shown must be the range used for grading. A formula shown in the UI must reproduce the API's number.
- Show amounts in big blinds. The API works in chips (bb = 2 chips).
