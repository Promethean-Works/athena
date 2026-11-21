"""The HTTPS listener: a second uvicorn server for the same app, run inside the app.

The main `athena serve` server keeps plain HTTP on its port. When HTTPS is on, this
starts another `uvicorn.Server` on `HttpsSettings.port` in the same event loop, with
`lifespan="off"` so the app's startup tasks don't run twice. It's started and stopped
from the app's lifespan, and restarted in process when the settings change, so a mode
or port change needs no service restart. A renewed certificate is loaded into the
running `SSLContext` (new handshakes use it) without restarting the listener.

The socket is bound here before uvicorn sees it: uvicorn calls `sys.exit` when it can't
bind, and a port that's in use must be a readable error, not a dead server.
"""

import asyncio
import contextlib
import errno
import logging
import socket
import ssl
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from athena import audit
from athena.https import lego, letsencrypt, local_ca
from athena.https import settings as https_settings
from athena.https.settings import HttpsSettings, LetsEncryptSettings
from athena.jobs import CommandFailedError, Job

log = logging.getLogger(__name__)

CERTIFICATE_JOB = "Get a Let's Encrypt certificate"

CHECK_SECONDS = 24 * 60 * 60
"""How often the certificate is checked: self-signed for expiry and new addresses,
Let's Encrypt for renewal."""
SHUTDOWN_GRACE_SECONDS = 2
STARTUP_TIMEOUT_SECONDS = 10
FIRST_CHECK_SECONDS = 60
"""The first check runs this soon after start, so a host that restarts daily still renews."""


def _lego_failure(job: Job, code: int) -> str:
    """lego's last error line (it stays on the page after the job log is closed)."""
    lines = [line.strip() for line in job.out().lines if line.strip()]
    errors = [line for line in lines if "error" in line.lower()]
    detail = (errors or lines or [""])[-1][-300:]
    return (
        f"lego failed (exit code {code}): {detail}" if detail else f"lego failed (exit code {code})"
    )


class HttpsError(Exception):
    """A readable reason the HTTPS listener can't start (shown to the admin as is)."""


class _Server(uvicorn.Server):
    """A uvicorn server that leaves signals to the main server."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


def bind(host: str, port: int) -> socket.socket:
    """A listening socket on host:port, or `HttpsError` saying why not."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        # create_server sets SO_REUSEADDR on POSIX only; on Windows it would let two
        # servers share a port.
        return socket.create_server((host, port), family=family)
    except PermissionError as exc:
        raise HttpsError(
            f"Athena isn't allowed to open port {port}. Pick a port above 1023."
        ) from exc
    except OSError as exc:
        if exc.errno in (errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", -1)):
            raise HttpsError(f"Port {port} is already in use by another program.") from exc
        raise HttpsError(f"Can't open port {port}: {exc.strerror or exc}") from exc


class HttpsManager:
    def __init__(self, app: FastAPI, host: str, http_port: int, data_dir: Path) -> None:
        self.app = app
        self.host = host
        self.http_port = http_port
        self.data_dir = data_dir
        self.paths = local_ca.tls_paths(data_dir)
        self.settings = HttpsSettings()
        self.last_error: str | None = None
        self.last_renewal: datetime | None = None
        """When Let's Encrypt last issued or renewed the certificate (this run)."""
        self.renewal_error: str | None = None
        """Why the last Let's Encrypt attempt failed; cleared by the next success."""
        self.renewal_job: Job | None = None
        self._server: _Server | None = None
        self._task: asyncio.Task[None] | None = None
        self._port: int | None = None
        self._check_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._stopping: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------ state

    @property
    def listening_port(self) -> int | None:
        """The port the HTTPS listener is serving on, or None."""
        if self._server is None or self._task is None or self._task.done():
            return None
        return self._port

    @property
    def redirect_port(self) -> int | None:
        """Where the HTTP listener sends browsers, or None to serve them as is."""
        return self.listening_port if self.settings.redirect else None

    # ------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        """Start from the stored settings. Never raises: errors go to `last_error`."""
        for db in self.app.state.db.session():
            self.settings = https_settings.load(db)
        try:
            await self.apply(self.settings)
        except HttpsError as exc:
            log.error("HTTPS listener not started: %s", exc)
        except Exception as exc:
            self.last_error = f"The HTTPS listener didn't start: {exc}"
            log.exception("HTTPS listener not started")
        self._check_task = asyncio.create_task(self._check_loop())

    async def stop(self) -> None:
        if self._check_task is not None:
            self._check_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._check_task
            self._check_task = None
        async with self._lock:
            await self._stop_server()
        if self._stopping:
            await asyncio.gather(*self._stopping, return_exceptions=True)

    async def apply(
        self, new: HttpsSettings, persist: Callable[[HttpsSettings], None] | None = None
    ) -> None:
        """Make the listener match `new`, then call `persist(new)`, under one lock so two
        saves at once can't leave the database and the listener disagreeing.

        On `HttpsError` nothing changes: the old listener keeps running and `persist`
        isn't called.
        """
        async with self._lock:
            try:
                await self._apply(new)
            except HttpsError as exc:
                self.last_error = str(exc)
                raise
            self.last_error = None
            if persist is not None:
                persist(new)

    async def rotate_ca(self) -> None:
        """Make a new local CA and server certificate, and serve the new one."""
        async with self._lock:
            await asyncio.to_thread(local_ca.rotate_ca, self.paths)
            if self.settings.mode != "letsencrypt":
                await asyncio.to_thread(self._ensure_cert, self.settings)
                self._reload_cert(self.settings)

    async def check_certificate(self) -> bool:
        """Reissue the self-signed certificate, or renew the Let's Encrypt one, if
        needed. True if a new certificate is being served."""
        if self.settings.mode == "letsencrypt":
            if not await asyncio.to_thread(letsencrypt.due, self.paths):
                return False
            job = self.start_certificate_job(self.settings.letsencrypt, by="daily check")
            await job.wait()
            return job.status == "succeeded"
        async with self._lock:
            if self.settings.mode != "self_signed":
                return False
            issued = await asyncio.to_thread(self._ensure_cert, self.settings)
            if issued:
                self._reload_cert(self.settings)
                log.info("HTTPS: issued a new self-signed certificate")
            return issued

    # ------------------------------------------------------------ Let's Encrypt

    async def save_letsencrypt(
        self, le: LetsEncryptSettings, persist: Callable[[HttpsSettings], None]
    ) -> None:
        """Store new Let's Encrypt settings without touching the listener."""
        async with self._lock:
            self.settings = self.settings.model_copy(update={"letsencrypt": le})
            persist(self.settings)

    @property
    def certificate_job_running(self) -> bool:
        job = self.renewal_job
        return job is not None and job.status == "running"

    def start_certificate_job(self, le: LetsEncryptSettings, by: str, force: bool = False) -> Job:
        """Get or renew the Let's Encrypt certificate in a job (one at a time; a running
        one is returned instead of starting another).

        `le` must hold the stored (encrypted) DNS secrets. `force` asks for a new
        certificate even if the current one isn't due. The certificate is served at once
        if Let's Encrypt mode is on; otherwise the admin turns it on afterwards.
        """
        if self.certificate_job_running:
            assert self.renewal_job is not None
            return self.renewal_job
        job = self.app.state.jobs.start(
            CERTIFICATE_JOB, lambda job: self._certificate(job, le, by, force)
        )
        self.renewal_job = job
        return job

    async def _certificate(self, job: Job, le: LetsEncryptSettings, by: str, force: bool) -> None:
        try:
            values = https_settings.dns_values(le, self.app.state.secret_box)
            binary = await lego.ensure_lego(self.data_dir, job.log)
            force = force or await asyncio.to_thread(letsencrypt.must_force, self.paths, le)
            cmd = letsencrypt.build_command(binary, self.paths, le, values, force=force)
            if le.challenge == "http":
                await job.log("Let's Encrypt will connect to port 80 on this host.")
            code = await job.run_command(cmd.argv, env=cmd.env)
            if code != 0:
                raise CommandFailedError(_lego_failure(job, code))
            # Under the lock so a save switching to this mode never reads a half-copied pair.
            async with self._lock:
                cert = await asyncio.to_thread(letsencrypt.install_certificate, self.paths, le)
                await self._serve_new_certificate()
        except Exception as exc:
            self.renewal_error = str(exc) or exc.__class__.__name__
            self._audit("https.renewal_failed", f"{by}: {self.renewal_error}")
            raise
        self.renewal_error = None
        self.last_renewal = datetime.now(UTC)
        expires = cert.not_valid_after_utc.date().isoformat()
        await job.log(f"Certificate for {', '.join(le.domains)} valid until {expires}")
        self._audit("https.certificate_issued", f"{', '.join(le.domains)} ({by})")

    async def _serve_new_certificate(self) -> None:
        """Load the new Let's Encrypt certificate, or start the listener if it couldn't
        start before (no certificate at start-up). Called with `_lock` held."""
        if self.settings.mode != "letsencrypt":
            return
        if self.listening_port is not None:
            self._reload_cert(self.settings)
            return
        try:
            await self._apply(self.settings)
            self.last_error = None
        except HttpsError as exc:
            self.last_error = str(exc)

    def _audit(self, action: str, target: str) -> None:
        for db in self.app.state.db.session():
            audit.record(db, "athena", action, target)

    # ------------------------------------------------------------ internals

    async def _apply(self, new: HttpsSettings) -> None:
        if new.mode == "off":
            self._stop_in_background()
            self.settings = new
            return
        if new.port == self.http_port:
            raise HttpsError(f"Port {new.port} is Athena's HTTP port. Pick another one.")
        try:
            await asyncio.to_thread(self._ensure_cert, new)
        except (OSError, ValueError, TypeError) as exc:
            log.exception("HTTPS certificate")
            raise HttpsError("Couldn't make the certificate; see the server log.") from exc
        if self.listening_port == new.port:
            try:
                self._reload_cert(new)
            except (OSError, ssl.SSLError) as exc:
                log.exception("HTTPS certificate reload")
                raise HttpsError("Couldn't load the new certificate; see the server log.") from exc
            self.settings = new
            return
        server, task = await self._start_server(new.port, new)
        # Only now that the new listener serves does the old one go away.
        self._stop_in_background()
        self._server, self._task, self._port = server, task, new.port
        self.settings = new
        log.info("HTTPS listening on %s:%d", self.host, new.port)

    async def _start_server(
        self, port: int, settings: HttpsSettings
    ) -> tuple["_Server", asyncio.Task[None]]:
        sock = bind(self.host, port)
        cert, key = self.cert_files(settings)
        try:
            config = uvicorn.Config(
                self.app,
                ssl_certfile=str(cert),
                ssl_keyfile=str(key),
                lifespan="off",
                log_config=None,
                timeout_graceful_shutdown=SHUTDOWN_GRACE_SECONDS,
            )
            config.load()  # builds the SSLContext here, so a bad certificate raises now
            if config.ssl is not None:
                config.ssl.minimum_version = ssl.TLSVersion.TLSv1_2
        except Exception as exc:
            sock.close()
            log.exception("HTTPS listener config")
            raise HttpsError("Couldn't load the certificate; see the server log.") from exc
        server = _Server(config)
        task = asyncio.create_task(server.serve(sockets=[sock]))
        task.add_done_callback(self._on_server_done)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + STARTUP_TIMEOUT_SECONDS
        while not server.started and not task.done() and loop.time() < deadline:
            await asyncio.sleep(0.01)
        if not server.started:
            await self._stop(server, task)
            raise HttpsError("The HTTPS listener didn't start; see the server log.")
        return server, task

    def _on_server_done(self, task: asyncio.Task[None]) -> None:
        """Say why a listener stopped on its own (a stop we asked for clears `_task` first)."""
        if task is not self._task or task.cancelled():
            return
        exc = task.exception()
        self.last_error = f"The HTTPS listener stopped: {exc or 'unknown reason'}"
        log.error("%s", self.last_error)

    def cert_files(self, settings: HttpsSettings) -> tuple[Path, Path]:
        """(certificate, key) served in `settings.mode`."""
        if settings.mode == "letsencrypt":
            return letsencrypt.le_paths(self.paths)
        return self.paths.cert, self.paths.key

    def _ensure_cert(self, settings: HttpsSettings) -> bool:
        if settings.mode == "letsencrypt":
            cert, key = letsencrypt.le_paths(self.paths)
            if local_ca.load_cert(cert) is None or not key.is_file():
                raise HttpsError("Get a Let's Encrypt certificate first.")
            issued = letsencrypt.issued_for(self.paths)  # None: placed by hand, unknown
            if issued is not None and issued != settings.letsencrypt.domains:
                raise HttpsError("Get a new certificate for these domains first.")
            return False
        return local_ca.ensure_server_cert(self.paths, settings.extra_names)

    def _reload_cert(self, settings: HttpsSettings) -> None:
        if self._server is None or self._server.config.ssl is None:
            return
        cert, key = self.cert_files(settings)
        self._server.config.ssl.load_cert_chain(str(cert), str(key))

    def _stop_in_background(self) -> None:
        """Stop the current listener without waiting for it.

        The request asking for the change may itself have come over this listener, and
        uvicorn's graceful shutdown waits for open requests: awaiting it here would wait on
        ourselves. The old listener closes its socket at once and finishes the request
        (so the browser gets its answer) before it's gone.
        """
        server, task = self._server, self._task
        self._server = self._task = self._port = None
        if server is None or task is None:
            return
        stopping = asyncio.create_task(self._stop(server, task))
        self._stopping.add(stopping)
        stopping.add_done_callback(self._stopping.discard)

    async def _stop_server(self) -> None:
        server, task = self._server, self._task
        self._server = self._task = self._port = None
        if server is not None and task is not None:
            await self._stop(server, task)

    @staticmethod
    async def _stop(server: "_Server", task: asyncio.Task[None]) -> None:
        server.should_exit = True
        try:
            await asyncio.wait_for(asyncio.shield(task), SHUTDOWN_GRACE_SECONDS + 3)
        except TimeoutError:
            server.force_exit = True
            with contextlib.suppress(Exception):
                await asyncio.wait_for(task, 3)
        except Exception:
            log.exception("HTTPS listener stopped with an error")

    async def _check_loop(self) -> None:
        delay = FIRST_CHECK_SECONDS
        while True:
            await asyncio.sleep(delay)
            delay = CHECK_SECONDS
            try:
                await self.check_certificate()
            except Exception:
                log.exception("HTTPS certificate check failed")
