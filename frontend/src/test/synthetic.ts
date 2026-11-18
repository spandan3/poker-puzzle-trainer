// SYNTHETIC fixture: no real spot has Villain never continuing against a bet (none turned up in
// 200 seeds), so this one is derived by hand from attempt_bet. It is not API output. It exists to
// test the edge case where the API's null fields appear: one branch ("Villain folds", 100%) and
// no equity when called.
import type { AttemptResult } from '../api/types'
import { attemptFixture, puzzleFixture } from './fixture'

/** attempt_bet (puzzle_flop_unopened) with the chosen bet folding out Villain every time. */
export function neverContinuesAttempt(): AttemptResult {
  const base = attemptFixture('bet')
  const pot = puzzleFixture('flop_unopened').pot
  return {
    ...base,
    options: base.options.map((o) =>
      o.is_chosen
        ? {
            ...o,
            fold_freq: 1,
            branches: [
              {
                label: 'Villain folds',
                share: 1,
                equity: null,
                value_chips: pot,
                value_bb: pot / 2,
                realisation: 1,
              },
            ],
            equity_vs_continue: null,
            equity_vs_continue_se: null,
            ahead_vs_continue: null,
            continue_grid: null,
            ev_chips: pot,
            ev_bb: pot / 2,
          }
        : o,
    ),
  }
}

// SYNTHETIC: a custom-size row stored before M9, when the grader kept the listed option as best
// even if the custom size beat it. Derived by hand from attempt_custom; not API output.
/** attempt_custom (puzzle_custom_allowed) with Bet 33% marked best, as a pre-M9 row stored it. */
export function customBelowListedBestAttempt(): AttemptResult {
  const base = attemptFixture('custom')
  return {
    ...base,
    grade: { ...base.grade, best_label: 'bet 33%' },
    options: base.options.map((o) => ({ ...o, is_best: o.label === 'bet 33%' })),
  }
}

// SYNTHETIC: the big blind calling an open (out of position pre-flop, realisation 80%). Derived by
// hand from attempt_raise_preflop by choosing its listed call instead; not API output. The
// options, EVs and equity are the fixture's; only the choice and the loss follow from it.
/** attempt_raise_preflop (puzzle_preflop_bb_facing_open) with the call chosen. */
export function bbCallAttempt(): AttemptResult {
  const base = attemptFixture('raise_preflop')
  const call = base.options.find((o) => o.kind === 'call')
  const best = base.options.find((o) => o.is_best)
  if (!call || !best) throw new Error('attempt_raise_preflop has a call and a best option')
  const lossChips = best.ev_chips - call.ev_chips
  return {
    ...base,
    answer: {
      ...base.answer,
      action: { ...base.answer.action, kind: 'call', to: 5 },
      chosen_label: call.label,
      option_index: base.options.indexOf(call),
      intent: null,
    },
    grade: {
      ...base.grade,
      chosen_label: call.label,
      ev_loss_chips: lossChips,
      ev_loss_bb: lossChips / 2,
      verdict: 'mistake',
      intent: null,
      intent_flag: null,
      intent_truth: null,
      bluff_check: null,
    },
    options: base.options.map((o) => ({ ...o, is_chosen: o === call })),
  }
}

// SYNTHETIC: a call whose equity and pot odds show the same number (21.4%), for the Maths tab's
// tie wording. Derived by hand from attempt_call (puzzle_facing_postflop_raise): only fold and
// call are kept, the equity is set just above or just below the pot odds, and the call's EV is
// the solver's call formula at that equity, so every line on screen reproduces. Not API output.
/** attempt_call cut to fold and call, with `equity` against the puzzle's 21.4% pot odds. */
export function potOddsTieAttempt(equity: number): AttemptResult {
  const base = attemptFixture('call')
  const pot = puzzleFixture('facing_postflop_raise').pot
  const kept = base.options.filter((o) => o.kind === 'fold' || o.kind === 'call')
  const callEv = (o: (typeof kept)[number]) => equity * (pot + o.put) - o.put
  const options = kept.map((o) =>
    o.kind === 'call' ? { ...o, ev_chips: callEv(o), ev_bb: callEv(o) / 2 } : o,
  )
  const call = options.find((o) => o.kind === 'call')
  if (!call) throw new Error('attempt_call has a call')
  const best = call.ev_chips >= 0 ? call : options.find((o) => o.kind === 'fold')
  if (!best) throw new Error('attempt_call has a fold')
  const lossChips = best.ev_chips - call.ev_chips
  return {
    ...base,
    grade: {
      ...base.grade,
      equity,
      best_label: best.label,
      ev_loss_chips: lossChips,
      ev_loss_bb: lossChips / 2,
      verdict: lossChips === 0 ? 'best' : 'fine',
    },
    options: options.map((o) => ({ ...o, is_best: o === best, is_chosen: o === call })),
  }
}
