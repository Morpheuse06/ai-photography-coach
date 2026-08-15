"""Cryptographic helpers for control-plane secrets.

Raw secrets (invitation codes, feedback tokens, idempotency keys, admin
tokens) are hashed immediately on entry and never stored or logged in
plaintext. Generated values use ``secrets``, never ``random``.
"""

import hashlib
import hmac
import secrets

# Ambiguous characters I/O/0/1 are excluded for readable manual entry.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def hash_secret(value: str) -> str:
    """SHA-256 hex digest for high-entropy random secrets."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    """Compare two hex digests without leaking timing information."""
    return hmac.compare_digest(left, right)


def generate_access_code() -> str:
    """One raw invitation code in ``PXC-XXXX-XXXX-XXXX-XXXX`` form."""
    groups = [
        "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
        for _ in range(4)
    ]
    return "PXC-" + "-".join(groups)


def access_code_prefix(code: str) -> str:
    """Short non-secret display hint, e.g. ``PXC-ABCD``."""
    return code[:8]


def generate_opaque_token() -> str:
    """43-character URL-safe token for feedback and admin sessions."""
    return secrets.token_urlsafe(32)
