"""Rule-based leaks over the newest first attempts. Stub until the rules land (M7 Task 3)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from poker_trainer.stats.service import StatRow


def detect(rows: Sequence[StatRow]) -> list[dict[str, Any]]:
    """``Leak``-shaped dicts for ``rows`` (every attempt; only first attempts will count)."""
    return []
