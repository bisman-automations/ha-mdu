"""Exceptions for the Montana-Dakota Utilities integration."""


class MDUError(Exception):
    """Base class for MDU errors."""


class MDUConnectionError(MDUError):
    """The portal could not be reached or returned something unexpected."""


class MDUAuthenticationError(MDUError):
    """The portal rejected the username or password."""


class MDUMfaRequired(MDUError):
    """The portal wants a security code before it will sign in.

    Raised by ``MDUClient.login``. The client keeps its session, so the caller
    can go on with ``mfa_contacts``, ``mfa_send_code`` and ``mfa_verify``.
    """


class MDUMfaError(MDUError):
    """A security code was rejected, expired, or could not be sent."""

    def __init__(self, message: str, reason: str = "invalid_code") -> None:
        super().__init__(message)
        self.reason = reason


class MDUSessionExpired(MDUError):
    """The portal session ended; signing in again should fix it."""
