"""SQL implementation of admin accounts, sessions, and authentication.

Passwords use Argon2id through argon2-cffi; raw session tokens are returned
exactly once and only their SHA-256 hashes are stored. Login failures never
reveal whether a username exists, and a dummy hash verification keeps the
timing roughly uniform.
"""

from dataclasses import dataclass
from datetime import timedelta
import logging

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from photography_coach.errors import (
    AdminAuthenticationFailedError,
    AdminAuthenticationRequiredError,
)
from photography_coach.persistence.models import (
    AdminSession,
    AdminUser,
    as_aware_utc,
    utc_now,
)
from photography_coach.schemas.admin import AdminSessionCreated
from photography_coach.security import constant_time_equals, generate_opaque_token, hash_secret


logger = logging.getLogger(__name__)

_DUMMY_HASH: str | None = None


@dataclass(frozen=True, slots=True)
class AdminSubject:
    """Stable identity of the authenticated administrator."""

    username: str


class SqlAdminAuthService:
    """Create, authenticate, and revoke short-lived admin sessions."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        session_ttl_hours: float,
        password_hasher: PasswordHasher | None = None,
    ) -> None:
        self._session = session
        self._session_ttl_hours = session_ttl_hours
        self._password_hasher = password_hasher or PasswordHasher()

    async def create_admin_user(self, username: str, password: str) -> None:
        """Create or update one administrator; used by the bootstrap script."""
        existing = await self._session.scalar(
            select(AdminUser).where(AdminUser.username == username)
        )
        password_hash = self._password_hasher.hash(password)
        if existing is None:
            self._session.add(
                AdminUser(
                    username=username,
                    password_hash=password_hash,
                    is_active=True,
                )
            )
        else:
            existing.password_hash = password_hash
            existing.is_active = True
        await self._session.commit()
        logger.info(
            "admin_user_upserted",
            extra={"event_data": {"username": username}},
        )

    async def create_session(
        self,
        username: str,
        password: str,
    ) -> AdminSessionCreated:
        """Exchange credentials for a short-lived bearer token."""
        user = await self._session.scalar(
            select(AdminUser).where(AdminUser.username == username)
        )
        password_hash = user.password_hash if user is not None else _dummy_hash()
        try:
            self._password_hasher.verify(password_hash, password)
        except VerifyMismatchError:
            raise AdminAuthenticationFailedError() from None

        if user is None or not user.is_active:
            raise AdminAuthenticationFailedError()

        raw_token = generate_opaque_token()
        now = utc_now()
        expires_at = now + timedelta(hours=self._session_ttl_hours)
        self._session.add(
            AdminSession(
                admin_user_id=user.id,
                token_hash=hash_secret(raw_token),
                expires_at=expires_at,
            )
        )
        user.last_login_at = now
        await self._session.commit()
        logger.info(
            "admin_session_created",
            extra={"event_data": {"username": username}},
        )
        return AdminSessionCreated(
            access_token=raw_token,
            token_type="bearer",
            expires_at=as_aware_utc(expires_at),
        )

    async def revoke_session(self, raw_token: str) -> bool:
        """Revoke one session; returns False when it was already gone."""
        row = await self._session.scalar(
            select(AdminSession).where(
                AdminSession.token_hash == hash_secret(raw_token)
            )
        )
        if row is None or row.revoked_at is not None:
            return False
        row.revoked_at = utc_now()
        await self._session.commit()
        logger.info("admin_session_revoked")
        return True

    async def authenticate(self, raw_token: str) -> AdminSubject:
        """Resolve one bearer token to an active administrator."""
        now = utc_now()
        row = await self._session.scalar(
            select(AdminSession).where(
                AdminSession.token_hash == hash_secret(raw_token)
            )
        )
        if (
            row is None
            or row.revoked_at is not None
            or row.expires_at <= now
        ):
            raise AdminAuthenticationRequiredError()
        user = await self._session.get(AdminUser, row.admin_user_id)
        if user is None or not user.is_active:
            raise AdminAuthenticationRequiredError()
        return AdminSubject(username=user.username)

    @staticmethod
    def token_matches(row: AdminSession, raw_token: str) -> bool:
        """Constant-time comparison for stored session hashes."""
        return constant_time_equals(row.token_hash, hash_secret(raw_token))


def _dummy_hash() -> str:
    """A lazily computed hash used to equalize login failure timing."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = PasswordHasher().hash("timing-equalization-placeholder")
    return _DUMMY_HASH
