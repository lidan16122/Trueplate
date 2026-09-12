import uuid

from pydantic import BaseModel, ConfigDict, Field


class GoogleSignInRequest(BaseModel):
    """The ID token produced by Google Identity Services in the browser."""

    credential: str = Field(min_length=1, description="Google ID token (JWT)")


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    avatar_url: str | None = None
    full_name: str
    initials: str


class SessionResponse(BaseModel):
    """Identity and onboarding state shared by sign-in, session discovery, and protected reads."""

    user: UserOut
    # Drives the design's post-sign-in fork: a user with no profile or no active
    # goal goes to the wizard, everyone else straight to today. The cookies are
    # httpOnly, so a cold page load has no other way to discover this.
    needs_onboarding: bool


class MessageResponse(BaseModel):
    detail: str
