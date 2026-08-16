import uuid
from datetime import datetime

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


class SignInResponse(BaseModel):
    user: UserOut
    # Drives the design's post-sign-in fork: a user with no profile or no active
    # goal goes to the wizard, everyone else straight to today.
    needs_onboarding: bool


class SessionOut(BaseModel):
    """One active device, for a "where am I signed in" view."""

    family_id: str
    device_label: str
    ip: str
    created_at: datetime
    last_used_at: datetime
    # Lets the UI mark "this device" without the client having to guess.
    is_current: bool = False


class SessionListResponse(BaseModel):
    sessions: list[SessionOut]


class MessageResponse(BaseModel):
    detail: str
