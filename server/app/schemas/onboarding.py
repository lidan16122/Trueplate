from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.enums import ActivityLevel, GoalType, Sex, UnitPreference


class OnboardingRequest(BaseModel):
    """Everything the wizard collects, submitted once at the end.

    Bounds mirror the wizard's own steppers so a hand-crafted request cannot
    reach a target the UI would never let a user produce.
    """

    # Prefilled from Google and confirmed on the wizard’s first page. Accepted
    # here rather than left to a separate PATCH so a corrected name and the
    # profile it belongs to commit together — a name that saved beside an
    # onboarding that failed would rename a user still stuck in the wizard.
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    age: int = Field(ge=14, le=120)
    sex: Sex
    height_cm: float = Field(gt=50, le=280)
    weight_kg: float = Field(gt=20, le=500)
    goal_type: GoalType
    # Absent when maintaining — the wizard hides that row entirely.
    target_weight_kg: float | None = Field(default=None, gt=20, le=500)
    rate_kg_per_week: float = Field(default=0.5, gt=0, le=1.5)

    # Captured from the browser rather than asked: daily_logs is keyed on the
    # user's local date, so "today" is undefined without it.
    timezone: str = Field(default="UTC", max_length=64)
    activity_level: ActivityLevel = ActivityLevel.LIGHT
    unit_preference: UnitPreference = UnitPreference.METRIC

    @model_validator(mode="after")
    def check_target_direction(self) -> OnboardingRequest:
        if self.goal_type == GoalType.MAINTAIN:
            # Any value sent here is meaningless; drop it rather than storing a
            # target the user never agreed to.
            object.__setattr__(self, "target_weight_kg", None)
            return self

        if self.target_weight_kg is None:
            raise ValueError("target_weight_kg is required unless the goal is 'maintain'")

        if self.goal_type == GoalType.LOSE and self.target_weight_kg >= self.weight_kg:
            raise ValueError("Target weight must be below current weight when losing")
        if self.goal_type == GoalType.GAIN and self.target_weight_kg <= self.weight_kg:
            raise ValueError("Target weight must be above current weight when gaining")
        return self


class MathRow(BaseModel):
    """One line of the target-reveal breakdown.

    The reveal screen shows its working; these are those lines, computed
    server-side so the explanation and the stored target cannot disagree.
    """

    label: str
    value: str


class TargetsOut(BaseModel):
    bmr: int
    activity_factor: float
    tdee: int
    delta: int
    target_calories: int
    protein_g: int
    carbs_g: int
    fat_g: int
    goal_type: str
    rate_kg_per_week: float
    target_weight_kg: float
    weeks_to_target: int
    math_rows: list[MathRow]
    summary: str


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # Names live on `users`, not the profile row, but they are editable from the
    # profile screen — so they are readable here too. Accepting them on the
    # update and omitting them from the response left the client unable to show
    # what it had just saved.
    first_name: str | None = None
    last_name: str | None = None
    age: int | None
    sex: str | None
    height_cm: float | None
    weight_kg: float | None
    activity_level: str
    unit_preference: str
    timezone: str


class ProfileUpdateRequest(BaseModel):
    """Every field optional — the profile screen saves fields independently."""

    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    age: int | None = Field(default=None, ge=14, le=120)
    sex: Sex | None = None
    height_cm: float | None = Field(default=None, gt=50, le=280)
    weight_kg: float | None = Field(default=None, gt=20, le=500)
    goal_type: GoalType | None = None
    target_weight_kg: float | None = Field(default=None, gt=20, le=500)
    rate_kg_per_week: float | None = Field(default=None, gt=0, le=1.5)
    activity_level: ActivityLevel | None = None
    timezone: str | None = Field(default=None, max_length=64)


class GoalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    goal_type: str
    target_weight_kg: float | None
    target_rate_kg_per_week: float
    target_calories: int
    target_protein_g: int
    target_carbs_g: int
    target_fat_g: int
    starts_on: date


class OnboardingResponse(BaseModel):
    goal: GoalOut
    targets: TargetsOut
