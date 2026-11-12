"""API fixtures: an app over a tmp-path SQLite file with a cached ``puzzle_factory``."""

import pytest
from fastapi.testclient import TestClient

from poker_trainer.api.app import create_app
from poker_trainer.db import make_engine, make_sessionmaker
from poker_trainer.puzzle.generate import generate_puzzle
from poker_trainer.settings import AppSettings

# Fixed seeds, generated once per session; the factory hands them out by street.
API_SEEDS = {
    "preflop": (1, "preflop"),  # BTN first in: no call option
    "pre_facing": (3, "preflop"),  # facing a raise: has a call option
    "flop": (1, "flop"),  # custom sizes in [2, 195]
    "turn": (1, "turn"),
    "river": (1, "river"),
}


@pytest.fixture(scope="session")
def cached_puzzles():
    return {k: generate_puzzle(seed, street=st) for k, (seed, st) in API_SEEDS.items()}


class CachedFactory:
    """``PuzzleFactory`` returning cached puzzles by street (``None`` -> flop).

    Records every call; ``fail`` makes the next N calls raise ``RuntimeError``.
    """

    def __init__(self, by_street):
        self.by_street = dict(by_street)
        self.calls = []
        self.fail = 0

    def __call__(self, seed, street, profile):
        self.calls.append((seed, street, profile))
        if self.fail > 0:
            self.fail -= 1
            raise RuntimeError("no puzzle")
        return self.by_street["flop" if street is None else street.name.lower()]


@pytest.fixture
def factory(cached_puzzles):
    return CachedFactory({k: cached_puzzles[k] for k in ("preflop", "flop", "turn", "river")})


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite:///{(tmp_path / 'api.db').as_posix()}"


# Every LLM setting explicit: a PPT_LLM_* variable on a dev machine must not reach the tests.
LLM_OFF = {
    "llm_provider": "none",
    "ollama_url": "http://127.0.0.1:11434",
    "ollama_model": "llama3.2:3b",
    "llm_timeout": 60.0,
}


@pytest.fixture
def llm_off():
    """``LLM_OFF`` for test modules that build their own ``AppSettings``."""
    return dict(LLM_OFF)


@pytest.fixture
def client(db_url, factory):
    app = create_app(
        AppSettings(_env_file=None, database_url=db_url, **LLM_OFF), puzzle_factory=factory
    )
    with TestClient(app) as c:
        yield c


@pytest.fixture
def sessions(client, db_url):
    """Direct DB access to the app's database (after the app has migrated it)."""
    engine = make_engine(db_url)
    yield make_sessionmaker(engine)
    engine.dispose()
