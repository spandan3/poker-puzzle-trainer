"""Pydantic request/response models for the JSON API.

Request models forbid unknown fields, so a client can never send an ``Action`` or a seed.
Floats from the client must be finite and in [0, 1].

Response models describe the dicts ``api/views.py`` and ``api/service.py`` build, so
``/openapi.json`` carries every response shape (the frontend's types are generated from it).
They also forbid extra fields: a key added to a view without its model fails the tests (a
response validation error) instead of being silently dropped.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from poker_trainer.villain.profiles import PROFILE_NAMES

StreetName = Literal["preflop", "flop", "turn", "river"]
IntentName = Literal["value", "bluff", "semi_bluff"]
ActionKindName = Literal["fold", "check", "call", "bet", "raise"]
VerdictName = Literal["best", "fine", "mistake", "blunder"]
ScoreName = Literal["great", "good", "off"]
CategoryCode = Literal["nuts", "strong", "strong_draw", "medium", "weak_draw", "weak", "air"]
# strict: a JSON "0.5" or true is not a probability (an int such as 0 or 1 still is)
Probability = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False, strict=True)]
RANDOM_PROFILE = "random"


def _check_profile(v: str | None, *, allow_random: bool) -> str | None:
    if v is None or v in PROFILE_NAMES or (allow_random and v == RANDOM_PROFILE):
        return v
    expected = [*PROFILE_NAMES, RANDOM_PROFILE] if allow_random else list(PROFILE_NAMES)
    raise ValueError(f"unknown profile {v!r}; expected one of {expected}")


class Health(BaseModel):
    status: Literal["ok"]
    version: str


class NewPuzzleIn(BaseModel):
    """Both optional: a null street is random; a null profile uses the settings, then random;
    ``"random"`` is random whatever the settings say."""

    model_config = ConfigDict(extra="forbid")

    street: StreetName | None = None
    profile: str | None = None

    @field_validator("profile")
    @classmethod
    def _known_profile(cls, v: str | None) -> str | None:
        return _check_profile(v, allow_random=True)


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
        return _check_profile(v, allow_random=False)


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


# 13x13, rows and columns in ``class_grid`` order; None = every combo of the class is blocked
Grid = list[list[float | None]]


class ProfileInfo(_Out):
    name: str
    label: str
    description: str


class ActionLogEntry(_Out):
    street: StreetName
    actor: Literal["hero", "villain"]
    kind: ActionKindName
    to: int
    text: str
    pot_before: int
    amount: int
    all_in: bool


class OptionBrief(_Out):
    index: int
    label: str
    kind: ActionKindName
    to: int


class CustomSizes(_Out):
    allowed: bool
    min_to: int | None
    max_to: int | None


class PuzzleView(_Out):
    """Everything visible at the table before an answer; nothing Villain-side or undealt."""

    id: int
    street: StreetName
    hero_seat: int
    hero_position: str
    villain_position: str
    hero_cards: list[str]
    board: list[str]
    stacks: list[int]
    street_bets: list[int]
    pot: int
    to_call: int
    pot_odds: float | None
    history: list[ActionLogEntry]
    villain_profile: ProfileInfo
    options: list[OptionBrief]
    custom: CustomSizes
    range_read_asked: bool
    attempts_so_far: int


class AttemptMeta(_Out):
    id: int
    puzzle_id: int
    attempt_no: int
    is_first: bool
    created_at: str  # ISO 8601, always ending +00:00


class StoredAction(_Out):
    seat: int
    kind: ActionKindName
    street: StreetName
    to: int


class AnswerView(_Out):
    option_index: int | None
    custom_to: int | None
    action: StoredAction
    equity_guess: float
    range_read_guess: float | None
    intent: IntentName | None
    chosen_label: str


class BluffCheck(_Out):
    required: float
    actual: float


class GradeView(_Out):
    verdict: VerdictName
    ev_loss_chips: float
    ev_loss_bb: float
    chosen_label: str
    best_label: str
    equity: float
    equity_std_error: float
    equity_exact: bool
    equity_guess: float
    equity_error: float
    equity_score: ScoreName
    ahead_now: float | None
    range_read_guess: float | None
    range_read_error: float | None
    range_read_score: ScoreName | None
    intent: IntentName | None
    intent_truth: IntentName | None
    intent_flag: str | None
    bluff_check: BluffCheck | None
    pot_odds: float | None


class Branch(_Out):
    label: str
    share: float
    equity: float | None
    value_chips: float
    value_bb: float


class OptionResult(_Out):
    label: str
    kind: ActionKindName
    to: int
    ev_chips: float
    ev_bb: float
    fold_freq: float | None
    equity_vs_continue: float | None
    equity_vs_continue_se: float | None
    ahead_vs_continue: float | None
    required_fold_equity: float | None
    put: int
    branches: list[Branch]
    simplifications: list[str]
    continue_grid: Grid | None
    is_best: bool
    is_chosen: bool


class Simplification(_Out):
    code: str
    text: str


class CategoryView(_Out):
    category: CategoryCode
    name: str
    share: float
    ahead: float
    equity: float
    win: float
    tie: float
    lose: float


class RangeStep(_Out):
    label: str
    street: StreetName
    grid: Grid
    combos: list[tuple[str, float]]  # [combo, weight] for every combo with weight > 0


class RevealProfile(ProfileInfo):
    version: int


class Showdown(_Out):
    hero_hand: str
    villain_hand: str
    winner: Literal["hero", "villain", "split"]


class Reveal(_Out):
    villain_cards: list[str]
    runout: list[str]  # all 5 board cards, including those already shown
    profile: RevealProfile
    showdown: Showdown


ExplanationSource = Literal["template", "llm"]
FallbackReason = Literal["off", "unavailable", "timeout", "error", "invalid", "guardrail"]


class ExplanationSection(_Out):
    id: Literal["hand", "verdict", "villain"]
    title: str
    paragraphs: list[str]


class Explanation(_Out):
    """Plain-English explanation of a result. Every number in it was computed by the grader and
    formatted by code; a language model may only reword it (``source == "llm"``)."""

    source: ExplanationSource
    headline: str  # one sentence
    sections: list[ExplanationSection]  # always in the order hand, verdict, villain
    model: str | None  # the model name when source == "llm"
    fallback: FallbackReason | None  # why the template is shown when the LLM was asked


class AttemptResult(_Out):
    """A stored attempt's full result: the stored grade plus the frozen puzzle's reveal."""

    attempt: AttemptMeta
    answer: AnswerView
    grade: GradeView
    options: list[OptionResult]
    simplifications: list[Simplification]
    categories: list[CategoryView] | None
    range_steps: list[RangeStep]
    reveal: Reveal
    judged_on_range_note: str
    explanation: Explanation  # always the template (source "template")


class AttemptSummary(_Out):
    attempt_id: int
    puzzle_id: int
    attempt_no: int
    is_first: bool
    created_at: str
    street: StreetName
    profile: str
    chosen_label: str
    action_kind: ActionKindName
    best_label: str
    best_kind: ActionKindName
    verdict: VerdictName
    ev_loss_bb: float
    equity_error: float
    range_read_error: float | None


class HistoryPage(_Out):
    items: list[AttemptSummary]
    total: int


class SettingsView(_Out):
    show_pot_odds: bool
    show_profile: bool
    profile: str | None
    daily_goal: int
    llm_provider: str
    llm_status: Literal["off", "on"]
    profiles: list[ProfileInfo]


# ---------------------------------------------------------------------------
# Stats (``stats.service.compute``): first attempts only; EV in bb, errors as fractions (0-1)
# ---------------------------------------------------------------------------


class StatsTotals(_Out):
    first_attempts: int
    retries: int


class StatsHeadline(_Out):
    """Means over the last 50 first attempts; ``ev_lost_bb_prev50`` is attempts 51-100 back,
    null until there are 100. All null with no attempts."""

    ev_lost_bb_last50: float | None
    ev_lost_bb_prev50: float | None
    accuracy_last50: float | None
    equity_error_last50: float | None
    range_read_error_last50: float | None


class TrendPoint(_Out):
    """One first attempt with rolling means over the last 50 first attempts ending at it."""

    n: int  # 1-based first-attempt number over all time
    attempt_id: int
    created_at: str  # ISO 8601, always ending +00:00
    ev_lost_bb: float
    equity_error: float
    range_read_error: float | None
    ev_lost_bb_avg: float
    equity_error_avg: float
    range_read_error_avg: float | None  # mean of the window's non-null values


class VerdictCounts(_Out):
    best: int
    fine: int
    mistake: int
    blunder: int


class BreakdownRow(_Out):
    key: str
    label: str
    count: int
    accuracy: float
    ev_lost_bb_avg: float
    equity_error_avg: float
    verdicts: VerdictCounts


class StatsBreakdowns(_Out):
    street: list[BreakdownRow]
    action: list[BreakdownRow]
    profile: list[BreakdownRow]


class StatsStreak(_Out):
    current: int
    best: int


class DayCount(_Out):
    date: str  # YYYY-MM-DD, local
    count: int


class StatsDays(_Out):
    goal: int
    today: int
    current_streak: int
    best_streak: int
    recent: list[DayCount]  # 14 days, oldest first, ending today


class Leak(_Out):
    id: str
    kind: Literal["share", "mean"]
    title: str
    detail: str
    count: int
    sample: int
    ev_lost_bb: float | None  # share rules
    mean_error: float | None  # mean rules: the signed mean


class StatsView(_Out):
    tz: str
    totals: StatsTotals
    headline: StatsHeadline
    trend: list[TrendPoint]
    breakdowns: StatsBreakdowns
    streak: StatsStreak
    days: StatsDays
    leaks: list[Leak]
