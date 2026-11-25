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
    show_range: Annotated[bool, Field(strict=True)] = False
    profile: str | None = None
    daily_goal: Annotated[int, Field(ge=1, le=500, strict=True)] = 10

    @field_validator("profile")
    @classmethod
    def _known_profile(cls, v: str | None) -> str | None:
        return _check_profile(v, allow_random=False)


class PlayActionIn(BaseModel):
    """Hero's move in a played hand: exactly one of ``option`` or ``custom_to``.

    ``expected_actions`` is the hand's ``action_count`` the client saw, so a stale or doubled
    click is refused instead of acting on a table Hero has not seen."""

    model_config = ConfigDict(extra="forbid")

    expected_actions: Annotated[int, Field(ge=0, strict=True)]
    option: Annotated[int, Field(ge=0, strict=True)] | None = None
    custom_to: Annotated[int, Field(gt=0, strict=True)] | None = None

    @model_validator(mode="after")
    def _exactly_one_action(self) -> PlayActionIn:
        if (self.option is None) == (self.custom_to is None):
            raise ValueError("give exactly one of option or custom_to")
        return self


class NextHandIn(BaseModel):
    """``expected_hands`` is the session's ``hands_played`` the client saw: a doubled or stale
    "next hand" is refused instead of dealing a hand Hero never saw."""

    model_config = ConfigDict(extra="forbid")

    expected_hands: Annotated[int, Field(ge=0, strict=True)]
    top_up: Annotated[bool, Field(strict=True)] = False


TableSize = Literal[2, 5]


class PlaySessionIn(BaseModel):
    """Optional body of ``POST /play/sessions``: heads-up (2, the default) or 5-max (5)."""

    model_config = ConfigDict(extra="forbid")

    # a JSON "5" or true is not a table size (the literal refuses them)
    table_size: TableSize = 2


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class _Out(BaseModel):
    # A field with a default (only fields added after a model first shipped have one) is still
    # listed as required in the response schema: every response carries it.
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


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
    realisation: float  # equity realisation factor used in the value (1.0 when unused)


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
    realisation: float  # factor in a call or check value; 1.0 for fold/bet/raise (see branches)
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
    show_range: bool
    profile: str | None
    daily_goal: int
    llm_provider: str
    # "off": provider none (templates only); else the last probe of the local model
    llm_status: Literal["off", "ready", "unavailable"]
    llm_model: str | None  # the model name when the provider is not "none"
    llm_detail: str | None  # what to do when the status is "unavailable"
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
    rolling_window: int  # first attempts each trend point and "last N" headline averages over
    totals: StatsTotals
    headline: StatsHeadline
    trend: list[TrendPoint]
    breakdowns: StatsBreakdowns
    streak: StatsStreak
    days: StatsDays
    leaks: list[Leak]


# ---------------------------------------------------------------------------
# Play vs Bots
# ---------------------------------------------------------------------------


class SeatView(_Out):
    """One seat at a played table. ``name`` is "You" for Hero, "Villain" for the heads-up bot
    and "Bot 1" to "Bot 4" in 5-max. ``profile`` is the bot's profile (null for Hero); the
    client hides it per setting. ``cards`` are Hero's cards, or a bot's cards once they are
    shown at a showdown; otherwise null. In a finished hand ``stack`` is the settled stack,
    ``street_bet`` is 0 and ``all_in`` is false."""

    seat: int
    name: str
    position: str
    stack: int
    street_bet: int
    folded: bool
    all_in: bool
    is_hero: bool
    is_button: bool
    profile: ProfileInfo | None
    cards: list[str] | None


class TableView(_Out):
    """The table in a played hand: ``PuzzleView`` without the answer-form fields.

    In a finished hand ``stacks`` are the settled stacks, ``street_bets`` are zero and ``pot``
    is the pot that was awarded. In 5-max that is the sum of the listed pots; when the hand is
    won by a fold, that pot includes the winner's own uncalled excess. The frames' ``pots`` leave
    the uncalled excess out, so ``frames[-1].pots`` need not equal ``table.pot``.
    ``villain_position`` and ``villain_profile`` are heads-up only (null
    in 5-max); ``seats`` describes every seat at any table size."""

    street: StreetName
    hero_seat: int
    hero_position: str
    villain_position: str | None
    hero_cards: list[str]
    board: list[str]
    stacks: list[int]
    street_bets: list[int]
    pot: int
    to_call: int
    pot_odds: float | None
    history: list[ActionLogEntry]
    villain_profile: ProfileInfo | None
    table_size: int
    seats: list[SeatView]


class TableFrame(_Out):
    """The table after the first ``k`` history entries, before any pot award.

    ``to_act`` is "hero", "villain" (any bot) or null; ``to_act_seat`` is that seat. ``folded``
    has one flag per seat. ``pots`` are the pots as they stand, the main pot first: only chips
    already in the middle (the bets of streets that are over), an uncalled excess left out;
    empty while nothing is in the middle."""

    stacks: list[int]
    street_bets: list[int]
    pot: int  # total pot including bets in front, as ``PuzzleView.pot``
    board_len: int
    to_act: Literal["hero", "villain"] | None
    to_act_seat: int | None = None
    folded: list[bool] = Field(default_factory=list)
    pots: list[int] = Field(default_factory=list)


class PotAwardView(_Out):
    """One pot of a finished hand: ``label`` is "main pot", "side pot 1", ...; ``eligible``
    are the seats contesting it and ``winners`` those it went to (a split has several)."""

    amount: int
    eligible: list[int]
    winners: list[int]
    label: str


class ShownCards(_Out):
    seat: int
    cards: list[str]


class PlayOutcome(_Out):
    """How a hand ended. ``winner`` heads-up is the hand's result; in 5-max it is "villain" when
    the hand was abandoned or Hero folded, and otherwise the sign of Hero's delta.
    ``villain_cards`` and ``showdown`` are heads-up showdowns only. ``pots`` are the awards
    (empty for an abandoned hand) and ``shown`` the bots' cards revealed at a showdown,
    clockwise from the seat after the button."""

    ended_by: Literal["fold", "showdown", "abandoned"]
    winner: Literal["hero", "villain", "split"]
    hero_delta_chips: int
    hero_delta_bb: float
    villain_cards: list[str] | None  # only for a heads-up showdown
    showdown: Showdown | None
    pots: list[PotAwardView] = Field(default_factory=list)
    shown: list[ShownCards] = Field(default_factory=list)


class PlayHandView(_Out):
    id: int
    hand_no: int
    session_id: int
    status: Literal["in_progress", "complete"]
    action_count: int
    decision_count: int
    table: TableView
    frames: list[TableFrame]
    options: list[OptionBrief]
    custom: CustomSizes
    outcome: PlayOutcome | None


class BotSeatInfo(_Out):
    """A bot at the session's table; ``profile`` is null when the profile setting is off."""

    seat: int
    name: str
    profile: ProfileInfo | None
    stack: int


class PlaySessionView(_Out):
    """``profile`` and ``bot_stack`` are the heads-up bot's (null in 5-max). ``bots`` lists
    every bot seat with its stack after the last finished hand."""

    id: int
    open: bool
    profile: ProfileInfo | None
    hero_stack: int
    bot_stack: int | None
    hero_bought_chips: int
    net_chips: int
    net_bb: float
    hands_played: int
    must_rebuy: bool
    can_top_up: bool
    hand: PlayHandView | None
    table_size: int
    bots: list[BotSeatInfo]


class PlaySessionSummary(_Out):
    id: int
    created_at: str  # ISO 8601, always ending +00:00
    ended_at: str | None
    profile_label: str  # "5-max" for a 5-max session
    hands_played: int
    net_bb: float
    open: bool
    table_size: int = 2


class PlayHandSummary(_Out):
    id: int
    hand_no: int
    hero_position: str
    result_bb: float | None  # null while the hand is running
    ended_by: Literal["fold", "showdown", "abandoned"] | None
    decision_count: int
    analysed: bool  # always false for 5-max hands (no analysis yet)
    ev_loss_bb: float | None
    table_size: int = 2
    # who took a pot, Hero as "You", in seat order; empty while running or when abandoned
    # in 5-max (a heads-up abandon reads as the bot's)
    winner_names: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Hand analysis: each Hero decision graded like a puzzle, against the bot's narrowed range
# ---------------------------------------------------------------------------


class DecisionGrade(_Out):
    """``GradeView`` without the guesses: in play Hero states no equity, range read or intent."""

    verdict: VerdictName
    ev_loss_chips: float
    ev_loss_bb: float
    chosen_label: str
    best_label: str
    equity: float
    equity_std_error: float
    equity_exact: bool
    ahead_now: float | None
    intent_truth: IntentName | None
    bluff_check: BluffCheck | None
    pot_odds: float | None


class DecisionReview(_Out):
    """One analysed Hero decision. ``not_graded`` carries the reason and the table only."""

    index: int  # 0-based among Hero's decisions in the hand
    status: Literal["graded", "not_graded"]
    reason: str | None
    view: TableView | None  # the table as it stood when Hero acted
    grade: DecisionGrade | None
    options: list[OptionResult]
    simplifications: list[Simplification]
    categories: list[CategoryView] | None
    range_steps: list[RangeStep]
    chosen_label: str | None  # the server's label; a custom size is relabelled in bb by the UI
    explanation: Explanation | None  # always the template (source "template")


class PlayReveal(_Out):
    """The bot's cards and the board as far as it was dealt (no undealt card)."""

    villain_cards: list[str]
    board: list[str]
    profile: RevealProfile  # the session's snapshot
    showdown: Showdown | None  # only when the hand ended in a showdown


class AnalysisSummary(_Out):
    ev_loss_bb: float  # over the graded decisions
    worst_index: int | None  # null when nothing was graded or nothing lost EV


class HandAnalysis(_Out):
    """What is stored so far: one entry per Hero decision, null until it is analysed."""

    hand_id: int
    decisions: list[DecisionReview | None]
    summary: AnalysisSummary | None  # once every decision is analysed
    reveal: PlayReveal
    model_changed: bool  # the Villain model has changed since the hand was played
    judged_on_range_note: str
