import re

import numpy as np
import pytest

from poker_trainer.engine.cards import parse_card, parse_cards
from poker_trainer.engine.combos import combo_index
from poker_trainer.engine.ranges import (
    class_grid,
    empty_range,
    full_range,
    parse_range,
    remove_blocked,
    total_weight,
)


def n_nonzero(r):
    return int(np.count_nonzero(r))


def test_basic_ranges():
    assert empty_range().shape == (1326,) and total_weight(empty_range()) == 0.0
    assert total_weight(full_range()) == 1326.0
    assert full_range().dtype == np.float64


def test_parse_pairs_plus():
    r = parse_range("QQ+")
    assert n_nonzero(r) == 18 and total_weight(r) == 18.0


def test_parse_suited_plus():
    assert n_nonzero(parse_range("ATs+")) == 16


def test_parse_offsuit_plus_and_both_plus():
    assert n_nonzero(parse_range("KTo+")) == 36  # KTo KJo KQo
    assert n_nonzero(parse_range("AT+")) == 4 * 16  # 4 classes x (4 + 12)


def test_parse_dash():
    assert n_nonzero(parse_range("A2s-A5s")) == 16
    assert n_nonzero(parse_range("22-44")) == 18


def test_dash_either_order():
    assert np.array_equal(parse_range("A5s-A2s"), parse_range("A2s-A5s"))
    assert np.array_equal(parse_range("44-22"), parse_range("22-44"))


@pytest.mark.parametrize("tok", ["A2s-K5s", "A2s-A5o", "22-A5s", "AKs-AQo"])
def test_dash_mismatch(tok):
    with pytest.raises(ValueError, match=re.escape(tok)):
        parse_range(tok)


def test_parse_specific_and_weight():
    r = parse_range("AhKh, AKo:0.5")
    assert r[combo_index(parse_card("Ah"), parse_card("Kh"))] == 1.0
    ako = [i for i in range(1326) if r[i] == 0.5]
    assert len(ako) == 12
    assert total_weight(r) == 7.0


def test_specific_case_and_weight():
    r = parse_range("ahKH:0.25")
    assert n_nonzero(r) == 1 and total_weight(r) == 0.25


def test_later_token_overwrites():
    r = parse_range("AA, AA:0.5")
    assert total_weight(r) == 3.0
    r = parse_range("AKo:0.5, AK")
    assert total_weight(r) == 16.0


def test_parse_whitespace_case():
    assert np.array_equal(parse_range(" qq+ , aks "), parse_range("QQ+,AKs"))


def test_empty_and_trailing_comma():
    assert total_weight(parse_range("")) == 0.0
    assert total_weight(parse_range("  ")) == 0.0
    assert np.array_equal(parse_range("AA,"), parse_range("AA"))
    assert np.array_equal(parse_range("AA,,KK"), parse_range("AA,KK"))


@pytest.mark.parametrize(
    "tok", ["AKx", "AK:1.5", "AK:-0.1", "AK:abc", "ZZ", "AhKh+", "AA:", "AKs+-"]
)
def test_parse_invalid_token(tok):
    with pytest.raises(ValueError, match=re.escape(tok.split(":")[0])):
        parse_range(tok)


def test_weight_bounds_ok():
    assert total_weight(parse_range("AA:0")) == 0.0
    assert total_weight(parse_range("AA:1")) == 6.0


def test_remove_blocked():
    r = parse_range("AA")
    before = r.copy()
    out = remove_blocked(r, parse_cards("Ah"))
    assert total_weight(out) == 3.0
    assert np.array_equal(r, before)
    assert out is not r


def test_class_grid():
    g = class_grid(parse_range("AKs"))
    assert g.shape == (13, 13)
    assert g[0, 1] == 1.0 and g[1, 0] == 0.0
    assert class_grid(parse_range("AhKh"))[0, 1] == 0.25
