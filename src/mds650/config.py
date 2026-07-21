"""Validated, presence-only configuration for bounded research runs."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from mds650.errors import ResearchOnlyViolation, SecretPresenceError


class ResearchSettings(BaseSettings):
    """Environment-backed settings with fail-closed research safety.

    Notes
    -----
    Secret fields are retained as ``SecretStr`` and are exposed only through
    boolean presence checks. The default mode is research-only and disabling it
    is rejected at validation time.
    """

    unusualwhales_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="UNUSUALWHALES_API_KEY",
        repr=False,
    )
    massive_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="MASSIVE_API_KEY",
        repr=False,
    )
    fmp_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="FMP_API_KEY",
        repr=False,
    )
    research_only: bool = Field(default=True, validation_alias="MDS650_RESEARCH_ONLY")
    raw_root: Path | None = Field(default=None, validation_alias="MDS650_RAW_ROOT")

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        env_file=None,
    )

    @model_validator(mode="after")
    def enforce_research_only(self) -> ResearchSettings:
        """Reject configurations that could enable external mutations.

        Raises
        ------
        ResearchOnlyViolation
            If ``MDS650_RESEARCH_ONLY`` is explicitly false.
        """
        if not self.research_only:
            raise ResearchOnlyViolation("RESEARCH_ONLY_REQUIRED")
        return self

    def secret_presence(self) -> dict[str, bool]:
        """Return provider-key presence without exposing values.

        Returns
        -------
        dict[str, bool]
            Stable environment variable names mapped to presence booleans.
        """
        return {
            "UNUSUALWHALES_API_KEY": self.unusualwhales_api_key is not None,
            "MASSIVE_API_KEY": self.massive_api_key is not None,
            "FMP_API_KEY": self.fmp_api_key is not None,
        }

    def require_provider_secrets(self) -> None:
        """Fail closed unless all three provider keys are present.

        Raises
        ------
        SecretPresenceError
            If one or more required credentials are absent. The error contains
            names only, never secret values.
        """
        missing = [name for name, present in self.secret_presence().items() if not present]
        if missing:
            raise SecretPresenceError("MISSING_PROVIDER_SECRETS:" + ",".join(missing))
