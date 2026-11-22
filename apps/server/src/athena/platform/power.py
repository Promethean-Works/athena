"""Raspberry Pi power and thermal flags (`vcgencmd get_throttled`).

The Pi firmware reports a bit field: under-voltage (a weak power supply or cable),
a capped ARM frequency, throttling and the soft temperature limit, each as "now" and
"has happened since boot". Other hosts have neither the command nor the sysfs file, so
`find_source` returns None and the dashboard hides the card (capability `host.power`).
"""

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from athena.platform.probe import Probe

SYSFS_PATH = "/sys/devices/platform/soc/soc:firmware/get_throttled"
"""Exposed by the Raspberry Pi firmware driver; hexadecimal, with or without `0x`."""

Flag = Literal["under_voltage", "freq_capped", "throttled", "soft_temp_limit"]

# Bit number of each flag "now"; "since boot" is the same bit plus 16.
FLAG_BITS: dict[Flag, int] = {
    "under_voltage": 0,
    "freq_capped": 1,
    "throttled": 2,
    "soft_temp_limit": 3,
}


class PowerStatus(BaseModel):
    now: list[Flag]
    """Conditions active right now."""
    since_boot: list[Flag]
    """Conditions that happened at any time since the host booted (includes `now`)."""


@dataclass(frozen=True)
class Source:
    provider: Literal["sysfs", "vcgencmd"]
    path: str
    """The sysfs file, or the vcgencmd binary."""


def parse(text: str) -> int | None:
    """The flags value from `throttled=0x50005` or the bare hex of the sysfs file."""
    match = re.fullmatch(r"(?:throttled=)?(0x[0-9a-fA-F]+|[0-9a-fA-F]+)", text.strip())
    if not match:
        return None
    try:
        return int(match.group(1), 16)
    except ValueError:
        return None


def status_of(raw: int) -> PowerStatus:
    return PowerStatus(
        now=[f for f, bit in FLAG_BITS.items() if raw >> bit & 1],
        since_boot=[f for f, bit in FLAG_BITS.items() if raw >> (bit + 16) & 1 or raw >> bit & 1],
    )


def read_raw(source: Source, probe: Probe) -> int | None:
    if source.provider == "sysfs":
        text = probe.read_text(source.path)
    else:
        result = probe.run([source.path, "get_throttled"], timeout=3)
        text = result.stdout if result.ok else None
    return None if text is None else parse(text)


def find_source(probe: Probe) -> Source | None:
    """The first way this host can report the flags (and does), or None. Linux only."""
    if probe.os != "linux":
        return None
    candidates = []
    if probe.exists(SYSFS_PATH):
        candidates.append(Source("sysfs", SYSFS_PATH))
    if path := probe.which("vcgencmd"):
        candidates.append(Source("vcgencmd", path))
    return next((c for c in candidates if read_raw(c, probe) is not None), None)


class PowerReader:
    """Reads the flags for the host monitor. The source is looked up once, so a host
    without one costs nothing per sample."""

    def __init__(self, probe: Probe | None = None) -> None:
        self._probe = probe or Probe()
        self._looked_up = False
        self._source: Source | None = None

    def __call__(self) -> PowerStatus | None:
        if not self._looked_up:
            self._source = find_source(self._probe)
            self._looked_up = True
        if self._source is None:
            return None
        raw = read_raw(self._source, self._probe)
        return None if raw is None else status_of(raw)
