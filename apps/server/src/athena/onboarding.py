"""The setup wizard's state (docs/specs/onboarding-wizard.md).

Only one fact is stored: when the admin finished (or dismissed) the wizard, in the
`onboarding` section of athena.json. Which steps are done is read from the real
settings each time, so it can't drift from what Settings shows.
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from athena.settings_file import SettingsFile

StepId = Literal["account", "language", "runtime", "locations", "network", "ai"]
STEPS: tuple[StepId, ...] = ("account", "language", "runtime", "locations", "network", "ai")


class OnboardingSettings(BaseModel):
    """The `onboarding` section of athena.json."""

    model_config = ConfigDict(extra="forbid")

    completed_at: datetime | None = None
    """When the wizard was finished or dismissed. Unset: the dashboard offers it."""


def is_completed(config: "SettingsFile") -> bool:
    return config.get().onboarding.completed_at is not None


def mark(config: "SettingsFile", completed: bool) -> None:
    """Record the wizard as finished, or (False) open it again."""
    section = config.section("onboarding")
    section.completed_at = datetime.now(UTC) if completed else None
    config.save("onboarding", section)
