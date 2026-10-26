"""Our own error types.

Keeping them in one small file lets both the client (which raises them) and
the API (which turns each one into an HTTP status code) share them.
"""


class LegacyPortalError(Exception):
    """Base class for every problem that comes from the legacy portal side."""


class ConfigError(LegacyPortalError):
    """Our own settings are incomplete (for example, no credentials in .env)."""


class UpstreamError(LegacyPortalError):
    """The portal was unreachable, returned a server error, or changed shape."""


class UpstreamTimeout(UpstreamError):
    """The portal did not answer in time."""


class UpstreamAuthError(UpstreamError):
    """Login failed or the portal session is no longer valid."""


class MeterNotFound(LegacyPortalError):
    """The requested meter does not exist in the portal."""


class NotImplementedYet(LegacyPortalError):
    """This part has not been investigated or built yet."""
