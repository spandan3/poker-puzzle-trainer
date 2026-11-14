# M9 competence sign-off report

Date: 2026-11-13. Branch `m9-signoff`. This report asks you to approve the four Villain profiles (TAG, LAG, Tight, Sticky) as "competent enough" for Phase 1. Section 9 lists what to look at and what is still imperfect.

All numbers come from scripts run on this branch (`uv run competence --seeds 0-5`, `uv run puzzle-sample`, a short inline run for the category table, the M9 solver for the pre-flop table). Nothing here comes from a language model. Amounts are in big blinds (bb) unless a line is quoted from a hand history, where bets are in chips (2 chips = 1 bb).

## 1. Two terms used below

- **MDF (minimum defence frequency).** If someone bets, the opponent must keep playing (call or raise) with at least a certain share of hands, or the bettor can bluff with any two cards and profit. That share is `pot before the bet / (pot before the bet + bet)`. Facing a bet of the pot's size it is 50%; facing a bet of half the pot it is 67%; facing a bet of 2.5 times the pot it is 29%. A defence ratio of 1.00 means "defends exactly at MDF". A person is not obliged to defend at exactly MDF: a player who folds more than MDF is exploitable by bluffs, one who folds less is exploitable by thin value bets. The checks use a band around 1.00, wider for the loose profile and lower for the tight one.
- **Realisation.** Equity (your share of the pot if all the cards were dealt out) is not what you actually collect. Out of position you act first on each later street, get pushed off hands, and can't always see a cheap card, so you collect less than your equity. In position you collect about all of it. The grader now models this with a factor applied before the river: in position 100%; out of position 80% pre-flop, 88% on the flop, 94% on the turn; the river and all-in pots 100%. The grader shows the factor in the Maths tab whenever it is below 100%.

## 2. What was tuned, and why

**The grader (not a Villain profile).** Two changes, both described in the plan:

1. **Position-aware realisation** (above). Before it, a big-blind hero that called or 3-bet got full credit for its equity even out of position, which made small 3-bets with trash hands (9h5s, 7d5s, 6c4h and similar) look 0.4 to 0.9 bb better than calling. That taught a wrong lesson.
2. **A custom bet size that beats the best listed option is graded as best** (a tie keeps the listed option). Before, it could score "worse than best" while having the higher EV.

**Villain profiles** (each profile file went from version 4 to 5; `categories.json` untouched; no competence band was widened):

1. **Defence against overbets (1.5 to 2.5 times the pot).** The baseline had Villain defending a 2.5-times-pot bet at 1.4 to 2.2 times the MDF it needs, because it folded its medium hands and weak draws too rarely when the bet was huge. A medium hand (a bluff catcher) now gives up against overbets as the price gets worse, so the whole range defends close to MDF at 1.5, 2 and 2.5 times the pot, in every profile. Strong hands keep a floor: they continue at least 75% of the time even against a 20-times-pot jam, and the nuts never fold.
2. **River raises.** Villain used to raise river bets with medium hands, where a raise only folds out worse hands and is called by better ones (the `raise_dominated` check, 0.26 to 0.34 against a limit of 0.10). All four profiles now carry a river-only table (`river_facing`) that raises with the nuts, a few air bluffs and very little else. The side effect is that river raises are now rare (see section 9).
3. **Fewer thin river bets with medium hands** (TAG and Sticky), because by the check's definition about 45% of those bets were "bluffs", which pushed the bluff share over its limit on one seed.
4. **Tight's shared defence rows were tightened** (WEAK, MEDIUM and the draws fold more), first because its turn defence had touched 1.013 against an upper limit of 1.00, then again so its averaged overbet defence stayed under 1.00. Some of its river bluff frequencies were raised to bring its river bluff share back into band.
5. **Sticky** folds slightly less with weak and medium hands (so it stays at or above its floor against the biggest bets).
6. **Pre-flop defence of the button against a 3-bet.** TAG, LAG and Tight called too rarely against a 3-bet, which let a hero 3-bet junk from the big blind and show a profit. Their button calling ranges were widened until a trash 3-bet gains no more than 0.25 bb over the best of calling or folding (the new test `test_bb_trash_3bet_not_best`, run for every profile). Tight also calls a jam with more hands now (JJ+, TT half the time, AK, AQs), because after the widening a jam with trash had become a 0.52 bb winner against it.

## 3. Competence report: before and after

`uv run competence --profile all --hands 400 --seeds 0-5`: 400 hands for each of seeds 0 to 5, all four profiles, 13 pass/fail checks (the original 10 plus `defence_overbet`, `raise_dominated`, `preflop_defence_3bet`) and 3 information-only values.

- **Before** (profiles before tuning, new checks included): 261 of 312 check-seeds pass (51 failures). The failures are `defence_overbet` and `raise_dominated` for every profile on every seed (48 of the 51), plus three older ones: TAG `bluff_share_33` on seed 2 (0.283 against a 0.28 limit), Sticky `bluff_share_33` on seed 2 (just over its 0.26 limit; the plan recorded 0.260 > 0.26, and the tables below round to three places) and Tight `defence_turn` on seed 5 (1.013 against 1.00). The original baseline, before any M9 change, had only those three failures on the ten original checks.
- **After:** 312 of 312 pass. No band was changed.

What each new check measures:

- `defence_overbet`: how much of its range Villain continues with (call plus raise) against Hero overbets of 1.5 to 2.5 times the pot (the check probes 1.5, 2 and 2.5 times), divided by the MDF for that bet. Averaged over every decision point on every street.
- `raise_dominated`: on the river, the share of Villain's raises that are made with a medium-or-better hand that has under 40% equity against the hands that would continue against the raise. A raise like that loses to everything that calls it. Limit 10%.
- `preflop_defence_3bet`: the share of the button's opening range that continues (calls or jams) against a 3-bet to 3 times the open (to 15 chips, 7.5 bb), divided by MDF 0.50. Band 0.90 to 1.40 for every profile. The argument for going above 1.0: the button has 5 chips in and must put in 10 more to win a final pot of 30, so a call needs 10/30 = 33.3% raw equity, well under the 50% that MDF suggests, and the grader credits the button, who is in position, with 100% of its equity while the 3-bettor (the big blind, out of position) is credited 80% pre-flop. Hands with 33% or more equity are profitable calls, so continuing above MDF is correct. The lower bound, 0.90, keeps the big blind's 3-bet bluffs from printing money; the trash 3-bet gate in section 6 is the direct test of that. The upper bound, 1.40, was set by controller ruling during M9 as a sanity ceiling, not derived from theory (see section 9 for Sticky, which sits at 1.375).

Values are the minimum and maximum over the six seeds. "Seeds passing" counts seeds out of 6. `river_stab` and `air_continue_max` are information only.

**TAG**

| Check | Band | Before (min–max, seeds passing) | After (min–max, seeds passing) |
|---|---|---|---|
| bluff_share_33 | [0.12, 0.28] | 0.223–0.283, 5/6 | 0.214–0.262, 6/6 |
| bluff_share_75 | [0.22, 0.38] | 0.260–0.307, 6/6 | 0.259–0.323, 6/6 |
| defence_flop | [0.85, 1.15] | 0.914–0.927, 6/6 | 0.909–0.930, 6/6 |
| defence_turn | [0.85, 1.15] | 1.031–1.073, 6/6 | 1.042–1.072, 6/6 |
| defence_river | [0.85, 1.15] | 0.896–0.950, 6/6 | 0.904–0.952, 6/6 |
| nuts_fold_max | [0.00, 0.00] | 0.000–0.000, 6/6 | 0.000–0.000, 6/6 |
| strong_fold_max | [0.00, 0.10] | 0.041–0.051, 6/6 | 0.040–0.051, 6/6 |
| air_call_max | [0.00, 0.10] | 0.036–0.079, 6/6 | 0.033–0.041, 6/6 |
| thin_value_dominated | [0.00, 0.10] | 0.060–0.077, 6/6 | 0.058–0.074, 6/6 |
| cbet_flop | [0.45, 0.70] | 0.563–0.576, 6/6 | 0.566–0.578, 6/6 |
| defence_overbet | [0.85, 1.15] | 1.633–1.703, 0/6 | 1.045–1.083, 6/6 |
| raise_dominated | [0.00, 0.10] | 0.277–0.316, 0/6 | 0.062–0.086, 6/6 |
| preflop_defence_3bet | [0.90, 1.40] | 1.137–1.137, 6/6 | 1.280–1.280, 6/6 |
| river_stab | (info) | 0.319–0.404 | 0.288–0.337 |
| air_continue_max | (info) | 0.086–0.086 | 0.046–0.046 |
| preflop_defence_open | (info) | 1.386–1.386 | 1.386–1.386 |

**LAG**

| Check | Band | Before (min–max, seeds passing) | After (min–max, seeds passing) |
|---|---|---|---|
| bluff_share_33 | [0.16, 0.32] | 0.248–0.296, 6/6 | 0.249–0.315, 6/6 |
| bluff_share_75 | [0.26, 0.42] | 0.328–0.381, 6/6 | 0.321–0.380, 6/6 |
| defence_flop | [0.85, 1.20] | 0.934–0.963, 6/6 | 0.935–0.957, 6/6 |
| defence_turn | [0.85, 1.20] | 1.068–1.102, 6/6 | 1.074–1.100, 6/6 |
| defence_river | [0.85, 1.20] | 0.922–0.963, 6/6 | 0.905–0.952, 6/6 |
| nuts_fold_max | [0.00, 0.00] | 0.000–0.000, 6/6 | 0.000–0.000, 6/6 |
| strong_fold_max | [0.00, 0.10] | 0.028–0.034, 6/6 | 0.028–0.034, 6/6 |
| air_call_max | [0.00, 0.10] | 0.049–0.084, 6/6 | 0.029–0.053, 6/6 |
| thin_value_dominated | [0.00, 0.10] | 0.052–0.071, 6/6 | 0.062–0.082, 6/6 |
| cbet_flop | [0.45, 0.70] | 0.631–0.638, 6/6 | 0.632–0.641, 6/6 |
| defence_overbet | [0.85, 1.20] | 1.728–1.786, 0/6 | 1.043–1.067, 6/6 |
| raise_dominated | [0.00, 0.10] | 0.293–0.342, 0/6 | 0.061–0.094, 6/6 |
| preflop_defence_3bet | [0.90, 1.40] | 1.168–1.168, 6/6 | 1.283–1.283, 6/6 |
| river_stab | (info) | 0.338–0.396 | 0.350–0.399 |
| air_continue_max | (info) | 0.086–0.086 | 0.053–0.054 |
| preflop_defence_open | (info) | 1.465–1.465 | 1.465–1.465 |

**Tight**

| Check | Band | Before (min–max, seeds passing) | After (min–max, seeds passing) |
|---|---|---|---|
| bluff_share_33 | [0.05, 0.22] | 0.158–0.203, 6/6 | 0.159–0.202, 6/6 |
| bluff_share_75 | [0.15, 0.32] | 0.165–0.236, 6/6 | 0.166–0.248, 6/6 |
| defence_flop | [0.70, 1.00] | 0.820–0.855, 6/6 | 0.739–0.768, 6/6 |
| defence_turn | [0.70, 1.00] | 0.929–1.013, 5/6 | 0.860–0.904, 6/6 |
| defence_river | [0.70, 1.00] | 0.852–0.890, 6/6 | 0.803–0.908, 6/6 |
| nuts_fold_max | [0.00, 0.00] | 0.000–0.000, 6/6 | 0.000–0.000, 6/6 |
| strong_fold_max | [0.00, 0.10] | 0.066–0.071, 6/6 | 0.069–0.085, 6/6 |
| air_call_max | [0.00, 0.10] | 0.020–0.036, 6/6 | 0.011–0.014, 6/6 |
| thin_value_dominated | [0.00, 0.10] | 0.023–0.056, 6/6 | 0.031–0.066, 6/6 |
| cbet_flop | [0.45, 0.70] | 0.499–0.513, 6/6 | 0.490–0.522, 6/6 |
| defence_overbet | [0.70, 1.00] | 1.424–1.503, 0/6 | 0.950–0.990, 6/6 |
| raise_dominated | [0.00, 0.10] | 0.258–0.304, 0/6 | 0.033–0.074, 6/6 |
| preflop_defence_3bet | [0.90, 1.40] | 0.925–0.925, 6/6 | 1.283–1.283, 6/6 |
| river_stab | (info) | 0.228–0.287 | 0.248–0.306 |
| air_continue_max | (info) | 0.045–0.046 | 0.017–0.017 |
| preflop_defence_open | (info) | 1.016–1.016 | 1.016–1.016 |

**Sticky**

| Check | Band | Before (min–max, seeds passing) | After (min–max, seeds passing) |
|---|---|---|---|
| bluff_share_33 | [0.10, 0.26] | 0.211–0.260, 5/6 | 0.202–0.248, 6/6 |
| bluff_share_75 | [0.20, 0.36] | 0.231–0.292, 6/6 | 0.234–0.309, 6/6 |
| defence_flop | [1.00, 1.35] | 1.045–1.071, 6/6 | 1.047–1.084, 6/6 |
| defence_turn | [1.00, 1.35] | 1.177–1.202, 6/6 | 1.198–1.219, 6/6 |
| defence_river | [1.00, 1.35] | 1.047–1.090, 6/6 | 1.089–1.111, 6/6 |
| nuts_fold_max | [0.00, 0.00] | 0.000–0.000, 6/6 | 0.000–0.000, 6/6 |
| strong_fold_max | [0.00, 0.10] | 0.028–0.034, 6/6 | 0.028–0.034, 6/6 |
| air_call_max | [0.00, 0.10] | 0.057–0.071, 6/6 | 0.056–0.057, 6/6 |
| thin_value_dominated | [0.00, 0.10] | 0.049–0.078, 6/6 | 0.059–0.087, 6/6 |
| cbet_flop | [0.45, 0.70] | 0.536–0.552, 6/6 | 0.546–0.554, 6/6 |
| defence_overbet | [1.00, 1.35] | 2.102–2.162, 0/6 | 1.194–1.225, 6/6 |
| raise_dominated | [0.00, 0.10] | 0.256–0.303, 0/6 | 0.069–0.093, 6/6 |
| preflop_defence_3bet | [0.90, 1.40] | 1.375–1.375, 6/6 | 1.375–1.375, 6/6 |
| river_stab | (info) | 0.319–0.349 | 0.266–0.309 |
| air_continue_max | (info) | 0.086–0.086 | 0.069–0.070 |
| preflop_defence_open | (info) | 1.544–1.544 | 1.544–1.544 |


### Why the big blind defends more than MDF (`preflop_defence_open`, information only)

Against a 2.5-times open, the MDF for the big blind is 4/7, about 0.571. The profiles defend 1.386 times that (TAG), 1.465 (LAG), 1.016 (Tight) and 1.544 (Sticky), unchanged by M9. That is correct play, and it is deliberately not a pass/fail check. The big blind has already posted 1 bb, and it closes the action. A call costs 1.5 bb to win a pot of 3.5 bb, so the call needs only 30% equity (1.5 out of the 5 bb in the pot after the call), before allowing for the position penalty. A range that defended only at MDF would be folding hands that are clear calls. Shrinking this number would also make the Hero's own button steals grade too well, as Villain would be folding to them too often. MDF is the point where a bluff with *any* two cards breaks even; it is a floor against being exploited, not a target when the price is this good.

## 4. What Villain does against a 2.5-times-pot bet, by hand category

A dry flop (K-7-2 in three suits), the big blind facing a bet of 25 chips into a pot of 10 (2.5 times the pot, MDF 0.29). Each cell is the share of that category's hands that call or raise. This is the test spot `test_big_bet_continue_by_category`, and the "after" row is a fresh run on this branch.

| Profile | | AIR | WEAK | MEDIUM | STRONG | NUTS | STRONG against a 20-times-pot jam |
|---|---|---|---|---|---|---|---|
| TAG | before | 0.007 | 0.248 | 0.684 | 0.931 | 1 | 0.653 |
| TAG | after | 0.014 | 0.105 | 0.294 | 0.845 | 1 | 0.750 |
| LAG | before | 0.007 | 0.304 | 0.742 | 0.954 | 1 | 0.754 |
| LAG | after | 0.014 | 0.118 | 0.308 | 0.861 | 1 | 0.750 |
| Tight | before | 0.002 | 0.070 | 0.560 | 0.887 | 1 | 0.488 |
| Tight | after | 0.007 | 0.037 | 0.227 | 0.814 | 1 | 0.750 |
| Sticky | before | 0.007 | 0.560 | 0.844 | 0.954 | 1 | 0.754 |
| Sticky | after | 0.014 | 0.179 | 0.346 | 0.861 | 1 | 0.750 |

(AIR: no pair and no draw. WEAK: a small pair or a weak draw. MEDIUM: the bluff catchers, middle and top-pair type hands. STRONG: strong made hands. NUTS: the best hands. The K-7-2 flop has no draws, so the draw categories are not shown. AIR continues only about 1% of the time before and after; the final curve gave it a slightly higher share than the first tuning pass.)

How to read it: against a bet of 2.5 times the pot only 29% of the range needs to continue, and the strongest 29% of a typical range is mostly STRONG and NUTS hands. So a profile that folds about 70% of its medium hands is doing the sums, not being weak. The old rows had TAG calling with 68% of its medium hands, well over what that price needs.

How defence varies with bet size, as a ratio to MDF, on the five test flops (K-7-2 rainbow, A-8-5, Q-8-3 two-tone, T-9-4 two-tone, J-6-2 two-tone), the mean of the five:

| Profile (band) | pot | 1.25x | 1.5x | 2x | 2.5x | 4x |
|---|---|---|---|---|---|---|
| TAG (0.85 to 1.15) | 1.03 | 0.99 | 0.95 | 0.91 | 0.89 | 0.92 |
| LAG (0.85 to 1.20) | 1.03 | 0.99 | 0.94 | 0.89 | 0.85 | 0.85 |
| Tight (0.70 to 1.00) | 0.81 | 0.81 | 0.82 | 0.84 | 0.86 | 1.00 |
| Sticky (1.00 to 1.35) | 1.26 | 1.19 | 1.12 | 1.05 | 1.01 | 0.99 |

After the first tuning pass, before the final curve, there was a dip: TAG defended only 0.66 of MDF at 2 times the pot on K-7-2 (it is 0.85 now). A pure-air bluff wins the pot whenever Villain folds, so its value is (1 minus the defence ratio) times the pot: about +0.34 of the pot then, and +0.15 now. (Before any M9 change the problem was the opposite: defence against overbets was about 1.6 times MDF, with no dip.)

## 5. Pre-flop defence, before and after

| | Big blind against a 2.5-times open, divided by MDF 4/7 (info) | Button against a 3-bet, divided by MDF 0.50 (band 0.90 to 1.40) |
|---|---|---|
| TAG | 1.386 to 1.386 | 1.137 to **1.280** (fold share 43.1% to 36.0%) |
| LAG | 1.465 to 1.465 | 1.168 to **1.283** (fold share 41.6% to 35.9%) |
| Tight | 1.016 to 1.016 | 0.925 to **1.283** (fold share 53.8% to 35.9%) |
| Sticky | 1.544 to 1.544 | 1.375 to 1.375 (unchanged) |

"Fold share" is the part of the button's opening range that folds to the 3-bet.

## 6. The big blind's small 3-bets: best option before and after

The spots: Hero in the big blind facing the button's open to 2.5 bb, holding one of eight weak hands. Villain's range is the profile's real opening range minus the cards Hero holds; 40,000 equity samples per spot. "Gap" is the best raise (2.5x, 3x or all-in) minus the better of calling and folding, in bb. The test gates, for each profile, the hands with under 40% equity against that profile's opening range: for them the gap must be at most 0.25 bb, and at least three hands per profile must be gated. The equity column below is against TAG's range. Jc3d is the only hand whose gating differs: 0.396 against TAG, 0.362 against Tight and 0.395 against Sticky (gated), but 0.413 against LAG's wider range (reported only).

**TAG, step by step** (each cell in bb):

| Hand | Equity | Call (before, no realisation) | Raise 2.5x (before) | Gap (before) | Gap, realisation only | Call (after) | Raise 2.5x (after) | Gap (after) |
|---|---|---|---|---|---|---|---|---|
| 9h5s (gated) | 0.379 | +0.39 | +0.90 | +0.51 | +0.44 | +0.01 | +0.13 | **+0.11** |
| 7d5s (gated) | 0.370 | +0.35 | +0.84 | +0.49 | +0.39 | -0.02 | +0.05 | **+0.05** |
| 6c4h (gated) | 0.355 | +0.27 | +0.82 | +0.55 | +0.37 | -0.08 | +0.02 | **+0.02** |
| Jc3d (0.396 against TAG: gated) | 0.396 | +0.48 | +1.02 | +0.54 | +0.46 | +0.09 | +0.23 | **+0.14** |
| Qs2h | 0.412 | +0.56 | +1.10 | +0.54 | +0.46 | +0.15 | +0.30 | +0.16 |
| Qs3c | 0.422 | +0.61 | +1.18 | +0.57 | +0.49 | +0.19 | +0.39 | +0.20 |
| Jd6d | 0.444 | +0.72 | +1.29 | +0.57 | +0.49 | +0.28 | +0.48 | +0.20 |
| Jc5h | 0.410 | +0.55 | +1.06 | +0.51 | +0.44 | +0.14 | +0.29 | +0.15 |

"Before" is main before M9 (config version 3, no realisation, TAG profile version 4). "Realisation only" is after Task 4: the factor alone shrank the gap by only 0.07 to 0.18 bb, because most of the gain comes from the button folding 43% of its range to any 3-bet, not from how much equity the call realises. The BTN-defence widening (section 5) did the rest. The 2.5x raise is still the top option for all eight hands after tuning, but by 0.02 to 0.20 bb, which is a small bluff with some fold equity.

**All four profiles, gap after tuning** (bb; "before" is the state after realisation and before the BTN-defence widening; TAG and Sticky did not change in the last step):

| Hand | TAG | LAG before to after | Tight before to after | Sticky |
|---|---|---|---|---|
| 9h5s (gated) | +0.11 | +0.37 to +0.06 | +0.88 to -0.04 | -0.15 |
| 7d5s (gated) | +0.05 | +0.37 to +0.08 | +0.90 to -0.01 | -0.20 |
| 6c4h (gated) | +0.02 | +0.29 to +0.19 | +0.86 to -0.07 | -0.27 |
| Jc3d (gated for TAG 0.396, Tight 0.362, Sticky 0.395; reported only for LAG, 0.413) | +0.14 | +0.37 to +0.13 | +0.95 to +0.08 | -0.07 |
| Qs2h | +0.16 | +0.34 to +0.14 | +0.97 to +0.13 | -0.09 |
| Qs3c | +0.20 | +0.36 to +0.16 | +0.95 to +0.13 | -0.07 |
| Jd6d | +0.20 | +0.35 to +0.19 | +1.00 to +0.22 | +0.02 |
| Jc5h | +0.15 | +0.32 to +0.09 | +0.99 to +0.13 | -0.07 |

A negative gap means calling or folding beats every raise. Sticky never needed changing: it already calls 3-bets with 69% of its opening range. The hands at 40 to 45% equity (the Q-x and J-x hands) are still small positives for TAG, LAG and Tight, +0.09 to +0.22 bb. I think these are plausible: a 3-bet bluff that has some equity and some fold equity is a real play. See section 9.

## 7. Twelve sample puzzles

Generated with `uv run puzzle-sample` (three per street, all four profiles). In each, "equity" is Hero's chance to win against Villain's range at that moment, "range" is the weighted number of hands that range contains, and EV is in bb with folding counted as zero. Bets shown "(30% pot)" are fractions of the pot. When Hero faces a bet, a raise "2.5x" is a raise to 2.5 times that bet; when Hero opens pre-flop (samples 1 and 2), "raise 2.5x" is an open to 2.5 bb. Each sample can be reproduced from `backend/` with the command on its heading line (the samples without `--profile` use the profile the seed picks). Hero is always dealt the cards below; Villain's cards are not used in grading.

### Pre-flop

Command: `uv run puzzle-sample --n 1 --street preflop --seed 10`

**1. TAG, seed 10. Hero on the button, Ad Kh, first to act.** Equity 65.2% against a random hand (Villain's range is every hand). The grader's options: fold 0.00, raise 2.5x +1.38, raise 3x +1.51 (best), all-in +1.50. Ace-king is a premium hand, so raising is obviously right. The model has the 3x raise a hair ahead of the all-in. That looks sensible: the three raises are close, and a jam isn't needed because the hand plays well after the flop.

Command: `uv run puzzle-sample --n 1 --street preflop --seed 11`

**2. Sticky, seed 11. Hero on the button, 7d 2s, first to act.** Equity 34.4%. Fold 0.00 (best), raise 2.5x -0.22, raise 3x -0.38, all-in -1.77. Seven-deuce offsuit is the worst starting hand. Against a profile that calls too much, a steal doesn't work, so folding is best. Sensible.

Command: `uv run puzzle-sample --n 1 --street preflop --seed 21 --profile lag`

**3. LAG, seed 21. Hero in the big blind with Ah Th, facing the button's open to 2.5 bb.** The LAG opens wide (1,015 combos left), and the hand has 63.7% equity against that range. The price to call is 30%. Fold 0.00, call +1.05, raise 2.5x +1.82 (best), raise 3x +1.79, all-in +1.44. A suited ace with a ten that is a big favourite against a wide range: 3-betting for value beats calling by 0.77 bb. Sensible, and it's the sort of spot where Villain's looseness is exactly what Hero should punish.

### Flop

Command: `uv run puzzle-sample --n 1 --street flop --seed 10`

**4. TAG, seed 10. Hero on the button with Ad Kh; Villain (big blind) called the open, then bet 1.5 bb (30% pot) on Qh Jh 3h.** Hero has a king-high flush draw (Kh with Qh Jh 3h on the board), a gutshot to broadway (any ten), and two overcards (A and K): 68.3% equity against a range of 63 hands. Pot odds are 18.8%. Fold 0.00, call +3.96, raise 2.5x +5.01, raise 3x +5.13, all-in +5.72 (best). Hero has a king-high flush draw (the ace of hearts is still live, so it is not the nut draw), a gutshot to broadway, and two overcards (A and K). That is a strong draw against a range that is betting into Hero, so raising is natural. A jam at 100 bb deep looks big, but the grader's numbers have it ahead of the smaller raises, and the grading is against Villain's range, not one result. It is a high-variance play, so it is the spot I would most like you to sanity-check.

Command: `uv run puzzle-sample --n 1 --street flop --seed 11`

**5. Sticky, seed 11. Hero in the big blind with Js Th on Td Ah 9c; Villain (button) opened and Hero called; Hero acts first.** Hero has a pair of tens (with a jack kicker) and some straight possibilities that need two more cards: 68.2% equity against 737 hands. Check +3.00, bet 33% +3.33, bet 50% +3.39, bet 75% +3.46, bet 100% +3.49 (best), all-in -5.20. A strong hand against a profile that calls too much: bet for value, and the bigger bets are a touch better because the caller doesn't fold. The difference between 33% and 100% is only 0.16 bb. Sensible.

Command: `uv run puzzle-sample --n 1 --street flop --seed 21 --profile tight`

**6. Tight, seed 21. Hero in the big blind with Kc Jh on 6s Th 9d; Villain (button) opened, Hero called; Hero acts first.** Hero has a gutshot (a queen), two overcards, 43.8% equity against 542 hands. Check +1.93, bet 33% +2.72 (best), bet 50% +2.59, bet 75% +2.38, bet 100% +2.24, all-in -5.01. A small bet with draws and overcards against a Tight opponent that folds a lot: it takes the pot often, and when called Hero still has outs. (Against the LAG profile in the same spot, the best play is also a 33% bet, +2.54, with 51% equity.) Sensible.

### Turn

Command: `uv run puzzle-sample --n 1 --street turn --seed 11`

**7. Sticky, seed 11. Hero in the big blind with Js Th on Td Ah 9c 4d. Villain (button) opened; Hero called; Hero checked the flop, Villain bet 4 bb (80% pot), Hero called; Hero acts first on the turn.** Equity is 42.5% against 139 hands. Villain opened, then bet the flop for 80% of the pot after Hero checked, so it is a narrowed range that has shown strength. Check +5.19 (best), bet 33% +3.84, bet 50% +3.12, bet 75% +1.93, bet 100% +0.97, all-in -23.56. Hero has a pair of tens but is behind the range that bet the flop. A bet into a range that has been betting gets called by hands that are better, and the model has Sticky calling often, so checking is better and the loss grows quickly with the size. Sensible.

Command: `uv run puzzle-sample --n 1 --street turn --seed 21 --profile lag`

**8. LAG, seed 21. Hero in the big blind with Kc Jh on 6s Th 9d 5d; flop checked through, Hero checked the turn, Villain bet 1.5 bb (30% pot).** Equity 41.3% against 111 hands, pot odds 18.8%. Fold 0.00, call +1.60, raise 2.5x +3.24 (best), raise 3x +3.21, all-in +1.13. Same gutshot-and-overcards hand as sample 6. A raise beats a call by 1.64 bb in the grader's numbers: Hero has outs when called and the model has the LAG fold often enough. A call is also clearly profitable (+1.60), so a player who just calls still makes money. Plausible, but the size of the gap depends on how often the model folds to a raise, so I would not argue if you thought it was too high.

Command: `uv run puzzle-sample --n 1 --street turn --seed 20 --profile tight`

**9. Tight, seed 20. Hero on the button with Qh Kh on 8d Ts Ah 9h; Villain (big blind) called the open, then the flop was checked through, and Villain checked the turn.** Hero has four hearts (Qh Kh with Ah 9h on the board), and any heart would be the nut flush because the ace of hearts is on the board. A jack makes a straight: 49.1% equity against 402 hands. Check +2.46, bet 33% +2.85 (best), bet 50% +2.76, bet 75% +2.60, bet 100% +2.49, all-in -7.27. A cheap semi-bluff with a big draw into a checking range. Sensible; larger bets lose a little because a Tight Villain's calls are strong.

### River

Command: `uv run puzzle-sample --n 1 --street river --seed 20 --profile tight`

**10. Tight, seed 20. Hero in the big blind with 5h 6d on 6s Ah 2c 8s 8c; the hand was checked down to the river, Hero checked, Villain (button) bets 4 bb (80% pot).** Hero technically has two pair, eights and sixes, but the eights are on the board and Villain shares them, so in practice Hero has one pair of sixes, and any Villain hand with its own pair (an ace, for example) beats it. Equity 33.9% against only 16 hands (Tight bets the river with very few hands) and pot odds of 30.8%. Fold 0.00, call +0.41 (best), raise 2.5x -1.18, raise 3x -2.02, all-in -43.03. That is why it is a thin, close call: Hero's equity beats the price by about 3 points. Sensible, and a good example of a spot where the numbers are fine but the margin is small.

Command: `uv run puzzle-sample --n 1 --street river --seed 20 --profile lag`

**11. LAG, seed 20. Hero in the big blind with 7c 5c on Ks Ah 7h 4d 9c; Hero called a flop bet of 4 bb and a turn bet of 4.5 bb, then acts first on the river.** A pair of sevens with 34.6% equity against 83 hands. Check +6.42 (best), bet 33% +4.46, bet 50% +2.56, bet 75% -0.28, bet 100% -3.03, all-in -14.97. Villain bet twice; a pair of sevens is a showdown-value hand and betting it only gets called by better hands. Sensible.

Command: `uv run puzzle-sample --n 1 --street river --seed 21 --profile lag`

**12. LAG, seed 21. Hero in the big blind with 9h 8s on Kc 5d 6c 5s Ad; Hero bet the flop (1.5 bb) and the turn (2.5 bb) and was called both times; Hero acts first on the river.** Hero missed a straight draw: nine-high, 5.2% equity against 323 hands. Check +0.53 (best), bet 33% -0.32, bet 50% -1.52, bet 75% -3.50, bet 100% -5.10, all-in -13.99. Giving up is right: Villain called two bets and an ace fell. Sensible.

My read on the twelve: none looks wrong. Samples 4, 8 and 10 are the ones I'd want you to look at, because the model recommends an aggressive jam (4), a raise where calling also wins (8), or a call by a thin margin (10).

## 8. Explanation check with a real model

`uv run explain-check --n 12` against a scratch copy of the app running `llama3.2:3b` through Ollama on a laptop RTX 3050 Ti, with `PPT_LLM_TIMEOUT=180`, the model already loaded. It creates one puzzle per row (streets in turn, and the first, last and middle option in turn), answers it, then asks for the explanation and records whether the model's text was kept (`llm`) or replaced by the fixed template (`template`, with the reason).

```
street   verdict  source    fallback      expl. s
preflop  best     llm       -                 8.8
flop     best     template  guardrail         3.5
turn     fine     template  guardrail         5.1
river    mistake  template  guardrail         5.8
preflop  best     llm       -                 6.3
flop     mistake  llm       -                 4.4
turn     blunder  llm       -                 5.2
river    blunder  llm       -                 4.3
preflop  best     llm       -                 5.4
flop     best     template  guardrail         4.5
turn     mistake  template  guardrail         4.5
river    best     llm       -                 4.2

total: 12
llm: 7
error: 0
guardrail: 5
```

- **Kept:** 7 of 12. **Replaced by the template because the guardrail rejected the model's text:** 5 of 12. **Errors or timeouts:** 0.
- The guardrail throws the model's text away if it uses a number the trainer did not compute, or (new in M9) names the plays in the wrong order. The pre-flop explanations were all kept (3 of 3); after the flop, 4 of 9 were kept. The rejected ones show a user a correct fixed explanation instead, so a rejection costs wording, never correctness.
- **Speed:** 3.5 to 8.8 seconds for each explanation once the model is loaded. The first call after loading the model can take over a minute on this machine, so the timeout should not be left at its 60 s default on a laptop.
- The plan's rule was "if most are rejected, loosen the prompt or the claim rules". 5 of 12 is not most, so nothing was changed in M9.
- Open item: the API reports only that the guardrail rejected the text, not whether a number or a claim failed, so I cannot split the five by reason.

## 9. What I want you to look at, and what is still imperfect

Please decide: **are the four profiles acceptable as the Phase 1 opponents?** If yes, approve the PR. The things I'd weigh:

1. **The big blind defends well above MDF pre-flop (1.39, 1.47, 1.02, 1.54).** I argue (section 3) that this is correct and have kept it as information only. If you disagree, the lever is the `bb_call` and `bb_threebet` ranges in each profile.
2. **River raises are now rare, about 2% of Villain's range.** The STRONG category is broad (hand strength 0.80 and above), and about 29% of the river raises it makes would have under 40% equity against the hands that call. The only way to keep `raise_dominated` under 10% was to keep STRONG raises to 1.5 to 3.5%. A thinner category split (or blockers) would let Villain raise thin value properly. A future Villain item.
3. **LAG defence trends down past 2 times the pot.** The mean over five flops is 0.85 at 2.5x and 4x, at the floor of its band, and one flop (A-8-5) is 0.78 at 4x. Sticky on K-7-2 is 0.92 at 2.5x, under its 1.00 floor (the mean over flops is 1.01). A category-based policy cannot hold every flop inside a band 0.3 wide; the test allows 0.10 of slack per board and checks the mean exactly.
4. **Villain over-defends an uncapped button lead at one pot or less.** The curve up to pot size is unchanged from before M9, and this is the safe direction (Hero's bluffs lose more often than they should).
5. **Tight's river fold rates are slightly looser than its shared fold rows.** Cosmetic: its river WEAK/MEDIUM fold rates (72% / 24%) were written before the shared rows were tightened to 75% / 27%. All its checks pass.
6. **Q-x and J-x 3-bets from the big blind (40 to 45% equity) still come out +0.09 to +0.22 bb ahead of calling** against TAG, LAG and Tight. These hands have real equity and some fold equity, so I think this is plausible; the test only gates hands under 40%.
7. **Tight is nitty against overbets.** Against a 2.5-times-pot bet on a dry flop it continues with 3.7% of its WEAK hands and 22.7% of its MEDIUM hands (section 4). Its whole range still defends at 0.86 of MDF on average at 2.5x, because that range is mostly strong.
8. **Pre-flop responses ignore the 3-bet size**, so widening Tight's defence to pass the 3-bet gate also widened its calls against bigger 3-bets, and Tight now defends a 3-bet at the same 1.28 as TAG. The profile is less "tight" against 3-bets than its name suggests.
9. **Sticky's button defends a 3-bet at 1.375 times MDF, close to the 1.40 ceiling.** That ceiling is a ruling, not a derived number (section 3). Sticky was not changed, and its pre-flop answers ignore the 3-bet size, so it would not fold more to a huge 3-bet.
10. **Deferred, not part of M9:** per-profile behaviour notes in explanations, a settings page, leak rules that flag "fine" plays, board-texture and blocker work, pre-flop raise-size awareness, and modelling the Hero. They are listed in the M9 plan.

## 10. Reproducing this report

```
cd backend
uv run competence --profile all --hands 400 --seeds 0-5
uv run puzzle-sample --n 3 --street flop --seed 10
uv run pytest -m slow tests/puzzle/test_solve.py
```

The last command runs `test_bb_trash_3bet_not_best` for all four profiles (section 6). The explanation check needs a running app and Ollama (see the README).
