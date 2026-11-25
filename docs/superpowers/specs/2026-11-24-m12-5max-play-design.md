# M12 Play vs Bots, 5-max (play only) — Design

> **Note (2026-11-25):** milestones after M12 were renumbered. 5-max analysis, called M13 here, is now M15 (later, if needed). M13 is a UI redesign and M14 is profile tuning. See the roadmap.

Date: 2026-11-24. Extends `2026-11-12-play-vs-bots-design.md` §5. Decisions marked "user" were made with the user on 2026-11-24; the rest are Claude's calls, open to change before the plan is built.

## 1. Intent

Play full 5-handed cash-game hands (Hero + 4 bots) in a saved session, next to the existing heads-up mode. Play only: no Analyse button for 5-max hands yet (M13). The hand record is stored completely so M13 can grade it later.

## 2. Decisions

### Made with the user
- **Both modes, picked per session.** The Play start screen offers Heads-up or 5-max. Heads-up is unchanged, Analyse included.
- **Side pots and all-ins are supported for real.** Uneven stacks, several all-ins, uncalled bets returned, an odd chip awarded by a fixed rule.
- **Multiway bots use a damping rule for now.** When three or more players are in the pot, the heads-up post-flop policy is reused and then damped per extra opponent (§5). Proper multiway tuning comes later in a separate profile-tuning milestone (roadmap M14).
- **No limps, pre-flop or anywhere.** The same pre-flop shape as heads-up: open or fold; facing an open, fold / call / 3-bet / jam; facing a 3-bet, fold / call / jam; facing a jam, fold / call. Limps and small 4-bets are left for the tuning milestone.
- **Simple pre-flop ranges.** The user doesn't care about range precision. Bots use one hand ranking and a percentage per position and profile (§4), not hand-built charts.
- **Villain's range display is turned off.** A new setting, "Show Villain's range", defaults to off. When it is off, the Range tab is hidden on Puzzles results and in heads-up analysis. The grader still uses the range exactly as before; only the display changes. (Claude's call: a setting rather than deleting the code, so it can be turned back on.)

### Claude's calls
- **One engine for any number of seats (2 to 6).** Heads-up is the two-seat case and behaves exactly as today: every existing test, golden file and fixture stays byte-identical.
- **Seats and positions.** Seat 0 is Hero for the whole session, shown at the bottom. Seats 1–4 are the bots, named Bot 1 to Bot 4, fixed for the session. The button moves one seat clockwise each hand, starting at a random seat. The positions follow the button: BTN, SB, BB, UTG, CO. Pre-flop UTG acts first. Post-flop the first live seat left of the button acts first.
- **Each bot seat gets its own random profile** at session start, from the four profiles (repeats allowed). The profile is stored with the session as in heads-up. Each seat shows a profile badge when "Show Villain profile" is on.
- **Stack rules as in heads-up, per seat.** Everyone starts at 100 bb. A bot below 40 bb tops up to 100 bb, and a bot above 150 bb is reset to 100 bb, both at the start of a hand. Hero must rebuy when below 5 bb and may top up to 100 bb between hands. Hero's rebuys count in the session tally.

## 3. Engine

- **State.** `HandState` holds per-seat tuples (stacks, street bets), and the number of seats comes from the stacks. Folded seats come from the history, and contributions come from the hand's start stacks. With two seats every rule, value and legal-action result is identical to today's.
- **Bet cap.** A seat can bet at most what the deepest other live player can still match. Heads-up that is the effective-stack cap used today. With more players, a seat can still be all-in for less than others and a bet can still exceed one caller's stack, so side pots arise.
- **Round end.** A betting round ends when every live seat that isn't all-in has acted since the last full raise and matched the bet. A short all-in doesn't reopen raising for seats that have already acted (today's `_can_reraise` rule, generalised). The board runs out once at most one seat can still bet.
- **Settlement (`game/settle.py`).**
  - Pots are built in layers from each seat's total contribution. A layer is contested by the live seats that paid into it, and its chips come from everyone who paid into it, folded seats included.
  - A layer only one seat paid into is an uncalled bet and is returned to that seat.
  - Each layer goes to the best hand among the seats contesting it. A tie splits it evenly, and an odd chip goes to the first winner clockwise from the button.
  - If everyone but one folds, that seat takes everything.
  - Invariant: chips are conserved in every state and every settlement.
- **Hand record.** The deck convention generalises: seat *i*'s hole cards are `deck[2i : 2i+2]` and the board is `deck[2n : 2n+5]`, so heads-up stays `deck[4:9]`. Each bot samples with its own seed stream, `f"{bot_seed}:{seat}:{i}"`. Heads-up keeps today's `f"{bot_seed}:{i}"`, so stored heads-up hands replay identically.

## 4. Pre-flop bots

- **Hand ranking.** One fixed ranking of the 169 starting-hand classes (by all-in equity against a random hand), computed once and stored as a data file with a version.
- **Percentages per profile** in a new data file, one block per profile:
  - an open % by position (UTG, CO, BTN, SB);
  - facing an open: a 3-bet % and a call %;
  - facing a 3-bet: a jam % and a call %;
  - facing a jam: a call %.

  A bucket is a slice of the ranking: the 3-bet range is the top *t*%, and the call range is the next *c*%. The loose profiles get wider numbers.
- **Which bucket applies** depends on the number of raises so far, not on callers or positions. No raise: open or fold. One raise: fold, call or 3-bet. Two raises: fold, call or jam. A jam faced: fold or call.
- **The big blind** facing an open closes the action, so it uses a wider call % (a fixed multiplier, stated in the data file). It never sees an unopened pot it can check, because a walk ends the hand.
- **Sizes.** Opens are 2.5 bb, and the small blind opens to 3 bb. A 3-bet is 3× the open, plus one open-size per caller in between. Every 4-bet is all-in. All sizes are capped and clamped as today.
- **Heads-up mode** keeps its existing per-combo pre-flop tables unchanged. The new ranking is used only when more than two seats are dealt in.

## 5. Post-flop bots: the multiway damping rule

- **Two live players** (one opponent): the heads-up policy is used exactly as it is, roles included (c-bet, lead, stab, facing bet, facing raise). This covers most 5-max flops.
- **Three or more live players:** start from the heads-up distribution for the seat to act, then apply a factor *d^k*, where *k* is the number of live opponents minus one:
  - bluffs (bets and raises with air, weak draws and weak made hands) are multiplied by *d_bluff^k*;
  - bets with medium hands are multiplied by *d_thin^k*;
  - the freed probability goes to check (unopened) or fold (facing a bet);
  - facing a bet, the continue probability of everything below strong hands is multiplied by *d_call^k*, and strong hands and the nuts keep their floor.

  Damping is applied to the policy's category tables, before actions are merged, and is skipped for committed hands at low SPR. The constants live in one data file, with starting values *d_bluff* = 0.5, *d_thin* = 0.6 and *d_call* = 0.8. Arrays still sum to 1 per combo.
- **Roles with several players.** "c-bet" is the previous street's last aggressor. "Lead" is the first seat to act on the street with no aggression before it. "Stab" means checked to by at least one seat.
- **SPR** uses the effective stack against the deepest live opponent.
- **Version.** `STRATEGY_VERSION` stays 1, because heads-up behaviour doesn't change and a test pins it. The 5-max policy is versioned by its two data files, stored with each 5-max hand.

## 6. Hero's options

The same option set as heads-up, generalised:
- **Pre-flop:**
  - unopened: fold, 2.5×, 3×, all-in;
  - facing an open, with or without callers: fold, call, 3-bet 2.5× / 3×, all-in;
  - facing a 3-bet: fold, call, all-in;
  - facing a jam: fold, call.
- **Post-flop:** check or bet 33/50/75/100%, all-in, a custom size; facing a bet, fold, call, raise 2.5× / 3×, all-in.

## 7. Session, storage, API

- `play_sessions` gains `table_size` (2 or 5, default 2) and a `seats` JSON column: per bot seat, its name, profile, profile snapshot and stack. Existing heads-up columns stay, so heads-up sessions are untouched. Migration 0005.
- `play_hands` already stores `button`, `start_stacks`, `deck`, `bot_seed` and `actions`. Lists simply get longer. The outcome becomes a per-seat result plus the pots (amount, contesting seats, winners). Hero's delta stays as it is.
- **API.** Starting a session takes `table_size`. Every 5-max response carries:
  - per-seat views (name, position, stack, street bet, folded or all-in, the profile if shown);
  - the actions since Hero's last decision, so the client can play them in order;
  - at the end of the hand, the showdown cards of every seat still in, and each pot with its winners.

  Bots' cards are never sent before the showdown, and cards of seats that folded are never sent.
- **When Hero folds,** the server plays the hand out at once and returns the full sequence. Hero sees the rest of the hand play out and can press Next hand at any time.
- **No Analyse** for 5-max hands. The route refuses them with a clear error, and the UI doesn't offer it.
- Play results stay out of puzzle stats, as in heads-up.

## 8. UI

- **Start panel:** a Heads-up / 5-max choice. The bot names and profiles are shown after the deal if the setting allows.
- **Table:** five seats from the existing slot layout, Hero at the bottom. Each seat shows its stack, bet, position chip (with the dealer button) and a Folded or All-in tag.
- **Pacing:** bot actions play one at a time, about 0.5 s each (instant with reduced motion), with a short action log ("Bot 2 raises to 7.5 bb").
- **Pot:** the main pot and each side pot are shown, labelled in bb. At the end of the hand an award line is shown per pot, after the reveal ("Bot 3 takes the side pot, 24 bb").
- **Fit:** 1024×768 and 1280×800 with no scroll, the one-row top bar kept, and the existing layout and e2e checks extended to the 5-max table.
- **Session hands list:** shows 5-max hands with Hero's result and who won, without an Analyse button.
- **Settings:** a "Show Villain's range" toggle, default off.

## 9. Testing

- **Engine properties:** chips are conserved over random multi-seat hands with random stacks and actions; side-pot layers sum to the pot; an uncalled bet is returned; odd chips follow the rule; heads-up results are identical to the old engine on a large replay set (the old engine is kept in tests as a reference).
- **Bots:** every 5-max spot reachable with these sizes gets a distribution, never `UnsupportedSpot`, checked by simulation. Opens widen from UTG to BTN. Damping is monotonic in the number of opponents and does nothing heads-up. Every distribution is valid (non-negative, sums to 1).
- **Simulation (slow):** thousands of 5-max hands of bots against random Hero play, with no errors and chips conserved.
- **API and UI:** contract and snapshot tests; 5-max views never leak bot cards; e2e covers a full 5-max hand, side pots and the layout checks.

## 10. Not in M12

- Analysis of 5-max hands (M13).
- Limps, small 4-bets, and a proper multiway policy (M14 tuning).
- Five-handed puzzles.
