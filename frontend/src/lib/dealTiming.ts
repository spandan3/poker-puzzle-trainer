// Deal timings (ms), shared by the Puzzles and Play pages. On a new hand everything lands within
// 600 ms; input is never blocked.
export const HOLE_DEAL_MS = [0, 120] // Hero's cards; Villain's are 60 ms after each
export const HOLE_STAGGER_MS = 60
export const BOARD_DEAL_BASE_MS = 80
export const BOARD_DEAL_STAGGER_MS = 40
// On reveal the run-out comes after Villain's cards turn over.
export const RUNOUT_BASE_MS = 380 // --duration-flip
export const RUNOUT_STAGGER_MS = 120
