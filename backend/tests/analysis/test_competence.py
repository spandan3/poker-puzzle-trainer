import numpy as np
import pytest

from poker_trainer.analysis import competence
from poker_trainer.analysis.competence import (
    CHECK_NAMES,
    INFO_NAMES,
    MIN_SAMPLES,
    CheckResult,
    break_even_bluff_share,
    competence_report,
    main,
    preflop_defence,
)
from poker_trainer.engine.cards import parse_cards
from poker_trainer.game.state import (
    Action,
    ActionKind,
    HandState,
    Street,
    apply,
    deal,
    legal_actions,
    new_hand,
    total_pot,
)
from poker_trainer.villain import strategy
from poker_trainer.villain.features import HandCategory
from poker_trainer.villain.profiles import PROFILE_NAMES, load_profile

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
    "defence_overbet",
    "raise_dominated",
    "preflop_defence_3bet",
)


def test_report_shape():
    report = competence_report("tag", n_hands=40)
    assert CHECK_NAMES == EXPECTED
    assert "preflop_defence_open" in INFO_NAMES
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


# Every check must pass on every seed of the report (`competence --seeds 0-5`); the slow
# suite runs two of them.
SLOW_SEEDS = (0, 3)


@pytest.fixture(scope="module")
def full_reports() -> dict[int, dict[str, list[CheckResult]]]:
    return {
        seed: {p: competence_report(p, n_hands=400, seed=seed) for p in PROFILE_NAMES}
        for seed in SLOW_SEEDS
    }


@pytest.mark.slow
@pytest.mark.parametrize("seed", SLOW_SEEDS)
@pytest.mark.parametrize("profile", PROFILE_NAMES)
def test_all_profiles_competent(full_reports, profile, seed):
    failed = [r for r in full_reports[seed][profile] if not r.passed and not r.info]
    assert not failed, failed


@pytest.mark.slow
@pytest.mark.parametrize("seed", SLOW_SEEDS)
def test_cbet_flop_ordering(full_reports, seed):
    cbet = {
        p: next(r.value for r in rs if r.name == "cbet_flop")
        for p, rs in full_reports[seed].items()
    }
    assert cbet["lag"] > cbet["tag"] > cbet["tight"], cbet


# ---------------------------------------------------------------------------
# M9 checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_preflop_defence_values(name):
    """Both ratios recomputed from the profile's range arrays and the stated MDFs."""
    pf = load_profile(name).preflop
    # BB vs a 2.5x open (to 5): 3 to call into 4 -> MDF 4/7; uniform over all combos.
    bb_continue = np.minimum(pf.bb_call + pf.bb_threebet, 1.0)
    open_ratio = float(bb_continue.mean()) / (4 / 7)
    # BTN vs a 3x 3-bet (to 15): 10 to call into 10 -> MDF 0.50; weighted by the open.
    btn_continue = np.minimum(pf.btn_call_threebet + pf.btn_jam, 1.0)
    threebet_ratio = float(pf.open @ btn_continue) / float(pf.open.sum()) / 0.50
    got_open, got_3bet = preflop_defence(load_profile(name))
    assert got_open == pytest.approx(open_ratio, abs=1e-9)
    assert got_3bet == pytest.approx(threebet_ratio, abs=1e-9)


def test_preflop_defence_in_report():
    report = {r.name: r for r in competence_report("tight", n_hands=4)}
    r = report["preflop_defence_3bet"]
    assert r.band == (0.90, 1.40)
    assert r.samples == 1326
    assert r.value == pytest.approx(preflop_defence(load_profile("tight"))[1])


def _flop_hero_unopened():
    """Villain (seat 0) on the button opens, Hero (BB) calls; Hero acts first on the flop."""
    s = new_hand(0)
    s = apply(s, strategy.raise_to(s, strategy.OPEN_MULT))
    s = apply(s, Action(1, ActionKind.CALL, Street.PREFLOP, 5))
    return deal(s, parse_cards("Kh7d2c"))


def _call_everything(real):
    """Real distributions, except that a seat facing a bet calls with every combo."""

    def fake(profile, s):
        dist = real(profile, s)
        if s.street == Street.PREFLOP or not strategy.role(s).startswith("facing"):
            return dist
        me = s.to_act
        call = Action(me, ActionKind.CALL, s.street, s.street_bets[me] + legal_actions(s).call)
        return {call: sum(dist.values())}

    return fake


def test_defence_overbet_probes_1_5_2_and_2_5_pot(monkeypatch):
    real = strategy.action_distribution
    monkeypatch.setattr(competence, "action_distribution", _call_everything(real))
    s = _flop_hero_unopened()
    live, cats = competence._board_info(s.board)
    tag = load_profile("tag")
    out: list = []
    competence._probe_records(out, s, tag, tag, live.copy(), live.copy(), cats)
    over = [r for r in out if r[0] == "defence_overbet"]
    assert competence._OVERBETS == (1.5, 2.0, 2.5)
    assert len(over) == 3  # one record per size, each weight 1
    for frac, (_, num, den, counted) in zip(competence._OVERBETS, over, strict=True):
        probe = apply(s, strategy.bet_to(s, frac))
        call = legal_actions(probe).call
        prior = total_pot(probe) - call
        assert prior == total_pot(s)
        assert call == round(frac * total_pot(s))  # not clamped to all-in on this pot
        mdf = prior / (prior + call)
        assert counted and den == 1.0
        assert num == pytest.approx(1.0 / mdf)
    # The overbet probes feed no other check: the max checks see only the 33/75/100% probes.
    assert sum(1 for r in out if r[0] == "nuts_fold_max") == 3


def test_defence_overbet_sizes_clamped_to_the_same_jam_count_once(monkeypatch):
    real = strategy.action_distribution
    monkeypatch.setattr(competence, "action_distribution", _call_everything(real))
    s = _flop_hero_unopened()
    s = HandState(**{**s.__dict__, "stacks": (12, 12), "total_chips": s.pot + 24})
    live, cats = competence._board_info(s.board)
    tag = load_profile("tag")
    out: list = []
    competence._probe_records(out, s, tag, tag, live.copy(), live.copy(), cats)
    jams = {strategy.bet_to(s, f) for f in competence._OVERBETS}
    assert len(jams) == 1  # every size is the 12-chip jam
    assert sum(1 for r in out if r[0] == "defence_overbet") == 1


def _river_hero_unopened():
    s = _flop_hero_unopened()
    s = apply(s, Action(1, ActionKind.CHECK, Street.FLOP))
    s = apply(s, Action(0, ActionKind.CHECK, Street.FLOP))
    s = deal(s, parse_cards("4s"))
    s = apply(s, Action(1, ActionKind.CHECK, Street.TURN))
    s = apply(s, Action(0, ActionKind.CHECK, Street.TURN))
    return deal(s, parse_cards("9c"))


def test_raise_dominated_counts_value_raises_only(monkeypatch):
    s = _river_hero_unopened()
    live, cats = competence._board_info(s.board)
    bet = strategy.bet_to(s, 0.33)
    probe = apply(s, bet)
    raise_ = strategy.raise_to(probe, strategy.RAISE_MULT)
    call = Action(0, ActionKind.CALL, Street.RIVER, bet.to)

    medium = cats == HandCategory.MEDIUM
    strong = cats == HandCategory.STRONG
    air = cats == HandCategory.AIR
    # Villain raises every MEDIUM, STRONG and AIR combo and calls with the rest.
    raising = (medium | strong | air).astype(float)
    villain_dist = {call: live - raising, raise_: raising}
    # Equity vs Hero's calling range: half the MEDIUMs are dominated (0.3), half are not
    # (0.45); STRONG 0.8; AIR 0.1 (a bluff raise: never counted as dominated value).
    low = np.zeros(len(cats), dtype=bool)
    low[np.flatnonzero(medium)[::2]] = True
    eq = np.where(strong, 0.8, np.where(air, 0.1, np.where(low, 0.3, 0.45)))
    seen_opp: list[np.ndarray] = []

    def fake_equity(board, opp):
        seen_opp.append(opp)
        return eq

    monkeypatch.setattr(competence, "river_equity", fake_equity)
    hero_call = Action(1, ActionKind.CALL, Street.RIVER, raise_.to)
    hero_fold = Action(1, ActionKind.FOLD, Street.RIVER)
    # Hero calls the raise with every combo below index 600 and folds the rest.
    calls = live * (np.arange(len(cats)) < 600)

    def fake(profile, st):
        assert st == apply(probe, raise_)
        return {hero_call: calls, hero_fold: live - calls}

    monkeypatch.setattr(competence, "action_distribution", fake)
    hero_bettors = live * 0.5  # Hero's range times its probability of making this bet
    villain = live * 3.0  # tracked weights need not sum to 1
    out: list = []
    competence._raise_records(
        out, probe, villain_dist, load_profile("tag"), villain, hero_bettors, cats, 0.4
    )
    assert len(out) == 1
    name, num, den, counted = out[0]
    assert name == "raise_dominated"
    total = float(villain.sum())
    assert num == pytest.approx(0.4 * float(villain[low].sum()) / total)
    assert den == pytest.approx(0.4 * float(villain[medium | strong | air].sum()) / total)
    assert counted  # weight 0.4 >= MIN_PROBE_WEIGHT
    # Equity is against the bettors that call the raise.
    np.testing.assert_allclose(seen_opp[0], hero_bettors * calls)


def test_raise_dominated_below_min_samples_is_info():
    report = {r.name: r for r in competence_report("tag", n_hands=10)}
    r = report["raise_dominated"]
    assert r.samples < MIN_SAMPLES
    assert r.info and not r.passed
    assert not any(x.info for x in report.values() if x.name != "raise_dominated")


def test_cli_seeds_summary(capsys):
    code = main(["--profile", "tag", "--hands", "40", "--seeds", "0,1"])
    assert code in (0, 1)
    out = capsys.readouterr().out
    assert out.count("seed 0") == 1 and out.count("seed 1") == 1
    assert out.count("defence_overbet") >= 3  # two tables and the summary
    summary = out[out.index("summary") :]
    header = summary.splitlines()[1]
    assert "min" in header and "max" in header


def test_parse_seeds():
    assert competence.parse_seeds("0-5") == [0, 1, 2, 3, 4, 5]
    assert competence.parse_seeds("0,3") == [0, 3]
    assert competence.parse_seeds("2") == [2]
