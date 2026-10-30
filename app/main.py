"""Source Finder — search vetted, peer-reviewed literature on any topic.

Run locally:  python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

This module only wires the web app together: security middleware, routes and
error handlers. The search pipeline lives in search.py, quality checks and
scoring in quality/, upstream API clients in sources/.

There are no accounts, cookies or database, so there is no session to hijack
and no CSRF or access-control surface. The main risks are XSS from upstream
data (handled in text.py and the frontend), abuse of the search and paid AI
review endpoints (rate limits and caps), and leaking internals in errors
(generic messages, details only in logs). The only POST endpoint,
/api/ai-review, takes nothing but a DOI the server has already vetted.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .ai_review import AIReviewer, ReviewError
from .config import Settings
from .limits import RateLimiter
from .search import MAX_TOKEN_LEN, SearchError, SearchService
from .text import normalize_doi
from .upstream import make_client

log = logging.getLogger("source_finder")
logging.basicConfig(level=logging.INFO)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    # no-referrer: clicking an article link must not leak the user's search terms.
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doi: str = Field(min_length=6, max_length=300)


def error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def same_origin(request: Request, allowed_hosts: tuple[str, ...]) -> bool:
    """Require a browser Origin header naming one of our own hosts.

    The page has no cookies, so this is not CSRF protection as such; it stops
    other websites from making visitors' browsers spend this server's AI budget.
    """
    try:
        host = urlsplit(request.headers.get("origin", "")).hostname
    except ValueError:
        return False
    return bool(host) and host in allowed_hosts


def create_app(settings: Settings | None = None,
               transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    """Build the app. `transport` lets tests replace the network."""
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        http = make_client(transport)
        app.state.search = SearchService(http, settings)
        try:
            yield
        finally:
            await http.aclose()
            await app.state.reviewer.close()

    # Interactive API docs are disabled; they are not needed and enlarge the surface.
    app = FastAPI(title="Source Finder", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    app.state.settings = settings
    app.state.reviewer = AIReviewer(settings)
    app.state.search_limiter = RateLimiter(settings.search_rate_limit_per_minute)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if request.url.scheme == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/search")
    async def search(request: Request, q: str = Query("", max_length=1000),
                     cursor: str = Query("", max_length=MAX_TOKEN_LEN)):
        if not app.state.search_limiter.allow(client_ip(request)):
            return error(429, "Too many searches. Please wait a minute and try again.")
        try:
            result = await app.state.search.search(q, cursor)
        except SearchError as exc:
            return error(exc.status, str(exc))
        # Only articles the server itself vetted can later be sent for AI review.
        app.state.reviewer.remember(result.articles)
        return result.payload | {"ai_review": app.state.reviewer.enabled}

    @app.post("/api/ai-review")
    async def ai_review(request: Request, body: ReviewRequest):
        if not request.headers.get("content-type", "").startswith("application/json"):
            return error(415, "Expected a JSON request.")
        if not same_origin(request, settings.allowed_hosts):
            return error(403, "Cross-site requests are not allowed.")
        doi = normalize_doi(body.doi)
        if not doi:
            return error(400, "Invalid DOI.")
        try:
            return {"doi": doi, "review": await app.state.reviewer.review(doi, client_ip(request))}
        except ReviewError as exc:
            return error(exc.status, str(exc))

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # FastAPI's default body echoes the rejected input back; keep errors generic.
        return error(400, "Invalid request.")

    @app.exception_handler(404)
    async def not_found(request: Request, exc):
        return error(404, "Not found.")

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.error("unhandled error", exc_info=exc)
        return error(500, "Something went wrong. Please try again.")

    return app


app = create_app()
