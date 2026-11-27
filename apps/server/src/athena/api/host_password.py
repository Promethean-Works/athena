"""Check the host account's password before an action needs it (macOS `sudo`)."""

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from athena import audit
from athena.api.files import _run
from athena.auth.deps import Authed, DbSession
from athena.auth.service import LoginThrottle
from athena.files.netshare import Elevation, run_command, with_elevation

router = APIRouter(tags=["system"])


class HostPasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=1024, repr=False)


@router.post(
    "/system/host-password/check",
    operation_id="checkHostPassword",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        403: {"description": "The password didn't work"},
        409: {"description": "This host doesn't ask for a password"},
        429: {"description": "Too many wrong passwords"},
    },
)
async def check_host_password(
    body: HostPasswordIn, request: Request, user: Authed, db: DbSession
) -> Response:
    """Run a harmless `sudo true` with the password, so the UI can reject a typo before the
    real action. The password is used for this request only; never stored or logged.

    Only offered when some capability on this host asks for a password (`elevation:
    "password"`), and throttled per admin like a sign-in."""
    manifest = await request.app.state.capabilities.get()
    if not any(
        c.status == "needs_privilege" and c.elevation == "password" for c in manifest.capabilities
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "This computer doesn't ask for a password")
    throttle: LoginThrottle = request.app.state.host_password_throttle
    key = user.user.username
    if wait := throttle.retry_after(key):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many wrong passwords. Try again in {wait} seconds.",
            headers={"Retry-After": str(wait)},
        )
    try:
        await _run(
            with_elevation(
                Elevation("sudo", body.password),
                lambda: run_command(["true"], "check the password"),
            )
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_403_FORBIDDEN:  # sudo refused the password
            throttle.fail(key)
            audit.record(db, key, "host_password.check", "refused")
        raise
    throttle.reset(key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
