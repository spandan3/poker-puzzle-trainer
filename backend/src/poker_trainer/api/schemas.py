"""Pydantic request/response models for the JSON API.

Request models forbid unknown fields, so a client can never send an ``Action`` or a seed.
Floats from the client must be finite and in [0, 1].
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from poker_trainer.villain.profiles import PROFILE_NAMES

StreetName = Literal["preflop", "flop", "turn", "river"]
IntentName = Literal["value", "bluff", "semi_bluff"]
Probability = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]


class Health(BaseModel):
    status: Literal["ok"]
    version: str


class NewPuzzleIn(BaseModel):
    """Both optional: a null street is random; a null profile uses the settings, then random."""

    model_config = ConfigDict(extra="forbid")

    street: StreetName | None = None
    profile: str | None = None

    @field_validator("profile")
    @classmethod
    def _known_profile(cls, v: str | None) -> str | None:
        if v is not None and v not in PROFILE_NAMES:
            raise ValueError(f"unknown profile {v!r}; expected one of {list(PROFILE_NAMES)}")
        return v


class AttemptIn(BaseModel):
    """An answer: exactly one of ``option`` (index into the stored options) or ``custom_to``."""

    model_config = ConfigDict(extra="forbid")

    # strict: a JSON true, "1" or 1.0 is not an option index or a chip count
    option: Annotated[int, Field(ge=0, strict=True)] | None = None
    custom_to: Annotated[int, Field(gt=0, strict=True)] | None = None
    equity_guess: Probability
    range_read_guess: Probability | None = None
    intent: IntentName | None = None

    @model_validator(mode="after")
    def _exactly_one_action(self) -> AttemptIn:
        if (self.option is None) == (self.custom_to is None):
            raise ValueError("give exactly one of option or custom_to")
        return self


class SettingsPatch(BaseModel):
    """Partial update: only fields the client sent are applied (``profile: null`` = random)."""

    model_config = ConfigDict(extra="forbid")

    # strict: a JSON 1 or "false" is not a toggle, 1.0 or "10" not a goal
    show_pot_odds: Annotated[bool, Field(strict=True)] = True
    show_profile: Annotated[bool, Field(strict=True)] = True
    profile: str | None = None
    daily_goal: Annotated[int, Field(ge=1, le=500, strict=True)] = 10

    @field_validator("profile")
    @classmethod
    def _known_profile(cls, v: str | None) -> str | None:
        if v is not None and v not in PROFILE_NAMES:
            raise ValueError(f"unknown profile {v!r}; expected one of {list(PROFILE_NAMES)}")
        return v
