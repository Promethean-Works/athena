"""The `backup` section of athena.json: host-wide knobs, no secrets (docs/specs/backup.md).

Destinations and plans are rows in SQLite (they're relational, hold encrypted secrets and
carry run state). These are the few things worth fixing by hand in an editor, like
`paused`, the escape hatch that stops every scheduled run when a backup misbehaves.
"""

from pydantic import BaseModel, ConfigDict, Field


class Retention(BaseModel):
    """How many versions of each item a plan keeps (`restic forget --keep-…`)."""

    model_config = ConfigDict(extra="forbid")

    keep_last: int = Field(default=7, ge=0, le=1000)
    keep_daily: int = Field(default=7, ge=0, le=1000)
    keep_weekly: int = Field(default=4, ge=0, le=1000)
    keep_monthly: int = Field(default=6, ge=0, le=1000)

    def keeps_something(self) -> bool:
        """`forget` with every count at 0 would delete every version."""
        return any((self.keep_last, self.keep_daily, self.keep_weekly, self.keep_monthly))


class BackupSettings(BaseModel):
    """Host-wide backup settings (the `backup` section of athena.json)."""

    model_config = ConfigDict(extra="forbid")

    paused: bool = False
    """True stops every scheduled backup run. Manual runs still work."""
    prune_interval_days: int = Field(default=7, ge=1, le=365)
    """At most one `restic prune` per destination in this many days."""
    check_interval_days: int = Field(default=30, ge=1, le=365)
    """At most one `restic check` (metadata only) per destination in this many days."""
    before_restore_keep_days: int = Field(default=7, ge=1, le=365)
    """How long the `*.before-restore-*` folder of a restored app is kept."""
    default_retention: Retention = Field(default_factory=Retention)
    """What a new plan starts with."""
