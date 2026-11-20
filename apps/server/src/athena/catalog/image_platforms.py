"""Look up which platforms a catalog app's images are published for, and write them
into its ``x-athena.platforms``.

    cd apps/server
    uv run python -m athena.catalog.image_platforms               # report differences
    uv run python -m athena.catalog.image_platforms --write       # update compose.yaml files
    uv run python -m athena.catalog.image_platforms jellyfin gitea --write

Docker Hub images are read through hub.docker.com's tag API, which doesn't count
against the anonymous pull rate limit. Other registries (ghcr.io, lscr.io, quay.io,
…) are read through the OCI distribution API with an anonymous token. An app's
platforms are the ones every image of its default compose file has.
"""

import argparse
import re
import sys
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import httpx2

from athena.catalog.loader import builtin_catalog_dir, load_catalog
from athena.catalog.model import CatalogApp
from athena.catalog.platforms import KNOWN_PLATFORMS, normalize

TIMEOUT = 20.0
RETRIES = 3
MAX_WAIT = 90
MANIFEST_TYPES = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)
_ALIASES = {"docker.io": "registry-1.docker.io", "index.docker.io": "registry-1.docker.io"}
_REDIRECTS = {"lscr.io": "ghcr.io"}  # LinuxServer's lscr.io serves the same images as ghcr.io


class ImageLookupError(Exception):
    """An image couldn't be read from its registry."""


@dataclass(frozen=True)
class ImageRef:
    registry: str
    repository: str
    reference: str
    """A tag or a ``sha256:`` digest."""


def parse_image(image: str) -> ImageRef:
    """``nginx`` -> docker.io/library/nginx:latest; ``ghcr.io/a/b:1`` -> ghcr.io a/b 1."""
    name, _, digest = image.partition("@")
    first, _, rest = name.partition("/")
    if rest and ("." in first or ":" in first or first == "localhost"):
        registry, path = first.lower(), rest
    else:
        registry, path = "docker.io", name
    tag = ""
    if ":" in path.rsplit("/", 1)[-1]:
        path, tag = path.rsplit(":", 1)
    if registry == "docker.io" and "/" not in path:
        path = f"library/{path}"
    return ImageRef(_REDIRECTS.get(registry, registry), path, digest or tag or "latest")


def _platform(os_: str | None, arch: str | None, variant: str | None) -> str | None:
    if os_ != "linux" or not arch:
        return None  # attestation manifests say unknown/unknown
    value = normalize(f"linux/{arch}" + (f"/{variant}" if arch == "arm" and variant else ""))
    return value if value in KNOWN_PLATFORMS else None


def _get(client: httpx2.Client, url: str, **kwargs) -> httpx2.Response:
    """GET, waiting out a 429 (Docker Hub's tag API allows about 180 requests a minute)."""
    for attempt in range(RETRIES + 1):
        res = client.get(url, **kwargs)
        if res.status_code != 429 or attempt == RETRIES:
            return res
        retry_after = res.headers.get("retry-after", "")
        time.sleep(min(int(retry_after) if retry_after.isdigit() else 30, MAX_WAIT))
    return res


def _hub(client: httpx2.Client, ref: ImageRef) -> set[str]:
    url = f"https://hub.docker.com/v2/repositories/{ref.repository}/tags/{ref.reference}"
    res = _get(client, url)
    if res.status_code == 404:
        raise ImageLookupError("tag not found on Docker Hub")
    res.raise_for_status()
    images = res.json().get("images") or []
    return {
        p for i in images if (p := _platform(i.get("os"), i.get("architecture"), i.get("variant")))
    }


def _token(client: httpx2.Client, challenge: str) -> str:
    params = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
    realm = params.pop("realm", None)
    if not challenge.lower().startswith("bearer") or not realm:
        raise ImageLookupError(f"unsupported auth challenge: {challenge[:80]}")
    res = _get(client, realm, params=params)
    if res.status_code in (401, 403):
        raise ImageLookupError("registry denied anonymous access")
    res.raise_for_status()
    body = res.json()
    return body.get("token") or body.get("access_token") or ""


def _registry_get(
    client: httpx2.Client, ref: ImageRef, path: str, auth: dict[str, str], accept: str
) -> httpx2.Response:
    host = _ALIASES.get(ref.registry, ref.registry)
    url = f"https://{host}/v2/{ref.repository}/{path}"
    res = _get(client, url, headers={"Accept": accept, **auth})
    if res.status_code == 401 and not auth:
        auth["Authorization"] = f"Bearer {_token(client, res.headers.get('www-authenticate', ''))}"
        res = _get(client, url, headers={"Accept": accept, **auth})
    if res.status_code in (401, 403):
        raise ImageLookupError("registry denied anonymous access")
    if res.status_code == 404:
        raise ImageLookupError("image or tag not found")
    res.raise_for_status()
    return res


def _oci(client: httpx2.Client, ref: ImageRef) -> set[str]:
    auth: dict[str, str] = {}
    manifest = _registry_get(client, ref, f"manifests/{ref.reference}", auth, MANIFEST_TYPES).json()
    if "manifests" in manifest:  # an index: one entry per platform
        return {
            p
            for m in manifest["manifests"]
            if (pl := m.get("platform") or {})
            and (p := _platform(pl.get("os"), pl.get("architecture"), pl.get("variant")))
        }
    # A single-platform image: the platform is in its config blob.
    digest = (manifest.get("config") or {}).get("digest")
    if not digest:
        raise ImageLookupError("manifest has no config")
    config = _registry_get(client, ref, f"blobs/{digest}", auth, "*/*").json()
    platform = _platform(config.get("os"), config.get("architecture"), config.get("variant"))
    return {platform} if platform else set()


def image_platforms(client: httpx2.Client, image: str) -> set[str]:
    """The known platforms ``image`` is published for. Raises ImageLookupError."""
    if "${" in image:
        raise ImageLookupError("image name uses a variable")
    ref = parse_image(image)
    try:
        if ref.registry == "docker.io" and not ref.reference.startswith("sha256:"):
            return _hub(client, ref)
        return _oci(client, ref)
    except httpx2.HTTPStatusError as exc:
        raise ImageLookupError(f"HTTP {exc.response.status_code}") from exc
    except (httpx2.HTTPError, ValueError) as exc:
        raise ImageLookupError(str(exc) or type(exc).__name__) from exc


@dataclass
class AppResult:
    app: CatalogApp
    platforms: list[str] | None
    """Sorted like KNOWN_PLATFORMS; None when an image couldn't be read."""
    errors: dict[str, str]


def lookup_apps(
    apps: Iterable[CatalogApp],
    workers: int = 4,
    transport: httpx2.BaseTransport | None = None,
) -> list[AppResult]:
    apps = list(apps)
    images = sorted({image for app in apps for image in app.images})
    found: dict[str, set[str]] = {}
    failed: dict[str, str] = {}

    with httpx2.Client(timeout=TIMEOUT, follow_redirects=True, transport=transport) as client:

        def one(image: str) -> None:
            try:
                found[image] = image_platforms(client, image)
            except ImageLookupError as exc:
                failed[image] = str(exc)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one, images))

    results = []
    for app in apps:
        errors = {i: failed[i] for i in app.images if i in failed}
        platforms = None
        if not errors:
            common = set(KNOWN_PLATFORMS)
            for image in app.images:
                common &= found[image]
            platforms = [p for p in KNOWN_PLATFORMS if p in common]
        results.append(AppResult(app, platforms, errors))
    return results


# ---------------------------------------------------------------- writing compose files

_X_ATHENA = re.compile(r"^x-athena:\s*$", re.M)
DECLARED = re.compile(r"^  platforms:", re.M)
_BLOCK_KEY = re.compile(r"^  [A-Za-z_][\w-]*:", re.M)


def set_platforms(text: str, platforms: list[str]) -> str:
    """Replace or add ``platforms:`` in the ``x-athena`` block, keeping everything else."""
    start = _X_ATHENA.search(text)
    if start is None:
        raise ValueError("no top-level x-athena block")
    end_match = re.compile(r"^\S", re.M).search(text, start.end())
    end = end_match.start() if end_match else len(text)
    block = text[start.end() : end]
    line = f"  platforms: [{', '.join(platforms)}]\n"

    existing = re.search(r"^  platforms:.*\n", block, re.M)
    if existing:
        # Drop the key and any `- item` lines under it.
        tail = block[existing.end() :]
        items = re.match(r"(?:^  (?: {2})?- .*\n)*", tail, re.M)
        cut = existing.end() + (items.end() if items else 0)
        block = block[: existing.start()] + line + block[cut:]
    else:
        category = re.search(r"^  category:.*\n", block, re.M)
        at = category.end() if category else 0
        if not category:
            first = _BLOCK_KEY.search(block)
            at = first.start() if first else 0
        block = block[:at] + line + block[at:]
    return text[: start.end()] + block + text[end:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("apps", nargs="*", help="app ids (default: every built-in app)")
    parser.add_argument("--write", action="store_true", help="update the compose.yaml files")
    args = parser.parse_args(argv)

    root = builtin_catalog_dir()
    if root is None:
        print("catalog/ not found", file=sys.stderr)
        return 2
    apps, errors = load_catalog(root, "builtin")
    if errors:
        print("\n".join(errors), file=sys.stderr)
    if args.apps:
        wanted = set(args.apps)
        apps = [a for a in apps if a.id in wanted]
        if missing := wanted - {a.id for a in apps}:
            print(f"unknown apps: {', '.join(sorted(missing))}", file=sys.stderr)
            return 2

    changed = unreadable = 0
    for result in lookup_apps(apps):
        app = result.app
        if result.platforms is None:
            unreadable += 1
            for image, error in result.errors.items():
                print(f"! {app.id}: {image}: {error}")
            continue
        if not result.platforms:
            print(f"! {app.id}: no image runs on any of {', '.join(KNOWN_PLATFORMS)}")
            continue
        path: Path = root / "apps" / app.id / "compose.yaml"
        text = path.read_text(encoding="utf-8")
        updated = set_platforms(text, result.platforms)
        if updated == text:
            continue
        changed += 1
        declared = app.meta.platforms if DECLARED.search(text) else "(not set)"
        print(f"~ {app.id}: {declared} -> {result.platforms}")
        if args.write:
            path.write_text(updated, encoding="utf-8")

    verb = "updated" if args.write else "differ"
    print(f"{len(apps)} apps: {changed} {verb}, {unreadable} couldn't be read")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
