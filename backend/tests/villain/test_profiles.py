from importlib.resources import files

import numpy as np
import pytest

from poker_trainer.engine.ranges import total_weight
from poker_trainer.villain.features import HandCategory
from poker_trainer.villain.profiles import PROFILE_NAMES, Profile, load_profile

ROLES = ("cbet", "lead", "stab")
FACING = ("facing_bet", "facing_raise")


@pytest.fixture(params=PROFILE_NAMES)
def profile(request) -> Profile:
    return load_profile(request.param)


def test_all_profiles_load(profile: Profile):
    assert profile.label
    assert profile.description
    assert profile.version >= 1
    assert profile.name in PROFILE_NAMES


def test_rows_sum_to_one(profile: Profile):
    tables = [(profile.unopened[r], {"check", "bet_33", "bet_75"}) for r in ROLES]
    tables += [(profile.facing[f], {"fold", "call", "raise"}) for f in FACING]
    for table, keys in tables:
        assert set(table) == set(HandCategory)
        for row in table.values():
            assert set(row) == keys
            assert all(0.0 <= p <= 1.0 for p in row.values())
            assert sum(row.values()) == pytest.approx(1.0)


def test_nuts_never_fold(profile: Profile):
    for f in FACING:
        assert profile.facing[f][HandCategory.NUTS]["fold"] == 0


def test_leads_rare(profile: Profile):
    def mean_bet(role: str) -> float:
        rows = profile.unopened[role].values()
        return float(np.mean([1 - row["check"] for row in rows]))

    assert mean_bet("lead") < mean_bet("cbet")


def test_facing_raise_tighter(profile: Profile):
    bet, raise_ = profile.facing["facing_bet"], profile.facing["facing_raise"]
    for cat in HandCategory:
        if cat <= HandCategory.MEDIUM:
            assert raise_[cat]["fold"] >= bet[cat]["fold"], cat.name


def test_range_widths_ordered():
    opens = {n: total_weight(load_profile(n).preflop.open) for n in PROFILE_NAMES}
    assert opens["tight"] < opens["tag"] < opens["lag"]
    calls = {n: total_weight(load_profile(n).preflop.bb_call) for n in PROFILE_NAMES}
    assert max(calls, key=calls.get) == "sticky"


def test_preflop_ranges_consistent(profile: Profile):
    p = profile.preflop
    assert np.all(p.bb_call + p.bb_threebet <= 1 + 1e-9)
    assert np.all(p.btn_call_threebet + p.btn_jam <= 1 + 1e-9)


def test_unknown_profile_raises():
    with pytest.raises(ValueError):
        load_profile("maniac")


def test_profiles_ship_as_package_data():
    root = files("poker_trainer.villain") / "profiles"
    for name in PROFILE_NAMES:
        assert (root / f"{name}.json").is_file()
