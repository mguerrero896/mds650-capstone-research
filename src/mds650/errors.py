"""Typed fail-closed errors used by the research pipeline."""

from __future__ import annotations


class MDS650Error(Exception):
    """Base class for expected pipeline failures."""


class SecretPresenceError(MDS650Error):
    """Raised when one or more provider credentials are absent."""


class ResearchOnlyViolation(MDS650Error):
    """Raised when a configuration would permit an external mutation."""


class AuthenticationError(MDS650Error):
    """Raised when a provider rejects authentication."""


class SchemaDriftError(MDS650Error):
    """Raised when a provider response changes its required schema."""


class LicensingError(MDS650Error):
    """Raised when a response cannot be used under verified license terms."""


class PITError(MDS650Error):
    """Raised when point-in-time availability cannot be established."""


class QualityGateError(MDS650Error):
    """Raised when configured data-quality acceptance criteria fail."""


class OverlapError(MDS650Error):
    """Raised when provider histories do not overlap sufficiently."""


class ProviderBlockedError(MDS650Error):
    """Raised when a provider gate fails closed with an exact blocker code."""

    def __init__(self, code: str) -> None:
        """Create a provider error preserving its machine-readable code.

        Parameters
        ----------
        code:
            Stable uppercase blocker code written to sanitized manifests.
        """
        self.code = code
        super().__init__(code)
