"""Local users, login, roles and permissions.

Passwords are stored as salted scrypt hashes (never in plain text). Five wrong
passwords lock an account for 15 minutes. When no user exists the application
is in *setup mode*: the desktop app asks for an administrator to be created
first; the CLI keeps working and warns until one is created.

Permissions are enforced at the application boundary (desktop UI and CLI) through
:func:`require`. A future web API calls the same function for every request.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select

from ..db.database import Database
from ..db.models import User, utcnow
from .common import ServiceError, audit

ROLES = {
    "admin": "Administrator",
    "manager": "Partner / Manager",
    "accountant": "Accountant",
    "viewer": "Viewer (read-only)",
}
PERMISSIONS = {
    "view": {"admin", "manager", "accountant", "viewer"},
    "export": {"admin", "manager", "accountant", "viewer"},
    "import": {"admin", "manager", "accountant"},
    "reconcile": {"admin", "manager", "accountant"},
    "review": {"admin", "manager", "accountant"},
    "claim": {"admin", "manager", "accountant"},
    "manage_clients": {"admin", "manager"},
    "manage_rules": {"admin", "manager"},
    "settings": {"admin", "manager"},
    "delete_data": {"admin"},
    "restore": {"admin"},
    "manage_users": {"admin"},
}
MAX_FAILED = 5
LOCK_MINUTES = 15
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}


class PermissionDenied(ServiceError):
    pass


@dataclass(frozen=True)
class Session:
    username: str
    role: str
    full_name: str = ""

    def can(self, permission: str) -> bool:
        return self.role in PERMISSIONS.get(permission, set())


#: Session used when no users exist yet (setup mode) – full access, clearly labelled.
SETUP_SESSION = Session("setup", "admin", "Setup mode (no users configured)")


def require(session: Session | None, permission: str) -> None:
    if session is None:
        raise PermissionDenied("Please log in")
    if not session.can(permission):
        raise PermissionDenied(f"{ROLES.get(session.role, session.role)} cannot {permission.replace('_', ' ')}")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return "scrypt${n}${r}${p}${salt}${dig}".format(salt=base64.b64encode(salt).decode(),
                                                     dig=base64.b64encode(digest).decode(), **_SCRYPT)


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dig = stored.split("$")
        if algo != "scrypt":
            return False
        expected = base64.b64decode(dig)
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, expected)


def check_password_policy(password: str) -> None:
    if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ServiceError("Password must have at least 8 characters, including letters and digits")


class AuthService:
    def __init__(self, db: Database):
        self.db = db

    def has_users(self) -> bool:
        with self.db.session() as s:
            return (s.scalar(select(func.count()).select_from(User)) or 0) > 0

    def create_user(self, username: str, password: str, role: str, full_name: str = "",
                    by: Session | None = None) -> User:
        username = username.strip().lower()
        if not re.fullmatch(r"[a-z0-9._-]{3,40}", username):
            raise ServiceError("User name: 3–40 characters, letters, digits, '.', '_' or '-'")
        if role not in ROLES:
            raise ServiceError(f"Role must be one of: {', '.join(ROLES)}")
        check_password_policy(password)
        first = not self.has_users()
        if first and role != "admin":
            raise ServiceError("The first user must be an administrator")
        if not first:
            require(by, "manage_users")
        with self.db.session() as s:
            if s.scalar(select(User).where(User.username == username)):
                raise ServiceError(f"User '{username}' already exists")
            u = User(username=username, full_name=full_name, role=role, password_hash=hash_password(password))
            s.add(u)
            s.flush()
            audit(s, "CREATE", "user", username, {"role": role}, by.username if by else username)
        return u

    def login(self, username: str, password: str) -> Session:
        username = username.strip().lower()
        error = None
        with self.db.session() as s:  # failures are committed (counter, lock, audit) before raising
            u = s.scalar(select(User).where(User.username == username))
            now = utcnow()
            if u is None or not u.active:
                audit(s, "LOGIN_FAILED", "user", username, {"reason": "unknown or inactive"}, username)
                error = "Invalid user name or password"
            elif u.locked_until and u.locked_until > now:
                minutes = int((u.locked_until - now).total_seconds() // 60) + 1
                audit(s, "LOGIN_FAILED", "user", username, {"reason": "locked"}, username)
                error = f"Account locked after repeated failures – try again in {minutes} minute(s)"
            elif not verify_password(password, u.password_hash):
                u.failed_attempts += 1
                if u.failed_attempts >= MAX_FAILED:
                    u.locked_until = now + timedelta(minutes=LOCK_MINUTES)
                    u.failed_attempts = 0
                audit(s, "LOGIN_FAILED", "user", username, {"reason": "wrong password"}, username)
                error = "Invalid user name or password"
            else:
                u.failed_attempts, u.locked_until, u.last_login = 0, None, now
                audit(s, "LOGIN", "user", username, {}, username)
                session = Session(u.username, u.role, u.full_name)
        if error:
            raise ServiceError(error)
        return session

    def change_password(self, username: str, old: str, new: str) -> None:
        self.login(username, old)
        check_password_policy(new)
        with self.db.session() as s:
            u = s.scalar(select(User).where(User.username == username.strip().lower()))
            u.password_hash = hash_password(new)
            u.must_change_password = False
            audit(s, "PASSWORD_CHANGE", "user", u.username, {}, u.username)

    def reset_password(self, username: str, new: str, by: Session) -> None:
        require(by, "manage_users")
        check_password_policy(new)
        with self.db.session() as s:
            u = s.scalar(select(User).where(User.username == username.strip().lower()))
            if u is None:
                raise ServiceError(f"No user '{username}'")
            u.password_hash = hash_password(new)
            u.must_change_password = True
            u.failed_attempts, u.locked_until = 0, None
            audit(s, "PASSWORD_RESET", "user", u.username, {}, by.username)

    def set_role(self, username: str, role: str, by: Session, active: bool | None = None) -> None:
        require(by, "manage_users")
        if role not in ROLES:
            raise ServiceError(f"Role must be one of: {', '.join(ROLES)}")
        with self.db.session() as s:
            u = s.scalar(select(User).where(User.username == username.strip().lower()))
            if u is None:
                raise ServiceError(f"No user '{username}'")
            admins = s.scalar(select(func.count()).select_from(User).where(User.role == "admin",
                                                                          User.active.is_(True)))
            demoting = u.role == "admin" and (role != "admin" or active is False)
            if demoting and admins <= 1:
                raise ServiceError("At least one active administrator must remain")
            before = {"role": u.role, "active": u.active}
            u.role = role
            if active is not None:
                u.active = active
            audit(s, "UPDATE", "user", u.username, {"before": before, "after": {"role": role, "active": u.active}},
                  by.username)

    def users(self) -> list[User]:
        with self.db.session() as s:
            return list(s.scalars(select(User).order_by(User.username)))
