"""Control-plane orchestration around the V2 RAG analysis service.

The service surrounds ``RagAnalysisService`` with quota reservations,
lifecycle recording, idempotent replays, and feedback capability issuance.
Database transactions stay short: reserve and record before the external
model call, confirm and consume afterwards.
"""

from datetime import UTC, datetime
import hashlib
import logging
from time import perf_counter
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from photography_coach.errors import (
    AppError,
    ControlPlaneUnavailableError,
    IdempotencyConflictError,
    RequestRateLimitedError,
)
from photography_coach.image_validation import ValidatedImage
from photography_coach.persistence.feedback import register_feedback_token
from photography_coach.persistence.models import (
    AnalysisRun,
    UsageReservation as UsageReservationRow,
)
from photography_coach.persistence.recording import (
    SqlAnalysisRecorder,
    stored_run_metadata,
)
from photography_coach.persistence.usage import PolicyDefaults, SqlUsageAuthorizer
from photography_coach.ports.control_plane import (
    AnalysisRunFailure,
    AnalysisRunStart,
    UsageReservation,
)
from photography_coach.schemas.analysis import AnalysisResponse, ImageMetadata
from photography_coach.schemas.interaction import (
    AnalysisAccess,
    AnalysisInteraction,
)
from photography_coach.schemas.report import PhotographyReport
from photography_coach.security import generate_opaque_token, hash_secret
from photography_coach.services.rag_analysis import RagAnalysisService
from photography_coach.services.rate_limiting import SourceRateLimiter


logger = logging.getLogger(__name__)


class ControlPlaneAnalysisService:
    """Quota-protected, recorded V2 analysis with idempotent retries."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        rag_service: RagAnalysisService,
        reservation_ttl_minutes: int,
        policy_defaults: PolicyDefaults,
        source_rate_limiter: SourceRateLimiter,
    ) -> None:
        self._session = session
        self._rag_service = rag_service
        self._authorizer = SqlUsageAuthorizer(
            session,
            reservation_ttl_minutes=reservation_ttl_minutes,
            policy_defaults=policy_defaults,
        )
        self._recorder = SqlAnalysisRecorder(session)
        self._rate_limiter = source_rate_limiter

    async def analyze(
        self,
        image_bytes: bytes,
        image: ValidatedImage,
        shooting_intent: str | None,
        *,
        idempotency_key: str,
        access_code: str | None,
        source: str,
    ) -> AnalysisResponse:
        """Run one quota-protected analysis and return the interaction data."""
        started_at = datetime.now(UTC)
        wall_started = perf_counter()
        await self._enforce_source_limit(source)

        analysis_id = uuid4()
        fingerprint = _request_fingerprint(
            image_bytes, image, shooting_intent, access_code
        )
        reservation = await self._authorizer.reserve(
            analysis_id=analysis_id,
            access_code=access_code,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
        )
        run_analysis_id = reservation.analysis_id
        owns_reservation = run_analysis_id == analysis_id

        replay = await self._replay_terminal_run(
            run_analysis_id, reservation
        )
        if replay is not None:
            return replay

        try:
            await self._recorder.start(
                AnalysisRunStart(
                    analysis_id=run_analysis_id,
                    api_version="v2",
                    started_at=started_at,
                    image=ImageMetadata(
                        media_type=image.media_type,
                        width=image.width,
                        height=image.height,
                        size_bytes=image.size_bytes,
                    ),
                    shooting_intent=shooting_intent,
                    reservation_id=reservation.reservation_id,
                )
            )
            result = await self._rag_service.analyze(
                image_bytes, image, shooting_intent
            )
            completed_at = datetime.now(UTC)
            await self._recorder.succeed(
                run_analysis_id,
                completed_at=completed_at,
                report=result.response.report,
                metadata=result.response.metadata,
            )
            access = await self._authorizer.commit(
                reservation.reservation_id,
                analysis_id=run_analysis_id,
            )
        except AppError as exc:
            if owns_reservation:
                await self._record_failure_and_release(
                    run_analysis_id, reservation, wall_started, exc
                )
            raise
        except Exception as exc:
            if owns_reservation:
                await self._record_failure_and_release(
                    run_analysis_id, reservation, wall_started, exc
                )
            raise

        feedback_token = generate_opaque_token()
        await register_feedback_token(
            self._session, run_analysis_id, feedback_token
        )
        response = result.response.model_copy(
            update={
                "interaction": AnalysisInteraction(
                    analysis_id=run_analysis_id,
                    feedback_token=feedback_token,
                    access=access,
                )
            }
        )
        return response

    async def _enforce_source_limit(self, source: str) -> None:
        policy = await self._authorizer.get_or_create_policy()
        limit = policy.per_source_hour_limit
        if limit is not None and not self._rate_limiter.allow(
            source, limit=limit
        ):
            raise RequestRateLimitedError()

    async def _replay_terminal_run(
        self,
        analysis_id,
        reservation: UsageReservation,
    ) -> AnalysisResponse | None:
        """Rebuild the response for a completed attempt of the same request."""
        run = await self._session.get(AnalysisRun, analysis_id)
        if run is None or run.status == "running":
            return None
        if run.status == "failed":
            raise _app_error_for(run.error_code, run.sanitized_diagnostic)
        if run.report_json is None:
            # Report content already passed the retention deadline.
            raise IdempotencyConflictError()
        metadata = stored_run_metadata(run)
        if metadata is None:
            raise IdempotencyConflictError()
        report = PhotographyReport.model_validate_json(run.report_json)

        reservation_row = await self._session.get(
            UsageReservationRow, reservation.reservation_id
        )
        if reservation_row is None or reservation_row.status != "released":
            access = await self._authorizer.commit(
                reservation.reservation_id,
                analysis_id=analysis_id,
            )
        else:
            logger.warning(
                "control_plane_replay_after_release",
                extra={"event_data": {"analysis_id": str(analysis_id)}},
            )
            access = AnalysisAccess(mode=reservation.mode)

        feedback_token = generate_opaque_token()
        await register_feedback_token(self._session, analysis_id, feedback_token)
        logger.info(
            "control_plane_replayed",
            extra={"event_data": {"analysis_id": str(analysis_id)}},
        )
        return AnalysisResponse(
            report=report,
            metadata=metadata,
            interaction=AnalysisInteraction(
                analysis_id=analysis_id,
                feedback_token=feedback_token,
                access=access,
            ),
        )

    async def _record_failure_and_release(
        self,
        analysis_id,
        reservation: UsageReservation,
        wall_started: float,
        exc: Exception,
    ) -> None:
        latency_ms = round((perf_counter() - wall_started) * 1_000)
        if isinstance(exc, AppError):
            error_code = exc.code
            diagnostic = exc.message
        else:
            error_code = "internal_error"
            diagnostic = None
        try:
            await self._recorder.fail(
                AnalysisRunFailure(
                    analysis_id=analysis_id,
                    completed_at=datetime.now(UTC),
                    error_code=error_code,
                    latency_ms=max(latency_ms, 0),
                    sanitized_diagnostic=diagnostic,
                )
            )
            await self._authorizer.release(
                reservation.reservation_id,
                analysis_id=analysis_id,
                reason=error_code,
            )
        except Exception as cleanup_exc:
            logger.error(
                "control_plane_failure_cleanup_failed",
                extra={
                    "event_data": {
                        "analysis_id": str(analysis_id),
                        "error_code": error_code,
                        "cleanup_error": type(cleanup_exc).__name__,
                    }
                },
            )


def _request_fingerprint(
    image_bytes: bytes,
    image: ValidatedImage,
    shooting_intent: str | None,
    access_code: str | None,
) -> str:
    """Hash of the non-secret fields that identify one user operation."""
    canonical = "|".join(
        [
            "v2",
            hashlib.sha256(image_bytes).hexdigest(),
            image.media_type,
            shooting_intent or "",
            hash_secret(access_code) if access_code else "",
        ]
    )
    return hash_secret(canonical)


def _app_error_for(code: str | None, message: str | None) -> AppError:
    for subclass in _app_error_subclasses():
        if subclass.code == code:
            return subclass(message)
    return ControlPlaneUnavailableError(
        message or "The recorded analysis failed."
    )


def _app_error_subclasses() -> list[type[AppError]]:
    found: list[type[AppError]] = []

    def walk(cls: type[AppError]) -> None:
        for subclass in cls.__subclasses__():
            found.append(subclass)
            walk(subclass)

    walk(AppError)
    return found
