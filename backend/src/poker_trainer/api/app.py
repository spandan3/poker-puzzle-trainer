"""FastAPI app: JSON routes under ``/api``.

Route handlers are plain ``def`` so FastAPI runs them in its threadpool (puzzle generation is
CPU-bound). Startup migrates the database and ensures the default local user; shutdown disposes
the engine.
"""

from __future__ import annotations

import math
import mimetypes
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from poker_trainer import __version__
from poker_trainer.api import service, views
from poker_trainer.api.schemas import AttemptIn, Health, NewPuzzleIn, SettingsPatch
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


def _puzzle_view(db: Session, user_id: int, puzzle_id: int, p: Any) -> dict[str, Any]:
    return views.puzzle_view(
        puzzle_id,
        p,
        custom_sizes_allowed=views.custom_allowed(p),
        attempts_so_far=service.count_attempts(db, user_id, puzzle_id),
    )


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


@router.get("/puzzles/current")  # before /puzzles/{puzzle_id}
def current_puzzle(db: Db, user_id: UserId) -> dict[str, Any]:
    puzzle_id, p = service.current_puzzle(db, user_id)
    return _puzzle_view(db, user_id, puzzle_id, p)


@router.get("/puzzles/{puzzle_id}")
def get_puzzle(puzzle_id: int, db: Db, user_id: UserId) -> dict[str, Any]:
    _, p = service.load_puzzle(db, user_id, puzzle_id)
    return _puzzle_view(db, user_id, puzzle_id, p)


@router.get("/puzzles/{puzzle_id}/attempts")
def puzzle_attempts(puzzle_id: int, db: Db, user_id: UserId) -> list[dict[str, Any]]:
    return service.puzzle_attempts(db, user_id, puzzle_id)


@router.post("/puzzles/{puzzle_id}/attempts", status_code=201)
def submit_attempt(puzzle_id: int, body: AttemptIn, db: Db, user_id: UserId) -> dict[str, Any]:
    row, p = service.submit_attempt(db, user_id, puzzle_id, body)
    return service.attempt_result_for(db, user_id, row, p)


@router.get("/attempts/{attempt_id}")
def get_attempt(attempt_id: int, db: Db, user_id: UserId) -> dict[str, Any]:
    row = service.load_attempt(db, user_id, attempt_id)
    return service.attempt_result_for(db, user_id, row)


@router.get("/history")
def history(
    db: Db,
    user_id: UserId,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    first_only: bool = False,
) -> dict[str, Any]:
    return service.history(db, user_id, limit=limit, offset=offset, first_only=first_only)


@router.get("/settings")
def get_user_settings(request: Request, db: Db, user_id: UserId) -> dict[str, Any]:
    return service.settings_view(db, user_id, request.app.state.settings)


@router.patch("/settings")
def patch_user_settings(
    body: SettingsPatch, request: Request, db: Db, user_id: UserId
) -> dict[str, Any]:
    changes = {k: getattr(body, k) for k in body.model_fields_set}
    service.patch_settings(db, user_id, changes)
    return service.settings_view(db, user_id, request.app.state.settings)


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------

# The Windows registry can map .js to text/plain, and browsers refuse module scripts served so.
for _type, _ext in (("text/javascript", ".js"), ("text/javascript", ".mjs"), ("text/css", ".css")):
    mimetypes.add_type(_type, _ext)


def _frontend_route(dist: Path) -> Any:
    """Catch-all GET: a file inside ``dist``, else ``index.html`` (SPA routing).

    Every candidate path is resolved and must lie inside the resolved ``dist``, so no
    traversal (``..``, encoded separators, symlinks) can reach a file outside it.
    """
    root = dist.resolve()

    def frontend(full_path: str) -> Any:
        rel = full_path.lstrip("/")
        if rel == "api" or rel.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        index = root / "index.html"
        if not index.is_file():
            return JSONResponse({"detail": "frontend not built"}, status_code=404)
        if rel:
            try:
                candidate = (root / rel).resolve()
                if candidate.is_relative_to(root) and candidate.is_file():
                    return FileResponse(candidate)
            except (OSError, ValueError):  # e.g. a name too long, a null byte
                pass
        return FileResponse(index)

    return frontend


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
    app.add_api_route(
        "/{full_path:path}",
        _frontend_route(settings.frontend_dist),
        methods=["GET", "HEAD"],
        include_in_schema=False,
    )
    return app


def main() -> None:
    """``uv run serve``: run the app with uvicorn on ``PPT_HOST`` / ``PPT_PORT``."""
    settings = get_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
