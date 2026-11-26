"""Builds the capability manifest for the current host.

Each detector is a small function of a `Probe`, returns one `Capability`, and never
raises: a failed probe becomes `missing` (or `stopped`) with a `detail` string.
Only capabilities relevant to the host's OS are reported, so a Mac never sees apt.
"""

import logging
import platform
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from athena import __version__
from athena.platform import power
from athena.platform.capabilities import Capability, CapabilityManifest, Status
from athena.platform.probe import Probe, os_version
from athena.service.platforms import (
    LAUNCHD_LABEL,
    SERVICE_NAME,
    WINDOWS_TASK,
    launchd_domain,
)

log = logging.getLogger(__name__)

Detector = Callable[[Probe], Capability | list[Capability]]

CONTAINERS = "containers"
CONTAINERS_LABEL = "Containers"


# ---------------------------------------------------------------- containers


def _engine(provider: str, version: str, where: str, endpoint: str | None) -> Capability:
    return Capability(
        id=CONTAINERS,
        label=CONTAINERS_LABEL,
        status="ready",
        provider=provider,
        detail=f"Engine {version} at {where}",
        endpoint=endpoint,
    )


def _no_runtime(detail: str) -> Capability:
    return Capability(
        id=CONTAINERS, label=CONTAINERS_LABEL, status="missing", detail=detail, actions=["setup"]
    )


def detect_containers_linux(probe: Probe) -> Capability:
    candidates = [
        ("docker-engine", "/var/run/docker.sock"),
        ("podman", "/run/podman/podman.sock"),
    ]
    for provider, sock in candidates:
        version = probe.docker_version(f"unix://{sock}")
        if version:
            return _engine(provider, version, sock, f"unix://{sock}")
    if probe.which("dockerd") or probe.exists("/var/run/docker.sock"):
        return Capability(
            id=CONTAINERS,
            label=CONTAINERS_LABEL,
            status="stopped",
            provider="docker-engine",
            detail="Docker Engine is installed but not responding",
            actions=["start"],
        )
    if probe.which("podman"):
        return Capability(
            id=CONTAINERS,
            label=CONTAINERS_LABEL,
            status="stopped",
            provider="podman",
            detail="Podman is installed, but its API socket isn't running "
            "(systemctl enable --now podman.socket)",
            actions=["start"],
        )
    return _no_runtime("No container engine found. Install Docker Engine or Podman.")


def detect_containers_darwin(probe: Probe) -> Capability:
    # Unix socket paths are always POSIX, even when tests build this plan on Windows.
    colima_sock = (probe.home() / ".colima" / "default" / "docker.sock").as_posix()
    if probe.which("colima"):
        version = probe.docker_version(f"unix://{colima_sock}")
        if version:
            return _engine("colima", version, colima_sock, f"unix://{colima_sock}")
        return Capability(
            id=CONTAINERS,
            label=CONTAINERS_LABEL,
            status="stopped",
            provider="colima",
            detail="Colima is installed but not running",
            actions=["start"],
        )
    if probe.which("podman"):
        result = probe.run(
            ["podman", "machine", "inspect", "--format", "{{.ConnectionInfo.PodmanSocket.Path}}"]
        )
        sock = result.first_line
        if result.ok and sock and (version := probe.docker_version(f"unix://{sock}")):
            return _engine("podman", version, sock, f"unix://{sock}")
        return Capability(
            id=CONTAINERS,
            label=CONTAINERS_LABEL,
            status="stopped",
            provider="podman",
            detail="Podman is installed but its machine isn't running",
            actions=["start"],
        )
    return _no_runtime(
        "Colima not found. Install it with: brew install colima docker docker-compose"
    )


def detect_containers_windows(probe: Probe) -> Capability:
    # Preference order from the design: Docker Engine in WSL2, Podman, Rancher Desktop.
    if probe.which("wsl"):
        result = probe.run(
            ["wsl.exe", "-e", "sh", "-c", "docker version --format '{{.Server.Version}}'"],
            timeout=10,
        )
        if result.ok and result.first_line:
            # No socket reachable from Windows: commands go through `wsl.exe -e docker`.
            return _engine("wsl-docker", result.first_line, "the default WSL distro", None)
    version = probe.docker_version("npipe:////./pipe/podman-machine-default")
    if version:
        return _engine(
            "podman",
            version,
            r"\\.\pipe\podman-machine-default",
            "npipe:////./pipe/podman-machine-default",
        )
    version = probe.docker_version("npipe:////./pipe/docker_engine")
    if version:
        provider = "rancher-desktop" if probe.which("rdctl") else "docker-engine"
        return _engine(
            provider, version, r"\\.\pipe\docker_engine", "npipe:////./pipe/docker_engine"
        )
    if probe.which("podman") or probe.which("rdctl"):
        return Capability(
            id=CONTAINERS,
            label=CONTAINERS_LABEL,
            status="stopped",
            provider="podman" if probe.which("podman") else "rancher-desktop",
            detail="A container runtime is installed but not running",
            actions=["start"],
        )
    return _no_runtime(
        "No container runtime found. Install Docker Engine in WSL2, Podman, or Rancher Desktop."
    )


# ---------------------------------------------------------------- package managers


@dataclass(frozen=True)
class PackageManagerSpec:
    id: str
    label: str
    binary: str
    version_args: tuple[str, ...] = ("--version",)
    system_wide: bool = False
    """Needs root on Linux (installs into the system)."""


LINUX_PACKAGE_MANAGERS = [
    PackageManagerSpec("apt", "APT", "apt-get", system_wide=True),
    PackageManagerSpec("dnf", "DNF", "dnf", system_wide=True),
    PackageManagerSpec("pacman", "pacman", "pacman", system_wide=True),
    PackageManagerSpec("zypper", "zypper", "zypper", system_wide=True),
    PackageManagerSpec("apk", "apk", "apk", system_wide=True),
    PackageManagerSpec("flatpak", "Flatpak", "flatpak"),
    PackageManagerSpec("snap", "Snap", "snap", system_wide=True),
    PackageManagerSpec("brew", "Homebrew", "brew"),
]
DARWIN_PACKAGE_MANAGERS = [PackageManagerSpec("brew", "Homebrew", "brew")]
WINDOWS_PACKAGE_MANAGERS = [
    PackageManagerSpec("winget", "WinGet", "winget"),
    PackageManagerSpec("scoop", "Scoop", "scoop"),
    PackageManagerSpec("choco", "Chocolatey", "choco"),
]


def detect_package_manager(spec: PackageManagerSpec, probe: Probe) -> Capability:
    cap_id = f"packages.{spec.id}"
    path = probe.which(spec.binary)
    if not path:
        return Capability(id=cap_id, label=spec.label, status="missing", provider=spec.id)
    version = probe.run([path, *spec.version_args]).first_line or None
    if probe.os == "linux" and spec.system_wide and not probe.is_root():
        return Capability(
            id=cap_id,
            label=spec.label,
            status="needs_privilege",
            provider=spec.id,
            detail="Athena must run as root to install system packages",
        )
    if spec.id == "brew" and probe.is_root():
        return Capability(
            id=cap_id,
            label=spec.label,
            status="needs_privilege",
            provider=spec.id,
            detail="Homebrew refuses to run as root",
        )
    return Capability(id=cap_id, label=spec.label, status="ready", provider=spec.id, detail=version)


# ---------------------------------------------------------------- other capabilities


def detect_terminal(probe: Probe) -> Capability:
    if probe.os == "windows":
        # ConPTY arrived in Windows 10 1809 (build 17763).
        if probe.windows_build() >= 17763:
            return Capability(
                id="terminal.host", label="Terminal", status="ready", provider="conpty"
            )
        return Capability(
            id="terminal.host",
            label="Terminal",
            status="unsupported",
            detail="Needs Windows 10 1809 or later",
        )
    return Capability(id="terminal.host", label="Terminal", status="ready", provider="pty")


WSL_CHECK = ["wsl.exe", "-e", "sh", "-c", "echo athena-wsl-ok"]


def detect_assistant_shell(probe: Probe) -> Capability:
    """Where the assistant's shell runs (§4.5): the host's own sh on Linux and macOS; on
    Windows, the default WSL distro when there is one, else PowerShell."""
    label = "Assistant shell"
    if probe.os != "windows":
        return Capability(id="assistant.shell", label=label, status="ready", provider="posix")
    if probe.which("wsl") and probe.run(WSL_CHECK, timeout=10).first_line == "athena-wsl-ok":
        return Capability(
            id="assistant.shell",
            label=label,
            status="ready",
            provider="wsl",
            detail="Runs in the default WSL distro",
        )
    return Capability(
        id="assistant.shell",
        label=label,
        status="ready",
        provider="powershell",
        detail="Runs in PowerShell (install a WSL distro for a Linux shell)",
    )


def detect_power(probe: Probe) -> list[Capability]:
    """Raspberry Pi under-voltage and throttling flags. Reported only on hosts that have
    them, so no other host sees a "missing" row for hardware it doesn't have."""
    source = power.find_source(probe)
    if source is None:
        return []
    return [
        Capability(
            id="host.power",
            label="Power and throttling",
            status="ready",
            provider=source.provider,
            detail="Raspberry Pi firmware flags",
        )
    ]


def detect_smb(probe: Probe) -> Capability:
    """SMB shares: publish a file location over the network (§4.3). Linux uses the
    installed Samba server, macOS its built-in `sharing` tool (both need root); Windows
    isn't wired yet."""
    label = "SMB shares"
    if probe.os == "linux":
        if probe.which("smbd"):
            return Capability(id="shares.smb", label=label, status="ready", provider="samba")
        return Capability(
            id="shares.smb",
            label=label,
            status="missing",
            provider="samba",
            detail="Samba not installed. Install it (apt install samba) to share folders over SMB.",
            actions=["setup"],
        )
    if probe.os == "darwin" and probe.which("sharing"):
        if probe.is_root():
            return Capability(id="shares.smb", label=label, status="ready", provider="sharing")
        return Capability(
            id="shares.smb",
            label=label,
            status="needs_privilege",
            provider="sharing",
            detail="Sharing folders over SMB needs Athena to run as root.",
        )
    return Capability(
        id="shares.smb",
        label=label,
        status="unsupported",
        provider="built-in",
        detail="Creating SMB shares from Athena isn't available on this operating system yet.",
    )


def detect_nfs(probe: Probe) -> Capability:
    """NFS shares: export a file location from the host's NFS server
    (docs/specs/network-shares.md). Linux only for now; Windows client editions have no
    NFS server. macOS uses its built-in nfsd (needs root)."""
    label = "NFS shares"
    if probe.os == "linux":
        if not probe.which("exportfs"):
            return Capability(
                id="shares.nfs",
                label=label,
                status="missing",
                provider="nfs-kernel-server",
                detail="NFS server not installed. Install it (apt install nfs-kernel-server).",
                actions=["setup"],
            )
        if not probe.is_root():
            return Capability(
                id="shares.nfs",
                label=label,
                status="needs_privilege",
                provider="nfs-kernel-server",
                detail="Exporting folders over NFS needs Athena to run as root.",
            )
        return Capability(
            id="shares.nfs", label=label, status="ready", provider="nfs-kernel-server"
        )
    if probe.os == "darwin" and probe.which("nfsd"):
        if probe.is_root():
            return Capability(id="shares.nfs", label=label, status="ready", provider="nfsd")
        return Capability(
            id="shares.nfs",
            label=label,
            status="needs_privilege",
            provider="nfsd",
            detail="Exporting folders over NFS needs Athena to run as root.",
        )
    return Capability(
        id="shares.nfs",
        label=label,
        status="unsupported",
        provider="built-in",
        detail="Windows has no NFS server outside Windows Server. Use SMB or WebDAV instead.",
    )


def detect_rclone(probe: Probe) -> Capability:
    path = probe.which("rclone")
    if not path:
        return Capability(
            id="cloud.rclone",
            label="Cloud storage",
            status="missing",
            provider="rclone",
            detail="rclone not found",
            actions=["setup"],
        )
    version = probe.run([path, "version"]).first_line or None
    return Capability(
        id="cloud.rclone", label="Cloud storage", status="ready", provider="rclone", detail=version
    )


OLLAMA_DEFAULT = "http://127.0.0.1:11434"


def ollama_url(probe: Probe) -> str:
    """Where Ollama listens: $OLLAMA_HOST (as Ollama reads it) or its default."""
    host = (probe.getenv("OLLAMA_HOST") or "").strip().rstrip("/")
    if not host:
        return OLLAMA_DEFAULT
    if "://" not in host:
        host = f"http://{host}"
    scheme, _, rest = host.partition("://")
    if rest.startswith("0.0.0.0"):  # a listen address, not one to connect to
        rest = "127.0.0.1" + rest.removeprefix("0.0.0.0")
    if ":" not in rest.rsplit("]", 1)[-1]:
        rest = f"{rest}:11434"
    return f"{scheme}://{rest}"


def detect_ollama(probe: Probe) -> Capability:
    url = ollama_url(probe)
    answer = probe.http_json(f"{url}/api/version")
    if isinstance(answer, dict) and answer.get("version"):
        return Capability(
            id="ai.ollama",
            label="Ollama",
            status="ready",
            provider="ollama",
            detail=f"Ollama {answer['version']}",
            endpoint=url,
        )
    if probe.which("ollama"):
        return Capability(
            id="ai.ollama",
            label="Ollama",
            status="stopped",
            provider="ollama",
            detail=f"Ollama is installed but not answering at {url} (run: ollama serve)",
            endpoint=url,
        )
    return Capability(
        id="ai.ollama",
        label="Ollama",
        status="missing",
        provider="ollama",
        detail="Ollama not found. Install it from ollama.com to run models on this server.",
    )


# ---------------------------------------------------------------- local AI servers


@dataclass(frozen=True)
class LocalAiServer:
    """A local OpenAI-style server Athena can find at its documented default URL
    (the kind's Base URL default in `assistant/kinds.py`)."""

    kind: str
    binaries: tuple[str, ...] = ()
    """On PATH means installed: "stopped" when nothing answers."""
    fingerprint: str | None = None
    """A path under the URL's root that only this server answers with a JSON object;
    needed where servers share a default port."""


LOCAL_AI_SERVERS: tuple[LocalAiServer, ...] = (
    LocalAiServer("llama-cpp", ("llama-server",), fingerprint="/props"),
    LocalAiServer("localai", ("local-ai",), fingerprint="/.well-known/localai.json"),
    LocalAiServer("llamafile", ("llamafile",)),
    LocalAiServer("mlx-lm", ("mlx_lm.server",)),
    LocalAiServer("vllm", ("vllm",), fingerprint="/version"),
    LocalAiServer("sglang"),
    LocalAiServer("jan"),
    LocalAiServer("gpt4all"),
    LocalAiServer("koboldcpp", ("koboldcpp",)),
    LocalAiServer("text-generation-webui", fingerprint="/v1/internal/model/info"),
    LocalAiServer("tabbyapi"),
    LocalAiServer("docker-model-runner"),
    LocalAiServer("lemonade", ("lemonade-server",)),
    LocalAiServer("xinference", ("xinference", "xinference-local")),
)


def _kind_url(kind: str) -> tuple[str, str]:
    from athena.assistant.kinds import BY_ID

    spec = BY_ID[kind]
    url = next(f.default for f in spec.fields if f.key == "base_url")
    return spec.label, url or ""


def _root(url: str) -> str:
    """http://host:port of a base URL."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _serves_models(probe: Probe, url: str) -> bool:
    answer = probe.http_json(f"{url}/models")
    return isinstance(answer, dict) and isinstance(answer.get("data"), list)


def _pick(probe: Probe, servers: list[LocalAiServer], url: str) -> LocalAiServer | None:
    """Which of the servers sharing `url` answers there, or None when it can't be told."""
    for server in servers:
        if server.fingerprint and isinstance(
            probe.http_json(_root(url) + server.fingerprint), dict
        ):
            return server
    plain = [s for s in servers if not s.fingerprint]
    installed = [s for s in plain if any(probe.which(b) for b in s.binaries)]
    if len(installed) == 1:
        return installed[0]
    if len(servers) == 1 and not servers[0].fingerprint:
        return servers[0]
    return None


def detect_local_ai(probe: Probe) -> list[Capability]:
    """Local AI servers answering at their default URL (`ai.local.<kind>`), or installed
    and not answering. Ones that are neither are left out, so the manifest stays short.
    A server answering where Athena can't tell which one it is shows up as a generic
    OpenAI-compatible server (`ai.local.port-<port>`)."""
    by_url: dict[str, list[LocalAiServer]] = {}
    for server in LOCAL_AI_SERVERS:
        by_url.setdefault(_kind_url(server.kind)[1], []).append(server)
    found: list[Capability] = []
    for url, servers in by_url.items():
        answering = _serves_models(probe, url)
        picked = _pick(probe, servers, url) if answering else None
        if answering and picked is None:
            port = urlsplit(url).port
            found.append(
                Capability(
                    id=f"ai.local.port-{port}",
                    label=f"OpenAI-compatible server on port {port}",
                    status="ready",
                    provider="openai-compatible",
                    detail=f"An OpenAI-compatible API answers at {url}",
                    endpoint=url,
                )
            )
        for server in servers:
            label, _ = _kind_url(server.kind)
            if server is picked:
                found.append(
                    Capability(
                        id=f"ai.local.{server.kind}",
                        label=label,
                        status="ready",
                        provider=server.kind,
                        detail=f"{label} answers at {url}",
                        endpoint=url,
                    )
                )
            elif any(probe.which(b) for b in server.binaries):
                found.append(
                    Capability(
                        id=f"ai.local.{server.kind}",
                        label=label,
                        status="stopped",
                        provider=server.kind,
                        detail=f"{label} is installed but not answering at {url}",
                        endpoint=url,
                    )
                )
    return found


def _installed_binary(probe: Probe, name: str) -> str | None:
    """`name` on PATH, or in the folders the tunnel installers use (often not on PATH)."""
    if found := probe.which(name):
        return found
    suffix = ".exe" if probe.os == "windows" else ""
    candidates = [probe.home() / ".local" / "bin" / f"{name}{suffix}"]
    if probe.os == "windows":
        candidates.append(probe.home() / "scoop" / "shims" / f"{name}.exe")
    else:
        candidates.insert(0, Path("/usr/local/bin") / name)
    for candidate in candidates:
        if probe.exists(candidate):
            return str(candidate)
    return None


def detect_tunnel_cloudflare(probe: Probe) -> Capability:
    path = _installed_binary(probe, "cloudflared")
    if not path:
        return Capability(
            id="tunnel.cloudflare",
            label="Cloudflare Tunnel",
            status="missing",
            provider="cloudflare",
            detail="cloudflared not found",
            actions=["setup"],
        )
    version = probe.run([path, "version"]).first_line or None
    return Capability(
        id="tunnel.cloudflare",
        label="Cloudflare Tunnel",
        status="ready",
        provider="cloudflare",
        detail=version,
    )


def detect_tunnel_tailscale(probe: Probe) -> Capability:
    path = probe.which("tailscale")
    if not path:
        return Capability(
            id="tunnel.tailscale",
            label="Tailscale Funnel",
            status="missing",
            provider="tailscale",
            detail="tailscale not found",
            actions=["setup"],
        )
    # Check if logged in and funnel is available
    result = probe.run([path, "status", "--json"])
    if result.ok:
        try:
            import json

            status = json.loads(result.stdout)
            if status.get("BackendState") == "Running":
                tailnet = status.get("CurrentTailnet", {}).get("MagicDNSSuffix", "tailnet")
                return Capability(
                    id="tunnel.tailscale",
                    label="Tailscale Funnel",
                    status="ready",
                    provider="tailscale",
                    detail=f"Logged in to {tailnet}",
                )
        except Exception:
            pass
    return Capability(
        id="tunnel.tailscale",
        label="Tailscale Funnel",
        status="stopped",
        provider="tailscale",
        detail="Tailscale installed but not logged in (run: tailscale up)",
    )


def detect_tunnel_ngrok(probe: Probe) -> Capability:
    path = _installed_binary(probe, "ngrok")
    if not path:
        return Capability(
            id="tunnel.ngrok",
            label="Ngrok",
            status="missing",
            provider="ngrok",
            detail="ngrok not found",
            actions=["setup"],
        )
    version = probe.run([path, "version"]).first_line or None
    return Capability(
        id="tunnel.ngrok",
        label="Ngrok",
        status="ready",
        provider="ngrok",
        detail=version,
    )


# ---------------------------------------------------------------- self-update


SELF_UPDATE = "self_update"
SELF_UPDATE_LABEL = "Update Athena"


def _not_ready(status: Status, detail: str) -> Capability:
    return Capability(id=SELF_UPDATE, label=SELF_UPDATE_LABEL, status=status, detail=detail)


def _service_pid_linux(probe: Probe) -> int | None:
    out = probe.run(["systemctl", "show", SERVICE_NAME, "--property=MainPID", "--value"])
    return int(out.first_line) if out.ok and out.first_line.isdigit() else None


def _service_pid_darwin(probe: Probe) -> int | None:
    out = probe.run(["launchctl", "print", f"{launchd_domain()}/{LAUNCHD_LABEL}"])
    for line in out.stdout.splitlines() if out.ok else []:
        key, _, value = line.strip().partition(" = ")
        if key == "pid" and value.isdigit():
            return int(value)
    return None


def _runs_as_service(probe: Probe) -> bool:
    """Whether this process is the one the installed service started (so the helper's stop
    and start replace it). Linux and macOS: the manager's main pid is one of our parents;
    Windows: the logon task exists and we run under `pythonw.exe`, as the task does."""
    chain = probe.ancestry()
    if probe.os == "windows":
        task = probe.run(["schtasks", "/Query", "/TN", WINDOWS_TASK])
        return task.ok and any(name.lower() == "pythonw.exe" for _, name in chain)
    pid = _service_pid_linux(probe) if probe.os == "linux" else _service_pid_darwin(probe)
    return pid is not None and pid in {p for p, _ in chain}


def detect_self_update(probe: Probe) -> Capability:
    from athena import self_update
    from athena.config import default_data_dir

    data_dir = Path(probe.getenv("ATHENA_DATA_DIR") or default_data_dir())
    problem = self_update.readiness(data_dir, uv=probe.which("uv"))
    if problem is not None:
        return _not_ready(problem[0], problem[1])  # type: ignore[arg-type]
    if not _runs_as_service(probe):
        return _not_ready("unsupported", "Athena was started from a terminal, not as a service")
    return Capability(
        id=SELF_UPDATE,
        label=SELF_UPDATE_LABEL,
        status="ready",
        provider="uv-tool",
        detail=f"Athena {__version__} was installed with uv",
    )


def _restic_detail() -> str:
    from athena.backup.restic import VERSION

    return f"restic {VERSION}"


def detect_builtin(probe: Probe) -> list[Capability]:
    return [
        Capability(id="files", label="Files", status="ready", provider="builtin"),
        Capability(id="automation", label="Automation", status="ready", provider="builtin"),
        Capability(id="shares.webdav", label="WebDAV shares", status="ready", provider="wsgidav"),
        Capability(id="https", label="HTTPS", status="ready", provider="builtin"),
        Capability(
            id="backup", label="Backup", status="ready", provider="restic", detail=_restic_detail()
        ),
    ]


# ---------------------------------------------------------------- manifest


def detectors_for(probe: Probe) -> list[Detector]:
    containers: Detector = {
        "linux": detect_containers_linux,
        "darwin": detect_containers_darwin,
        "windows": detect_containers_windows,
    }[probe.os]
    managers = {
        "linux": LINUX_PACKAGE_MANAGERS,
        "darwin": DARWIN_PACKAGE_MANAGERS,
        "windows": WINDOWS_PACKAGE_MANAGERS,
    }[probe.os]
    package_detectors: list[Detector] = [
        (lambda p, spec=spec: detect_package_manager(spec, p)) for spec in managers
    ]
    return [
        containers,
        *package_detectors,
        detect_terminal,
        detect_assistant_shell,
        detect_rclone,
        detect_power,
        detect_smb,
        detect_nfs,
        detect_ollama,
        detect_local_ai,
        detect_tunnel_cloudflare,
        detect_tunnel_tailscale,
        detect_tunnel_ngrok,
        detect_self_update,
    ]


def _safe(detector: Detector, probe: Probe) -> list[Capability]:
    try:
        found = detector(probe)
    except Exception:  # a detector bug must not break the whole manifest
        log.exception("capability detector %s failed", getattr(detector, "__name__", detector))
        return []
    return found if isinstance(found, list) else [found]


def detect(probe: Probe | None = None) -> CapabilityManifest:
    probe = probe or Probe()
    detectors = detectors_for(probe)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda d: _safe(d, probe), detectors))
    capabilities = [c for found in results for c in found] + detect_builtin(probe)
    return CapabilityManifest(
        os=probe.os,
        os_version=os_version(probe.os),
        arch=platform.machine().lower(),
        detected_at=datetime.now(UTC),
        capabilities=capabilities,
    )
