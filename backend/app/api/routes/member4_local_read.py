"""Explicit development-only access to two Member 4 GET endpoints."""
import os
from fastapi import HTTPException

ALLOWED_PATHS = {
    "/api/v1/risks/research/farms/FARM_X/assessments",
    "/api/v1/risks/research/farms/FARM_X/milk-decline-predictions",
}


def local_read_allowed(request):
    if os.environ.get("C4_LOCAL_READ_ONLY") != "on":
        return False
    # Fail closed when opt-in is mistakenly used outside this exact local setup.
    if (os.environ.get("APP_ENV") != "development"
            or request.method != "GET" or request.url.path not in ALLOWED_PATHS
            or request.client is None or request.client.host not in ("127.0.0.1", "::1")
            or request.headers.get("host") not in ("localhost:8000", "127.0.0.1:8000", "[::1]:8000")
            or request.url.scheme != "http"
            or request.headers.get("origin") not in (None, "http://localhost:5173", "http://127.0.0.1:5173")
            or request.headers.get("sec-fetch-site") == "cross-site"
            or any(name in request.headers for name in ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto"))):
        raise HTTPException(403, detail={"code": "member4_local_read_restricted"})
    return True
