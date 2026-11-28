"""What a backup plan contains (docs/specs/backup.md): the shape of `backup_plans.items`."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from athena.apps.store import APP_NAME
from athena.backup.settings import Retention


class PlanApp(BaseModel):
    """One app in a plan: its name, the bind mounts to include, and whether to back
    it up while it's still running."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=APP_NAME, max_length=63)
    bind_mounts: list[str] = Field(default_factory=list, max_length=50)
    """Host paths outside the app folder to back up too, opted in per path.
    Device and socket mounts are never offered (docs/specs/backup.md)."""
    while_running: bool = False
    """Back it up without stopping it ("Back up while running"), for apps that can't stop."""


class PlanItems(BaseModel):
    """Athena itself, the users' files and the apps a plan backs up. Each is its own snapshot."""

    model_config = ConfigDict(extra="forbid")

    athena: bool = True
    user_files: bool = True
    """Everyone's personal folders (`<data-dir>/users/`), as one snapshot tagged `users`."""
    apps: list[PlanApp] = Field(default_factory=list, max_length=200)

    @field_validator("apps")
    @classmethod
    def _unique(cls, apps: list[PlanApp]) -> list[PlanApp]:
        names = [a.name for a in apps]
        if len(set(names)) != len(names):
            raise ValueError("An app is listed twice")
        return apps

    def is_empty(self) -> bool:
        return not self.athena and not self.user_files and not self.apps


def parse_items(text: str) -> PlanItems:
    return PlanItems.model_validate_json(text or "{}")


def parse_retention(text: str) -> Retention:
    return Retention.model_validate_json(text or "{}")
