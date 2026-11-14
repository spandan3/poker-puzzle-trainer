# Poker Puzzle Trainer

A personal trainer for No-Limit Hold'em, heads-up. The app deals you a spot (your cards, the board, the action so far), you pick a play, and it grades the decision by expected value (EV) against the range of hands a model opponent ("Villain") could hold, never by how the hand turned out. It shows the maths behind every grade, tracks your progress and leaks, and can optionally have a local language model reword the explanations. Every equity, pot-odds and EV number is computed by the code; the language model only explains numbers it is given. Amounts are shown in big blinds.

The backend is FastAPI (Python, managed with uv). The frontend is Vite, React and TypeScript. In normal use the backend serves the built frontend, so one process is enough.

## Requirements

- [uv](https://docs.astral.sh/uv/). It installs Python 3.13 for you.
- Node.js 22.12 or newer. The version CI uses is in `frontend/.nvmrc`.
- Optional: [Ollama](https://ollama.com) 0.5 or newer, for local explanations.

Windows and macOS are both supported (CI runs on both). The commands below work unchanged in PowerShell and in zsh.

## Setup

```
cd backend
uv sync
cd ../frontend
npm ci
```

## Run

Build the frontend once, then start the backend, which serves it:

```
cd frontend
npm run build
cd ../backend
uv run serve
```

Open http://127.0.0.1:8000. The database (`backend/poker_trainer.db`) is created and migrated on first start.

For live reload while changing the frontend, keep `uv run serve` running in `backend/` and start the dev server in a second terminal:

```
cd frontend
npm run dev
```

Then open http://localhost:5173. It proxies API calls to the backend.

## Optional: local explanations with Ollama

Without this the app uses fixed templates for its explanations, and nothing leaves your machine either way. To have a local model reword them:

1. Install Ollama (0.5 or newer) and start it.
2. Pull the model: `ollama pull llama3.2:3b`
3. Copy the settings file: `cp backend/.env.example backend/.env`
4. In `backend/.env`, set `PPT_LLM_PROVIDER=ollama`.
5. Restart `uv run serve`, and reload the app page (it checks Ollama when the page loads).

If the model uses a number the trainer did not compute, or names the plays in the wrong order, its text is discarded and the template is shown instead.

`PPT_LLM_TIMEOUT` is how many seconds the app waits for the model. The default is 60. On a laptop GPU or a CPU, the first answer after loading the model can take over a minute, so set it to 120 to 180 if explanations keep falling back to the template with a timeout. Later answers are much faster (3 to 9 seconds on a laptop RTX 3050 Ti in the M9 measurement).

## Settings

Set these in `backend/.env` (read from the folder you run `uv run serve` in, which is `backend/`) or as environment variables. The file is never committed. Every variable has the default shown.

| Variable | Default | Meaning |
|---|---|---|
| `PPT_DATABASE_URL` | `sqlite:///./poker_trainer.db` | Database. A relative path is relative to where you run the server. |
| `PPT_FRONTEND_DIST` | `../frontend/dist` | The built frontend that the backend serves. |
| `PPT_HOST` | `127.0.0.1` | Address to listen on. |
| `PPT_PORT` | `8000` | Port to listen on. |
| `PPT_LLM_PROVIDER` | `none` | `none` (templates only, no network) or `ollama`. |
| `PPT_OLLAMA_URL` | `http://127.0.0.1:11434` | Where Ollama is running. |
| `PPT_OLLAMA_MODEL` | `llama3.2:3b` | The model to use. Pull it first. |
| `PPT_LLM_TIMEOUT` | `60` | Seconds to wait for the model's answer. |

## Checks

Run these before a pull request. Each block starts from the repository root.

```
cd backend
uv run pytest -m "not slow"
uv run ruff check
uv run ruff format --check
```

```
cd frontend
npm test
npm run lint
npm run typecheck
npm run format:check
npm run build
npm run e2e
```

`npm run e2e` starts its own backend on port 8765 with a scratch database. If the browser is missing, run `npx playwright install chromium` first. The slower ground-truth tests are run with `uv run pytest -m slow`.

## Tools

Run these from `backend/`.

- `uv run competence --profile all --hands 400 --seeds 0-5` plays each Villain profile against a reference player and checks its behaviour (bluff share, defence against bets, pre-flop defence and more) against bands. It prints a table per seed and a summary, and exits non-zero if any check fails. `--profile` takes `tag`, `lag`, `tight`, `sticky` or `all`.
- `uv run puzzle-sample --n 3 --street flop --seed 10` prints sample puzzles with the grader's EV for every option. `--street` is `preflop`, `flop`, `turn` or `river`, and `--profile` fixes the Villain.
- `uv run explain-check --url http://127.0.0.1:8000 --n 12` measures the explanations against a running app: it answers 12 puzzles and reports, for each, whether the model's text was kept or replaced by the template, and how long it took. Start the app with `PPT_LLM_PROVIDER=ollama` and a long `PPT_LLM_TIMEOUT` first, ideally on a scratch database (for example `PPT_DATABASE_URL=sqlite:///./scratch.db`), because it adds attempts to the database it talks to.

## Layout

- `backend/`: the FastAPI app and the poker logic (`src/poker_trainer/`: engine, game, Villain profiles, puzzle generator and grader, stats, explanations, analysis tools) and its tests (`tests/`).
- `frontend/`: the React app (`src/`), the Playwright end-to-end tests (`e2e/`) and the generated API types.
- `docs/superpowers/`: the design specs, the milestone plans and the M9 competence sign-off report (`reports/`).
- `CLAUDE.md` and `handoff.md`: working notes for the AI-assisted workflow used to build the project.
