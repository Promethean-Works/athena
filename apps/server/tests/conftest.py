from pathlib import Path

import pytest
from fake_probe import FakeProbe
from fastapi.testclient import TestClient

from athena.assistant import models_dev
from athena.config import Settings
from athena.main import create_app
from athena.platform.detect import detect
from athena.platform.store import CapabilityStore


@pytest.fixture(autouse=True)
def _no_models_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every app start refreshes the models.dev cache; tests never reach the internet."""

    async def empty(self: models_dev.ModelsDevService) -> dict:
        return {}

    monkeypatch.setattr(models_dev.ModelsDevService, "_fetch_models_dev", empty)


@pytest.fixture(autouse=True)
def _no_update_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """The update notice checks GitHub on every app start; tests never reach it."""
    monkeypatch.setenv("ATHENA_UPDATE_CHECK_URL", "")


ADMIN = {"username": "admin", "password": "correct horse battery"}


def make_app(
    tmp_path: Path,
    web_dir: Path | None = None,
    store: CapabilityStore | None = None,
    **settings_args,
):
    settings = Settings(
        data_dir=tmp_path / "data", web_dir=web_dir or tmp_path / "no-web", **settings_args
    )
    store = store or CapabilityStore(detector=lambda: detect(FakeProbe(os="darwin")))
    return create_app(settings, capability_store=store)


def signed_in(client: TestClient) -> TestClient:
    """Create the admin (first run) and send the CSRF header on every request."""
    res = client.post("/api/auth/setup", json=ADMIN)
    assert res.status_code == 201, res.text
    client.headers["X-CSRF-Token"] = res.json()["csrf_token"]
    return client
