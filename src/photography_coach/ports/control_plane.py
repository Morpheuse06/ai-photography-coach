"""Interfaces for quota, analysis telemetry, and anonymous feedback storage."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from photography_coach.schemas.analysis import AnalysisMetadata, ImageMetadata
from photography_coach.schemas.interaction import (
    AccessMode,
    AnalysisAccess,
    ProblemReportCreate,
    ProblemReportReceipt,
    RatingReceipt,
    RatingTarget,
    RatingUpsertRequest,
)
from photography_coach.schemas.report import PhotographyReport


@dataclass(frozen=True, slots=True)
class UsageReservation:
    """One concurrency-safe temporary claim on an analysis use."""

    reservation_id: UUID
    analysis_id: UUID
    mode: AccessMode
    access_code_id: UUID | None
    remaining_uses_after_reservation: int | None
    expires_at: datetime


@runtime_checkable
class UsageAuthorizer(Protocol):
    """Atomically reserve, consume, or release one analysis use.

    Raw access codes and idempotency keys must be hashed before persistence and
    must never be placed in application logs.
    """

    async def reserve(
        self,
        *,
        analysis_id: UUID,
        access_code: str | None,
        idempotency_key: str,
    ) -> UsageReservation:
        """Reserve one use or raise a public access/quota application error."""
        ...

    async def commit(
        self,
        reservation_id: UUID,
        *,
        analysis_id: UUID,
    ) -> AnalysisAccess:
        """Convert a successful reservation into one consumed use."""
        ...

    async def release(
        self,
        reservation_id: UUID,
        *,
        analysis_id: UUID,
        reason: str,
    ) -> None:
        """Return a reservation after a model or application failure."""
        ...


@dataclass(frozen=True, slots=True)
class AnalysisRunStart:
    """Safe data recorded before external model work begins."""

    analysis_id: UUID
    api_version: str
    started_at: datetime
    image: ImageMetadata
    shooting_intent: str | None
    reservation_id: UUID | None


@dataclass(frozen=True, slots=True)
class AnalysisRunFailure:
    """Bounded failure data; raw provider output and secrets are forbidden."""

    analysis_id: UUID
    completed_at: datetime
    error_code: str
    latency_ms: int
    sanitized_diagnostic: str | None = None


@runtime_checkable
class AnalysisRecorder(Protocol):
    """Persist analysis lifecycle data without receiving original photo bytes."""

    async def start(self, run: AnalysisRunStart) -> None:
        """Create the running record before calling external model services."""
        ...

    async def succeed(
        self,
        analysis_id: UUID,
        *,
        completed_at: datetime,
        report: PhotographyReport,
        metadata: AnalysisMetadata,
    ) -> None:
        """Store report data without ever receiving the feedback capability token."""
        ...

    async def fail(self, failure: AnalysisRunFailure) -> None:
        """Store one sanitized terminal failure for operational diagnosis."""
        ...


RuntimeMetadata = Mapping[str, str | int | bool | None]


@runtime_checkable
class FeedbackRepository(Protocol):
    """Validate feedback capability tokens and persist anonymous feedback.

    Implementations must hash feedback tokens immediately. The raw token must
    never be stored or logged.
    """

    async def upsert_rating(
        self,
        *,
        analysis_id: UUID,
        feedback_token: str,
        target: RatingTarget,
        rating: RatingUpsertRequest,
    ) -> RatingReceipt:
        """Create or replace the token's single rating for one target."""
        ...

    async def delete_rating(
        self,
        *,
        analysis_id: UUID,
        feedback_token: str,
        target: RatingTarget,
    ) -> bool:
        """Delete a rating and report whether a stored rating existed."""
        ...

    async def create_problem_report(
        self,
        report: ProblemReportCreate,
        *,
        runtime_metadata: RuntimeMetadata | None = None,
    ) -> ProblemReportReceipt:
        """Store a public issue with only explicitly approved runtime metadata."""
        ...
