"""Server-side authentication for the FastAPI command center.

Same security posture as the old Streamlit gate, ported to signed-cookie
sessions:
  * Credentials come only from the environment (APP_USERNAME + a PBKDF2 hash in
    APP_PASSWORD_HASH). Fail CLOSED when they are missing.
  * Constant-time check on BOTH username and password (no timing oracle).
  * The same generic error whether user or password was wrong.
  * Brute force throttled per-session AND globally, with a hard lockout window.
  * Auth state lives in a server-signed session cookie (Starlette
    SessionMiddleware); it is a signed token, not a client-forgeable flag, and
    it expires so an unattended tab does not stay authenticated forever.
"""
from __future__ import annotations

import hmac
import os
import time
from collections import deque

from fastapi import HTTPException, Request

from security import hash_is_wellformed, verify_password

# --- tunables -------------------------------------------------------------
SESSION_TIMEOUT_S = 60 * 60        # re-login after 1 hour idle
MAX_FAILS_PER_SESSION = 5
GLOBAL_FAIL_LIMIT = 15             # across all sessions...
GLOBAL_FAIL_WINDOW_S = 300         # ...within this window
GLOBAL_LOCKOUT_S = 900            # then lock everyone out this long
FAILED_LOGIN_DELAY_S = 1.0        # slow down automated guessing

# Global (per-process) brute-force tracking. The app runs as one container,
# so module state is shared across all browser sessions.
_recent_failures: deque[float] = deque()
_locked_until: float = 0.0


def auth_configured() -> tuple[bool, str]:
    """(ok, message). Fail CLOSED: with no/malformed credentials the app is
    not usable and says exactly why."""
    user_env = os.getenv("APP_USERNAME", "")
    hash_env = os.getenv("APP_PASSWORD_HASH", "")
    if not user_env or not hash_env:
        return False, ("Authentication is not configured. Set APP_USERNAME and "
                       "APP_PASSWORD_HASH on the server.")
    if not hash_is_wellformed(hash_env):
        return False, ("APP_PASSWORD_HASH is malformed, so no password can ever "
                       "match it. If the value contains '$', Docker Compose ate "
                       "part of it — regenerate with `python make_password.py`.")
    return True, "ok"


def globally_locked() -> float:
    """Seconds remaining on the global lockout (0 if not locked)."""
    global _locked_until
    now = time.time()
    while _recent_failures and now - _recent_failures[0] > GLOBAL_FAIL_WINDOW_S:
        _recent_failures.popleft()
    if len(_recent_failures) >= GLOBAL_FAIL_LIMIT and now >= _locked_until:
        _locked_until = now + GLOBAL_LOCKOUT_S
        _recent_failures.clear()
    return max(0.0, _locked_until - now)


def _record_failure(session: dict) -> None:
    _recent_failures.append(time.time())
    session["auth_fails"] = session.get("auth_fails", 0) + 1


def current_user(request: Request) -> str | None:
    """The signed-in username, or None. Enforces the idle timeout."""
    sess = request.session
    if not sess.get("authed"):
        return None
    if time.time() - sess.get("authed_at", 0) > SESSION_TIMEOUT_S:
        sess["authed"] = False
        return None
    return sess.get("user")


def attempt_login(request: Request, username: str, password: str
                  ) -> tuple[bool, str]:
    """Try to sign in. Returns (ok, message). Applies throttling + delay on
    failure so this is safe to call directly from the login endpoint."""
    ok, msg = auth_configured()
    if not ok:
        return False, msg

    sess = request.session
    locked_for = globally_locked()
    if locked_for > 0:
        return False, (f"Too many failed attempts. Locked for "
                       f"{int(locked_for // 60) + 1} more minute(s).")
    if sess.get("auth_fails", 0) >= MAX_FAILS_PER_SESSION:
        return False, ("Too many failed attempts in this session. "
                       "Reload the page to try again.")

    user_env = os.getenv("APP_USERNAME", "")
    hash_env = os.getenv("APP_PASSWORD_HASH", "")
    # Constant-time on BOTH fields; always run the KDF so a wrong username costs
    # the same as a wrong password.
    user_ok = hmac.compare_digest(username or "", user_env)
    pass_ok = verify_password(password or "", hash_env)
    if user_ok and pass_ok:
        sess["authed"] = True
        sess["authed_at"] = time.time()
        sess["auth_fails"] = 0
        sess["user"] = user_env
        return True, user_env

    _record_failure(sess)
    time.sleep(FAILED_LOGIN_DELAY_S)
    return False, "Invalid credentials."   # never say which field was wrong


def logout(request: Request) -> None:
    for k in ("authed", "authed_at", "user"):
        request.session.pop(k, None)


def require_auth(request: Request) -> str:
    """FastAPI dependency: 401 unless signed in. Returns the username."""
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
