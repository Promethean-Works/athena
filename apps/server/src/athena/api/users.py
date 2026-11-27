"""Accounts: admins add, change and remove users (roles: admin or user)."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, Field, field_validator
from sqlmodel import col, delete, func, select

from athena import audit
from athena.api.auth import USERNAME_RE
from athena.auth import service
from athena.auth.deps import AdminUser, DbSession
from athena.db.models import AuthSession, Share, User

router = APIRouter(prefix="/users", tags=["users"])

UserId = Annotated[int, Path(ge=1)]


class UserRow(BaseModel):
    id: int
    username: str
    is_admin: bool
    created_at: datetime

    @classmethod
    def of(cls, user: User) -> "UserRow":
        assert user.id is not None
        return cls(
            id=user.id,
            username=user.username,
            is_admin=user.is_admin,
            created_at=user.created_at,
        )


class NewUser(BaseModel):
    username: str
    password: str = Field(min_length=service.MIN_PW_LENGTH, max_length=256)
    is_admin: bool = False

    @field_validator("username")
    @classmethod
    def valid_username(cls, value: str) -> str:
        value = value.strip()
        if not USERNAME_RE.match(value):
            raise ValueError("3 to 64 characters: letters, digits, dot, dash or underscore")
        return value


class UserUpdate(BaseModel):
    is_admin: bool | None = None
    password: str | None = Field(default=None, min_length=service.MIN_PW_LENGTH, max_length=256)
    """A new password. The user is signed out everywhere."""


def _get(db: DbSession, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such user")
    return user


def _admin_count(db: DbSession) -> int:
    return db.exec(select(func.count()).select_from(User).where(col(User.is_admin))).one()


def _sign_out(db: DbSession, user_id: int) -> None:
    db.exec(delete(AuthSession).where(AuthSession.user_id == user_id))


@router.get("", operation_id="listUsers")
def list_users(_: AdminUser, db: DbSession) -> list[UserRow]:
    rows = db.exec(select(User).order_by(User.created_at, User.id)).all()
    return [UserRow.of(u) for u in rows]


@router.post("", operation_id="createUser", status_code=status.HTTP_201_CREATED)
def create_user(body: NewUser, me: AdminUser, db: DbSession) -> UserRow:
    taken = db.exec(select(User).where(func.lower(User.username) == body.username.lower())).first()
    if taken is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That username is taken")
    user = service.create_user(db, body.username, body.password, is_admin=body.is_admin)
    audit.record(
        db, me.user.username, "user.create", user.username, "admin" if user.is_admin else "user"
    )
    return UserRow.of(user)


@router.patch("/{user_id}", operation_id="updateUser")
def update_user(user_id: UserId, body: UserUpdate, me: AdminUser, db: DbSession) -> UserRow:
    """Change a user's role or reset their password."""
    user = _get(db, user_id)
    if body.is_admin is None and body.password is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Nothing to change")
    if body.is_admin is not None and body.is_admin != user.is_admin:
        if user.is_admin and _admin_count(db) <= 1:
            raise HTTPException(status.HTTP_409_CONFLICT, "There must be at least one admin")
        user.is_admin = body.is_admin
        db.add(user)
        _sign_out(db, user_id)
        db.commit()
        audit.record(
            db, me.user.username, "user.update", user.username, "admin" if user.is_admin else "user"
        )
    if body.password is not None:
        service.set_password(db, user, body.password)
        audit.record(db, me.user.username, "user.password_reset", user.username)
    db.refresh(user)
    return UserRow.of(user)


@router.delete("/{user_id}", operation_id="deleteUser", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: UserId, me: AdminUser, db: DbSession) -> None:
    user = _get(db, user_id)
    if user.id == me.user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You can't delete your own account")
    if user.is_admin and _admin_count(db) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "There must be at least one admin")
    username = user.username
    _sign_out(db, user_id)
    # Their links go with them (the database cascades too; this doesn't rely on it).
    db.exec(delete(Share).where(col(Share.owner_id) == user_id))
    db.delete(user)
    db.commit()
    audit.record(db, me.user.username, "user.delete", username)
