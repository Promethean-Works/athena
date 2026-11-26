"""The catalog smoke test's selection, install values and report (no container engine)."""

import argparse
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from athena.catalog import smoke
from athena.catalog.model import parse_app

COMPOSE = """\
services:
  web:
    image: nginx:1
    ports: ["${WEB_PORT}:80"]
    volumes: ["${MEDIA}:/media", "${CONFIG}:/config"]
x-athena:
  title: Demo
  description: d
  category: utilities
  web_port: WEB_PORT
  env:
    - {key: WEB_PORT, label: Port, type: port, default: "8080"}
    - {key: MEDIA, label: Media, type: path, default: /DATA/Media}
    - {key: CONFIG, label: Config, type: path, default: "@app_data/config"}
    - {key: PASSWORD, label: Password, type: password, generate: secret}
"""


def app(app_id: str = "demo", compose: str = COMPOSE, extra: str = ""):
    text = compose + extra
    return parse_app(app_id, "builtin", [("compose.yaml", text, smoke.parse_compose(text))])


class FakeEngine:
    def __init__(self) -> None:
        self.next = 40000

    def free_port(self) -> int:
        self.next += 1
        return self.next


def test_install_values_move_ports_and_paths(tmp_path: Path) -> None:
    demo = app()
    target = smoke.Target(demo, demo.variants[0])
    values = smoke.install_values(target, tmp_path, FakeEngine())  # type: ignore[arg-type]
    assert values["WEB_PORT"] == "40001"
    assert values["MEDIA"] == str(tmp_path / "paths" / "media")
    assert (tmp_path / "paths" / "media").is_dir()
    assert values["CONFIG"] == str(tmp_path / "data" / "config")
    assert len(values["PASSWORD"]) >= 24
    assert smoke._web_port(demo.variants[0], demo, values) == 40001


def test_project_names_are_prefixed() -> None:
    demo = app()
    assert smoke.Target(demo, demo.variants[0]).project == "athena-test-demo"


def test_smoke_metadata_defaults_to_web() -> None:
    assert app().meta.smoke == "web"
    marked = app(extra="  smoke: skip\n  smoke_note: needs an NVIDIA GPU\n")
    assert marked.meta.smoke == "skip"
    assert marked.meta.smoke_note == "needs an NVIDIA GPU"


def test_host_network_is_detected() -> None:
    assert not smoke._uses_host_network(COMPOSE)
    assert smoke._uses_host_network("services:\n  a:\n    image: x\n    network_mode: host\n")


def test_select_and_shard() -> None:
    apps = [app(f"a{i}") for i in range(5)]
    assert [t.app.id for t in smoke.select(apps, [], False, None)] == [f"a{i}" for i in range(5)]
    assert [t.app.id for t in smoke.select(apps, ["a3", "a1"], False, None)] == ["a1", "a3"]
    shards = [[t.app.id for t in smoke.select(apps, [], False, (k, 2))] for k in (1, 2)]
    assert shards == [["a0", "a2", "a4"], ["a1", "a3"]]


@pytest.mark.parametrize("value", ["0/2", "3/2", "x", "1/", "/2"])
def test_bad_shards(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        smoke._shard(value)


def test_summary_lists_failures_first() -> None:
    results = [
        smoke.Result("b", "default", "passed", "web", "HTTP 200", 3.0),
        smoke.Result("a", "postgres", "failed", "pull", "manifest unknown | x", 1.0),
        smoke.Result("c", "default", "skipped", "unsupported CPU"),
    ]
    text = smoke.summary(results, "aarch64", "darwin")
    assert "1 passed, 1 failed, 1 skipped." in text
    rows = [line for line in text.splitlines() if line.startswith("| ") and "❌" in line]
    assert rows == ["| a (postgres) | ❌ failed | pull | manifest unknown \\| x | 1.0 |"]
    assert text.index("a (postgres)") < text.index("| b |") < text.index("| c |")


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_changed_apps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Git hooks export GIT_DIR and GIT_INDEX_FILE; left in, `git init` here would act on
    # the real repository (it once set core.bare = true there and committed to its branch).
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    root = tmp_path / "catalog"
    for app_id in ("old", "edited"):
        (root / "apps" / app_id).mkdir(parents=True)
        (root / "apps" / app_id / "compose.yaml").write_text("a\n")
    git("init", "-q", "-b", "main")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "x", "--allow-empty")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    git("branch", "base")
    (root / "apps" / "edited" / "compose.yaml").write_text("b\n")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "edit")
    (root / "apps" / "new").mkdir()
    (root / "apps" / "new" / "compose.yaml").write_text("c\n")  # untracked
    assert smoke.changed_apps(root, "base") == {"edited", "new"}


def test_profiles_flag_adds_one_run_per_app_with_optional_parts() -> None:
    import yaml

    from athena.catalog.model import parse_app
    from athena.catalog.smoke import select

    plain = "services:\n  a:\n    image: x:1\n"
    head = "x-athena:\n  title: T\n  description: d\n  category: utilities\n"
    with_profile = (
        head
        + "  profiles:\n    - {id: extra, label: Extra}\n"
        + plain
        + "  b:\n    image: y:1\n    profiles: [extra]\n"
    )
    apps = [
        parse_app(name, "builtin", [("compose.yaml", text, yaml.safe_load(text))])
        for name, text in (("plain", head + plain), ("rich", with_profile))
    ]
    assert [t.project for t in select(apps, [], False, None)] == [
        "athena-test-plain",
        "athena-test-rich",
    ]
    targets = select(apps, [], False, None, with_profiles=True)
    assert [t.project for t in targets] == [
        "athena-test-plain",
        "athena-test-rich",
        "athena-test-rich-profiles",
    ]
    assert targets[-1].with_profiles
