"""FastAPI app: JSON routes under ``/api``.

Route handlers are plain ``def`` so FastAPI runs them in its threadpool (puzzle generation is
CPU-bound). Startup migrates the database and ensures the default local user; shutdown disposes
the engine.
"""

from __future__ import annotations

import math
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import uvicorn
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from poker_trainer import __version__
from poker_trainer.api import service, views
from poker_trainer.api.schemas import AttemptIn, Health, NewPuzzleIn
from poker_trainer.api.service import PuzzleFactory, ServiceError
from poker_trainer.db.models import DEFAULT_USER_ID
from poker_trainer.db.session import (
    ensure_default_user,
    make_engine,
    make_sessionmaker,
    migrate,
)
from poker_trainer.settings import AppSettings, get_settings

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.sessionmaker() as db:
        yield db


def current_user() -> int:
    """The single local user until accounts arrive."""
    return DEFAULT_USER_ID


def get_factory(request: Request) -> PuzzleFactory:
    return request.app.state.puzzle_factory


Db = Annotated[Session, Depends(get_db)]
UserId = Annotated[int, Depends(current_user)]
Factory = Annotated[PuzzleFactory, Depends(get_factory)]

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> Health:
    return Health(status="ok", version=__version__)


@router.post("/puzzles", status_code=201)
def new_puzzle(
    db: Db, user_id: UserId, factory: Factory, body: NewPuzzleIn | None = None
) -> dict[str, Any]:
    body = body or NewPuzzleIn()
    puzzle_id, p = service.new_puzzle(
        db, user_id, factory, street=body.street, profile=body.profile
    )
    return views.puzzle_view(
        puzzle_id, p, custom_sizes_allowed=views.custom_allowed(p), attempts_so_far=0
    )


@router.post("/puzzles/{puzzle_id}/attempts", status_code=201)
def submit_attempt(puzzle_id: int, body: AttemptIn, db: Db, user_id: UserId) -> dict[str, Any]:
    row, p = service.submit_attempt(db, user_id, puzzle_id, body)
    return service.attempt_result_for(db, user_id, row, p)


@router.get("/attempts/{attempt_id}")
def get_attempt(attempt_id: int, db: Db, user_id: UserId) -> dict[str, Any]:
    row = service.load_attempt(db, user_id, attempt_id)
    return service.attempt_result_for(db, user_id, row)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _service_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ServiceError)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


def _json_safe(obj: Any) -> Any:
    """Non-finite floats become strings (a 422 echoes the rejected input, e.g. NaN)."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    return obj


def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return JSONResponse({"detail": _json_safe(jsonable_encoder(exc.errors()))}, status_code=422)


def create_app(
    settings: AppSettings | None = None, *, puzzle_factory: PuzzleFactory | None = None
) -> FastAPI:
    settings = settings if settings is not None else get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        migrate(settings.database_url)
        engine = make_engine(settings.database_url)
        try:
            app.state.sessionmaker = make_sessionmaker(engine)
            with app.state.sessionmaker() as db:
                ensure_default_user(db)
                db.commit()
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="Poker Puzzle Trainer", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.puzzle_factory = puzzle_factory or service.default_factory
    app.add_exception_handler(ServiceError, _service_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.include_router(router)
    return app


def main() -> None:
    """``uv run serve``: run the app with uvicorn on ``PPT_HOST`` / ``PPT_PORT``."""
    settings = get_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
