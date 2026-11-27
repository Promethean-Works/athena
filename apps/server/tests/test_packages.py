"""Package manager parsers against recorded output (tests/fixtures/packages/README.md),
plus the read flows with a fake runner. Runs on every OS."""

import asyncio
import json
from pathlib import Path

import pytest

from athena.packages import MANAGERS
from athena.packages import apps as pk_apps
from athena.packages import linux as pk_linux
from athena.packages import windows as pk_win
from athena.packages.base import (
    PACKAGE_NAME,
    SEARCH_QUERY,
    CmdResult,
    PackageError,
    column_table,
    parse_fields,
)

FIX = Path(__file__).parent / "fixtures" / "packages"


def fx(path: str) -> str:
    return (FIX / path).read_text(encoding="utf-8")


# ---------------------------------------------------------------- apt


def test_apt_search() -> None:
    results = pk_linux.parse_apt_search(fx("apt/search.txt"))
    by = {r.name: r for r in results}
    assert by["gojq"].description == "pure Go implementation of jq (program)"
    assert by["fq"].description == "jq for binary formats (program)"
    assert all(r.version is None for r in results)


def test_dpkg_installed_skips_removed_and_trims_status() -> None:
    pkgs = pk_linux.parse_dpkg_installed(fx("apt/installed.txt"))
    by = {p.name: p for p in pkgs}
    assert by["apt"].version == "3.0.3"
    assert by["bsdutils"].version == "1:2.41.5-0+deb13u1"  # epoch kept
    assert by["apache2"].description == "Apache HTTP Server"
    removed = "rc \tgone\t1.0\tremoved package\n"
    assert pk_linux.parse_dpkg_installed(removed) == []
    held = "hi \tkept\t2.0\theld package\n"
    assert [p.name for p in pk_linux.parse_dpkg_installed(held)] == ["kept"]


def test_apt_upgrade_simulation() -> None:
    ups = pk_linux.parse_apt_upgrade_simulation(fx("apt/upgrade-simulate.txt"))
    by = {u.name: u for u in ups}
    assert len(ups) == 10
    assert (by["apt"].version, by["apt"].latest) == ("3.0.3", "3.0.4")
    assert by["zlib1g"].latest == "1:1.3.dfsg+really1.3.1-1+deb13u1"
    assert "Conf" not in by


def test_apt_commands() -> None:
    apt = pk_linux.Apt()
    assert apt.install_argv("jq")[:3] == ["apt-get", "install", "-y"]
    assert apt.install_argv("jq")[-1] == "jq"
    assert apt.upgrade_argv(None)[:3] == ["apt-get", "upgrade", "-y"]
    assert apt.upgrade_argv("jq")[:3] == ["apt-get", "install", "--only-upgrade"]
    assert apt.refresh_argv() == ["apt-get", "update"]
    assert apt.env["DEBIAN_FRONTEND"] == "noninteractive"


def test_apt_search_escapes_regex() -> None:
    assert pk_linux.literal_regex("g++") == r"g\+\+"
    assert pk_linux.literal_regex("libc6.1") == r"libc6\.1"


# ---------------------------------------------------------------- rpm / dnf / zypper


def test_rpm_installed() -> None:
    pkgs = pk_linux.parse_rpm_installed(fx("rpm-installed.txt"))
    by = {p.name: p for p in pkgs}
    assert by["bash"].version == "5.1.8-9.el9"
    assert by["bash"].description == "The GNU Bourne Again shell"
    assert "gpg-pubkey" not in by


@pytest.mark.parametrize("variant", ["dnf", "dnf4"])
def test_dnf_search_both_generations(variant: str) -> None:
    results = pk_linux.parse_dnf_search(fx(f"{variant}/search.txt"))
    jq = next(r for r in results if r.name == "jq")
    assert jq.description == "Command-line JSON processor"
    assert jq.version and jq.version.startswith("1.")
    assert len({r.name for r in results}) == len(results)


@pytest.mark.parametrize("variant", ["dnf", "dnf4"])
def test_dnf_upgrades_both_generations(variant: str) -> None:
    ups = pk_linux.parse_dnf_upgrades(fx(f"{variant}/upgradable.txt"))
    assert ups[0].name == "bash" and ups[0].latest


def test_dnf_upgradable_fills_installed_version() -> None:
    async def run(argv, env):
        if argv[0] == "rpm":
            return CmdResult(0, "bash\t5.3.14-1.fc45\tshell\n", "")
        return CmdResult(0, "bash\t5.3.15-2.fc45\n", "")

    ups = asyncio.run(pk_linux.Dnf(run).upgradable())
    assert (ups[0].version, ups[0].latest) == ("5.3.14-1.fc45", "5.3.15-2.fc45")


def test_dnf_passes_real_tabs_and_newlines() -> None:
    seen = []

    async def run(argv, env):
        seen.append(argv)
        return CmdResult(0, "", "")

    asyncio.run(pk_linux.Dnf(run).search("jq"))
    qf = seen[0][seen[0].index("--qf") + 1]
    assert "\t" in qf and qf.endswith("\n") and "\\t" not in qf
    assert seen[0][-1] == "*jq*"


def test_zypper_search_and_updates() -> None:
    results = pk_linux.parse_zypper_search(fx("zypper/search.xml"))
    by = {r.name: r for r in results}
    assert by["jq"].description == "A lightweight and flexible command-line JSON processor"
    assert by["jq"].installed is False
    ups = pk_linux.parse_zypper_updates(fx("zypper/list-updates.xml"))
    assert [(u.name, u.version, u.latest) for u in ups] == [
        ("openSUSE-build-key", "1.0-68.1", "1.0-69.1")
    ]


def test_zypper_no_matches_is_not_an_error() -> None:
    async def run(argv, env):
        return CmdResult(104, "<?xml version='1.0'?><stream></stream>", "")

    assert asyncio.run(pk_linux.Zypper(run).search("zzz")) == []


# ---------------------------------------------------------------- pacman


def test_pacman_search() -> None:
    results = pk_linux.parse_pacman_search(fx("pacman/search.txt"))
    by = {r.name: r for r in results}
    assert (by["jq"].version, by["jq"].source) == ("1.8.2-1", "extra")
    assert by["jq"].description == "Command-line JSON processor"
    installed = pk_linux.parse_pacman_search(fx("pacman/search-installed.txt"))
    assert installed[0].name == "bash" and installed[0].installed
    grouped = "core/gcc 15.2.1-1 (base-devel) [installed: 15.1.0-1]\n    The GNU Compiler\n"
    gcc = pk_linux.parse_pacman_search(grouped)[0]
    assert (gcc.name, gcc.version, gcc.installed) == ("gcc", "15.2.1-1", True)


def test_pacman_installed_and_upgrades() -> None:
    pkgs = pk_linux.parse_pacman_installed(fx("pacman/installed.txt"))
    assert {p.name: p.version for p in pkgs}["bash"] == "5.3.20-1"
    ups = pk_linux.parse_pacman_upgrades(fx("pacman/upgradable.txt"))
    assert (ups[0].name, ups[0].version, ups[0].latest) == ("bash", "5.3.19-1", "5.3.20-1")


def test_pacman_only_upgrades_everything() -> None:
    pacman = pk_linux.Pacman()
    assert pacman.can_upgrade_one is False
    assert pacman.install_argv("jq") == ["pacman", "-Syu", "--noconfirm", "--needed", "jq"]
    assert pacman.upgrade_argv(None) == ["pacman", "-Syu", "--noconfirm"]


# ---------------------------------------------------------------- apk


def test_apk_parsers() -> None:
    results = pk_linux.parse_apk_search(fx("apk/search.txt"))
    by = {r.name: r for r in results}
    assert by["jq"].version == "1.8.2-r0"
    assert by["perl-jq-lite"].version == "2.45-r0"
    assert by["acf-jquery"].description == "jquery libraries for ACF"
    pkgs = pk_linux.parse_apk_installed(fx("apk/installed.txt"))
    names = {p.name: p.version for p in pkgs}
    assert names["busybox-binsh"] == "1.37.0-r31"
    assert not any(n.startswith(".") for n in names)  # virtual packages skipped
    ups = {u.name: u for u in pk_linux.parse_apk_upgradable(fx("apk/upgradable.txt"))}
    assert (ups["zlib"].version, ups["zlib"].latest) == ("1.3.2-r1", "1.4-r0")


# ---------------------------------------------------------------- brew


def test_brew_search_names() -> None:
    names = pk_apps.parse_brew_search(fx("brew/search.txt"))
    assert names[:3] == ["gojq", "ijq", "jq"]
    assert "jquake" in names and "" not in names


def test_brew_info_and_installed() -> None:
    info = {r.name: r for r in pk_apps.parse_brew_info(fx("brew/info-search.json"))}
    assert info["gojq"].description == "Pure Go implementation of jq"
    assert info["gojq"].source == "formula" and info["gojq"].version
    assert info["jquake"].source == "cask" and info["jquake"].title == "JQuake"
    inst = {p.name: p for p in pk_apps.parse_brew_installed(fx("brew/info-installed.json"))}
    assert inst["docker"].version == "29.9.2"
    assert inst["jquake"].version == "1.8.4" and inst["jquake"].source == "cask"


def test_brew_outdated() -> None:
    ups = {u.name: u for u in pk_apps.parse_brew_outdated(fx("brew/outdated.json"))}
    assert (ups["docker"].version, ups["docker"].latest) == ("29.9.2", "29.9.3")
    assert ups["jquake"].latest == "1.8.5"


def test_brew_search_enriches_top_results() -> None:
    calls = []

    async def run(argv, env):
        calls.append(argv)
        if argv[1] == "search":
            return CmdResult(0, fx("brew/search.txt"), "")
        if argv[1] in ("formulae", "casks"):
            return CmdResult(0, "", "")
        return CmdResult(0, fx("brew/info-search.json"), "")

    results = asyncio.run(pk_apps.Brew(run).search("jq"))
    by = {r.name: r for r in results}
    assert by["gojq"].description and by["ijq"].description is None
    assert results[0].name == "jq"  # exact name first
    assert calls[-1][:3] == ["brew", "info", "--json=v2"]
    assert pk_apps.Brew().install_argv("jquake", "cask") == ["brew", "install", "--cask", "jquake"]


def test_brew_search_finds_vscode_by_abbreviation() -> None:
    """`brew search vscode` finds nothing; the cask is visual-studio-code (VS Code)."""
    cask = {
        "token": "visual-studio-code",
        "name": ["Microsoft Visual Studio Code", "VS Code"],
        "desc": "Open-source code editor",
        "version": "1.9",
    }
    info = json.dumps({"formulae": [], "casks": [cask]})
    asked = []

    async def run(argv, env):
        if argv[1] == "search":
            return CmdResult(1, "", "Error: No formulae or casks found for vscode.")
        if argv[1] == "formulae":
            return CmdResult(0, "vscode-langservers-extracted\nvim\n", "")
        if argv[1] == "casks":
            return CmdResult(0, "visual-studio-code\nvisual-studio-code@insiders\nvlc\n", "")
        asked.append(argv)
        return CmdResult(0, info, "")

    results = asyncio.run(pk_apps.Brew(run).search("vscode"))
    assert results[0].name == "visual-studio-code"
    assert results[0].title == "Microsoft Visual Studio Code"
    assert "vlc" not in asked[0] and "visual-studio-code@insiders" in asked[0]


def test_brew_no_results() -> None:
    async def run(argv, env):
        if argv[1] in ("formulae", "casks"):
            return CmdResult(0, "", "")
        return CmdResult(1, "", "Error: No formulae or casks found for zzz.")

    assert asyncio.run(pk_apps.Brew(run).search("zzz")) == []


# ---------------------------------------------------------------- flatpak / snap


def test_flatpak_parsers() -> None:
    results = pk_apps.parse_flatpak_search(fx("flatpak/search.txt"))
    calc = next(r for r in results if r.name == "org.gnome.Calculator")
    assert (calc.title, calc.version, calc.source) == ("Calculator", "51.1", "flathub")
    assert pk_apps.parse_flatpak_search(fx("flatpak/search-none.txt")) == []
    inst = pk_apps.parse_flatpak_installed(fx("flatpak/installed.txt"))
    assert inst[1].name == "org.kde.kalk" and inst[1].version == "26.08.2"
    assert pk_apps.parse_flatpak_installed(fx("flatpak/installed-empty.txt")) == []
    ups = pk_apps.parse_flatpak_updates(fx("flatpak/updates.txt"))
    assert (ups[0].name, ups[0].latest) == ("org.kde.kalk", "26.08.3")
    assert pk_apps.Flatpak().install_argv("org.kde.kalk", None)[-2:] == ["flathub", "org.kde.kalk"]


def test_snap_parsers() -> None:
    found = {r.name: r for r in pk_apps.parse_snap_find(fx("snap/find.txt"))}
    assert found["jq"].version == "1.5+dfsg-1"
    assert found["jq"].source == "mvo"  # verified mark stripped
    assert found["yq"].description == "A lightweight and portable command-line YAML processor"
    inst = {p.name: p for p in pk_apps.parse_snap_list(fx("snap/list.txt"))}
    assert inst["lxd"].version == "5.21.2-2f4ba6b" and inst["core22"].source == "canonical"
    ups = pk_apps.parse_snap_refresh_list(fx("snap/refresh-list.txt"))
    assert (ups[0].name, ups[0].latest) == ("lxd", "5.21.3-c5ae129")


# ---------------------------------------------------------------- windows


def test_winget_search_strips_progress_and_reads_columns() -> None:
    results = {r.name: r for r in pk_win.parse_winget_search(fx("winget/search.txt"))}
    assert results["jqlang.jq"].title == "jq"
    assert results["jqlang.jq"].version == "1.7.1"
    assert results["itchyny.gojq"].source == "winget"
    assert results["yamafaktory.jql"].title == "JSON Query Language CLI"
    assert pk_win.parse_winget_search(fx("winget/none.txt")) == []


def test_winget_list_and_upgrade() -> None:
    # Real output from the GitHub Actions Windows runner (CRLF, progress spinner, a
    # truncated name and id, ARP ids with spaces, rows without a source).
    installed, upgradable = pk_win.parse_winget_list(fx("winget/list.txt"))
    by = {p.name: p for p in installed}
    assert by["Git.Git"].version == "2.56.0.4" and by["Git.Git"].source == "winget"
    assert by["ImageMagick.ImageMagick"].title == "ImageMagick 7.1.2-25 Q16-HDRI (64-bit) …"
    firefox = by["ARP\\Machine\\X64\\Mozilla Firefox"]
    assert (firefox.title, firefox.version, firefox.source) == (
        "Mozilla Firefox (x64 en-US)",
        "159.0.1",
        None,
    )
    assert "ARP\\Machine\\X64\\MozillaMaintenanceServi…" in by
    ups = {u.name: u for u in upgradable}
    assert (ups["7zip.7zip"].version, ups["7zip.7zip"].latest) == ("26.05", "26.06")
    assert ups["Anaconda.Miniconda3"].latest == "py314_26.9.4-1"
    assert "Git.Git" not in ups
    _, ups2 = pk_win.parse_winget_list(fx("winget/upgrade.txt"))
    assert [u.name for u in ups2] == ["Git.Git"]  # footer line ignored


def test_winget_no_match_exit_code_is_empty() -> None:
    async def run(argv, env):
        return CmdResult(-1978335212, fx("winget/none.txt"), "")

    assert asyncio.run(pk_win.Winget(run).search("zzz")) == []


def test_scoop_parsers() -> None:
    results = {r.name: r for r in pk_win.parse_scoop_search(fx("scoop/search.txt"))}
    assert results["gojq"].version == "0.12.16" and results["jid"].source == "main"
    inst = {p.name: p for p in pk_win.parse_scoop_export(fx("scoop/export.json"))}
    assert inst["git"].version == "2.45.2"
    ups = pk_win.parse_scoop_status(fx("scoop/status.txt"))
    assert [(u.name, u.version, u.latest) for u in ups] == [("git", "2.45.2", "2.46.0")]
    assert pk_win.Scoop().upgrade_argv(None) == ["scoop", "update", "*"]
    assert pk_win.Scoop().install_argv("jq", "main") == ["scoop", "install", "main/jq"]


def test_choco_parsers() -> None:
    assert next((r.name, r.version) for r in pk_win.parse_choco_search(fx("choco/search.txt"))) == (
        "jq",
        "1.7.1",
    )
    assert {p.name for p in pk_win.parse_choco_list(fx("choco/list.txt"))} == {"chocolatey", "jq"}
    ups = pk_win.parse_choco_outdated(fx("choco/outdated.txt"))
    assert (ups[0].name, ups[0].version, ups[0].latest) == ("jq", "1.6", "1.7.1")
    assert pk_win.Choco().upgrade_argv(None)[:3] == ["choco", "upgrade", "all"]


# ---------------------------------------------------------------- shared


def test_column_table_uses_dash_groups_for_headers_with_spaces() -> None:
    rows = column_table(fx("scoop/status.txt"), min_columns=3)
    assert rows[0][:3] == ["git", "2.45.2", "2.46.0"]


def test_read_failures_raise_with_the_tool_message() -> None:
    async def run(argv, env):
        return CmdResult(100, "", "E: Could not open lock file /var/lib/dpkg/lock-frontend\n")

    with pytest.raises(PackageError, match="lock-frontend"):
        asyncio.run(pk_linux.Apt(run).installed())


def test_names_and_queries_cannot_be_options() -> None:
    for ok in ["jq", "libc6:arm64", "g++", "homebrew/cask/firefox", "Git.Git", "org.kde.kalk"]:
        assert PACKAGE_NAME.match(ok), ok
    for bad in ["-rf", "--all", "", "a b", "x;rm", "$(id)"]:
        assert not PACKAGE_NAME.match(bad), bad
    assert SEARCH_QUERY.match("media server")
    assert not SEARCH_QUERY.match("--help")


def test_every_detected_manager_has_an_implementation() -> None:
    import re

    import athena.platform.detect as detect

    source = Path(detect.__file__).read_text()
    assert set(re.findall(r'PackageManagerSpec\("(\w+)"', source)) == set(MANAGERS)


# ---------------------------------------------------------------- real tools (read-only)

# Which binary shows a manager is present, for the real read tests below. They only read
# (installed list and a search), so they run wherever the tool exists: Homebrew on the
# macOS runner and dev Macs, apt on the Ubuntu runner, Chocolatey on the Windows runner.
# That checks the hand-written Windows fixtures against the real thing in CI.
REAL_PROBE = {"apt": "dpkg-query", "brew": "brew", "choco": "choco", "winget": "winget"}


@pytest.mark.parametrize("manager_id", sorted(REAL_PROBE))
def test_real_tool_reads(manager_id: str) -> None:
    import shutil

    if not shutil.which(REAL_PROBE[manager_id]):
        pytest.skip(f"{manager_id} isn't on this machine")
    pm = MANAGERS[manager_id]()
    installed = asyncio.run(pm.installed())
    if not installed:
        pytest.skip(f"{manager_id} reports nothing installed on this runner")
    # Names are single tokens, except winget's ids for locally installed apps
    # ("ARP\\Machine\\X64\\Mozilla Firefox").
    spaced_ok = manager_id == "winget"
    odd = [
        p for p in installed if not p.name or (not spaced_ok and any(c.isspace() for c in p.name))
    ]
    if odd:
        raw = ""
        if manager_id == "winget":
            from athena.packages.base import run_command

            raw = asyncio.run(run_command(["winget", "list", *pk_win._WINGET_FLAGS], None)).stdout
        lines = "\n".join(repr(line) for line in raw.splitlines()[:25])
        pytest.fail(f"{manager_id}: odd names {[(p.name, p.title) for p in odd][:5]}\n{lines}")
    if manager_id in ("apt", "brew"):  # searches that work from local package data
        found = asyncio.run(pm.search("jq"))
        assert any(r.name == "jq" for r in found), [r.name for r in found][:10]


# ---------------------------------------------------------------- aliases and name matching


def test_abbreviation_match() -> None:
    from athena.packages.aliases import abbreviation_match as ab

    assert ab("vscode", "visual-studio-code")
    assert ab("vs code", "visual-studio-code@insiders")
    assert ab("vsc", "visual-studio-code")
    assert ab("gcp", "google-cloud-platform")
    assert not ab("vscode", "vscode")  # a plain name isn't an abbreviation
    assert not ab("vscode", "vlc")
    assert not ab("code", "visual-studio-code")  # must start at the first word
    assert not ab("vscode", "vscode-langservers-extracted")
    assert not ab("vs", "visual-studio-code")  # too short


def test_expand_query_and_rank() -> None:
    from athena.packages.aliases import expand_query, match_rank

    assert expand_query("vscode") == ["vscode", "visual studio code"]
    assert expand_query("jq") == ["jq"]
    assert expand_query("visual-studio") == ["visual-studio", "visual studio"]
    assert match_rank("vscode", "visual-studio-code") == 1
    assert match_rank("vscode", "x", "VS Code") == 0
    assert match_rank("jq", "jq") == 0 < match_rank("jq", "jquake") == 2 < match_rank("jq", "gojq")


def test_find_merges_aliases_and_ignores_failing_alias() -> None:
    class Fake(pk_apps.PackageManager):
        id = "fake"
        label = "Fake"

        async def search(self, query):
            if query == "vscode":
                return []
            if query == "visual studio code":
                return [pk_apps.PackageRef(name="Microsoft.VisualStudioCode")]
            raise PackageError("boom")

    found = asyncio.run(Fake().find("vscode"))
    assert [r.name for r in found] == ["Microsoft.VisualStudioCode"]


# ---------------------------------------------------------------- details (`info`)


def info(path: str) -> str:
    return fx(f"info/{path}")


def test_apt_show() -> None:
    d = pk_linux.parse_apt_show(info("apt.txt"))
    assert (d.name, d.version) == ("jq", "1.7.1-6+deb13u4")
    assert d.summary == "lightweight and flexible command-line JSON processor"
    assert d.homepage == "https://jqlang.github.io/jq" and d.size == "161 KiB"
    assert d.dependencies == ["libc6", "libjq1"]
    assert d.source == "utils" and not d.has_icon


def test_rpm_info_dnf_and_zypper() -> None:
    d = pk_linux.parse_rpm_info(info("dnf.txt"))
    assert (d.name, d.version) == ("jq", "1.8.2-5.fc45")
    assert d.summary == "Command-line JSON processor"
    assert d.license == "MIT AND ICU AND CC-BY-3.0" and d.homepage == "https://jqlang.org/"
    assert d.source == "fedora" and d.maintainer == "Fedora Project"
    assert d.description and "jq is like sed" in d.description
    z = pk_linux.parse_rpm_info(info("zypper.txt"))
    assert (z.name, z.version, z.source) == ("jq", "1.8.2-3.1", "openSUSE-Tumbleweed-Oss")
    assert z.homepage == "https://github.com/jqlang"
    assert z.description and z.description.startswith("A lightweight and flexible")


def test_pacman_and_apk_info() -> None:
    p = pk_linux.parse_pacman_info(info("pacman.txt"))
    assert (p.name, p.version, p.license, p.source) == ("jq", "1.8.2-1", "MIT", "extra")
    assert p.dependencies == ["glibc", "oniguruma"] and p.size == "480.87 KiB"
    a = pk_linux.parse_apk_info(info("apk.txt"), "jq")
    assert (a.version, a.license, a.size) == ("1.8.2-r0", "MIT", "387 KiB")
    assert a.homepage == "https://jqlang.github.io/jq/" and a.dependencies == []


def test_brew_details() -> None:
    cask = pk_apps.parse_brew_details(info("brew-cask.json"), "cask")
    assert cask.name == "visual-studio-code" and cask.title == "Microsoft Visual Studio Code"
    assert cask.homepage == "https://code.visualstudio.com/" and cask.source == "cask"
    assert not cask.installed and not cask.has_icon
    formula = pk_apps.parse_brew_details(info("brew-formula.json"), "formula")
    assert (formula.name, formula.license, formula.dependencies) == ("jq", "MIT", ["oniguruma"])
    with pytest.raises(PackageError):
        pk_apps.parse_brew_details('{"formulae": [], "casks": []}')


def test_brew_info_argv_picks_cask() -> None:
    calls = []

    async def run(argv, env):
        calls.append(argv)
        return CmdResult(0, info("brew-cask.json"), "")

    d = asyncio.run(pk_apps.Brew(run).details("visual-studio-code", "cask"))
    assert calls[0] == ["brew", "info", "--json=v2", "--cask", "visual-studio-code"]
    assert d.name == "visual-studio-code"


def test_flatpak_info_uses_flathub_for_icon_and_text() -> None:
    store = json.loads(info("flathub.json"))
    d = pk_apps.parse_flatpak_info(info("flatpak.txt"), "org.gnome.Calculator", "flathub", store)
    assert d.title == "Calculator" and d.license == "GPL-3.0-or-later"
    assert d.summary == "Perform arithmetic, scientific or financial calculations"
    assert d.description and "<p>" not in d.description
    assert d.size == "5.2 MB" and d.has_icon and d.icon_url.startswith("https://dl.flathub.org/")
    bare = pk_apps.parse_flatpak_info(info("flatpak.txt"), "org.gnome.Calculator", "other")
    assert not bare.has_icon and bare.name == "org.gnome.Calculator"


def test_snap_store_details() -> None:
    d = pk_apps.parse_snap_store(json.loads(info("snap.json")), "vlc")
    assert (d.name, d.license, d.maintainer) == ("vlc", "GPL-2.0+", "VideoLAN")
    assert d.homepage == "https://www.videolan.org/vlc/" and d.size and d.size.endswith("MiB")
    assert d.icon_url == "https://dashboard.snapcraft.io/site_media/appmedia/2016/07/vlc.png"


def test_windows_details() -> None:
    w = pk_win.parse_winget_show(info("winget.txt"), "Git.Git")
    assert (w.name, w.title, w.version) == ("Git.Git", "Git", "2.47.1")
    assert w.homepage == "https://gitforwindows.org/" and w.maintainer.startswith("The Git")
    assert w.description and "BASH emulation" in w.description
    assert w.extra[0].value == "git vcs"
    s = pk_win.parse_scoop_info(info("scoop.txt"), "7zip")
    assert (s.version, s.homepage, s.installed, s.installed_version) == (
        "24.09", "https://www.7-zip.org", True, "24.09"
    )  # fmt: skip
    c = pk_win.parse_choco_info(info("choco.txt"), "git")
    assert (c.name, c.version, c.title) == ("git", "2.47.1", "Git")
    assert c.homepage == "https://git-scm.com/" and c.summary == "Git (for Windows)"
    assert c.description and "Note: this is only a mirror" in c.description


def test_info_fills_installed_state() -> None:
    async def run(argv, env):
        if argv[0] == "apt-cache":
            return CmdResult(0, info("apt.txt"), "")
        return CmdResult(0, "ii \tjq\t1.7\tjson processor\n", "")

    d = asyncio.run(pk_linux.Apt(run).info("jq"))
    assert d.installed and d.installed_version == "1.7"


def test_parse_fields_ignores_colons_in_text() -> None:
    f = parse_fields(
        "Name : x\nDescription : first\n  Note: kept\nURL : https://a",
        {"name", "description", "url"},
    )
    assert f == {"name": "x", "description": "first\nNote: kept", "url": "https://a"}


def test_image_host_allow_list() -> None:
    from athena.packages import http

    assert http.host_allowed("https://dl.flathub.org/a.png", ("flathub.org",))
    assert not http.host_allowed("http://dl.flathub.org/a.png", ("flathub.org",))
    assert not http.host_allowed("https://evilflathub.org/a.png", ("flathub.org",))
    assert not http.host_allowed("https://flathub.org.evil.com/a.png", ("flathub.org",))
    assert pk_apps.Flatpak.image_hosts() == ("flathub.org", "flatpak.org")
    assert "debian.org" in pk_linux.Apt.image_hosts()
    with pytest.raises(PackageError):
        asyncio.run(http.fetch_image("https://example.com/x.png", ("flathub.org",)))


def _mock_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    import httpx2

    from athena.packages import http

    http._cache.clear()
    real = httpx2.AsyncClient
    monkeypatch.setattr(
        http.httpx2,
        "AsyncClient",
        lambda **kw: real(transport=httpx2.MockTransport(handler), **kw),
    )


def test_fetch_image_checks_type_size_and_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx2

    from athena.packages import http

    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path == "/ok.png":
            return httpx2.Response(200, content=b"png", headers={"content-type": "image/png"})
        if path == "/page":
            return httpx2.Response(200, content=b"<html>", headers={"content-type": "text/html"})
        if path == "/big.png":
            big = b"x" * (http.MAX_IMAGE_BYTES + 1)
            return httpx2.Response(200, content=big, headers={"content-type": "image/png"})
        if path == "/away":
            return httpx2.Response(302, headers={"location": "https://evil.example/x.png"})
        if path == "/within":
            return httpx2.Response(302, headers={"location": "https://cdn.flathub.org/ok.png"})
        return httpx2.Response(404)

    _mock_client(monkeypatch, handler)
    hosts = ("flathub.org",)

    async def get(path: str, host: str = "dl.flathub.org"):
        return await http.fetch_image(f"https://{host}{path}", hosts)

    assert asyncio.run(get("/ok.png")) == (b"png", "image/png")
    assert asyncio.run(get("/within")) == (b"png", "image/png")
    for bad in ("/page", "/big.png", "/away", "/missing"):
        with pytest.raises(PackageError):
            asyncio.run(get(bad))
