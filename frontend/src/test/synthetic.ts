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
