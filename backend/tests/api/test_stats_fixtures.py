"""``write_stats_fixtures`` with the session's cached puzzles (fast: no seed search)."""

import json

import pytest

from poker_trainer.api import service
from poker_trainer.api.dev_fixtures import FIXED_NOW, STATS_GOAL, write_stats_fixtures
from poker_trainer.api.schemas import HistoryPage, StatsView

FILES = ("stats.json", "stats_empty.json", "history_page.json")


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_write_stats_fixtures(tmp_path, cached_puzzles):
    real_clock = service.utcnow
    puzzles = list(cached_puzzles.values())
    write_stats_fixtures(tmp_path / "a", puzzles)
    assert service.utcnow is real_clock  # the scripted clock is put back
    for name in FILES:
        assert (tmp_path / "a" / name).is_file(), name
        assert b"\r\n" not in (tmp_path / "a" / name).read_bytes()

    stats = StatsView.model_validate(_load(tmp_path / "a" / "stats.json"))
    assert len(stats.trend) == 105
    assert stats.totals.first_attempts == 105 and stats.totals.retries == 3
    assert stats.headline.ev_lost_bb_prev50 is not None
    assert stats.days.goal == STATS_GOAL == 3
    assert stats.days.current_streak > 0 and stats.days.best_streak > 0
    assert any(d.count < 3 for d in stats.days.recent)  # the scripted gap
    assert stats.days.recent[-1].date == FIXED_NOW.date().isoformat()
    assert stats.days.today > 0
    assert sum(d.count for d in stats.days.recent) > 0
    assert len(stats.breakdowns.street) >= 2
    assert {"best", "mistake"} <= {
        v for row in stats.breakdowns.street for v, c in row.verdicts.model_dump().items() if c
    }
    # the scripted answers show leaks of both kinds (the Progress page's leak list)
    assert len(stats.leaks) >= 2
    assert {leak.kind for leak in stats.leaks} == {"share", "mean"}

    empty = StatsView.model_validate(_load(tmp_path / "a" / "stats_empty.json"))
    assert empty.totals.first_attempts == 0 and empty.trend == []

    history = HistoryPage.model_validate(_load(tmp_path / "a" / "history_page.json"))
    assert history.total == 108 and len(history.items) == 25
    assert any(not item.is_first for item in history.items)  # a practice row to show

    write_stats_fixtures(tmp_path / "b", puzzles)
    for name in FILES:
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name


def test_clock_restored_when_the_factory_fails(tmp_path):
    real_clock = service.utcnow
    with pytest.raises(AttributeError):  # the factory hands out something that isn't a puzzle
        write_stats_fixtures(tmp_path, [object()])
    assert service.utcnow is real_clock
