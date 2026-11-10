import pytest

from poker_trainer.analysis.competence import CHECK_NAMES, CheckResult, competence_report, main
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


@pytest.mark.slow
@pytest.mark.parametrize("profile", PROFILE_NAMES)
def test_all_profiles_competent(profile):
    failed = [r for r in competence_report(profile, n_hands=400) if not r.passed]
    assert not failed, failed
