"""Stable error-code tests."""

from mds650.errors import ProviderBlockedError


def test_provider_blocker_preserves_machine_readable_code() -> None:
    """Provider failures retain an exact blocker code for manifests."""
    error = ProviderBlockedError("MASSIVE_AUTH_OR_PLAN_UNAUTHORIZED")

    assert error.code == "MASSIVE_AUTH_OR_PLAN_UNAUTHORIZED"
    assert str(error) == "MASSIVE_AUTH_OR_PLAN_UNAUTHORIZED"
