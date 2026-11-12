"""The template explanation: golden texts, the guardrail against its own facts, and what it
must never say."""

import re

import pytest
from explain_cases import FIXTURE_SEEDS, puzzle, result

from poker_trainer.api import views
from poker_trainer.engine.cards import card_str
from poker_trainer.explain import format as fmt
from poker_trainer.explain.facts import EV_EPSILON, build_facts
from poker_trainer.explain.guardrail import unknown_numbers
from poker_trainer.explain.template import explain, render, text_of
from poker_trainer.game.state import ActionKind

# Golden texts (sections by id). Regenerate deliberately when the wording changes.

RIVER_CALL = {
    "headline": "Call was the top play, and you found it.",
    "hand": [
        (
            "You held 8♠ T♦ on the button, against Villain, a LAG player, in the big blind. "
            "Pre-flop, you opened to 2.5 bb and Villain called."
        ),
        (
            "The flop came T♣ 6♣ T♥: Villain bet 1.5 bb and you called. The turn was the 7♣: "
            "Villain bet 2.5 bb and you called. The river was the 5♠: Villain bet 10 bb. You "
            "faced 10 bb more to call, with 23 bb in the pot."
        ),
    ],
    "verdict": [
        ("You chose Call (EV 3.53 bb), the top play against Villain's range. Verdict: Best."),
        (
            "Your equity against Villain's whole range is 41.0%. Calling 10 bb into a pot of "
            "23 bb needs 10 bb / (23 bb + 10 bb) = 30.3% equity; 41.0% is above that, so "
            "calling beats folding."
        ),
        (
            "The largest parts of the range are Strong value (60.4% of it; your equity 7%) "
            "and Air (26.0% of it; your equity 100%)."
        ),
    ],
    "villain": [
        ("Villain is a LAG player. Loose-aggressive: wide ranges, frequent pressure, more bluffs."),
        (
            "Villain's range narrowed with each action: Pre-flop: calls; Flop: bets 1.5 bb "
            "(30% pot); Turn: bets 2.5 bb (31% pot); River: bets 10 bb (77% pot)."
        ),
        ("The range in the Range tab is the range this puzzle was graded on."),
    ],
}
FLOP_BET_BEST = {
    "headline": "Bet 33% was the top play, and you found it.",
    "hand": [
        (
            "You held T♦ K♠ in the big blind, against Villain, a LAG player, on the button. "
            "Pre-flop, Villain opened to 2.5 bb and you called."
        ),
        ("The flop came 3♥ 2♠ 6♠. It was your turn to act with 5 bb in the pot."),
    ],
    "verdict": [
        ("You chose Bet 33% (EV 2.57 bb), the top play against Villain's range. Verdict: Best."),
        ("Your equity against Villain's whole range is 46.4%."),
        (
            "Bet 33%: Villain folds 34% of the time and you have 37.1% equity against the "
            "hands that continue. To profit on folds alone, a bet this size needs 23.1% folds "
            "(1.5 bb / (5 bb + 1.5 bb))."
        ),
        (
            "Right now you are ahead of 47.0% of Villain's range. The largest parts of the "
            "range are Weak draw (20.6% of it; your equity 61%) and Air (20.6% of it; your "
            "equity 80%)."
        ),
    ],
    "villain": [
        ("Villain is a LAG player. Loose-aggressive: wide ranges, frequent pressure, more bluffs."),
        ("Villain's range narrowed with each action: Pre-flop: opens to 2.5 bb."),
        ("The range in the Range tab is the range this puzzle was graded on."),
    ],
}
PREFLOP_FOLD = {
    "headline": "Fold was close: within 0.37 bb of the top play, Raise 2.5x.",
    "hand": [
        (
            "You held 4♣ K♥ on the button, against Villain, a LAG player, in the big blind. "
            "It was your turn to act with 1.5 bb in the pot."
        ),
    ],
    "verdict": [
        (
            "You chose Fold (EV 0 bb). The top play was Raise 2.5x (EV 0.37 bb), so your "
            "choice gives up 0.37 bb against Villain's range. That is close to the top play, "
            "so the verdict is Fine."
        ),
        ("Your equity against Villain's whole range is 52.2%."),
        (
            "Raise 2.5x: Villain folds 16% of the time and you have 49.4% equity against the "
            "hands that continue."
        ),
        ("Right now you are ahead of 70.9% of Villain's range."),
    ],
    "villain": [
        ("Villain is a LAG player. Loose-aggressive: wide ranges, frequent pressure, more bluffs."),
        ("Villain had not acted yet, so the range is every hand Villain can hold."),
        ("The range in the Range tab is the range this puzzle was graded on."),
    ],
}
RIVER_CHECK_BEST_BET_CHOSEN = {
    "headline": "Check was the top play; betting 75% loses 2.96 bb against Villain's range.",
    "hand": [
        (
            "You held 7♦ Q♠ in the big blind, against Villain, a LAG player, on the button. "
            "Pre-flop, Villain opened to 2.5 bb and you called."
        ),
        (
            "The flop came Q♥ J♦ 9♣: you checked and Villain checked. The turn was the 5♥: "
            "you checked, Villain bet 4 bb and you called. The river was the T♥. It was your "
            "turn to act with 13 bb in the pot."
        ),
    ],
    "verdict": [
        (
            "You chose Bet 75% (EV 1.14 bb). The top play was Check (EV 4.1 bb), so your "
            "choice gives up 2.96 bb against Villain's range. Verdict: Mistake."
        ),
        (
            "Your equity against Villain's whole range is 37.0%. Checking (EV 4.1 bb) does "
            "better than the best bet, Bet 33% (EV 3.28 bb)."
        ),
        (
            "Bet 75%: Villain folds 36% of the time and you have 15.7% equity against the "
            "hands that continue. To profit on folds alone, a bet this size needs 43.5% folds "
            "(10 bb / (13 bb + 10 bb))."
        ),
        (
            "The largest parts of the range are Weak made hand (28.0% of it; your equity 54%) "
            "and Strong value (28.0% of it; your equity 0%)."
        ),
    ],
    "villain": [
        ("Villain is a LAG player. Loose-aggressive: wide ranges, frequent pressure, more bluffs."),
        (
            "Villain's range narrowed with each action: Pre-flop: opens to 2.5 bb; Flop: "
            "checks; Turn: bets 4 bb (80% pot)."
        ),
        ("The range in the Range tab is the range this puzzle was graded on."),
    ],
}


GOLDEN = [
    # river call facing a bet (call best and chosen)
    ((8, "river"), {"option": 1}, RIVER_CALL),
    # flop bet best and chosen
    ((3, "flop"), {"option": 1, "intent": "value"}, FLOP_BET_BEST),
    # pre-flop fold, first in on the button (attempt_fold_preflop's spot)
    ((1, "preflop"), {"option": 0}, PREFLOP_FOLD),
    # river check best with a bet chosen
    ((4, "river"), {"option": 3, "intent": "bluff"}, RIVER_CHECK_BEST_BET_CHOSEN),
]


@pytest.mark.parametrize(("key", "answer", "golden"), GOLDEN)
def test_golden_texts(key, answer, golden):
    e = result(puzzle(*key), **answer)["explanation"]
    assert e["source"] == "template" and e["model"] is None and e["fallback"] is None
    assert [s["id"] for s in e["sections"]] == ["hand", "verdict", "villain"]
    assert [s["title"] for s in e["sections"]] == ["The hand", "Why", "Villain"]
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
    f = build_facts(res, p)
    text = text_of(res["explanation"])
    assert res["explanation"] == render(f)
    assert unknown_numbers(text, f.values_text()) == set(), text
    hidden = [*p.spot.villain_hole, *p.spot.runout[len(p.spot.state.board) :]]
    for c in hidden:
        assert fmt.card(card_str(c)) not in text
    assert not _LOSS.search(text), text
    assert "showdown" not in text.lower()
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
    assert explain(rest, p) == res["explanation"]
