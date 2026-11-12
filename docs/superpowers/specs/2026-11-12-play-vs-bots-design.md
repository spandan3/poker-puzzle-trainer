# Play vs Bots — Design

Date: 2026-11-12
Status: draft for approval
Builds on: `2026-11-10-poker-puzzle-trainer-design.md` (the main spec). Everything there still holds unless this document says otherwise.

## 1. Intent

A second part of the app, next to Puzzles: the user plays **full hands, start to finish**, against bots, like sitting at a real table. After any hand they can click **Analyse** and get a chess.com-style game review of that hand: every decision they made, graded, with what they could have done better.

Puzzles drill one decision in a spot chosen for them. Play vs Bots is where the user practises the same skills in the flow of real hands, then reviews only the hands they choose.

**Success** = the user enjoys playing sessions here, and the per-hand analysis teaches them the same lessons the puzzles do (EV lost per decision, range reading), on hands they played themselves.

## 2. Goals, non-goals, anti-goals

**Goals**
- Heads-up play (Hero vs 1 bot) with full hands: pre-flop to showdown or fold.
- Cash-game session: stacks carry over between hands, the button alternates, a running session result in bb.
- Optional per-hand analysis, computed **only when the user clicks Analyse** on that hand. Hands the user doesn't analyse cost nothing and show nothing extra.
- Analysis grades each Hero decision in the hand the same way puzzles do, and presents it in the M6 results-view style.
- Later (separate milestones): 5-max (Hero + 4 bots), first play only, then analysis.

**Non-goals**
- Real money, online play against people, tournaments.
- Hand-history import/export.
- A redesign of the analysis format. The user wants M6 style for now and will iterate later.
- UI polish beyond what M5/M6 already give. That is milestone M11.

**Anti-goals (a failure even if it works)**
- Bots that play differently from the Villain model the puzzles teach against. The bot must be the same policy (main spec §5, "one policy, used three ways").
- Analysis that grades on the result (who won the hand) instead of the decision against the range.
- The analysis range disagreeing with the range the bot's actions actually imply.
- Analysis computed for every hand automatically, slowing play or cluttering the screen.
- Any EV or equity number from an LLM.

## 3. Decisions made with the user

- **Full hands, analysis optional per hand.** After each hand an "Analyse" button is offered. Only a click generates analysis. Playing on without clicking gives no analysis.
- **Analysis content:** walk through each Hero decision in the hand, M6 results-view style (verdict, EV lost, options table, maths, range). Format to be iterated later.
- **Session format:** cash game. Everyone starts at 100 bb, stacks carry over, button moves each hand. Bots that drop below 40 bb top back up to 100 bb. Hero must rebuy when below 5 bb (§4). A session tally shows bb won/lost.
- **Bot profiles are random.** In 5-max each bot seat gets its own random profile.
- **Scope order:** heads-up with analysis first. 5-max later: play first, its analysis after.
- **Milestone order** (roadmap): M6 results view → M7 progress → M8 explanations (local LLM) → M9 Phase 1 sign-off → **M10 Play vs Bots heads-up** → **M11 UI polish** (after Play vs Bots exists, so every screen can be polished together) → **M12 5-max play** → **M13 5-max analysis**.

## 4. Heads-up play (M10)

### The bot
- The bot is the existing Villain policy: `villain/strategy.action_distribution(profile, state)` gives per-combo action probabilities. The bot samples one action for its actual hole cards. No new bot logic in M10.
- One random profile per session (TAG, LAG, Tight, Sticky, from the existing profile files). Always random in M10: the puzzles' Villain select does not apply here (Claude's call, following the user's "randomized"). Whether it is shown during play follows the existing "show Villain profile" setting. It is always shown in the analysis.

### Hero's actions are the trainer's option set (Claude's call)
The Villain policy only supports this pre-flop tree: Button opens or folds (no limps), Big Blind folds / calls / 3-bets, Button facing a 3-bet folds / calls / jams, Big Blind facing a jam folds / calls. Anything else raises `UnsupportedSpot`.

So Hero's action menu in play is the same option set the puzzles offer (`puzzle/options.py`):
- Pre-flop: no limping from the Button; Hero's opens and 3-bets use the trainer sizes (2.5x / 3x / all-in); facing a 3-bet, Hero can fold, call or jam (no smaller 4-bet).
- Post-flop: 33/50/75/100% pot bets, 2.5x/3x raises, all-in, plus a custom size, exactly as in puzzles.

This keeps every hand inside what the bot can play and what the grader can grade, given the minimum-stack rule below. Widening the tree (limps, small 4-bets) is a later Villain-model task, not M10.

Known simplification, carried over from puzzles: pre-flop, the bot's response ignores the size of Hero's open or 3-bet (2.5x and 3x get the same response; an all-in is treated as a jam). State it in the UI help so it isn't mistaken for a bug.

### Session and stacks (Claude's call on details)
- Blinds 1/2 chips (bb = 2), start stack 100 bb (200 chips), matching the engine's defaults.
- The button alternates every hand.
- Bot below 40 bb at the start of a hand: topped up to 100 bb. Bot above 150 bb: reset to 100 bb ("racks some chips"). This keeps effective stacks at or under 150 bb, close to the depth the profiles were tuned for.
- Hero: when below 5 bb at the start of a hand, Hero must rebuy to 100 bb before the next deal (Claude's call: a stack that the blind alone puts all-in creates spots the pre-flop tree doesn't support, e.g. a 1 bb big blind leaves the button unable to open). Hero may also top up to 100 bb between hands whenever below it. Each rebuy/top-up is counted in the session tally, so the tally is true net bb.
- Session tally: net bb and hands played, shown in the top bar. Sessions are saved. Only one session is open at a time (Claude's call). Leaving for Puzzles, closing the tab or reloading pauses it, including a hand in progress, and it resumes exactly where it was when the user comes back. Nothing times out. Only "End session" closes it; ending during a hand counts as Hero folding that hand, so the tally stays true net bb.

### Engine work
- `game/state.py` has no showdown, pot award or split-pot logic (the only showdown code is in `api/views.py`, for frozen puzzle spots). Settlement (winner, pot award, chopped pot on a tie) is new code in M10, with tests that chips are conserved across hands. Heads-up with bets capped at the effective stack there are no side pots, and a chopped pot is always an even number of chips, so no odd-chip rule is needed.
- **Each hand's randomness is fixed when it starts:** the deck order and a seed for the bot's action sampling are drawn and stored with the hand, so a resumed hand continues identically.

### Play flow
1. Deal: Hero's cards face up, the bot's face down, blinds posted. Reuse the M5 table, seats, cards and deal animations.
2. When it's the bot's turn, it acts after a short pause (about 0.6 s) so the user can follow; the action history panel updates.
3. When it's Hero's turn, the answer panel shows only the action and size controls. **No equity guess, range read or intent during play** (Claude's call: it would slow play down; the analysis shows true values instead).
4. Hand ends: at showdown the bot's cards are shown; if someone folds, the bot's cards stay hidden at the table. Stacks update.
5. Between hands: "Next hand" (keyboard shortcut) and "Analyse this hand". The user can also analyse any earlier hand of the session from a session hand list.

### Analysis (on click only)
- For each Hero decision in the hand, build the spot as it stood (Hero's cards, board, history, stacks, the bot's range narrowed by its actual actions via the existing `RangeTracker`) and grade Hero's actual action with the existing grader (`puzzle/solve` + `puzzle/grade`). This needs an adapter: `grade()` takes a `Puzzle(Spot, Solution)` and requires an equity guess, so M10 either builds a `Spot` per decision or refactors the grader so the guess scores are optional. Builder's choice; puzzle grading results must not change.
- Show the decisions as a step list (pre-flop, flop, turn, river). Each step uses the M6 results view components: verdict and EV lost, options table, step-by-step maths, range grid and its narrowing, Hero vs range breakdown.
- A hand summary on top: total EV lost in the hand, worst decision highlighted.
- The bot's actual cards and profile are revealed in the analysis even if the hand ended in a fold. The "judged on range, not on result" note is shown.
- No equity-guess or range-read scores (nothing was guessed during play).
- If a decision can't be graded (it should not happen given the option-set rule), show "not graded" with the reason; never crash the analysis.
- Analysis is computed once and stored with the hand, so reopening it is instant. Hands from ended sessions can still be analysed from the session history.
- Analysis runs a full `solve` per decision (Monte-Carlo equity), so it shows a loading state with progress per decision. Target: a typical hand (up to 6 Hero decisions) analysed in under 10 s on the dev machine.
- **Villain model changes (Claude's call):**
  - Each session stores a snapshot of its bot's profile data. The bot plays from the snapshot, and the analysis adapter always passes `respond=villain_respond(snapshot_profile)` to both `solve` and `grade`, so `grade._resolve` never reloads the live profile. M10 makes building a `Profile` from stored data public (today only the private `_profile_from_dict` does it).
  - Category thresholds (`categories.json`) and the strategy code are global and not snapshotted. M10 adds `STRATEGY_VERSION` to `villain/strategy.py`, bumped by hand whenever the policy's behaviour changes. Each hand stores `STRATEGY_VERSION`, the `categories.json` version and the puzzle config version. If any differs at analysis time, the analysis is shown with a "Villain model has changed since this hand" label.
- If an LLM provider is on (M8), the explanation for each decision uses the same provider and guardrail as puzzles.

### Storage and stats
- New tables for sessions and hands (each hand stores its full action history, cards, stacks, and, once requested, its analysis). Same database and migrations approach as M4.
- Play vs Bots results are **kept separate** from puzzle progress (M7): puzzle stats stay comparable over time (Claude's call). A play-session history list can show net bb per session and per-hand EV lost for analysed hands.
- Reloading the page mid-hand resumes the session and the current hand.

## 5. 5-max (M12, M13) — outline only

- Seats: Hero + 4 bots, positions UTG, CO, BTN, SB, BB (the M5 layout is already ready for 5 seats). Each bot seat gets its own random profile.
- **M12, play only:** needs a multiway game state and bots that act sensibly when more than two players are in. Pots that end heads-up after pre-flop folds can reuse the heads-up policy; multiway pots need an extended or approximate policy. No Analyse button yet.
- **M13, analysis:** heads-up-by-the-flop pots graded as in M10; pots with three or more players graded approximately and labelled as approximate (as the main spec's Phase 2 already allows).
- Each gets its own design pass when we reach it.

## 6. Relationship to other milestones

- **M6 results view** must be built from components that can render one decision given its graded data, so M10 can reuse them per decision without the puzzle-specific parts (guess scores, Next puzzle).
- **M8 explanations** apply per decision in the analysis.
- **M11 UI polish** covers Puzzles, Results, Progress and Play vs Bots together.

## 7. When this gets planned

The implementation plan for M10 is written when M9 is merged, as for every milestone, so it can use the real M6 results-view components and the M8 explanation provider. M6 should still keep its per-decision components reusable (§6), but M6 isn't planned around this document.

## 8. Left to the builder

- API shape (endpoints for session start, hand state, Hero action, bot action, analyse).
- Whether bot actions are computed server-side per request or in a loop until Hero is to act (server-side is required; the client never sees the bot's cards before showdown or analysis).
- Seeding and reproducibility of shuffles and bot sampling for tests.
- Exact layout of the analysis step list and the session hand list (M6 components, M5 table).
- Test plan, following the main spec §13: property tests that bot actions come from the policy's distribution, stacks are conserved within a hand, the analysis range equals the narrowing of the bot's real actions.
