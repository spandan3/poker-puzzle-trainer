"""The template explanation: golden texts, the guardrail against its own facts, and what it
must never say."""

import dataclasses
import re

import pytest
from explain_cases import FIXTURE_SEEDS, facts, puzzle, result

from poker_trainer.api import views
from poker_trainer.engine.cards import card_str
from poker_trainer.explain import format as fmt
from poker_trainer.explain.facts import EV_EPSILON
from poker_trainer.explain.guardrail import check_claims, unknown_numbers
from poker_trainer.explain.ollama import fields_of
from poker_trainer.explain.template import GRADED_ON_RANGE, explain, render, text_of
from poker_trainer.game.state import ActionKind

# Golden texts (sections by id). Regenerate deliberately when the wording changes.
#
# Each golden pins the wording; every number that comes from a float (equity, EV, fold
# frequency, category share) is built from the result dict with the format helpers, so a
# last-digit float difference between OSes cannot break it. Amounts in bb are exact (chips).


def _opt(res, label):
    return next(o for o in res["options"] if fmt.option_label(o["label"]) == label)


def _ev(res, label):
    return fmt.ev_bb(_opt(res, label)["ev_bb"])


def _folds(res, label):
    return fmt.pct(_opt(res, label)["fold_freq"], 0)


def _needs(res, label):
    return fmt.pct(_opt(res, label)["required_fold_equity"], 1)


def _eq_continue(res, label):
    return fmt.pct(_opt(res, label)["equity_vs_continue"], 1)


def _cat(res, name):
    """``"Air (26.0% of it; your equity 100%)"``."""
    c = next(c for c in res["categories"] if c["name"] == name)
    return f"{name} ({fmt.pct(c['share'], 1)} of it; your equity {fmt.pct(c['equity'], 0)})"


def _numbers(res):
    g = res["grade"]
    return {
        "eq": fmt.pct(g["equity"], 1),
        "loss": fmt.ev_bb(g["ev_loss_bb"]),
        "ahead": None if g["ahead_now"] is None else fmt.pct(g["ahead_now"], 1),
        "pot_odds": None if g["pot_odds"] is None else fmt.pct(g["pot_odds"], 1),
        "needs": None if g["bluff_check"] is None else fmt.pct(g["bluff_check"]["required"], 1),
    }


LAG = "Villain is a LAG player. Loose-aggressive: wide ranges, frequent pressure, more bluffs."


def river_call(res):
    n = _numbers(res)
    return {
        "headline": "Call was the top play, and you found it.",
        "hand": [
            (
                "You held 8♠ T♦ on the button, against Villain, a LAG player, in the big blind. "
                "Pre-flop, you opened to 2.5 bb and Villain called."
            ),
            (
                "The flop came T♣ 6♣ T♥: Villain bet 1.5 bb and you called. The turn was the "
                "7♣: Villain bet 2.5 bb and you called. The river was the 5♠: Villain bet 10 bb. "
                "You faced 10 bb more to call, with 23 bb in the pot."
            ),
        ],
        "verdict": [
            (
                f"You chose Call (EV {_ev(res, 'Call')}), the top play against Villain's range. "
                "Verdict: Best."
            ),
            (
                f"Your equity against Villain's whole range is {n['eq']}. Calling 10 bb into a "
                f"pot of 23 bb needs 10 bb / (23 bb + 10 bb) = {n['pot_odds']} equity; "
                f"{n['eq']} is above that, so calling beats folding."
            ),
            (
                f"The largest parts of the range are {_cat(res, 'Strong value')} "
                f"and {_cat(res, 'Air')}."
            ),
        ],
        "villain": [
            LAG,
            (
                "Villain's range narrowed with each action: Pre-flop: calls; Flop: bets 1.5 bb "
                "(30% pot); Turn: bets 2.5 bb (31% pot); River: bets 10 bb (77% pot)."
            ),
            GRADED_ON_RANGE,
        ],
    }


def flop_bet_best(res):
    n = _numbers(res)
    return {
        "headline": "Bet 33% was the top play, and you found it.",
        "hand": [
            (
                "You held T♦ K♠ in the big blind, against Villain, a LAG player, on the button. "
                "Pre-flop, Villain opened to 2.5 bb and you called."
            ),
            "The flop came 3♥ 2♠ 6♠. It was your turn to act with 5 bb in the pot.",
        ],
        "verdict": [
            (
                f"You chose Bet 33% (EV {_ev(res, 'Bet 33%')}), the top play against Villain's "
                "range. Verdict: Best."
            ),
            f"Your equity against Villain's whole range is {n['eq']}.",
            (
                f"Bet 33%: Villain folds {_folds(res, 'Bet 33%')} of the time, more than the "
                f"{n['needs']} a bet this size needs to profit on folds alone "
                "(1.5 bb / (5 bb + 1.5 bb)), so folds alone pay for it, even when every "
                "hand that continues beats you. On top of that, you have "
                f"{_eq_continue(res, 'Bet 33%')} equity against the hands that continue."
            ),
            (
                f"Right now you are ahead of {n['ahead']} of Villain's range. The largest parts "
                f"of the range are {_cat(res, 'Weak draw')} and {_cat(res, 'Air')}."
            ),
        ],
        "villain": [
            LAG,
            "Villain's range narrowed with each action: Pre-flop: opens to 2.5 bb.",
            GRADED_ON_RANGE,
        ],
    }


def preflop_fold(res):
    n = _numbers(res)
    return {
        "headline": f"Fold was close: within {n['loss']} of the top play, Raise 2.5x.",
        "hand": [
            (
                "You held 4♣ K♥ on the button, against Villain, a LAG player, in the big blind. "
                "It was your turn to act with 1.5 bb in the pot."
            ),
        ],
        "verdict": [
            (
                f"You chose Fold (EV {_ev(res, 'Fold')}). The top play was Raise 2.5x "
                f"(EV {_ev(res, 'Raise 2.5x')}), so your choice gives up {n['loss']} against "
                "Villain's range. That is close to the top play, so the verdict is Fine."
            ),
            f"Your equity against Villain's whole range is {n['eq']}.",
            (
                f"Raise 2.5x: Villain folds {_folds(res, 'Raise 2.5x')} of the time, less than "
                f"the {_needs(res, 'Raise 2.5x')} a raise this size needs to profit on folds "
                "alone (2 bb / (1.5 bb + 2 bb)), so folds alone don't pay for it: it relies on "
                f"your {_eq_continue(res, 'Raise 2.5x')} equity against the hands that continue."
            ),
            f"Right now you are ahead of {n['ahead']} of Villain's range.",
        ],
        "villain": [
            LAG,
            "Villain had not acted yet, so the range is every hand Villain can hold.",
            GRADED_ON_RANGE,
        ],
    }


def river_check_best_bet_chosen(res):
    n = _numbers(res)
    return {
        "headline": (
            f"Check was the top play; betting 75% loses {n['loss']} against Villain's range."
        ),
        "hand": [
            (
                "You held 7♦ Q♠ in the big blind, against Villain, a LAG player, on the button. "
                "Pre-flop, Villain opened to 2.5 bb and you called."
            ),
            (
                "The flop came Q♥ J♦ 9♣: you checked and Villain checked. The turn was the 5♥: "
                "you checked, Villain bet 4 bb and you called. The river was the T♥. It was "
                "your turn to act with 13 bb in the pot."
            ),
        ],
        "verdict": [
            (
                f"You chose Bet 75% (EV {_ev(res, 'Bet 75%')}). The top play was Check "
                f"(EV {_ev(res, 'Check')}), so your choice gives up {n['loss']} against "
                "Villain's range. Verdict: Mistake."
            ),
            (
                f"Your equity against Villain's whole range is {n['eq']}. Checking does better "
                f"than the most profitable bet, Bet 33% (EV {_ev(res, 'Bet 33%')})."
            ),
            (
                f"Bet 75%: Villain folds {_folds(res, 'Bet 75%')} of the time, less than the "
                f"{n['needs']} a bet this size needs to profit on folds alone "
                "(10 bb / (13 bb + 10 bb)), so folds alone don't pay for it: it relies on your "
                f"{_eq_continue(res, 'Bet 75%')} equity against the hands that continue."
            ),
            (
                f"The largest parts of the range are {_cat(res, 'Weak made hand')} "
                f"and {_cat(res, 'Strong value')}."
            ),
        ],
        "villain": [
            LAG,
            (
                "Villain's range narrowed with each action: Pre-flop: opens to 2.5 bb; Flop: "
                "checks; Turn: bets 4 bb (80% pot)."
            ),
            GRADED_ON_RANGE,
        ],
    }


def custom_matched(res):
    """A custom size with zero EV loss that is not the listed top play."""
    return {
        "headline": "Bet 1 bb was the top play, and you found it.",
        "verdict_0": (
            f"You chose Bet 1 bb (EV {fmt.ev_bb(_chosen(res)['ev_bb'])}), which matched or "
            "beat the top listed play (Bet 33%) against Villain's range. Verdict: Best."
        ),
    }


def _chosen(res):
    return next(o for o in res["options"] if o["is_chosen"])


GOLDEN = [
    # river call facing a bet (call best and chosen)
    ((8, "river"), {"option": 1}, river_call),
    # flop bet best and chosen
    ((3, "flop"), {"option": 1, "intent": "value"}, flop_bet_best),
    # pre-flop fold, first in on the button (attempt_fold_preflop's spot)
    ((1, "preflop"), {"option": 0}, preflop_fold),
    # river check best with a bet chosen
    ((4, "river"), {"option": 3, "intent": "bluff"}, river_check_best_bet_chosen),
]


@pytest.mark.parametrize(("key", "answer", "golden"), GOLDEN)
def test_golden_texts(key, answer, golden):
    res = result(puzzle(*key), **answer)
    golden = golden(res)
    e = res["explanation"]
    assert e["source"] == "template" and e["model"] is None and e["fallback"] is None
    assert [s["id"] for s in e["sections"]] == ["hand", "verdict", "villain"]
    assert [s["title"] for s in e["sections"]] == ["The hand", "The verdict", "Villain"]
    assert e["headline"] == golden["headline"]
    for s in e["sections"]:
        assert s["paragraphs"] == golden[s["id"]], s["id"]


def _answers(p):
    """Every listed option once, intents labelled so a bluff check is graded."""
    for i, o in enumerate(p.solution.options):
        aggressive = o.option.action.kind in (ActionKind.BET, ActionKind.RAISE)
        yield {"option": i, "intent": "value" if aggressive else None}


_LOSS = re.compile(r"\byou (won|lost|win|lose)\b", re.IGNORECASE)


def _assert_sound(p, res):
    """The template passes the guardrail against its own facts' values, and never mentions
    Villain's cards, the run-out after the decision or who won."""
    f = facts(res, p)
    text = text_of(res["explanation"])
    assert res["explanation"] == render(f)
    assert unknown_numbers(text, f.values_text()) == set(), text
    hidden = [*p.spot.villain_hole, *p.spot.runout[len(p.spot.state.board) :]]
    for c in hidden:
        assert fmt.card(card_str(c)) not in text
    assert not _LOSS.search(text), text
    assert "showdown" not in text.lower()
    # the claim checks a model's text must pass, on the template's own fields
    assert check_claims(fields_of(res["explanation"]), f) == {}, text
    # the summary's strings: equity always, the EV lost when it is shown as lost
    assert fmt.pct(res["grade"]["equity"], 1) in text
    if res["grade"]["ev_loss_bb"] >= EV_EPSILON:
        assert fmt.ev_bb(res["grade"]["ev_loss_bb"]) in text


@pytest.mark.parametrize("key", sorted(set(FIXTURE_SEEDS.values())))
def test_fixture_spots_pass_the_guardrail(key):
    p = puzzle(*key)
    for answer in _answers(p):
        _assert_sound(p, result(p, **answer))


def test_custom_size_passes_the_guardrail():
    p = puzzle(*FIXTURE_SEEDS["custom_allowed"])
    lo, hi = views.custom_bounds(p)
    for to in (lo, hi - 1):
        res = result(p, custom_to=to)
        _assert_sound(p, res)
        label = fmt.custom_label(res["answer"]["action"]["kind"], to)
        assert label in res["explanation"]["sections"][1]["paragraphs"][0]


# 50 generated puzzles, every street, every listed option once
GENERATED = [
    (seed, street) for seed in range(101, 114) for street in ("preflop", "flop", "turn", "river")
][:50]


def test_generated_puzzles_pass_the_guardrail():
    kinds = set()
    for seed, street in GENERATED:
        p = puzzle(seed, street)
        for answer in _answers(p):
            res = result(p, **answer)
            _assert_sound(p, res)
            kinds.add(res["answer"]["action"]["kind"])
    assert kinds == {"fold", "check", "call", "bet", "raise"}


def test_custom_size_that_matches_the_top_play_is_not_called_the_top_play():
    p = puzzle(*FIXTURE_SEEDS["custom_allowed"])  # attempt_custom: a 1 bb bet, EV above Bet 33%
    res = result(p, custom_to=2)
    assert res["grade"]["ev_loss_bb"] < EV_EPSILON and not _chosen(res)["is_best"]
    golden = custom_matched(res)
    e = res["explanation"]
    assert e["headline"] == golden["headline"]  # verdictLine's wording
    assert e["sections"][1]["paragraphs"][0] == golden["verdict_0"]
    assert "top play" not in e["sections"][1]["paragraphs"][0].replace("top listed play", "")


def test_headline_follows_verdict_line():
    p = puzzle(17, "flop")  # facing a raise: call best (2.25 bb), raise 2.5x fine, fold lost
    texts = [result(p, option=i)["explanation"]["headline"] for i in range(3)]
    assert texts == [
        "Call was the top play; folding loses 2.25 bb against Villain's range.",
        "Call was the top play, and you found it.",
        "Raise 2.5x was close: within 0.66 bb of the top play, Call.",
    ]


def test_explain_is_what_the_view_adds():
    p = puzzle(8, "river")
    res = result(p, option=0)
    rest = {k: v for k, v in res.items() if k != "explanation"}
    assert explain(rest, p, views.action_log(p.spot)) == res["explanation"]


def test_check_best_states_the_check_ev_once():
    res = result(puzzle(4, "river"), option=3, intent="bluff")  # check best, bet 75% chosen
    check_ev = f"EV {_ev(res, 'Check')}"
    assert text_of(res["explanation"]).count(check_ev) == 1


def test_range_steps_are_grouped_by_street():
    res = result(puzzle(17, "flop"), option=1)  # attempt_call: Villain checks, then raises
    villain = res["explanation"]["sections"][2]["paragraphs"][1]
    assert villain == (
        "Villain's range narrowed with each action: Pre-flop: calls; "
        "Flop: checks, then raises to 4.5 bb."
    )


def _with(f, **changes):
    return dataclasses.replace(f, **changes)


def _pot_odds_sentence(f):
    return render(f)["sections"][1]["paragraphs"][1]


def test_pot_odds_conclusion_follows_the_choice():
    p = puzzle(3, "preflop")  # BB facing an open: fold, call, raises
    raised = facts(result(p, option=2), p)  # raise chosen and best: call and fold neither
    assert raised.chosen.kind == "raise" and raised.best.kind == "raise"
    assert _pot_odds_sentence(raised).endswith(", so calling would beat folding.")
    called = facts(result(p, option=1), p)  # call chosen
    assert _pot_odds_sentence(called).endswith(", so calling beats folding.")
    folded = facts(result(p, option=0), p)
    assert _pot_odds_sentence(folded).endswith(", so calling beats folding.")


def test_pot_odds_equal_strings_are_never_above():
    p = puzzle(3, "preflop")
    f = facts(result(p, option=1), p)
    even = _with(f, equity=f.pot_odds, equity_beats_pot_odds=True)
    text = _pot_odds_sentence(even)
    assert f"{f.pot_odds} is exactly what it needs, so calling beats folding." in text
    assert "above" not in text
    short = _with(f, equity=f.pot_odds, equity_beats_pot_odds=False)
    text = _pot_odds_sentence(short)
    assert f"{f.pot_odds} falls just short of that, so folding beats calling." in text
    assert "below" not in text


def test_fold_equity_close_to_when_the_shown_numbers_disagree():
    p = puzzle(1, "river")  # attempt_check_river: Bet 33% best, Check chosen
    f = facts(result(p, option=0), p)
    best = _with(f.best, fold_relation="close to", folds_pay=False)
    options = tuple(best if o.is_best else o for o in f.options)
    text = render(_with(f, options=options))["sections"][1]["paragraphs"][2]
    assert text.startswith(f"Bet 33%: Villain folds {f.best.fold_freq} of the time, close to the ")
    assert "so folds alone don't pay for it: it relies on your" in text
