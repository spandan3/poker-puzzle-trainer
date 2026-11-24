# M12 heads-up baselines

Recorded 2026-11-24 on branch `m12-5max`, before any M12 engine change (Task 0).

Environment: code at commit `4613233` (the original heads-up engine, no M12 engine change). Python 3.13.18, numpy 2.5.4, Linux 6.18.44 x86_64 (glibc 2.39). The competence run takes about 2 minutes.

Deterministic: the command was run twice and the two outputs are byte-identical, and identical to the block below. Task 3 must match it exactly.

Pre-existing baseline FAIL rows (not regressions, and not to be fixed in M12):

- seed 0, `tight bluff_share_75` = 0.145, band [0.15, 0.32], 36 samples: FAIL.
- seed 0, `tight cbet_flop` = 0.515, band [0.45, 0.70], 25 samples: FAIL (insufficient samples).

These are the only two FAIL rows in the output (summary: `tight bluff_share_75` 1/2 and `tight cbet_flop` 1/2). Tuning `tight` belongs to M14 (profile tuning).

## Competence output

Command, from `backend/`: `uv run competence --profile all --hands 200 --seeds 0-1`

Task 3 must reproduce this output exactly.

```text
=== seed 0 ===
profile  check                    value  band            samples  result
------------------------------------------------------------------------
tag      bluff_share_33           0.230  [0.12, 0.28]         53  PASS
tag      bluff_share_75           0.297  [0.22, 0.38]         53  PASS
tag      defence_flop             0.926  [0.85, 1.15]        146  PASS
tag      defence_turn             1.017  [0.85, 1.15]         92  PASS
tag      defence_river            0.882  [0.85, 1.15]         65  PASS
tag      nuts_fold_max            0.000  [0.00, 0.00]        656  PASS
tag      strong_fold_max          0.040  [0.00, 0.10]        214  PASS
tag      air_call_max             0.033  [0.00, 0.10]        121  PASS
tag      thin_value_dominated     0.055  [0.00, 0.10]        106  PASS
tag      cbet_flop                0.565  [0.45, 0.70]         43  PASS
tag      defence_overbet          1.023  [0.85, 1.15]        639  PASS
tag      raise_dominated          0.066  [0.00, 0.10]         65  PASS
tag      preflop_defence_3bet     1.280  [0.90, 1.40]       1326  PASS
lag      bluff_share_33           0.251  [0.16, 0.32]         55  PASS
lag      bluff_share_75           0.338  [0.26, 0.42]         55  PASS
lag      defence_flop             0.937  [0.85, 1.20]        144  PASS
lag      defence_turn             1.081  [0.85, 1.20]        100  PASS
lag      defence_river            0.919  [0.85, 1.20]         58  PASS
lag      nuts_fold_max            0.000  [0.00, 0.00]        623  PASS
lag      strong_fold_max          0.027  [0.00, 0.10]        214  PASS
lag      air_call_max             0.027  [0.00, 0.10]        106  PASS
lag      thin_value_dominated     0.052  [0.00, 0.10]        110  PASS
lag      cbet_flop                0.631  [0.45, 0.70]         54  PASS
lag      defence_overbet          1.049  [0.85, 1.20]        636  PASS
lag      raise_dominated          0.068  [0.00, 0.10]         58  PASS
lag      preflop_defence_3bet     1.283  [0.90, 1.40]       1326  PASS
tight    bluff_share_33           0.134  [0.05, 0.22]         36  PASS
tight    bluff_share_75           0.145  [0.15, 0.32]         36  FAIL
tight    defence_flop             0.757  [0.70, 1.00]        105  PASS
tight    defence_turn             0.904  [0.70, 1.00]         71  PASS
tight    defence_river            0.956  [0.70, 1.00]         51  PASS
tight    nuts_fold_max            0.000  [0.00, 0.00]        450  PASS
tight    strong_fold_max          0.085  [0.00, 0.10]        142  PASS
tight    air_call_max             0.014  [0.00, 0.10]         75  PASS
tight    thin_value_dominated     0.026  [0.00, 0.10]         72  PASS
tight    cbet_flop                0.515  [0.45, 0.70]         25  FAIL (insufficient samples)
tight    defence_overbet          0.966  [0.70, 1.00]        415  PASS
tight    raise_dominated          0.031  [0.00, 0.10]         48  PASS
tight    preflop_defence_3bet     1.283  [0.90, 1.40]       1326  PASS
sticky   bluff_share_33           0.196  [0.10, 0.26]         64  PASS
sticky   bluff_share_75           0.253  [0.20, 0.36]         64  PASS
sticky   defence_flop             1.075  [1.00, 1.35]        160  PASS
sticky   defence_turn             1.192  [1.00, 1.35]        127  PASS
sticky   defence_river            1.120  [1.00, 1.35]         84  PASS
sticky   nuts_fold_max            0.000  [0.00, 0.00]        784  PASS
sticky   strong_fold_max          0.028  [0.00, 0.10]        239  PASS
sticky   air_call_max             0.056  [0.00, 0.10]        131  PASS
sticky   thin_value_dominated     0.050  [0.00, 0.10]        128  PASS
sticky   cbet_flop                0.545  [0.45, 0.70]         37  PASS
sticky   defence_overbet          1.220  [1.00, 1.35]        712  PASS
sticky   raise_dominated          0.093  [0.00, 0.10]         83  PASS
sticky   preflop_defence_3bet     1.375  [0.90, 1.40]       1326  PASS

info (not checks): river_stab = whole-range river stab bet frequency;
air_continue_max = AIR call+raise share facing river bets >= 75% pot (max);
preflop_defence_open = BB call+3-bet share of all combos vs a 2.5x open / MDF 4/7.
tag      river_stab=0.271  air_continue_max=0.046  preflop_defence_open=1.386
lag      river_stab=0.330  air_continue_max=0.053  preflop_defence_open=1.465
tight    river_stab=0.298  air_continue_max=0.017  preflop_defence_open=1.016
sticky   river_stab=0.285  air_continue_max=0.070  preflop_defence_open=1.544

=== seed 1 ===
profile  check                    value  band            samples  result
------------------------------------------------------------------------
tag      bluff_share_33           0.255  [0.12, 0.28]         54  PASS
tag      bluff_share_75           0.286  [0.22, 0.38]         54  PASS
tag      defence_flop             0.917  [0.85, 1.15]        140  PASS
tag      defence_turn             1.088  [0.85, 1.15]        105  PASS
tag      defence_river            0.963  [0.85, 1.15]         54  PASS
tag      nuts_fold_max            0.000  [0.00, 0.00]        657  PASS
tag      strong_fold_max          0.051  [0.00, 0.10]        212  PASS
tag      air_call_max             0.041  [0.00, 0.10]         99  PASS
tag      thin_value_dominated     0.086  [0.00, 0.10]        108  PASS
tag      cbet_flop                0.563  [0.45, 0.70]         52  PASS
tag      defence_overbet          1.071  [0.85, 1.15]        623  PASS
tag      raise_dominated          0.094  [0.00, 0.10]         51  PASS
tag      preflop_defence_3bet     1.280  [0.90, 1.40]       1326  PASS
lag      bluff_share_33           0.311  [0.16, 0.32]         57  PASS
lag      bluff_share_75           0.371  [0.26, 0.42]         57  PASS
lag      defence_flop             0.955  [0.85, 1.20]        152  PASS
lag      defence_turn             1.103  [0.85, 1.20]        109  PASS
lag      defence_river            0.922  [0.85, 1.20]         63  PASS
lag      nuts_fold_max            0.000  [0.00, 0.00]        725  PASS
lag      strong_fold_max          0.027  [0.00, 0.10]        230  PASS
lag      air_call_max             0.043  [0.00, 0.10]        113  PASS
lag      thin_value_dominated     0.049  [0.00, 0.10]        114  PASS
lag      cbet_flop                0.647  [0.45, 0.70]         58  PASS
lag      defence_overbet          1.072  [0.85, 1.20]        677  PASS
lag      raise_dominated          0.071  [0.00, 0.10]         60  PASS
lag      preflop_defence_3bet     1.283  [0.90, 1.40]       1326  PASS
tight    bluff_share_33           0.197  [0.05, 0.22]         40  PASS
tight    bluff_share_75           0.224  [0.15, 0.32]         40  PASS
tight    defence_flop             0.740  [0.70, 1.00]        101  PASS
tight    defence_turn             0.871  [0.70, 1.00]         81  PASS
tight    defence_river            0.894  [0.70, 1.00]         43  PASS
tight    nuts_fold_max            0.000  [0.00, 0.00]        490  PASS
tight    strong_fold_max          0.071  [0.00, 0.10]        157  PASS
tight    air_call_max             0.012  [0.00, 0.10]         73  PASS
tight    thin_value_dominated     0.042  [0.00, 0.10]         80  PASS
tight    cbet_flop                0.501  [0.45, 0.70]         32  PASS
tight    defence_overbet          0.942  [0.70, 1.00]        454  PASS
tight    raise_dominated          0.062  [0.00, 0.10]         41  PASS
tight    preflop_defence_3bet     1.283  [0.90, 1.40]       1326  PASS
sticky   bluff_share_33           0.257  [0.10, 0.26]         79  PASS
sticky   bluff_share_75           0.283  [0.20, 0.36]         79  PASS
sticky   defence_flop             1.081  [1.00, 1.35]        195  PASS
sticky   defence_turn             1.212  [1.00, 1.35]        157  PASS
sticky   defence_river            1.093  [1.00, 1.35]        111  PASS
sticky   nuts_fold_max            0.000  [0.00, 0.00]        967  PASS
sticky   strong_fold_max          0.034  [0.00, 0.10]        296  PASS
sticky   air_call_max             0.057  [0.00, 0.10]        152  PASS
sticky   thin_value_dominated     0.096  [0.00, 0.10]        158  PASS
sticky   cbet_flop                0.536  [0.45, 0.70]         49  PASS
sticky   defence_overbet          1.213  [1.00, 1.35]        861  PASS
sticky   raise_dominated          0.077  [0.00, 0.10]        108  PASS
sticky   preflop_defence_3bet     1.375  [0.90, 1.40]       1326  PASS

info (not checks): river_stab = whole-range river stab bet frequency;
air_continue_max = AIR call+raise share facing river bets >= 75% pot (max);
preflop_defence_open = BB call+3-bet share of all combos vs a 2.5x open / MDF 4/7.
tag      river_stab=0.339  air_continue_max=0.045  preflop_defence_open=1.386
lag      river_stab=0.360  air_continue_max=0.054  preflop_defence_open=1.465
tight    river_stab=0.281  air_continue_max=0.017  preflop_defence_open=1.016
sticky   river_stab=0.326  air_continue_max=0.069  preflop_defence_open=1.544

=== summary over 2 seeds, 200 hands each ===
profile  check                      min     max  band             pass  info
----------------------------------------------------------------------------
tag      bluff_share_33           0.230   0.255  [0.12, 0.28]      2/2  
tag      bluff_share_75           0.286   0.297  [0.22, 0.38]      2/2  
tag      defence_flop             0.917   0.926  [0.85, 1.15]      2/2  
tag      defence_turn             1.017   1.088  [0.85, 1.15]      2/2  
tag      defence_river            0.882   0.963  [0.85, 1.15]      2/2  
tag      nuts_fold_max            0.000   0.000  [0.00, 0.00]      2/2  
tag      strong_fold_max          0.040   0.051  [0.00, 0.10]      2/2  
tag      air_call_max             0.033   0.041  [0.00, 0.10]      2/2  
tag      thin_value_dominated     0.055   0.086  [0.00, 0.10]      2/2  
tag      cbet_flop                0.563   0.565  [0.45, 0.70]      2/2  
tag      defence_overbet          1.023   1.071  [0.85, 1.15]      2/2  
tag      raise_dominated          0.066   0.094  [0.00, 0.10]      2/2  
tag      preflop_defence_3bet     1.280   1.280  [0.90, 1.40]      2/2  
tag      river_stab               0.271   0.339  (info)              -
tag      air_continue_max         0.045   0.046  (info)              -
tag      preflop_defence_open     1.386   1.386  (info)              -
lag      bluff_share_33           0.251   0.311  [0.16, 0.32]      2/2  
lag      bluff_share_75           0.338   0.371  [0.26, 0.42]      2/2  
lag      defence_flop             0.937   0.955  [0.85, 1.20]      2/2  
lag      defence_turn             1.081   1.103  [0.85, 1.20]      2/2  
lag      defence_river            0.919   0.922  [0.85, 1.20]      2/2  
lag      nuts_fold_max            0.000   0.000  [0.00, 0.00]      2/2  
lag      strong_fold_max          0.027   0.027  [0.00, 0.10]      2/2  
lag      air_call_max             0.027   0.043  [0.00, 0.10]      2/2  
lag      thin_value_dominated     0.049   0.052  [0.00, 0.10]      2/2  
lag      cbet_flop                0.631   0.647  [0.45, 0.70]      2/2  
lag      defence_overbet          1.049   1.072  [0.85, 1.20]      2/2  
lag      raise_dominated          0.068   0.071  [0.00, 0.10]      2/2  
lag      preflop_defence_3bet     1.283   1.283  [0.90, 1.40]      2/2  
lag      river_stab               0.330   0.360  (info)              -
lag      air_continue_max         0.053   0.054  (info)              -
lag      preflop_defence_open     1.465   1.465  (info)              -
tight    bluff_share_33           0.134   0.197  [0.05, 0.22]      2/2  
tight    bluff_share_75           0.145   0.224  [0.15, 0.32]      1/2  
tight    defence_flop             0.740   0.757  [0.70, 1.00]      2/2  
tight    defence_turn             0.871   0.904  [0.70, 1.00]      2/2  
tight    defence_river            0.894   0.956  [0.70, 1.00]      2/2  
tight    nuts_fold_max            0.000   0.000  [0.00, 0.00]      2/2  
tight    strong_fold_max          0.071   0.085  [0.00, 0.10]      2/2  
tight    air_call_max             0.012   0.014  [0.00, 0.10]      2/2  
tight    thin_value_dominated     0.026   0.042  [0.00, 0.10]      2/2  
tight    cbet_flop                0.501   0.515  [0.45, 0.70]      1/2  
tight    defence_overbet          0.942   0.966  [0.70, 1.00]      2/2  
tight    raise_dominated          0.031   0.062  [0.00, 0.10]      2/2  
tight    preflop_defence_3bet     1.283   1.283  [0.90, 1.40]      2/2  
tight    river_stab               0.281   0.298  (info)              -
tight    air_continue_max         0.017   0.017  (info)              -
tight    preflop_defence_open     1.016   1.016  (info)              -
sticky   bluff_share_33           0.196   0.257  [0.10, 0.26]      2/2  
sticky   bluff_share_75           0.253   0.283  [0.20, 0.36]      2/2  
sticky   defence_flop             1.075   1.081  [1.00, 1.35]      2/2  
sticky   defence_turn             1.192   1.212  [1.00, 1.35]      2/2  
sticky   defence_river            1.093   1.120  [1.00, 1.35]      2/2  
sticky   nuts_fold_max            0.000   0.000  [0.00, 0.00]      2/2  
sticky   strong_fold_max          0.028   0.034  [0.00, 0.10]      2/2  
sticky   air_call_max             0.056   0.057  [0.00, 0.10]      2/2  
sticky   thin_value_dominated     0.050   0.096  [0.00, 0.10]      2/2  
sticky   cbet_flop                0.536   0.545  [0.45, 0.70]      2/2  
sticky   defence_overbet          1.213   1.220  [1.00, 1.35]      2/2  
sticky   raise_dominated          0.077   0.093  [0.00, 0.10]      2/2  
sticky   preflop_defence_3bet     1.375   1.375  [0.90, 1.40]      2/2  
sticky   river_stab               0.285   0.326  (info)              -
sticky   air_continue_max         0.069   0.070  (info)              -
sticky   preflop_defence_open     1.544   1.544  (info)              -
```

## Fixture sha256 (`frontend/src/test/fixtures`)

| file | sha256 |
| --- | --- |
| `attempt_bet.json` | `8864d27667871a49bb675250184dc258871b3554be48dc48908d9d82e0e08cb6` |
| `attempt_call.json` | `e5d8aea858001aee36e5558744239050aca9256f22bfddeb2145913edca38901` |
| `attempt_check_river.json` | `da54e549d74036a63e6f021bc5d44bd3ff84c15a95fb65cff4f22163848d3030` |
| `attempt_custom.json` | `ca6d4a3512862390aa9571599b64dc1a6c7e46cdd8e30d78e3c6c5d4670f76ef` |
| `attempt_fold.json` | `7eda15b0113663548dd3ead5957eeeada8db6bde5217f40c3c6f0003233e3054` |
| `attempt_fold_preflop.json` | `705567eb942883bedaddcbcf1b966f69cb7c1ed881d1a0b2b1f36f13b4ec536c` |
| `attempt_raise_preflop.json` | `e013bd805108ac3e93ff98ee7f769d7d68990301b1117db669d5b915614c7f48` |
| `explanation_llm.json` | `71bae473bb674634d1ae6ce7f8e089867f375029e2aae7771fd62210e3631adc` |
| `history_page.json` | `97b69da2a1798d4000fde392576c0fe30373d6743b03c50624fdc2c55b91c2c0` |
| `play_hand_analysis.json` | `141f9a73a1973707e9eedd00d137aa8242c3e59785617c3d500c4f7ffa4f0961` |
| `play_hands.json` | `5f7357e6ed48813b77d6959017403b8a6ae22f998ecb619ef140ba32acba5d57` |
| `play_session_hand_over_fold.json` | `b763166d4e33cc8619bc9f09c29973ba12c6dd96173734ca09298080c0a3841b` |
| `play_session_hand_over_showdown.json` | `bad31cebe6b79c44c16d106c28e432bdd0354a797c983a1aa4f2c9e71185c64a` |
| `play_session_hero_to_act.json` | `30d30e176e1f72625d989bad41e623597e07474d627d261f60a9b6c7c07ab670` |
| `play_sessions.json` | `1d23d991628223dd6c5dc31e7e3b7d1aa614e1f07a66d17142fead74b468a3d8` |
| `puzzle_custom_allowed.json` | `771eb3e2ba1abcaf380b91741bbde8f53baf945832808d816f153e15c1ca6a28` |
| `puzzle_facing_all_in.json` | `a7252b8be533016e6c3524c71f9649cf2282cdbaa526b7412472469017ac5858` |
| `puzzle_facing_postflop_raise.json` | `10635ccf1543d6df80a48d43f28c74da6857d84ebdc71a619133b04e928b4a0d` |
| `puzzle_flop_unopened.json` | `2a930f387d5a0cd5b6af5fd082187884c87210e1e9d9809d97ffc2ed8016fcdf` |
| `puzzle_history_3bet_and_all_in.json` | `5f31fbd0730b8c2ffedf2e87b9ad7a15af81e3c946ee7eae33fd626e3e4779c4` |
| `puzzle_preflop_bb_facing_open.json` | `79034516450f5e71d9a113e06e32d25c609141fb7ac6eb8a4e18cbd8933d7b2e` |
| `puzzle_preflop_btn_first_in.json` | `ec65c7e1de53e6d096782e2284f3fb121a17d7f5463d70479125eeb559fb36d0` |
| `puzzle_preflop_facing_3bet.json` | `1e2a8ebfa5ac1d6da4befaf320064750ec98a3333210c4e0d3679f96185ae524` |
| `puzzle_river.json` | `33b7a33310abca2d5e0a7603a7271243449e1f1fb04a52ed4cf434f3ac851f7a` |
| `puzzle_turn.json` | `776d4cd57e6cde15ba8aa1696fd8adb2bae2e328514501f2c370ecc718965f31` |
| `settings.json` | `b9484d8f6abf83c0d905f27c9a3926ca7b943a1b26b399f58400f7f59f81e376` |
| `stats.json` | `2a815dfd4ebb31441d16ebd90cef3be8794a9a302bd86cf46905740726201326` |
| `stats_empty.json` | `45e83059e16aa23742cff39c456fc4d57220c893f9e760713d91b870e4420aad` |
