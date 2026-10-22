"""Opt-in loopback-only Member 4 research session; no global auth changes."""
import hashlib
import hmac
import os
import secrets
import threading
import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, SecretStr

router = APIRouter(prefix="/research/session", tags=["member4-session"])
COOKIE = "c4_research_session"
PATH = "/api/v1/risks/research"
TTL = 3600
_attempts = []
_lock = threading.Lock()


def local_config(request):
    # Never expose this password-based local mode on LAN/reverse proxies.
    if (os.environ.get("C4_LOCAL_AUTH_ENABLED") != "on" or request.client is None
            or request.client.host not in ("127.0.0.1", "::1")
            or request.url.hostname not in ("localhost", "127.0.0.1", "::1")):
        raise HTTPException(403, detail="member4_local_session_disabled")
    username = os.environ.get("C4_LOCAL_USERNAME", "")
    password_hash = os.environ.get("C4_LOCAL_PASSWORD_HASH", "")
    signing_key = os.environ.get("C4_LOCAL_SIGNING_KEY", "")
    if not username or len(signing_key) < 64 or len(password_hash.split(":")) != 2:
        raise HTTPException(503, detail="member4_session_not_configured")
    return username, password_hash, signing_key


def valid_session(request):
    try:
        username, password_hash, key = local_config(request)
        token = request.cookies.get(COOKIE, "")
        expires, nonce, signature = token.split(".")
        message = f"{username}:{password_hash}:{expires}:{nonce}".encode()
        expected = hmac.new(key.encode(), message, hashlib.sha256).hexdigest()
        remaining = int(expires) - time.time()
        return 0 < remaining <= TTL and hmac.compare_digest(signature, expected)
    except (HTTPException, ValueError, TypeError):
        return False


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(max_length=1024)


@router.post("")
def login(body: Login, request: Request, response: Response):
    username, stored, key = local_config(request)
    # Exact origin check prevents cross-site login; local UI uses localhost.
    if request.headers.get("origin") != "http://localhost:5173":
        raise HTTPException(403, detail="member4_origin_not_allowed")
    now = time.time()
    with _lock:
        _attempts[:] = [attempt for attempt in _attempts if now - attempt < 60]
        if len(_attempts) >= 5:
            raise HTTPException(429, detail="member4_login_rate_limited")
        _attempts.append(now)
    try:
        salt, expected = stored.split(":")
        digest = hashlib.pbkdf2_hmac("sha256", body.password.get_secret_value().encode(), bytes.fromhex(salt), 600000).hex()
    except ValueError:
        raise HTTPException(503, detail="member4_session_not_configured") from None
    if not (hmac.compare_digest(body.username.encode(), username.encode()) & hmac.compare_digest(digest, expected)):
        raise HTTPException(401, detail="member4_login_failed")
    expires, nonce = str(int(now) + TTL), secrets.token_hex(16)
    signature = hmac.new(key.encode(), f"{username}:{stored}:{expires}:{nonce}".encode(), hashlib.sha256).hexdigest()
    response.set_cookie(COOKIE, f"{expires}.{nonce}.{signature}", max_age=TTL,
                        httponly=True, samesite="strict", secure=False, path=PATH)
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": True, "scope": "member4:read", "expires_in_seconds": TTL}
