"""What a backup plan contains (docs/specs/backup.md): the shape of `backup_plans.items`."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from athena.apps.store import APP_NAME
from athena.backup.settings import Retention


class PlanApp(BaseModel):
    """One app in a plan."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=APP_NAME, max_length=63)
    while_running: bool = False
    """Back it up without stopping it ("Back up while running"), for apps that can't stop."""


class PlanItems(BaseModel):
    """Athena itself and the apps a plan backs up. Each becomes its own restic snapshot."""

    model_config = ConfigDict(extra="forbid")

    athena: bool = True
    apps: list[PlanApp] = Field(default_factory=list, max_length=200)

    @field_validator("apps")
    @classmethod
    def _unique(cls, apps: list[PlanApp]) -> list[PlanApp]:
        names = [a.name for a in apps]
        if len(set(names)) != len(names):
            raise ValueError("An app is listed twice")
        return apps

    def is_empty(self) -> bool:
        return not self.athena and not self.apps


def parse_items(text: str) -> PlanItems:
    return PlanItems.model_validate_json(text or "{}")


def parse_retention(text: str) -> Retention:
    return Retention.model_validate_json(text or "{}")
