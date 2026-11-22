import pytest
from fake_probe import FakeProbe

from athena.platform import power
from athena.platform.detect import detect
from athena.platform.power import PowerReader, PowerStatus, find_source, parse, status_of
from athena.platform.probe import RunResult


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("throttled=0x50005\n", 0x50005),
        ("0x0", 0),
        ("50005\n", 0x50005),
        ("garbage", None),
        ("", None),
    ],
)
def test_parse(text: str, value: int | None) -> None:
    assert parse(text) == value


def test_flags_now_and_since_boot() -> None:
    # 0x50005: under-voltage and throttled now, and both have happened since boot.
    assert status_of(0x50005) == PowerStatus(
        now=["under_voltage", "throttled"], since_boot=["under_voltage", "throttled"]
    )
    # 0x50000: both happened earlier, nothing now.
    assert status_of(0x50000) == PowerStatus(now=[], since_boot=["under_voltage", "throttled"])
    assert status_of(0x8) == PowerStatus(now=["soft_temp_limit"], since_boot=["soft_temp_limit"])
    assert status_of(0) == PowerStatus(now=[], since_boot=[])


def vcgencmd(output: str = "throttled=0x0\n") -> FakeProbe:
    return FakeProbe(
        os="linux",
        binaries={"vcgencmd": "/usr/bin/vcgencmd"},
        commands={("/usr/bin/vcgencmd", "get_throttled"): RunResult(0, output)},
    )


def test_a_pi_with_vcgencmd_has_the_capability() -> None:
    cap = next(c for c in detect(vcgencmd()).capabilities if c.id == "host.power")
    assert (cap.status, cap.provider) == ("ready", "vcgencmd")


def test_the_sysfs_file_is_preferred() -> None:
    probe = vcgencmd()
    probe.paths.add(power.SYSFS_PATH)
    probe.files[power.SYSFS_PATH] = "50005\n"
    source = find_source(probe)
    assert source is not None and source.provider == "sysfs"
    assert PowerReader(probe)() == status_of(0x50005)


def test_a_broken_sysfs_file_falls_back_to_vcgencmd() -> None:
    probe = vcgencmd("throttled=0x1\n")
    probe.paths.add(power.SYSFS_PATH)  # exists but unreadable
    source = find_source(probe)
    assert source is not None and source.provider == "vcgencmd"


@pytest.mark.parametrize("os", ["linux", "darwin", "windows"])
def test_hosts_without_the_flags_do_not_list_the_capability(os) -> None:
    ids = {c.id for c in detect(FakeProbe(os=os)).capabilities}
    assert "host.power" not in ids
    assert PowerReader(FakeProbe(os=os))() is None


def test_a_failing_vcgencmd_is_not_a_source() -> None:
    probe = FakeProbe(os="linux", binaries={"vcgencmd": "/usr/bin/vcgencmd"})  # command fails
    assert find_source(probe) is None


def test_other_oses_ignore_a_vcgencmd_on_path() -> None:
    probe = vcgencmd()
    probe.os = "darwin"
    assert find_source(probe) is None
