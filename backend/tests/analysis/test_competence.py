import pytest

from poker_trainer.analysis.competence import (
    CHECK_NAMES,
    CheckResult,
    break_even_bluff_share,
    competence_report,
    main,
)
from poker_trainer.villain.profiles import PROFILE_NAMES

EXPECTED = (
    "bluff_share_33",
    "bluff_share_75",
    "defence_flop",
    "defence_turn",
    "defence_river",
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
