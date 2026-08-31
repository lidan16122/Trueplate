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
    """Who is signed in, and whether they still owe the onboarding wizard.

    One shape for both ``POST /auth/google`` and ``GET /auth/me`` on purpose:
    signing in and reloading the page ask the same question. Answering it in two
    shapes is what let the client grow two components that disagreed about where
    a user with no profile belongs.
    """

    user: UserOut
    # Drives the design's post-sign-in fork: a user with no profile or no active
    # goal goes to the wizard, everyone else straight to today. The cookies are
    # httpOnly, so a cold page load has no other way to discover this.
    needs_onboarding: bool


class MessageResponse(BaseModel):
    detail: str
