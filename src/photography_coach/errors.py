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
