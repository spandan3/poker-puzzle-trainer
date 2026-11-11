"""DB plus puzzle logic behind the API routes. No FastAPI here.

Errors are ``ServiceError`` subclasses carrying an HTTP status and a ``detail`` message; the app
turns them into FastAPI's standard ``{"detail": ...}`` body. Every query filters by ``user_id``,
and another user's row is simply not found.
"""

from __future__ import annotations

import math
import secrets
from collections.abc import Callable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from poker_trainer.api.schemas import RANDOM_PROFILE, AttemptIn
from poker_trainer.api.views import (
    attempt_result,
    option_ev_from_dict,
    option_ev_to_dict,
    villain_model_current,
)
from poker_trainer.db.blob import decode_puzzle, encode_puzzle
from poker_trainer.db.models import AttemptRow, PuzzleRow, UserSettings, utcnow
from poker_trainer.game.state import Action, ActionKind, Street
from poker_trainer.puzzle.generate import generate_puzzle, parse_street
from poker_trainer.puzzle.grade import Answer, Grade, grade
from poker_trainer.puzzle.model import FORMAT, Puzzle, load_config
from poker_trainer.puzzle.options import custom_action
from poker_trainer.settings import AppSettings
from poker_trainer.villain.profiles import PROFILE_NAMES, load_profile

PuzzleFactory = Callable[[int, Street | None, str | None], Puzzle]

GENERATION_TRIES = 3
SEED_BITS = 62
MAX_ID = 2**63 - 1  # ids beyond a signed 64-bit integer can't exist (SQLite would overflow)
STALE_MODEL = (
    "Villain model changed since this puzzle was generated; custom sizes are disabled for this "
    "puzzle"
)


class ServiceError(Exception):
    status_code = 500

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFound(ServiceError):
    status_code = 404


class InvalidAnswer(ServiceError):
    status_code = 422


class StaleModel(ServiceError):
    status_code = 409


class ConcurrentSubmit(ServiceError):
    status_code = 409


class GenerationFailed(ServiceError):
    status_code = 503


class UnsupportedFormat(ServiceError):
    status_code = 500


def default_factory(seed: int, street: Street | None, profile: str | None) -> Puzzle:
    return generate_puzzle(seed, street=street, profile=profile)


def new_seed() -> int:
    return secrets.randbelow(2**SEED_BITS)


# ---------------------------------------------------------------------------
# Puzzles
# ---------------------------------------------------------------------------


_AGGRESSIVE = (ActionKind.BET, ActionKind.RAISE)


def _known_profile(name: str | None) -> str | None:
    """``name`` if it is still a profile, else None (random): a stored profile that has since
    been renamed or removed must not break generation or the settings view."""
    return name if name in PROFILE_NAMES else None


def settings_profile(db: Session, user_id: int) -> str | None:
    """The user's preferred Villain profile, or None for random (also when it no longer exists)."""
    row = db.get(UserSettings, user_id)
    return None if row is None else _known_profile(row.profile)


def new_puzzle(
    db: Session,
    user_id: int,
    factory: PuzzleFactory,
    *,
    street: str | None,
    profile: str | None,
) -> tuple[int, Puzzle]:
    """Generate and store a frozen puzzle; up to ``GENERATION_TRIES`` fresh seeds, then 503.

    ``profile`` None uses the user's settings profile (then random); ``"random"`` is random
    whatever the settings say.
    """
    if profile is None:
        profile = settings_profile(db, user_id)
    elif profile == RANDOM_PROFILE:
        profile = None
    db.rollback()  # don't hold a transaction open during CPU-bound generation
    target = None if street is None else parse_street(street)
    for _ in range(GENERATION_TRIES):
        try:
            p = factory(new_seed(), target, profile)
            break
        except RuntimeError:
            continue
    else:
        raise GenerationFailed("could not generate a puzzle, try again")

    sp = p.spot
    row = PuzzleRow(
        user_id=user_id,
        created_at=utcnow(),
        seed=sp.seed,
        street=sp.state.street.name.lower(),
        profile=sp.profile,
        profile_version=sp.profile_version,
        categories_version=sp.categories_version,
        config_version=sp.config_version,
        format=FORMAT,
        data=encode_puzzle(p),
    )
    db.add(row)
    db.commit()
    return row.id, p


def _decode(row: PuzzleRow) -> Puzzle:
    try:
        return decode_puzzle(row.data)
    except ValueError as e:
        if str(e).startswith("unsupported puzzle format"):
            raise UnsupportedFormat("unsupported puzzle format") from e
        raise


def load_puzzle(db: Session, user_id: int, puzzle_id: int) -> tuple[PuzzleRow, Puzzle]:
    if not 0 < puzzle_id <= MAX_ID:
        raise NotFound("puzzle not found")
    row = db.scalar(
        select(PuzzleRow).where(PuzzleRow.id == puzzle_id, PuzzleRow.user_id == user_id)
    )
    if row is None:
        raise NotFound("puzzle not found")
    return row, _decode(row)


def count_attempts(db: Session, user_id: int, puzzle_id: int) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(AttemptRow)
            .where(AttemptRow.puzzle_id == puzzle_id, AttemptRow.user_id == user_id)
        )
        or 0
    )


# ---------------------------------------------------------------------------
# Attempts
# ---------------------------------------------------------------------------


def _resolve_action(p: Puzzle, inp: AttemptIn) -> Action:
    """The canonical action for ``inp``: a stored option's, or ``custom_action(state, to)``.

    A custom size equal to a listed option grades as that option, even on a stale puzzle;
    any other custom size needs the puzzle's Villain model versions to be current (409).
    """
    options = p.solution.options
    if inp.option is not None:
        if inp.option >= len(options):
            raise InvalidAnswer(f"option must be in [0, {len(options) - 1}]")
        return options[inp.option].option.action
    assert inp.custom_to is not None
    try:
        action = custom_action(p.spot.state, inp.custom_to)
    except ValueError as e:
        raise InvalidAnswer(str(e)) from e
    if any(o.option.action == action for o in options):
        return action
    if not villain_model_current(p):
        raise StaleModel(STALE_MODEL)
    return action


def _check_finite(obj: Any, name: str) -> None:
    """Postgres JSON rejects NaN and responses must never carry one: fail loudly instead."""
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise ValueError(f"non-finite value in {name}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _check_finite(v, f"{name}.{k}")
    elif isinstance(obj, list | tuple):
        for v in obj:
            _check_finite(v, name)


def _action_dict(a: Action) -> dict[str, Any]:
    return {"seat": int(a.seat), "kind": a.kind.value, "street": int(a.street), "to": int(a.to)}


def _opt(x: float | None) -> float | None:
    return None if x is None else float(x)


def _grade_fields(p: Puzzle, inp: AttemptIn, action: Action, g: Grade) -> dict[str, Any]:
    """The attempt's stored columns. Inputs the grader ignores are stored as None: a range read
    on the river (it equals equity there) and an intent on a fold, check or call."""
    on_river = p.spot.state.street == Street.RIVER
    fields: dict[str, Any] = {
        "option_index": inp.option,
        "custom_to": inp.custom_to,
        "action": _action_dict(action),
        "equity_guess": float(inp.equity_guess),
        "range_read_guess": None if on_river else _opt(inp.range_read_guess),
        "intent": inp.intent if action.kind in _AGGRESSIVE else None,
        "verdict": g.verdict,
        "action_kind": g.chosen.option.action.kind.value,
        "best_kind": g.best.option.action.kind.value,
        "ev_loss_chips": float(g.ev_loss_chips),
        "equity_error": float(g.equity_error),
        "equity_score": g.equity_score,
        "range_read_error": _opt(g.range_read_error),
        "range_read_score": g.range_read_score,
        "intent_truth": g.intent_truth,
        "intent_flag": g.intent_flag,
        "bluff_required": None if g.bluff_check is None else float(g.bluff_check[0]),
        "bluff_actual": None if g.bluff_check is None else float(g.bluff_check[1]),
        "chosen": option_ev_to_dict(g.chosen),
        "chosen_label": g.chosen.option.label,
        "best_label": g.best.option.label,
        "best_ev_chips": float(g.best.ev_chips),
        "config_version": load_config().version,
    }
    _check_finite(fields, "attempt")
    return fields


def _next_attempt_no(db: Session, puzzle_id: int) -> int:
    last = db.scalar(
        select(func.max(AttemptRow.attempt_no)).where(AttemptRow.puzzle_id == puzzle_id)
    )
    return (last or 0) + 1


def submit_attempt(
    db: Session, user_id: int, puzzle_id: int, inp: AttemptIn
) -> tuple[AttemptRow, Puzzle]:
    """Grade ``inp`` against the stored puzzle and store the attempt with its full grade.

    ``attempt_no`` is max + 1 inside the transaction; the unique ``(puzzle_id, attempt_no)``
    constraint catches a concurrent submit, which is retried once. Returns the stored row and
    the decoded puzzle, so the caller needn't decode the blob again.
    """
    _, p = load_puzzle(db, user_id, puzzle_id)
    action = _resolve_action(p, inp)
    try:
        g = grade(p, Answer(action, inp.equity_guess, inp.range_read_guess, inp.intent))
    except ValueError as e:
        raise InvalidAnswer(str(e)) from e
    fields = _grade_fields(p, inp, action, g)

    for retry in (False, True):
        no = _next_attempt_no(db, puzzle_id)
        row = AttemptRow(
            user_id=user_id,
            puzzle_id=puzzle_id,
            attempt_no=no,
            is_first=no == 1,
            created_at=utcnow(),
            **fields,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if retry:
                raise ConcurrentSubmit("concurrent submit, try again") from None
            continue
        return row, p
    raise AssertionError("unreachable")


def load_attempt(db: Session, user_id: int, attempt_id: int) -> AttemptRow:
    if not 0 < attempt_id <= MAX_ID:
        raise NotFound("attempt not found")
    row = db.scalar(
        select(AttemptRow).where(AttemptRow.id == attempt_id, AttemptRow.user_id == user_id)
    )
    if row is None:
        raise NotFound("attempt not found")
    return row


def attempt_dict(row: AttemptRow) -> dict[str, Any]:
    """The stored row in the shape ``views.attempt_result`` expects."""
    return {
        "id": row.id,
        "puzzle_id": row.puzzle_id,
        "attempt_no": row.attempt_no,
        "is_first": row.is_first,
        "created_at": row.created_at.isoformat(),
        "option_index": row.option_index,
        "custom_to": row.custom_to,
        "action": row.action,
        "equity_guess": row.equity_guess,
        "range_read_guess": row.range_read_guess,
        "intent": row.intent,
        "verdict": row.verdict,
        "ev_loss_chips": row.ev_loss_chips,
        "equity_error": row.equity_error,
        "equity_score": row.equity_score,
        "range_read_error": row.range_read_error,
        "range_read_score": row.range_read_score,
        "intent_truth": row.intent_truth,
        "intent_flag": row.intent_flag,
        "bluff_required": row.bluff_required,
        "bluff_actual": row.bluff_actual,
        "best_label": row.best_label,
    }


def attempt_result_for(
    db: Session, user_id: int, row: AttemptRow, puzzle: Puzzle | None = None
) -> dict[str, Any]:
    """The full stored result: never regraded, built from the row plus the frozen puzzle."""
    p = load_puzzle(db, user_id, row.puzzle_id)[1] if puzzle is None else puzzle
    return attempt_result(
        attempt=attempt_dict(row), puzzle=p, chosen=option_ev_from_dict(row.chosen)
    )


# ---------------------------------------------------------------------------
# Replay, history
# ---------------------------------------------------------------------------


def current_puzzle(db: Session, user_id: int) -> tuple[int, Puzzle]:
    """The user's newest puzzle if it is still unanswered (to resume after a reload), else 404.

    Only the newest puzzle counts: an older unanswered puzzle was skipped by asking for a new
    one, and must not come back.
    """
    pid = db.scalar(
        select(PuzzleRow.id)
        .where(PuzzleRow.user_id == user_id)
        .order_by(PuzzleRow.id.desc())
        .limit(1)
    )
    if pid is None or count_attempts(db, user_id, pid) > 0:
        raise NotFound("no unanswered puzzle")
    return pid, load_puzzle(db, user_id, pid)[1]


def _summary(m: Any) -> dict[str, Any]:
    return {
        "attempt_id": m.id,
        "puzzle_id": m.puzzle_id,
        "attempt_no": m.attempt_no,
        "is_first": m.is_first,
        "created_at": m.created_at.isoformat(),
        "street": m.street,
        "profile": m.profile,
        "chosen_label": m.chosen_label,
        "action_kind": m.action_kind,
        "best_label": m.best_label,
        "best_kind": m.best_kind,
        "verdict": m.verdict,
        "ev_loss_bb": m.ev_loss_chips / 2,
        "equity_error": m.equity_error,
        "range_read_error": m.range_read_error,
    }


def _summary_query(user_id: int) -> Any:
    """Attempt columns joined to the puzzle's street and profile; never the puzzle blob, nor
    the ``chosen`` JSON (about 20 KB per bet option)."""
    return (
        select(
            AttemptRow.id,
            AttemptRow.puzzle_id,
            AttemptRow.attempt_no,
            AttemptRow.is_first,
            AttemptRow.created_at,
            AttemptRow.chosen_label,
            AttemptRow.action_kind,
            AttemptRow.best_label,
            AttemptRow.best_kind,
            AttemptRow.verdict,
            AttemptRow.ev_loss_chips,
            AttemptRow.equity_error,
            AttemptRow.range_read_error,
            PuzzleRow.street,
            PuzzleRow.profile,
        )
        .join(PuzzleRow, PuzzleRow.id == AttemptRow.puzzle_id)
        .where(AttemptRow.user_id == user_id, PuzzleRow.user_id == user_id)
    )


def puzzle_attempts(db: Session, user_id: int, puzzle_id: int) -> list[dict[str, Any]]:
    """Attempt summaries of one puzzle, oldest first (404 if it isn't the user's)."""
    if not 0 < puzzle_id <= MAX_ID:
        raise NotFound("puzzle not found")
    owned = db.scalar(
        select(PuzzleRow.id).where(PuzzleRow.id == puzzle_id, PuzzleRow.user_id == user_id)
    )
    if owned is None:
        raise NotFound("puzzle not found")
    q = _summary_query(user_id).where(AttemptRow.puzzle_id == puzzle_id)
    return [_summary(m) for m in db.execute(q.order_by(AttemptRow.attempt_no)).all()]


def history(
    db: Session,
    user_id: int,
    *,
    limit: int,
    offset: int,
    first_only: bool,
    street: str | None = None,
    verdict: str | None = None,
    action_kind: str | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    """Attempt summaries, newest first. Every filter is optional and they combine with AND."""
    q = _summary_query(user_id)
    if first_only:
        q = q.where(AttemptRow.is_first.is_(True))
    if street is not None:
        q = q.where(PuzzleRow.street == street)
    if verdict is not None:
        q = q.where(AttemptRow.verdict == verdict)
    if action_kind is not None:
        q = q.where(AttemptRow.action_kind == action_kind)
    if profile is not None:
        q = q.where(PuzzleRow.profile == profile)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0  # same rows as items
    rows = db.execute(q.order_by(AttemptRow.id.desc()).limit(limit).offset(offset)).all()
    return {"items": [_summary(m) for m in rows], "total": total}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def _settings_row(db: Session, user_id: int) -> UserSettings:
    row = db.get(UserSettings, user_id)
    if row is None:
        row = UserSettings(user_id=user_id)
        db.add(row)
        db.flush()
    return row


def settings_view(db: Session, user_id: int, app_settings: AppSettings) -> dict[str, Any]:
    row = _settings_row(db, user_id)
    profiles = []
    for name in PROFILE_NAMES:
        prof = load_profile(name)
        profiles.append({"name": name, "label": prof.label, "description": prof.description})
    return {
        "show_pot_odds": bool(row.show_pot_odds),
        "show_profile": bool(row.show_profile),
        "profile": _known_profile(row.profile),
        "daily_goal": int(row.daily_goal),
        "llm_provider": app_settings.llm_provider,
        "llm_status": "off" if app_settings.llm_provider == "none" else "on",
        "profiles": profiles,
    }


def patch_settings(db: Session, user_id: int, changes: dict[str, Any]) -> None:
    """Apply only the fields the client sent; an empty patch changes nothing."""
    row = _settings_row(db, user_id)
    for key, value in changes.items():
        setattr(row, key, value)
    if changes:
        row.updated_at = utcnow()
    db.commit()
