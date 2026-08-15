"""Application errors that can be safely translated into HTTP responses."""


class AppError(Exception):
    """Base class for expected errors with a public code and message."""

    status_code = 500
    code = "internal_error"
    default_message = "An unexpected error occurred."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class InvalidImageError(AppError):
    status_code = 400
    code = "invalid_image"
    default_message = "The uploaded file is not a supported image."


class InvalidRequestError(AppError):
    status_code = 422
    code = "invalid_request"
    default_message = "The request data is invalid."


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "image_too_large"
    default_message = "The uploaded image is too large."


class ModelRateLimitError(AppError):
    status_code = 429
    code = "model_rate_limited"
    default_message = "The photography model is busy. Please try again shortly."


class ModelOutputError(AppError):
    status_code = 502
    code = "invalid_model_output"
    default_message = "The photography model returned an invalid report."


class ModelUnavailableError(AppError):
    status_code = 503
    code = "model_unavailable"
    default_message = "The photography model is currently unavailable."


class ModelTimeoutError(AppError):
    status_code = 504
    code = "model_timeout"
    default_message = "The photography analysis timed out. Please try again."


class AccessCodeRequiredError(AppError):
    status_code = 401
    code = "access_code_required"
    default_message = "An access code is required for this analysis."


class AccessDeniedError(AppError):
    status_code = 403
    code = "access_denied"
    default_message = "The provided access code is not valid."


class AnalysisClosedError(AppError):
    status_code = 403
    code = "analysis_closed"
    default_message = "New analyses are currently disabled."


class IdempotencyConflictError(AppError):
    status_code = 409
    code = "idempotency_conflict"
    default_message = "This idempotency key was already used for another request."


class AccessQuotaExhaustedError(AppError):
    status_code = 429
    code = "access_quota_exhausted"
    default_message = "This access code has no remaining uses."


class RequestRateLimitedError(AppError):
    status_code = 429
    code = "request_rate_limited"
    default_message = "Too many requests from this source. Please try again shortly."


class GlobalQuotaExhaustedError(AppError):
    status_code = 429
    code = "global_quota_exhausted"
    default_message = "The daily analysis budget has been reached."


class ConcurrencyLimitReachedError(AppError):
    status_code = 429
    code = "concurrency_limit_reached"
    default_message = "Too many analyses are running right now. Please try again shortly."


class ControlPlaneUnavailableError(AppError):
    status_code = 503
    code = "control_plane_unavailable"
    default_message = "The analysis service is temporarily unavailable."


class FeedbackForbiddenError(AppError):
    status_code = 403
    code = "feedback_forbidden"
    default_message = "This feedback token is not valid for this analysis."


class AnalysisNotFoundError(AppError):
    status_code = 404
    code = "analysis_not_found"
    default_message = "The analysis was not found."


class FeedbackRateLimitedError(AppError):
    status_code = 429
    code = "feedback_rate_limited"
    default_message = "Feedback is being submitted too quickly. Please try again shortly."


class AdminAuthenticationFailedError(AppError):
    status_code = 401
    code = "admin_authentication_failed"
    default_message = "Authentication failed."


class AdminAuthenticationRequiredError(AppError):
    status_code = 401
    code = "admin_authentication_required"
    default_message = "A valid admin session is required."
