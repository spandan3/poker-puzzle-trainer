import pytest

from poker_trainer.game.state import Action, ActionKind, Street
from poker_trainer.puzzle.model import Option, OptionEV, Solution, load_config
from poker_trainer.puzzle.trivial import is_trivial

P = 20  # total pot in chips: Best margin = max(0.5, 0.4) = 0.5 chips; gap rule > 10 chips


def _ev(label: str, kind: ActionKind, ev: float) -> OptionEV:
    return OptionEV(
        option=Option(label, Action(0, kind, Street.TURN, 0)),
        ev_chips=ev,
        fold_freq=None,
        equity_vs_continue=None,
        ahead_vs_continue=None,
        equity_vs_continue_se=None,
        required_fold_equity=None,
        put=0,
        continue_range=None,
        branches=(),
        simplifications=(),
    )


def _sol(equity: float, evs: list[float]) -> Solution:
    kinds = [ActionKind.CHECK, ActionKind.BET, ActionKind.RAISE]
    options = tuple(_ev(f"o{i}", kinds[i % 3], ev) for i, ev in enumerate(evs))
    return Solution(
        equity=equity,
        equity_std_error=0.0,
        equity_exact=True,
        ahead_now=None,
        pot_odds=0.0,
        options=options,
        best=max(range(len(options)), key=lambda i: options[i].ev_chips),
        combo_equity=None,  # type: ignore[arg-type]  # unused by is_trivial
        category_breakdown=None,
        simplifications=(),
    )


@pytest.mark.parametrize(
    "equity,evs,trivial",
    [
        (0.95, [10.0, 4.0, 0.0], True),  # rule 1: equity > 0.92
        (0.03, [10.0, 4.0, 0.0], True),  # rule 1: equity < 0.04
        (0.50, [5.0, 4.6, 4.9], True),  # rule 2: all within 0.5 chips of best
        (0.88, [20.0, 8.0, 0.0], True),  # rule 3: gap 12 > 10 and equity > 0.85
        (0.08, [20.0, 8.0, 0.0], True),  # rule 3: gap 12 > 10 and equity < 0.10
        (0.88, [20.0, 12.0, 0.0], False),  # gap 8 <= 10: rule 3 does not fire
        (0.50, [20.0, 8.0, 0.0], False),  # big gap but mid equity
        (0.50, [5.0, 3.0, 0.0], False),  # ordinary spot
    ],
)
def test_trivial_rules(equity, evs, trivial):
    reason = is_trivial(_sol(equity, evs), P, load_config())
    assert (reason is not None) == trivial
    if trivial:
        assert isinstance(reason, str) and reason
