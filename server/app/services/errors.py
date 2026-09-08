"""Application failures whose HTTP meaning is chosen by the API boundary."""


class NotFoundError(Exception):
    """The requested resource is absent from the caller's scope."""


class InvalidOperationError(Exception):
    """Valid input cannot be applied to the current application state."""
