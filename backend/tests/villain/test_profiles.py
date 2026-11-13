import copy
import json
from importlib.resources import files

import numpy as np
import pytest

from poker_trainer.engine.ranges import parse_range, total_weight
from poker_trainer.villain.features import HandCategory
from poker_trainer.villain.profiles import (
    PROFILE_NAMES,
    Profile,
    _profile_from_dict,
    load_profile,
)

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
    # Later spots are conditional on reaching them: no weight outside the parent range.
    for child in (p.btn_call_threebet, p.btn_jam, p.btn_call_jam):
        assert not np.any((child > 0) & (p.open == 0))
    assert not np.any((p.bb_call_jam > 0) & (p.bb_threebet == 0))


def test_btn_jam_is_value_only(profile: Profile):
    # A 100bb jam over a 3-bet risks ~97.5bb to win ~10bb, so bluffs need ~91% folds.
    value = parse_range("TT+, AQs+, AKo")
    jam = profile.preflop.btn_jam
    assert not np.any((jam > 0) & (value == 0))


def test_tables_are_immutable(profile: Profile):
    with pytest.raises(TypeError):
        profile.unopened["cbet"][HandCategory.AIR]["check"] = 0.0  # type: ignore[index]
    with pytest.raises(TypeError):
        profile.facing["facing_bet"][HandCategory.AIR] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        profile.unopened["lead"] = {}  # type: ignore[index]
    with pytest.raises(ValueError):
        profile.preflop.open[0] = 1.0
    with pytest.raises(TypeError):
        profile.river_unopened["cbet"][HandCategory.AIR]["check"] = 0.0  # type: ignore[index]


def _raw(name: str = "tag") -> dict:
    text = (files("poker_trainer.villain") / "profiles" / f"{name}.json").read_text(
        encoding="utf-8"
    )
    return json.loads(text)


def test_loader_accepts_raw_profile():
    assert _profile_from_dict("tag", _raw()).version == 4


def test_bad_row_sum_raises():
    raw = copy.deepcopy(_raw())
    raw["unopened"]["cbet"]["AIR"]["check"] = 0.9
    with pytest.raises(ValueError, match="cbet.AIR"):
        _profile_from_dict("tag", raw)


def test_missing_category_raises():
    raw = copy.deepcopy(_raw())
    del raw["facing"]["facing_bet"]["NUTS"]
    with pytest.raises(ValueError, match="facing_bet"):
        _profile_from_dict("tag", raw)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.pop("preflop"),
        lambda r: r["preflop"].pop("btn_jam"),
        lambda r: r["bands"].update(bluff_offset=[0.1]),
        lambda r: r["bands"].update(defence_ratio=[1.2, 0.8]),
        lambda r: r["facing"].pop("facing_raise"),
        lambda r: r.update(version=0),
        lambda r: r["river_unopened"].update(facing_bet={}),
        lambda r: r["river_unopened"]["cbet"].update(BOGUS={}),
        lambda r: r["river_unopened"]["cbet"]["AIR"].update(check=0.5),
        lambda r: r["river_unopened"]["cbet"]["AIR"].pop("bet_75"),
    ],
)
def test_structural_errors_raise_value_error(mutate):
    raw = copy.deepcopy(_raw())
    mutate(raw)
    with pytest.raises(ValueError):
        _profile_from_dict("tag", raw)


def test_unknown_profile_raises():
    with pytest.raises(ValueError):
        load_profile("maniac")


def test_profiles_ship_as_package_data():
    root = files("poker_trainer.villain") / "profiles"
    for name in PROFILE_NAMES:
        assert (root / f"{name}.json").is_file()


def test_river_overrides_optional():
    raw = copy.deepcopy(_raw())
    del raw["river_unopened"]
    assert dict(_profile_from_dict("tag", raw).river_unopened) == {}


def test_river_overrides_partial(profile: Profile):
    for role, rows in profile.river_unopened.items():
        assert role in ROLES
        for row in rows.values():
            assert sum(row.values()) == pytest.approx(1.0)


def test_profile_meta_known():
    from poker_trainer.villain.profiles import profile_meta

    assert profile_meta("tag") == (load_profile("tag").label, load_profile("tag").description)


def test_profile_meta_unknown():
    from poker_trainer.villain.profiles import profile_meta

    assert profile_meta("maniac") == ("Maniac", "")
