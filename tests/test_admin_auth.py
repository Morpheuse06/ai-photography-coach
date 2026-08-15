"""Tests for admin accounts, sessions, and authentication."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from argon2 import PasswordHasher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from photography_coach.errors import (
    AdminAuthenticationFailedError,
    AdminAuthenticationRequiredError,
)
from photography_coach.persistence.admin_auth import SqlAdminAuthService
from photography_coach.persistence.engine import (
    create_db_engine,
    create_schema,
    session_factory_for,
)
from photography_coach.persistence.models import AdminSession
from photography_coach.security import hash_secret


class SqlAdminAuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        url = f"sqlite+aiosqlite:///{Path(self._tmp.name) / 'admin.db'}"
        self.engine = create_db_engine(url)
        self.session_factory = session_factory_for(self.engine)
        await create_schema(self.engine)
        self._sessions: list[AsyncSession] = []
        self._fast_hasher = PasswordHasher(time_cost=1, memory_cost=1_024)

    async def asyncTearDown(self) -> None:
        for session in self._sessions:
            await session.close()
        await self.engine.dispose()
        self._tmp.cleanup()

    def session(self) -> AsyncSession:
        session = self.session_factory()
        self._sessions.append(session)
        return session

    def service(self, session: AsyncSession) -> SqlAdminAuthService:
        return SqlAdminAuthService(
            session,
            session_ttl_hours=12,
            password_hasher=self._fast_hasher,
        )

    async def test_create_session_and_authenticate(self) -> None:
        session = self.session()
        service = self.service(session)
        await service.create_admin_user("owner", "correct horse battery staple")

        created = await service.create_session(
            "owner", "correct horse battery staple"
        )
        subject = await service.authenticate(created.access_token)

        self.assertEqual(subject.username, "owner")
        self.assertEqual(created.token_type, "bearer")
        self.assertGreater(created.expires_at, datetime.now(UTC))

        rows = (
            await session.scalars(select(AdminSession))
        ).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0].token_hash, hash_secret(created.access_token)
        )

    async def test_login_failures_are_uniform(self) -> None:
        session = self.session()
        service = self.service(session)
        await service.create_admin_user("owner", "correct horse battery staple")

        with self.assertRaises(AdminAuthenticationFailedError):
            await service.create_session("owner", "wrong password value")
        with self.assertRaises(AdminAuthenticationFailedError):
            await service.create_session("nobody", "whatever password")

    async def test_revoked_and_expired_sessions_are_rejected(self) -> None:
        session = self.session()
        service = self.service(session)
        await service.create_admin_user("owner", "correct horse battery staple")
        created = await service.create_session(
            "owner", "correct horse battery staple"
        )

        self.assertTrue(await service.revoke_session(created.access_token))
        self.assertFalse(await service.revoke_session(created.access_token))
        with self.assertRaises(AdminAuthenticationRequiredError):
            await service.authenticate(created.access_token)

        second = await service.create_session(
            "owner", "correct horse battery staple"
        )
        rows = (await session.scalars(select(AdminSession))).all()
        for row in rows:
            row.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        await session.commit()
        with self.assertRaises(AdminAuthenticationRequiredError):
            await service.authenticate(second.access_token)

    async def test_inactive_admin_cannot_log_in_or_authenticate(self) -> None:
        session = self.session()
        service = self.service(session)
        await service.create_admin_user("owner", "correct horse battery staple")
        created = await service.create_session(
            "owner", "correct horse battery staple"
        )

        from photography_coach.persistence.models import AdminUser

        user = await session.scalar(select(AdminUser))
        user.is_active = False
        await session.commit()

        with self.assertRaises(AdminAuthenticationFailedError):
            await service.create_session("owner", "correct horse battery staple")
        with self.assertRaises(AdminAuthenticationRequiredError):
            await service.authenticate(created.access_token)

    async def test_unknown_token_is_rejected(self) -> None:
        session = self.session()
        service = self.service(session)

        with self.assertRaises(AdminAuthenticationRequiredError):
            await service.authenticate("Z" * 43)


if __name__ == "__main__":
    unittest.main()
