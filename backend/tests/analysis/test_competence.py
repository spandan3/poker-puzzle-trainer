import math

import numpy as np
import pytest

from poker_trainer.analysis import competence
from poker_trainer.analysis.competence import (
    CHECK_NAMES,
    CheckResult,
    break_even_bluff_share,
    competence_report,
    main,
)
from poker_trainer.engine.cards import parse_cards
from poker_trainer.game.state import Action, ActionKind, apply, deal, legal_actions, new_hand
from poker_trainer.villain.profiles import PROFILE_NAMES, load_profile
from poker_trainer.villain.strategy import OPEN_MULT, raise_to

EXPECTED = (
    "bluff_share_33",
    "bluff_share_75",
    "defence_flop",
    "defence_turn",
    "defence_river",
    "defence_overbet",
    "defence_overbet_p10",
    "nuts_fold_max",
    "strong_fold_max",
    "air_call_max",
    "thin_value_dominated",
    "cbet_flop",
)


def test_report_shape():
    report = competence_report("tag", n_hands=40)
    assert CHECK_NAMES == EXPECTED
    assert tuple(r.name for r in report) == EXPECTED
    for r in report:
        assert isinstance(r, CheckResult)
        assert r.profile == "tag"
        assert r.band[0] <= r.band[1]
        assert r.samples >= 0
        if r.samples < 30:
            assert not r.passed


def test_report_deterministic():
    # repr, not ==: a check without samples reports nan, and nan != nan.
    a = competence_report("lag", n_hands=20, seed=3)
    assert repr(a) == repr(competence_report("lag", n_hands=20, seed=3))


def test_cli_header(capsys):
    code = main(["--profile", "tag", "--hands", "40"])
    assert code in (0, 1)
    assert "bluff_share_75" in capsys.readouterr().out


def test_break_even_from_bet_size():
    assert break_even_bluff_share(0.75) == pytest.approx(0.30)
    assert break_even_bluff_share(0.33) == pytest.approx(0.33 / 1.66)
    assert break_even_bluff_share(1.0) == pytest.approx(1 / 3)


@pytest.fixture(scope="module")
def full_reports() -> dict[str, list[CheckResult]]:
    return {p: competence_report(p, n_hands=400) for p in PROFILE_NAMES}


@pytest.mark.slow
@pytest.mark.parametrize("profile", PROFILE_NAMES)
def test_all_profiles_competent(full_reports, profile):
    failed = [r for r in full_reports[profile] if not r.passed]
    assert not failed, failed


@pytest.mark.slow
def test_cbet_flop_ordering(full_reports):
    cbet = {p: next(r.value for r in rs if r.name == "cbet_flop") for p, rs in full_reports.items()}
    assert cbet["lag"] > cbet["tag"] > cbet["tight"], cbet


# ---------------------------------------------------------------------------
# Overbet probes
# ---------------------------------------------------------------------------


def _flop_lead(stacks: tuple[int, int]):
    """BTN opens to 5, BB calls, flop Kh7d2c: BB (seat 1, the probing Hero) to act, pot 10."""
    s = new_hand(0, stacks)
    s = apply(s, raise_to(s, OPEN_MULT))
    s = apply(s, Action(1, ActionKind.CALL, s.street, 5))
    return deal(s, parse_cards("Kh7d2c"))


def _probe(monkeypatch, stacks: tuple[int, int]):
    """Run _probe_records at a flop lead spot; return (records, [(bet chips, defence_weight)])."""
    s = _flop_lead(stacks)
    assert s.pot == 10
    live, cats = competence._board_info(s.board)
    seen: list[tuple[int, float]] = []
    real = competence._facing_records

    def spy(out, probe, dist, villain, cats_, defence_weight):
        last = probe.history[-1]
        assert last.kind == ActionKind.BET
        seen.append((last.to, defence_weight))
        real(out, probe, dist, villain, cats_, defence_weight)

    monkeypatch.setattr(competence, "_facing_records", spy)
    out: list = []
    tag = load_profile("tag")
    competence._probe_records(out, s, tag, tag, live.copy(), live.copy(), cats)
    return out, seen


def _names(records) -> list[str]:
    return [r[0] for r in records]


def test_overbet_probes_deep(monkeypatch):
    out, seen = _probe(monkeypatch, (200, 200))  # 195 behind: 2x pot and all-in are distinct
    assert [b for b, _ in seen] == [3, 8, 10, 20, 195]
    assert len({b for b, _ in seen}) == len(seen)
    # Overbet probes never carry a defence weight, so they never feed defence_<street>.
    assert dict(seen)[20] == 0.0 and dict(seen)[195] == 0.0
    assert _names(out).count("defence_flop") <= 2
    # Only the 2x probe is inside the 2x-3x window; the 19.5x all-in is not.
    overbet = [r for r in out if r[0] == "defence_overbet"]
    assert len(overbet) == 1
    # The tail check gets the same per-probe ratio.
    assert [r[1:] for r in out if r[0] == "defence_overbet_p10"] == [overbet[0][1:]]
    _name, num, den, counted = overbet[0]
    assert den == 1.0 and counted
    assert 0.0 < num  # continue rate / MDF


def test_overbet_probe_clamped_to_allin_is_probed_once(monkeypatch):
    out, seen = _probe(monkeypatch, (30, 30))  # 25 behind: 2x pot clamps to all-in (2.5x)
    assert [b for b, _ in seen] == [3, 8, 10, 25]
    assert _names(out).count("defence_overbet") == 1
    assert _names(out).count("defence_overbet_p10") == 1


def test_allin_below_2x_pot_gives_no_overbet_record(monkeypatch):
    out, seen = _probe(monkeypatch, (20, 20))  # 15 behind: pot, 2x and all-in are all 15
    assert [b for b, _ in seen] == [3, 8, 15]
    assert "defence_overbet" not in _names(out)
    assert "defence_overbet_p10" not in _names(out)


def test_overbet_record_is_continue_over_mdf(monkeypatch):
    out, _ = _probe(monkeypatch, (200, 200))
    s = _flop_lead((200, 200))
    live, _cats = competence._board_info(s.board)
    probe = apply(s, Action(1, ActionKind.BET, s.street, 20))
    dist = competence.action_distribution(load_profile("tag"), probe)
    cont = competence._sum_kind(dist, ActionKind.CALL, ActionKind.RAISE)
    rate = float(live @ cont) / float(live.sum())
    assert legal_actions(probe).call == 20
    (rec,) = [r for r in out if r[0] == "defence_overbet"]
    assert rec[1] == pytest.approx(rate / (1.0 / 3.0))
    assert np.isfinite(rec[1])


def test_overbet_p10_is_tenth_percentile_with_fixed_band():
    ratios = [0.1 * i for i in range(1, 41)]  # 0.1 .. 4.0
    records = [("defence_overbet_p10", r, 1.0, True) for r in ratios]
    value, samples = competence._aggregate(records, "defence_overbet_p10")
    assert samples == 40
    assert value == pytest.approx(float(np.percentile(ratios, 10)))
    floors = {"tag": 0.70, "lag": 0.70, "tight": 0.55, "sticky": 0.85}
    for name in PROFILE_NAMES:
        p = load_profile(name)
        lo = p.bands.defence_ratio[0] - competence._P10_MARGIN
        assert competence._band(p, "defence_overbet_p10") == (pytest.approx(lo), math.inf)
        assert lo == pytest.approx(floors[name])
    # The mean check keeps the profile band.
    tag = load_profile("tag")
    assert competence._band(tag, "defence_overbet") == tag.bands.defence_ratio


def test_format_table_prints_open_band():
    r = CheckResult("tag", "defence_overbet_p10", 0.8, (0.70, math.inf), True, 40)
    assert "[0.70, inf]" in competence.format_table([r])
