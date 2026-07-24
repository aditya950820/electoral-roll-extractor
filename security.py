"""Pure password hashing / verification — no web framework imported.

Extracted so both the CLI helper (make_password.py) and the web auth layer
(webauth.py) share one implementation. This module must stay dependency-free
(standard library only) so it is trivially importable anywhere.

Design notes (this app handles electoral-roll PII, so the bar is high):
  * No credential ever lives in the code or the repo. The username and a
    PBKDF2-SHA256 password *hash* come from the environment; the plaintext
    password exists only in the operator's head.
  * Verification is constant-time (hmac.compare_digest).
  * The hash separator is ':' and never '$' — a '$' would be eaten by Docker
    Compose variable interpolation on the way into the container, silently
    corrupting the hash so that every login fails.

Generate a hash with:  python make_password.py
"""
from __future__ import annotations

import hashlib
import hmac
import os

PBKDF2_ITERATIONS = 600_000        # OWASP-recommended floor for SHA-256


def hash_password(password: str, salt: bytes | None = None) -> str:
    """Return 'pbkdf2_sha256:<iters>:<salt_hex>:<hash_hex>'."""
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256:{PBKDF2_ITERATIONS}:{salt.hex()}:{dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verify. '$' is still accepted so hashes minted by older
    builds keep working."""
    sep = ":" if ":" in stored else "$"
    try:
        algo, iters, salt_hex, hash_hex = stored.strip().split(sep)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def hash_is_wellformed(stored: str) -> bool:
    """True if `stored` has the shape of a hash we could verify against."""
    sep = ":" if ":" in stored else "$"
    parts = stored.strip().split(sep)
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return False
    _, iters, salt_hex, hash_hex = parts
    try:
        return (int(iters) > 0
                and bool(salt_hex) and bool(hash_hex)
                and bytes.fromhex(salt_hex) is not None
                and bytes.fromhex(hash_hex) is not None)
    except ValueError:
        return False
