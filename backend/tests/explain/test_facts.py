import copy

from explain_cases import facts, puzzle, result

from poker_trainer.engine.cards import card_str
from poker_trainer.explain import format as fmt
from poker_trainer.explain.facts import FRACTION_TOL, _fraction_formula
from poker_trainer.explain.template import render
from poker_trainer.game.state import total_pot


def _river_facing_bet():
    """River, Villain (LAG) bets 10 bb into 13 bb; Hero's top play is a call."""
    return puzzle(8, "river")


def test_facing_bet_facts_hold_the_ui_numbers():
    p = _river_facing_bet()
    res = result(p, option=0)  # fold, the call was best
    f = facts(res, p)
    lines = f.as_lines()
    g = res["grade"]
    # the summary's strings (guessLines, verdictLine)
    assert f"Your equity against the whole range: {fmt.pct(g['equity'], 1)}" in lines
    assert f"EV lost: {fmt.ev_bb(g['ev_loss_bb'])}" in lines
    # Maths: pot odds with its formula, pot = total_pot (Villain's bet included)
    assert "Pot odds: 30.3%" in lines
    assert "Pot odds formula: 10 bb / (23 bb + 10 bb) = 30.3%" in lines
    assert fmt.bb(total_pot(p.spot.state)) == "23 bb"
    assert "To call: 10 bb" in lines
    # every option's EV as the Options table shows it
    for o in res["options"]:
        assert any(
            line.startswith(f"Option: {fmt.option_label(o['label'])}: EV {fmt.ev_bb(o['ev_bb'])}")
            for line in lines
        ), o["label"]
    assert "Option: Raise 2.5x: EV −1.5 bb, Villain folds 36%, " in "\n".join(lines)
    assert "EV lost: 3.53 bb" in lines
    assert "Your choice: Fold" in lines and "Top play: Call" in lines


def test_values_text_is_the_values_only():
    p = _river_facing_bet()
    f = facts(result(p, option=1), p)
    values = f.values_text().split("\n")
    assert values == [line.split(": ", 1)[1] for line in f.as_lines()]
    assert "Pot odds" not in f.values_text()


def test_range_steps_in_bb_without_start():
    p = _river_facing_bet()
    f = facts(result(p, option=1), p)
    assert f.range_steps == (
        "Pre-flop: calls",
        "Flop: bets 1.5 bb (30% pot)",
        "Turn: bets 2.5 bb (31% pot)",
        "River: bets 10 bb (77% pot)",
    )


def test_narrative_facts_come_from_kind_and_to():
    p = _river_facing_bet()
    f = facts(result(p, option=1), p)
    assert [(a.street, a.actor, a.text) for a in f.actions] == [
        ("preflop", "hero", "opened to 2.5 bb"),
        ("preflop", "villain", "called"),
        ("flop", "villain", "bet 1.5 bb"),
        ("flop", "hero", "called"),
        ("turn", "villain", "bet 2.5 bb"),
        ("turn", "hero", "called"),
        ("river", "villain", "bet 10 bb"),
    ]
    assert (f.flop, f.turn, f.river) == ("T♣ 6♣ T♥", "7♣", "5♠")


def test_no_runout_after_the_decision_and_no_villain_cards():
    p = puzzle(3, "flop")  # flop decision: the turn and river are undealt
    for i in range(len(p.solution.options)):
        f = facts(result(p, option=i), p)
        text = f.values_text()
        hidden = [*p.spot.villain_hole, *p.spot.runout[3:]]
        for c in hidden:
            assert fmt.card(card_str(c)) not in text
        assert f.turn is None and f.river is None


def test_first_in_on_the_button_is_not_facing_a_bet():
    p = puzzle(1, "preflop")  # BTN first in: fold / raises / all-in, no call
    f = facts(result(p, option=0), p)
    assert not f.facing_bet and f.to_call is None and f.pot_odds is None
    assert f.range_steps == ()


def test_fraction_formula_only_when_it_reproduces_the_api_number():
    # put 1 chip into a pot of 3 chips: 1 / (3 + 1) = 0.25; the tolerance is strict (< 0.001)
    assert FRACTION_TOL == 0.001
    assert _fraction_formula(1, 3, 0.25) == "0.5 bb / (1.5 bb + 0.5 bb)"
    assert _fraction_formula(1, 3, 0.25 + 0.0009) == "0.5 bb / (1.5 bb + 0.5 bb)"
    assert _fraction_formula(1, 3, 0.25 - 0.0009) == "0.5 bb / (1.5 bb + 0.5 bb)"
    assert _fraction_formula(1, 3, 0.25 + 0.001) is None
    assert _fraction_formula(1, 3, 0.25 - 0.001) is None
    assert _fraction_formula(0, 0, 0.0) is None


def test_no_formula_when_the_api_number_differs():
    p = _river_facing_bet()
    res = copy.deepcopy(result(p, option=2, intent="bluff"))  # raise 2.5x: pot odds and bluff check
    g = res["grade"]
    assert facts(res, p).pot_odds_formula is not None and facts(res, p).bluff_formula is not None
    g["pot_odds"] += 0.002
    g["bluff_check"]["required"] += 0.002
    f = facts(res, p)
    assert f.pot_odds_formula is None and f.bluff_formula is None
    why = "\n".join(render(f)["sections"][1]["paragraphs"])
    assert f"needs {fmt.pct(g['pot_odds'], 1)} equity" in why
    assert f"needs {fmt.pct(g['bluff_check']['required'], 1)} folds." in why
    assert "/" not in why
    assert not any("formula" in line for line in f.as_lines())


def test_no_villain_actually_folds_fact():
    p = _river_facing_bet()
    f = facts(result(p, option=2, intent="bluff"), p)
    assert f.bluff_required is not None
    assert not any(line.startswith("Villain actually folds") for line in f.as_lines())
