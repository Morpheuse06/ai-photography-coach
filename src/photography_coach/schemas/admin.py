"""Management API contracts without database or authentication implementations."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from photography_coach.schemas.analysis import AnalysisMetadata
from photography_coach.schemas.interaction import (
    AccessMode,
    ProblemCategory,
    ProblemReportStatus,
    RatingReasonCode,
    RatingTarget,
    RatingVote,
)
from photography_coach.schemas.report import PhotographyReport


AdminLabel = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]
AdminNote = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
]
CodePrefix = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=4, max_length=20),
]
GeneratedCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=16, max_length=200),
]
AdminUsername = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=100),
]
AdminPassword = Annotated[
    str,
    StringConstraints(min_length=12, max_length=200),
]
AdminAccessToken = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=32, max_length=512),
]


class AdminSessionCreate(BaseModel):
    """Credentials exchanged for a short-lived management access token."""

    model_config = ConfigDict(extra="forbid")

    username: AdminUsername
    password: AdminPassword = Field(repr=False)


class AdminSessionCreated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: AdminAccessToken = Field(repr=False)
    token_type: str = "bearer"
    expires_at: datetime


class PageInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total_items: int = Field(ge=0)
    total_pages: int = Field(ge=0)


class AccessPolicyView(BaseModel):
    """Current public access and cost-protection policy."""

    model_config = ConfigDict(extra="forbid")

    mode: AccessMode
    per_source_hour_limit: int | None = Field(default=None, ge=1)
    global_daily_limit: int | None = Field(default=None, ge=1)
    concurrent_analysis_limit: int = Field(ge=1)
    updated_at: datetime


class AccessPolicyUpdate(BaseModel):
    """Partial policy update; explicit null clears an optional limit."""

    model_config = ConfigDict(extra="forbid")

    mode: AccessMode | None = None
    per_source_hour_limit: int | None = Field(default=None, ge=1)
    global_daily_limit: int | None = Field(default=None, ge=1)
    concurrent_analysis_limit: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def update_must_contain_a_field(self) -> "AccessPolicyUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one access policy field must be supplied")
        return self


class AccessCodeStatus(StrEnum):
    ACTIVE = "active"
    EXHAUSTED = "exhausted"
    EXPIRED = "expired"
    REVOKED = "revoked"


class AccessCodeBatchCreate(BaseModel):
    """Generate several codes with the same quota and expiry policy."""

    model_config = ConfigDict(extra="forbid")

    quantity: int = Field(ge=1, le=100)
    uses_per_code: int = Field(ge=1, le=10_000)
    expires_at: datetime | None = None
    label: AdminLabel | None = None


class GeneratedAccessCode(BaseModel):
    """One raw code shown only in the batch-creation response."""

    model_config = ConfigDict(extra="forbid")

    code_id: UUID
    code: GeneratedCode = Field(repr=False)
    prefix: CodePrefix
    uses_total: int = Field(ge=1)
    expires_at: datetime | None = None


class AccessCodeBatchCreated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    created_at: datetime
    codes: list[GeneratedAccessCode] = Field(min_length=1, max_length=100)


class AccessCodeRecord(BaseModel):
    """Safe management view that never returns the raw invitation code."""

    model_config = ConfigDict(extra="forbid")

    code_id: UUID
    batch_id: UUID
    prefix: CodePrefix
    label: AdminLabel | None = None
    status: AccessCodeStatus
    uses_total: int = Field(ge=1)
    uses_consumed: int = Field(ge=0)
    uses_reserved: int = Field(ge=0)
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def usage_cannot_exceed_the_total(self) -> "AccessCodeRecord":
        if self.uses_consumed + self.uses_reserved > self.uses_total:
            raise ValueError("consumed and reserved uses cannot exceed uses_total")
        return self


class AccessCodePage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AccessCodeRecord]
    page: PageInfo


class AccessCodeGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    additional_uses: int = Field(ge=1, le=10_000)
    reason: AdminNote


class AccessCodeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: AdminLabel | None = None
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def update_must_contain_a_field(self) -> "AccessCodeUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one access code field must be supplied")
        return self


class AccessCodeRevoke(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: AdminNote


class UsageEventStatus(StrEnum):
    RESERVED = "reserved"
    CONSUMED = "consumed"
    RELEASED = "released"


class AccessCodeUsageEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    usage_event_id: UUID
    code_id: UUID
    analysis_id: UUID
    status: UsageEventStatus
    occurred_at: datetime
    release_reason: str | None = None


class AccessCodeUsageEventPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AccessCodeUsageEvent]
    page: PageInfo


class AnalysisRunStatus(StrEnum):
    RESERVED = "reserved"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AnalysisRunSummary(BaseModel):
    """Bounded row used by the management analysis list."""

    model_config = ConfigDict(extra="forbid")

    analysis_id: UUID
    status: AnalysisRunStatus
    api_version: Annotated[
        str,
        StringConstraints(pattern=r"^v[1-9][0-9]*$"),
    ]
    started_at: datetime
    completed_at: datetime | None = None
    access_code_prefix: CodePrefix | None = None
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    error_code: str | None = None
    up_votes: int = Field(default=0, ge=0)
    down_votes: int = Field(default=0, ge=0)


class AnalysisRunDetail(AnalysisRunSummary):
    """Management detail; report and intent may be removed after retention."""

    shooting_intent: str | None = None
    metadata: AnalysisMetadata | None = None
    report: PhotographyReport | None = None
    report_retained_until: datetime | None = None
    sanitized_diagnostic: str | None = None


class AnalysisRunPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AnalysisRunSummary]
    page: PageInfo


class RatingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating_id: UUID
    analysis_id: UUID
    target: RatingTarget
    vote: RatingVote
    reason_codes: list[RatingReasonCode] = Field(max_length=5)
    comment: str | None = None
    created_at: datetime
    updated_at: datetime


class RatingTargetSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: RatingTarget
    up_votes: int = Field(ge=0)
    down_votes: int = Field(ge=0)


class RatingSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RatingTargetSummary]


class RatingPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RatingRecord]
    page: PageInfo


class ProblemPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class ProblemReportRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    problem_report_id: UUID
    analysis_id: UUID | None = None
    category: ProblemCategory
    message: str
    status: ProblemReportStatus
    priority: ProblemPriority = ProblemPriority.NORMAL
    tags: list[AdminLabel] = Field(default_factory=list, max_length=20)
    admin_note: AdminNote | None = None
    created_at: datetime
    updated_at: datetime


class ProblemReportUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ProblemReportStatus | None = None
    priority: ProblemPriority | None = None
    tags: list[AdminLabel] | None = Field(default=None, max_length=20)
    admin_note: AdminNote | None = None

    @model_validator(mode="after")
    def update_must_contain_a_field(self) -> "ProblemReportUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one problem report field must be supplied")
        return self


class ProblemReportPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProblemReportRecord]
    page: PageInfo


class OverviewMetrics(BaseModel):
    """Core dashboard metrics for one requested time window."""

    model_config = ConfigDict(extra="forbid")

    period_started_at: datetime
    period_ended_at: datetime
    analyses_total: int = Field(ge=0)
    analyses_succeeded: int = Field(ge=0)
    analyses_failed: int = Field(ge=0)
    model_timeouts: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    average_latency_ms: float | None = Field(default=None, ge=0)
    up_votes: int = Field(ge=0)
    down_votes: int = Field(ge=0)
    open_problem_reports: int = Field(ge=0)


class MetricBucket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bucket_started_at: datetime
    analyses_total: int = Field(ge=0)
    analyses_succeeded: int = Field(ge=0)
    analyses_failed: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    up_votes: int = Field(ge=0)
    down_votes: int = Field(ge=0)


class OverviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    totals: OverviewMetrics
    series: list[MetricBucket] = Field(max_length=366)


class SystemStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    application_version: str
    started_at: datetime
    access_mode: AccessMode
    rag_enabled: bool
    knowledge_index_ready: bool
    recent_error_rate: float = Field(ge=0, le=1)


class SystemVersions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    report_prompt_version: str
    retrieval_prompt_version: str | None = None
    knowledge_source_id: str | None = None
    knowledge_source_version: str | None = None
    embedding_model: str | None = None
    reranker_model: str | None = None


class AuditEvent(BaseModel):
    """Append-only record of a security-sensitive management action."""

    model_config = ConfigDict(extra="forbid")

    audit_event_id: UUID
    admin_subject: str
    action: str
    resource_type: str
    resource_id: str | None = None
    occurred_at: datetime
    details: dict[str, str | int | bool | None] = Field(default_factory=dict)


class AuditEventPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AuditEvent]
    page: PageInfo
