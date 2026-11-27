"""Request dependencies: database session, current user, and CSRF enforcement."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session

from athena.auth.service import session_for_token
from athena.db.models import AuthSession, User
from athena.settings_file import SettingsFile

COOKIE_NAME = "athena_session"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_db(request: Request) -> Iterator[Session]:
    yield from request.app.state.db.session()


@dataclass
class CurrentUser:
    user: User
    session: AuthSession


DbSession = Annotated[Session, Depends(get_db)]


def get_settings_file(request: Request) -> SettingsFile:
    return request.app.state.settings_file


SettingsStore = Annotated[SettingsFile, Depends(get_settings_file)]
"""athena.json: host-wide settings (`athena.settings_file`)."""


def current_user(request: Request, db: DbSession) -> CurrentUser:
    """Requires a valid session cookie, and a matching CSRF header on writes."""
    token = request.cookies.get(COOKIE_NAME)
    found = session_for_token(db, token) if token else None
    if found is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    session, user = found
    if request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER)
        if not sent or sent != session.csrf_token:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing or invalid CSRF token")
    return CurrentUser(user=user, session=session)


Authed = Annotated[CurrentUser, Depends(current_user)]
require_user = Depends(current_user)


def admin_user(user: Authed) -> CurrentUser:
    """Requires an admin. Use as a router or route dependency; plain users get 403."""
    if not user.user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can do this")
    return user


AdminUser = Annotated[CurrentUser, Depends(admin_user)]
require_admin = Depends(admin_user)
