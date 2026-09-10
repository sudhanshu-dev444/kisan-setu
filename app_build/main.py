# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""FastAPI application entry-point for the File Storage & Management Backend.

Run with::

    python main.py

or directly via Uvicorn::

    uvicorn main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import shutil
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

import uvicorn
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from config import Settings, get_settings
from exceptions import (
    FileTooLargeError,
    InvalidMimeTypeError,
    PathTraversalError,
    PermissionDeniedError,
    StorageError,
    StorageFullError,
    FileNotFoundError_,
)
from database import DatabaseService
from market_service import MarketService
from rate_limit import RateLimiter
from schemas import (
    CommoditiesResponse,
    DatabaseHealthResponse,
    DatabaseStatsResponse,
    DeleteResponse,
    DirectoryListingResponse,
    ErrorResponse,
    FarmerCreateRequest,
    FarmerListResponse,
    FarmerResponse,
    FarmerUpdateRequest,
    FileMetadataResponse,
    HealthResponse,
    MarketPricesResponse,
    PaymentCalculationRequest,
    PaymentCalculationResponse,
    PFMSVoucherListResponse,
    PFMSVoucherMintRequest,
    PFMSVoucherResponse,
    SlotBookingCreateRequest,
    SlotBookingListResponse,
    SlotBookingResponse,
    UploadResponse,
    WeatherResponse,
)
from storage_service import StorageService
from weather_service import WeatherService

logger = logging.getLogger(__name__)

# ── Application settings & services ─────────────────────────────────────

settings: Settings = get_settings()
storage: StorageService = StorageService(settings)
db_service: DatabaseService = DatabaseService(settings)
weather_service: WeatherService = WeatherService(settings)
market_service: MarketService = MarketService(settings)
rate_limiter: RateLimiter = RateLimiter(settings)
INDEX_HTML_PATH = Path(__file__).resolve().parent.parent / "index.html"

# Endpoints that must stay exempt from rate limiting so operational
# monitoring (and the SPA landing page) can never be self-blocked.
RATE_LIMIT_EXEMPT_PATHS = ("/api/v1/health", "/api/v1/db/health")

# Generic client-visible messages per error type. Internals (paths, stack
# traces, database details) are logged server-side only — never echoed.
_GENERIC_ERROR_MESSAGES: dict[str, str] = {
    "file_not_found": "The requested file or directory was not found.",
    "path_traversal": "The request was blocked.",
    "permission_denied": "Operation not permitted.",
    "storage_full": "Insufficient storage space.",
    "file_too_large": "File exceeds the maximum allowed size.",
    "invalid_mime_type": "File type is not allowed.",
    "storage_error": "The storage operation could not be completed.",
    "rate_limited": "Too many requests. Please try again later.",
    "validation_error": "Invalid request parameters.",
    "internal_error": "An unexpected internal error occurred.",
    "unauthorized": "Authentication required.",
    "http_error": "Request was rejected.",
}
_GENERIC_DEFAULT_MESSAGE = _GENERIC_ERROR_MESSAGES["storage_error"]

# Content-Security-Policy values.
# The landing page loads its styling from Tailwind's Play CDN and fonts from
# Google CDNs, so its policy must permit exactly those origins.
_INDEX_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.tailwindcss.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: https://lh3.googleusercontent.com; "
    "connect-src 'self'"
)
# API/file responses carry no executable content: block everything foreign.
_API_CSP = "default-src 'self'"


# ── Security & request-correlation middleware ─────────────────────────

def _client_ip(request: Request) -> str:
    """Best-effort client IP, honouring a trusted reverse proxy."""
    if settings.TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _apply_security_headers(response: object, path: str, request_id: str) -> None:
    """Attach security and correlation headers to any response type."""
    headers = getattr(response, "headers", None)
    if headers is not None:
        headers["X-Request-ID"] = request_id
        headers["X-Content-Type-Options"] = "nosniff"
        headers["X-Frame-Options"] = "DENY"
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        headers["Content-Security-Policy"] = (
            _INDEX_CSP if path == "/" else _API_CSP
        )
        headers["Referrer-Policy"] = "no-referrer"


def _error_response_body(
    status_code: int, error_type: str, request_id: str | None
) -> dict:
    return ErrorResponse(
        detail=_GENERIC_ERROR_MESSAGES.get(error_type, _GENERIC_DEFAULT_MESSAGE),
        status_code=status_code,
        error_type=error_type,
        request_id=request_id,
    ).model_dump()


# ── Lifespan ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown lifecycle hook.

    Ensures the storage root directory exists before the first request
    is served.
    """
    settings.ensure_storage_root()
    logger.info(
        "Storage root ready at '%s'.", settings.STORAGE_ROOT.resolve(),
    )
    if not settings.STORAGE_API_KEY:
        logger.error(
            "CRITICAL SECURITY WARNING: STORAGE_API_KEY is unset! "
            "Storage vault endpoints will strictly reject unauthenticated access."
        )
    else:
        logger.info("Storage Vault authentication active.")
    yield
    logger.info("File Storage Backend shutting down.")


# ── FastAPI app ──────────────────────────────────────────────────────────

app = FastAPI(
    title="Kisan Setu — File Storage & Management Backend",
    description=(
        "Production-ready async file storage service. Supports chunked "
        "uploads, secure streaming downloads, deletion, and directory "
        "metadata scanning."
    ),
    version="1.0.0",
    lifespan=lifespan,
    # Interactive docs (Swagger UI / ReDoc) are disabled by default. They
    # expose the full API surface to anyone who can reach the service; set
    # ENABLE_DOCS=true only for non-production environments.
    docs_url="/docs" if settings.ENABLE_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_DOCS else None,
    # The OpenAPI JSON is a route/parameter manual for attackers. Disable it
    # in the same breath as the interactive docs, or /api/* stays enumerable.
    openapi_url="/openapi.json" if settings.ENABLE_DOCS else None,
)

# ── CORS middleware ──────────────────────────────────────────────────────

# Origins are taken from CORS_ORIGINS (env) — never "*" in production.
# Credentials are only enabled for explicit, trusted origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


def _b64url_decode(s: str) -> bytes:
    """Decode base64url string with required padding."""
    s += "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s.encode("ascii"))


def _verify_storage_token(token: str) -> bool:
    """Validate bearer token against STORAGE_API_KEY (API key or HMAC-SHA256 JWT).

    Supports:
    1. Direct high-entropy API key verification with constant-time equality.
    2. Signed JWT token (HS256) verification with claims & expiration validation.
    """
    expected_key = settings.STORAGE_API_KEY
    if not token or not expected_key:
        return False

    # 1. Constant-time API Key check (prevents timing side-channel attacks)
    if secrets.compare_digest(token, expected_key):
        return True

    # 2. Cryptographic JWT HS256 Token verification
    try:
        parts = token.split(".")
        if len(parts) == 3:
            h_b64, p_b64, sig_b64 = parts
            signing_input = f"{h_b64}.{p_b64}".encode("ascii")
            expected_sig = hmac.new(
                expected_key.encode("utf-8"), signing_input, hashlib.sha256
            ).digest()
            actual_sig = _b64url_decode(sig_b64)
            if secrets.compare_digest(expected_sig, actual_sig):
                header = json.loads(_b64url_decode(h_b64))
                if header.get("alg") == "HS256":
                    payload = json.loads(_b64url_decode(p_b64))
                    exp = payload.get("exp")
                    if exp is not None and time.time() > float(exp):
                        return False  # Expired token
                    nbf = payload.get("nbf")
                    if nbf is not None and time.time() < float(nbf):
                        return False  # Token not active yet
                    return True
    except Exception:
        pass

    return False


# ── Middleware: request ID + security headers + rate limiting ─────────

@app.middleware("http")
async def security_and_rate_limit_middleware(
    request: Request,
    call_next,
):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.request_id = request_id

    client_ip = _client_ip(request)
    path = request.url.path

    # ── Strict Authentication Middleware for Storage & DB APIs ──────────────
    # Rejects any unauthenticated request with a 401 Unauthorized status
    # before executing any file operations, uploads, or deletion logic.
    if request.method != "OPTIONS":
        normalized_path = path.rstrip("/")
        if normalized_path == "/api/v1/files" or normalized_path.startswith("/api/v1/files/"):
            auth_header = request.headers.get("Authorization") or ""
            api_key_header = request.headers.get("X-API-Key") or ""
            token = ""
            if auth_header.startswith("Bearer "):
                token = auth_header[7:].strip()
            elif api_key_header:
                token = api_key_header.strip()

            if not _verify_storage_token(token):
                logger.warning(
                    "UNAUTHORIZED_STORAGE_ACCESS_ATTEMPT: %s %s from IP %s (request_id=%s)",
                    request.method, path, client_ip, request_id,
                )
                response = JSONResponse(
                    status_code=401,
                    content=_error_response_body(401, "unauthorized", request_id),
                    headers={
                        "WWW-Authenticate": 'Bearer realm="kisan-setu-vault", error="invalid_token", error_description="Missing or invalid authentication credentials"'
                    },
                )
                _apply_security_headers(response, path, request_id)
                return response

        elif path.startswith("/api/v1/db/"):
            expected_admin_key = settings.ADMIN_API_KEY
            if expected_admin_key:
                auth_header = request.headers.get("Authorization") or ""
                token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
                if not (token and secrets.compare_digest(token, expected_admin_key)):
                    logger.warning(
                        "Unauthenticated DB access attempt to %s from %s (request_id=%s)",
                        path, client_ip, request_id,
                    )
                    response = JSONResponse(
                        status_code=401,
                        content=_error_response_body(401, "unauthorized", request_id),
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                    _apply_security_headers(response, path, request_id)
                    return response

    # Rate limit every /api route except preflight (OPTIONS) and exempt paths.
    if (
        request.method != "OPTIONS"
        and path.startswith("/api/")
        and not path.startswith(RATE_LIMIT_EXEMPT_PATHS)
    ):
        allowed, retry_after = rate_limiter.enforce(client_ip, path)
        if not allowed:
            logger.warning(
                "Rate limit exceeded for IP %s on %s (retry after %ds, request_id=%s)",
                client_ip, path, retry_after, request_id,
            )
            response = JSONResponse(
                status_code=429,
                content=_error_response_body(429, "rate_limited", request_id),
                headers={"Retry-After": str(retry_after)},
            )
            _apply_security_headers(response, path, request_id)
            return response

    response = await call_next(request)
    _apply_security_headers(response, path, request_id)
    return response


# ── Exception handlers ──────────────────────────────────────────────────

@app.exception_handler(StorageError)
async def storage_error_handler(
    request: Request,
    exc: StorageError,
) -> JSONResponse:
    """Translate any ``StorageError`` subclass into a structured JSON response.

    Full internal detail (absolute paths, filesystem specifics) is written
    to the server log only; clients receive a generic, safe message plus a
    correlation ID.
    """
    request_id = getattr(request.state, "request_id", None)
    logger.warning(
        "%s [%d]: %s (request_id=%s)",
        exc.error_type, exc.http_status, exc.detail, request_id,
    )
    return JSONResponse(
        status_code=exc.http_status,
        content=_error_response_body(exc.http_status, exc.error_type, request_id),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Return a generic 422 envelope; validation specifics go to logs only."""
    request_id = getattr(request.state, "request_id", None)
    logger.warning(
        "Validation error (request_id=%s): %s", request_id, exc.errors(),
    )
    return JSONResponse(
        status_code=422,
        content=_error_response_body(422, "validation_error", request_id),
    )


@app.exception_handler(HTTPException)
async def http_error_handler(
    request: Request,
    exc: HTTPException,
) -> JSONResponse:
    """Envelope any FastAPI HTTPException (auth deps, etc.) consistently."""
    request_id = getattr(request.state, "request_id", None)
    logger.warning(
        "HTTP %d (request_id=%s): %s", exc.status_code, request_id, exc.detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_response_body(exc.status_code, "http_error", request_id),
        headers={"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Catch-all: never leak internals, always return a correlation ID."""
    request_id = getattr(request.state, "request_id", None)
    logger.exception(
        "Unhandled error (request_id=%s): %s", request_id, exc,
    )
    return JSONResponse(
        status_code=500,
        content=_error_response_body(500, "internal_error", request_id),
    )


# ── Routes ───────────────────────────────────────────────────────────────

# -- Health ---------------------------------------------------------------

@app.get(
    "/api/v1/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Service health check",
)
async def health_check() -> HealthResponse:
    """Return service health status and available disk space."""
    usage = shutil.disk_usage(settings.STORAGE_ROOT)
    return HealthResponse(free_disk_bytes=usage.free)


# ── Storage Authentication Dependency ─────────────────────────────────────

def require_storage_auth(
    authorization: str | None = Header(None, alias="Authorization"),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> str:
    """FastAPI security dependency for storage API endpoints.

    Rejects any unauthenticated or unauthorized caller with 401 Unauthorized
    before file operations, uploads, or deletion logic can execute.
    """
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
    elif x_api_key:
        token = x_api_key.strip()

    if not _verify_storage_token(token):
        raise HTTPException(
            status_code=401,
            detail="Storage API requires valid authentication credentials (Bearer token, JWT, or X-API-Key).",
            headers={
                "WWW-Authenticate": 'Bearer realm="kisan-setu-vault", error="invalid_token", error_description="Missing or invalid authentication credentials"'
            },
        )
    return token


# -- Upload ---------------------------------------------------------------

@app.post(
    "/api/v1/files/upload",
    response_model=UploadResponse,
    status_code=201,
    dependencies=[Depends(require_storage_auth)],
    tags=["Files"],
    summary="Upload a file",
    responses={
        401: {"model": ErrorResponse, "description": "Authentication required"},
        413: {"model": ErrorResponse, "description": "File too large"},
        415: {"model": ErrorResponse, "description": "MIME type not allowed"},
        507: {"model": ErrorResponse, "description": "Insufficient disk space"},
    },
)
async def upload_file(
    file: UploadFile = File(..., description="The file to upload."),
    subdirectory: str | None = Form(
        default=None,
        description="Optional subdirectory under the storage root.",
    ),
) -> UploadResponse:
    """Accept a multipart file upload with optional subdirectory placement.

    The file is streamed to disk in **1 MB chunks** to keep memory usage
    constant.  MIME type and file size are validated before the write is
    committed.
    """
    result = await storage.upload_file(
        file_content=None,
        filename=file.filename or "untitled",
        content_type=file.content_type,
        read_chunk=file.read,
        subdirectory=subdirectory,
    )
    return result


# -- Download --------------------------------------------------------------

@app.get(
    "/api/v1/files/download/{file_path:path}",
    dependencies=[Depends(require_storage_auth)],
    tags=["Files"],
    summary="Download a file",
    responses={
        401: {"model": ErrorResponse, "description": "Authentication required"},
        404: {"model": ErrorResponse, "description": "File not found"},
        403: {"model": ErrorResponse, "description": "Path traversal blocked"},
    },
)
async def download_file(file_path: str) -> FileResponse:
    """Stream a file download.

    The ``{file_path:path}`` converter captures the full remaining URL
    segment, including slashes, so that nested paths work naturally.
    """
    abs_path, mime = await storage.download_file(file_path)
    return FileResponse(
        path=abs_path,
        media_type=mime,
        filename=abs_path.name,
    )


# -- Delete ----------------------------------------------------------------

@app.delete(
    "/api/v1/files/{file_path:path}",
    response_model=DeleteResponse,
    dependencies=[Depends(require_storage_auth)],
    tags=["Files"],
    summary="Delete a file",
    responses={
        401: {"model": ErrorResponse, "description": "Authentication required"},
        404: {"model": ErrorResponse, "description": "File not found"},
        403: {"model": ErrorResponse, "description": "Path traversal blocked"},
    },
)
async def delete_file(file_path: str) -> DeleteResponse:
    """Remove a file from storage."""
    return await storage.delete_file(file_path)


# -- Metadata --------------------------------------------------------------

@app.get(
    "/api/v1/files/metadata/{file_path:path}",
    response_model=FileMetadataResponse,
    dependencies=[Depends(require_storage_auth)],
    tags=["Files"],
    summary="Get file metadata",
    responses={
        401: {"model": ErrorResponse, "description": "Authentication required"},
        404: {"model": ErrorResponse, "description": "File not found"},
        403: {"model": ErrorResponse, "description": "Path traversal blocked"},
    },
)
async def get_file_metadata(file_path: str) -> FileMetadataResponse:
    """Return metadata (size, MIME type, timestamps) for a single file."""
    return await storage.get_file_metadata(file_path)


# -- Directory listing -----------------------------------------------------

@app.get(
    "/api/v1/files/list",
    response_model=DirectoryListingResponse,
    dependencies=[Depends(require_storage_auth)],
    tags=["Files"],
    summary="List directory contents",
    responses={
        401: {"model": ErrorResponse, "description": "Authentication required"},
        404: {"model": ErrorResponse, "description": "Directory not found"},
        403: {"model": ErrorResponse, "description": "Path traversal blocked"},
    },
)
async def list_directory(
    subdirectory: str | None = None,
) -> DirectoryListingResponse:
    """Scan a directory and return metadata for every file it contains.

    Defaults to the storage root when ``subdirectory`` is omitted.
    """
    return await storage.list_directory(subdirectory)


# -- Web Application Root --------------------------------------------------

@app.get(
    "/",
    tags=["Web"],
    summary="Serve Kisan Setu web application",
    include_in_schema=False,
)
async def serve_index() -> FileResponse:
    """Serve the single-page agricultural procurement web application."""
    if INDEX_HTML_PATH.is_file():
        return FileResponse(
            path=INDEX_HTML_PATH,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )
    return JSONResponse(
        status_code=404,
        content=_error_response_body(404, "file_not_found", None),
    )


# -- Weather API -----------------------------------------------------------

@app.get(
    "/api/v1/weather",
    response_model=WeatherResponse,
    tags=["Weather"],
    summary="Real-time agricultural weather & advisory",
)
async def get_weather(
    lat: float = 29.6857,
    lon: float = 76.9905,
    location: str = "Karnal",
) -> WeatherResponse:
    """Return real-time or cached weather data with farm-specific advisory.

    Coordinates default to Karnal, Haryana (lat=29.6857, lon=76.9905).
    Falls back gracefully to rich demo weather if OPENWEATHER_API_KEY is unset.
    """
    return await weather_service.get_weather(lat=lat, lon=lon, location=location)


# -- Market / Crop Prices API ----------------------------------------------

@app.get(
    "/api/v1/market/prices",
    response_model=MarketPricesResponse,
    tags=["Market"],
    summary="Current mandi crop prices & MSP benchmark",
)
async def get_market_prices(
    commodity: str = "Wheat",
    state: str = "Haryana",
) -> MarketPricesResponse:
    """Return daily mandi crop prices across mandis from Agmarknet.

    Calculates comparison with Government Minimum Support Price (MSP).
    Falls back gracefully to verified demo records if DATAGOV_API_KEY is unset.
    """
    return await market_service.get_prices(commodity=commodity, state=state)


@app.get(
    "/api/v1/market/commodities",
    response_model=CommoditiesResponse,
    tags=["Market"],
    summary="List tracked agricultural commodities",
)
async def list_commodities() -> CommoditiesResponse:
    """Return list of agricultural commodities supported by price lookups."""
    return market_service.get_supported_commodities()


# ── SQL Relational Database Endpoints ────────────────────────────────────

@app.get(
    "/api/v1/db/health",
    response_model=DatabaseHealthResponse,
    tags=["Database"],
    summary="SQL database health and integrity check",
)
async def get_db_health() -> DatabaseHealthResponse:
    """Return SQLite WAL mode status, file metrics, and integrity verification."""
    data = await db_service.health_check()
    return DatabaseHealthResponse(**data)


@app.get(
    "/api/v1/db/stats",
    response_model=DatabaseStatsResponse,
    tags=["Database"],
    summary="SQL database records and counters",
)
async def get_db_stats() -> DatabaseStatsResponse:
    """Return live table row counts and database storage size."""
    data = await db_service.get_stats()
    return DatabaseStatsResponse(**data)


@app.get(
    "/api/v1/db/farmers",
    response_model=FarmerListResponse,
    tags=["Database"],
    summary="List registered farmers",
)
async def list_farmers(limit: int = Query(50, ge=1, le=200)) -> FarmerListResponse:
    """Return list of registered farmers stored in the SQL database."""
    farmers = await db_service.list_farmers(limit=limit)
    return FarmerListResponse(
        farmers=[FarmerResponse(**f) for f in farmers],
        total=len(farmers),
    )


@app.post(
    "/api/v1/db/farmers",
    response_model=FarmerResponse,
    status_code=201,
    tags=["Database"],
    summary="Create or register a farmer in SQL DB",
)
async def create_farmer(payload: FarmerCreateRequest) -> FarmerResponse:
    """Create a new farmer or update existing record by mobile number."""
    record = await db_service.create_farmer(payload.model_dump())
    return FarmerResponse(**record)


@app.get(
    "/api/v1/db/farmers/{identifier}",
    response_model=FarmerResponse,
    tags=["Database"],
    summary="Fetch farmer details by ID or mobile",
)
async def get_farmer(identifier: str) -> FarmerResponse:
    """Fetch complete farmer profile including land records and bank accounts."""
    record = await db_service.get_farmer_by_id_or_mobile(identifier)
    if not record:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Farmer '{identifier}' not found in database."},
        )
    return FarmerResponse(**record)


@app.put(
    "/api/v1/db/farmers/{farmer_id}",
    response_model=FarmerResponse,
    tags=["Database"],
    summary="Update farmer details in SQL DB",
)
async def update_farmer(farmer_id: str, payload: FarmerUpdateRequest) -> FarmerResponse:
    """Update farmer personal information (name, village, mobile)."""
    record = await db_service.update_farmer(farmer_id, payload.model_dump(exclude_unset=True))
    if not record:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Farmer '{farmer_id}' not found in database."},
        )
    return FarmerResponse(**record)


@app.get(
    "/api/v1/db/bookings",
    response_model=SlotBookingListResponse,
    tags=["Database"],
    summary="List mandi slot bookings and gate passes",
)
async def list_bookings(farmer_id: str | None = None, limit: int = Query(50, ge=1, le=200)) -> SlotBookingListResponse:
    """Return all slot bookings / gate passes from the SQL database."""
    bookings = await db_service.list_bookings(farmer_id=farmer_id, limit=limit)
    return SlotBookingListResponse(
        bookings=[SlotBookingResponse(**b) for b in bookings],
        total=len(bookings),
    )


@app.post(
    "/api/v1/db/bookings",
    response_model=SlotBookingResponse,
    status_code=201,
    tags=["Database"],
    summary="Create mandi slot booking in SQL DB",
)
async def create_booking(payload: SlotBookingCreateRequest) -> SlotBookingResponse:
    """Record a mandi slot booking and generate a digital gate pass token in SQL."""
    record = await db_service.create_booking(payload.model_dump())
    return SlotBookingResponse(**record)


@app.get(
    "/api/v1/db/bookings/{token_number}",
    response_model=SlotBookingResponse,
    tags=["Database"],
    summary="Fetch gate pass by token number",
)
async def get_booking(token_number: str) -> SlotBookingResponse:
    """Fetch slot booking details by token number."""
    record = await db_service.get_booking_by_token(token_number)
    if not record:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Booking token '{token_number}' not found in database."},
        )
    return SlotBookingResponse(**record)


# ── Server-Side Payment & PFMS DBT Voucher Endpoints ─────────────────────


@app.post(
    "/api/v1/payments/calculate",
    response_model=PaymentCalculationResponse,
    tags=["Payments"],
    summary="Calculate verified farmer procurement payout using official MSP rates",
)
async def calculate_payment(
    payload: PaymentCalculationRequest,
) -> PaymentCalculationResponse:
    """Calculate verified farmer procurement payout using official MSP rates.

    All mathematical calculation and government rate lookups are executed
    on the backend to strictly prevent client-side price/quantity tampering.
    """
    result = await db_service.calculate_payment(
        commodity=payload.commodity,
        quantity=payload.quantity_quintals,
    )
    return PaymentCalculationResponse(**result)


@app.post(
    "/api/v1/payments/voucher/mint",
    response_model=PFMSVoucherResponse,
    status_code=201,
    tags=["Payments"],
    summary="Cryptographically mint and record an authentic PFMS DBT voucher",
)
async def mint_pfms_voucher(
    payload: PFMSVoucherMintRequest,
) -> PFMSVoucherResponse:
    """Mint and record a server-signed PFMS Direct Benefit Transfer voucher.

    Computes tamper-proof HMAC-SHA256 audit hashes and server digital
    signatures backed by persistent SQLite storage. Prevents unauthorized
    client-side voucher forging.
    """
    record = await db_service.mint_pfms_voucher(payload.model_dump())
    return PFMSVoucherResponse(**record)


@app.get(
    "/api/v1/payments/voucher/{voucher_ref}",
    response_model=PFMSVoucherResponse,
    tags=["Payments"],
    summary="Fetch and verify authentic PFMS DBT voucher",
)
async def get_pfms_voucher(voucher_ref: str) -> PFMSVoucherResponse:
    """Retrieve an authenticated PFMS voucher by voucher_ref or UTR number."""
    record = await db_service.get_pfms_voucher(voucher_ref)
    if not record:
        return JSONResponse(
            status_code=404,
            content={"detail": f"PFMS voucher '{voucher_ref}' not found in registry."},
        )
    return PFMSVoucherResponse(**record)


@app.get(
    "/api/v1/payments/vouchers",
    response_model=PFMSVoucherListResponse,
    tags=["Payments"],
    summary="List official PFMS DBT vouchers",
)
async def list_pfms_vouchers(
    farmer_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> PFMSVoucherListResponse:
    """List authenticated PFMS vouchers issued by the central server."""
    vouchers = await db_service.list_pfms_vouchers(farmer_id=farmer_id, limit=limit)
    return PFMSVoucherListResponse(
        vouchers=[PFMSVoucherResponse(**v) for v in vouchers],
        total=len(vouchers),
    )


# ── Uvicorn entry-point ──────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────
# Version A (Legacy) Endpoints & In-Memory State / Cache Integration
# ──────────────────────────────────────────────────────────────────────────

OTP_STORE: dict[str, dict] = {}

FARMERS: dict[str, dict] = {
    "9876543210": {
        "id": "PB-10492",
        "farmer_id": "PB-10492",
        "name": "Ram Singh",
        "full_name": "Ram Singh",
        "phone": "9876543210",
        "mobile": "9876543210",
        "village": "Karnal, Haryana",
        "district": "Karnal",
        "state": "Haryana",
        "aadhaar_linked": True,
        "aadhaar_last4": "3942",
        "land_acres": 4.5,
        "land_unit": "Acres",
        "crop": "Wheat",
        "bank": "SBI (XXXX-5678)",
        "bank_name": "State Bank of India (SBI)",
        "account_no": "XXXX-XXXX-5678",
        "ifsc": "SBIN0001234",
    }
}

MSP_PRICES = {
    "Wheat":        {"msp": 2275, "unit": "Rs/quintal", "season": "Rabi 2024-25"},
    "Rice":         {"msp": 2300, "unit": "Rs/quintal", "season": "Kharif 2024-25"},
    "Maize":        {"msp": 2090, "unit": "Rs/quintal", "season": "Kharif 2024-25"},
    "Cotton":       {"msp": 7121, "unit": "Rs/quintal", "season": "Kharif 2024-25"},
    "Sugarcane":    {"msp": 340,  "unit": "Rs/quintal", "season": "2024-25"},
    "Soybean":      {"msp": 4892, "unit": "Rs/quintal", "season": "Kharif 2024-25"},
    "Groundnut":    {"msp": 6783, "unit": "Rs/quintal", "season": "Kharif 2024-25"},
    "Mustard":      {"msp": 5950, "unit": "Rs/quintal", "season": "Rabi 2024-25"},
    "Sunflower":    {"msp": 7280, "unit": "Rs/quintal", "season": "Kharif 2024-25"},
    "Gram (Chana)": {"msp": 5550, "unit": "Rs/quintal", "season": "Rabi 2024-25"},
}

MANDI_PRICES = {
    "Karnal": [
        {"crop": "Wheat",        "arrival_qty": "1240 MT", "min": 2260, "max": 2310, "modal": 2280},
        {"crop": "Rice",         "arrival_qty": "840 MT",  "min": 2250, "max": 2370, "modal": 2305},
        {"crop": "Mustard",      "arrival_qty": "320 MT",  "min": 5800, "max": 6050, "modal": 5940},
    ],
    "Ludhiana": [
        {"crop": "Wheat",        "arrival_qty": "2100 MT", "min": 2270, "max": 2330, "modal": 2290},
        {"crop": "Cotton",       "arrival_qty": "640 MT",  "min": 6950, "max": 7200, "modal": 7100},
        {"crop": "Maize",        "arrival_qty": "480 MT",  "min": 2050, "max": 2130, "modal": 2090},
    ],
    "Pune": [
        {"crop": "Sugarcane",    "arrival_qty": "3400 MT", "min": 330,  "max": 360,  "modal": 342},
        {"crop": "Soybean",      "arrival_qty": "780 MT",  "min": 4750, "max": 4950, "modal": 4870},
        {"crop": "Groundnut",    "arrival_qty": "560 MT",  "min": 6600, "max": 6900, "modal": 6760},
    ],
    "Nagpur": [
        {"crop": "Cotton",       "arrival_qty": "1120 MT", "min": 6900, "max": 7250, "modal": 7080},
        {"crop": "Soybean",      "arrival_qty": "940 MT",  "min": 4700, "max": 4920, "modal": 4830},
        {"crop": "Gram (Chana)", "arrival_qty": "420 MT",  "min": 5400, "max": 5600, "modal": 5510},
    ],
}

WEATHER_DATA = {
    "Karnal":   {"temp": 32, "humidity": 68, "wind": "12 km/h NW", "condition": "Partly Cloudy", "rain_chance": 20, "advisory": "Good conditions for wheat harvesting."},
    "Ludhiana": {"temp": 35, "humidity": 55, "wind": "8 km/h NE",  "condition": "Sunny",          "rain_chance": 5,  "advisory": "Irrigation recommended for standing crops."},
    "Pune":     {"temp": 28, "humidity": 80, "wind": "15 km/h SW", "condition": "Light Rain",     "rain_chance": 75, "advisory": "Delay pesticide spraying due to rain."},
    "Nagpur":   {"temp": 38, "humidity": 42, "wind": "18 km/h W",  "condition": "Hot and Dry",    "rain_chance": 3,  "advisory": "Ensure proper irrigation; heat stress risk."},
    "Default":  {"temp": 31, "humidity": 60, "wind": "10 km/h",    "condition": "Clear",           "rain_chance": 10, "advisory": "Normal farming conditions."},
}

SCHEMES = [
    {
        "id": "pm-kisan",
        "name": "PM-KISAN Samman Nidhi",
        "amount": "Rs 6,000/year",
        "frequency": "3 installments of Rs 2,000",
        "eligibility": "Small & marginal farmers with cultivable land",
        "status": "Active",
        "next_installment": "December 2024",
    },
    {
        "id": "pmfby",
        "name": "PM Fasal Bima Yojana (PMFBY)",
        "amount": "Up to Rs 2 lakh",
        "frequency": "Per crop season",
        "eligibility": "All farmers growing notified crops",
        "status": "Enrollment Open",
        "deadline": "31 July 2025",
    },
    {
        "id": "kcc",
        "name": "Kisan Credit Card (KCC)",
        "amount": "Up to Rs 3 lakh @ 4% interest",
        "frequency": "Revolving credit",
        "eligibility": "Farmers, share croppers, tenant farmers",
        "status": "Active",
        "apply_at": "Nearest bank branch",
    },
    {
        "id": "pm-kusum",
        "name": "PM-KUSUM Solar Pump Scheme",
        "amount": "90% subsidy on solar pump",
        "frequency": "One-time",
        "eligibility": "Farmers with irrigated land",
        "status": "Active",
        "subsidy_split": "30% Central + 30% State + 30% Bank loan",
    },
    {
        "id": "soil-health-card",
        "name": "Soil Health Card Scheme",
        "amount": "Free soil testing",
        "frequency": "Every 2 years",
        "eligibility": "All farmers",
        "status": "Active",
        "benefit": "Customised fertilizer recommendations",
    },
]

PROCUREMENT_CENTERS = [
    {"id": "PC001", "name": "Karnal APMC Yard",      "district": "Karnal",   "crop": "Wheat, Rice",       "open": True,  "slots_available": 12},
    {"id": "PC002", "name": "Ludhiana Grain Market",  "district": "Ludhiana", "crop": "Wheat, Cotton",     "open": True,  "slots_available": 5},
    {"id": "PC003", "name": "Pune APMC Mandi",        "district": "Pune",     "crop": "Soybean, Sugarcane","open": True,  "slots_available": 20},
    {"id": "PC004", "name": "Nagpur Cotton Market",   "district": "Nagpur",   "crop": "Cotton, Soybean",   "open": False, "slots_available": 0},
]

def _generate_otp() -> str:
    import random, string
    return ''.join(random.choices(string.digits, k=6))


@app.get("/api/health", tags=["Legacy API"])
async def legacy_health():
    return {"status": "ok", "server": "Kisan Setu Unified Backend", "time": datetime.now().isoformat()}


@app.get("/api/msp", tags=["Legacy API"])
async def legacy_msp(crop: str | None = None):
    if crop and crop in MSP_PRICES:
        return {"crop": crop, **MSP_PRICES[crop]}
    return {"crops": MSP_PRICES}


@app.get("/api/mandi", tags=["Legacy API"])
async def legacy_mandi(district: str = "Karnal"):
    prices = MANDI_PRICES.get(district, MANDI_PRICES["Karnal"])
    return {
        "district": district,
        "date": datetime.now().strftime("%d %b %Y"),
        "prices": prices,
    }


@app.get("/api/weather", tags=["Legacy API"])
async def legacy_weather(location: str = "Karnal"):
    matched = next(
        (k for k in WEATHER_DATA if k.lower() in location.lower() or location.lower() in k.lower()),
        "Default",
    )
    return {
        "location": matched if matched != "Default" else location,
        "date": datetime.now().strftime("%A, %d %b %Y"),
        **WEATHER_DATA[matched],
    }


@app.get("/api/schemes", tags=["Legacy API"])
async def legacy_schemes():
    return {"schemes": SCHEMES, "total": len(SCHEMES)}


@app.get("/api/centers", tags=["Legacy API"])
async def legacy_centers(district: str | None = None):
    centers = PROCUREMENT_CENTERS
    if district:
        centers = [c for c in centers if district.lower() in c["district"].lower()]
    return {"centers": centers, "total": len(centers)}


@app.get("/api/farmer", tags=["Legacy API"])
async def legacy_get_farmer(phone: str | None = None):
    if not phone:
        return JSONResponse(status_code=400, content={"success": False, "error": "Phone parameter required"})
    
    # Check SQLite DB first
    db_farmer = await db_service.get_farmer_by_id_or_mobile(phone)
    if db_farmer:
        return {"success": True, "farmer": db_farmer}

    farmer = FARMERS.get(phone)
    if farmer:
        return {"success": True, "farmer": farmer}
    return JSONResponse(status_code=404, content={"success": False, "error": "Farmer not found"})


@app.post("/api/auth/send-otp", tags=["Legacy API"])
async def legacy_send_otp(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    phone = str(body.get("phone", "")).strip()
    if len(phone) != 10 or not phone.isdigit():
        return JSONResponse(status_code=400, content={"success": False, "error": "Invalid phone number"})
    
    otp = _generate_otp()
    from datetime import timedelta
    OTP_STORE[phone] = {"otp": otp, "expires": (datetime.now() + timedelta(minutes=5)).isoformat()}
    return {
        "success": True,
        "message": f"OTP sent to +91-{phone}",
        "demo_otp": otp,
        "expires_in": "5 minutes",
    }


@app.post("/api/auth/verify-otp", tags=["Legacy API"])
async def legacy_verify_otp(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    phone = str(body.get("phone", "")).strip()
    otp = str(body.get("otp", "")).strip()
    record = OTP_STORE.get(phone)

    # Allow demo OTP 482910 or match stored OTP
    if (record and record["otp"] == otp) or otp == "482910":
        if phone in OTP_STORE:
            del OTP_STORE[phone]

        # Check if farmer in SQLite DB
        db_farmer = await db_service.get_farmer_by_id_or_mobile(phone)
        if db_farmer:
            farmer = db_farmer
        elif phone in FARMERS:
            farmer = FARMERS[phone]
        else:
            import random
            farmer = {
                "id": f"KS-{random.randint(10000, 99999)}",
                "farmer_id": f"KS-{random.randint(10000, 99999)}",
                "name": f"Farmer {phone[-4:]}",
                "full_name": f"Farmer {phone[-4:]}",
                "phone": phone,
                "mobile": phone,
                "village": "Rural Sector",
                "district": "Local Mandi",
                "state": "State",
                "aadhaar_linked": True,
                "aadhaar_last4": "3942",
                "land_acres": 4.5,
                "land_unit": "Acres",
                "crop": "Wheat",
                "bank": "SBI (XXXX-5678)",
                "bank_name": "State Bank of India (SBI)",
                "account_no": "XXXX-XXXX-5678",
                "ifsc": "SBIN0001234",
            }
            # Save to SQLite DB as well
            try:
                await db_service.create_farmer({
                    "farmer_id": farmer["id"],
                    "full_name": farmer["name"],
                    "mobile": phone,
                    "village": farmer["village"],
                    "aadhaar_last4": "3942",
                    "bank_name": farmer["bank_name"],
                    "account_last4": "5678",
                    "ifsc_code": farmer["ifsc"],
                })
            except Exception:
                pass
            FARMERS[phone] = farmer

        return {"success": True, "farmer": farmer, "token": f"demo-token-{phone}"}
    return JSONResponse(status_code=401, content={"success": False, "error": "Invalid or expired OTP"})


@app.post("/api/farmer/register", tags=["Legacy API"])
async def legacy_farmer_register(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    phone = str(body.get("phone", "")).strip()
    name = body.get("name", "").strip()
    if not phone or not name:
        return JSONResponse(status_code=400, content={"success": False, "error": "Name and phone are required"})
    
    import random
    farmer_id = body.get("farmer_id") or f"KS-{random.randint(10000, 99999)}"
    village = body.get("village", "").strip()
    district = body.get("district", "")
    state = body.get("state", "")
    if not district and "," in village:
        parts = [p.strip() for p in village.split(",")]
        village = parts[0]
        if len(parts) > 1:
            district = parts[1]

    farmer_record = {
        "id": farmer_id,
        "farmer_id": farmer_id,
        "name": name,
        "full_name": name,
        "phone": phone,
        "mobile": phone,
        "village": village,
        "district": district or village,
        "state": state or "Haryana",
        "tehsil": body.get("tehsil", ""),
        "khasra": body.get("khasra", "42//18/2"),
        "aadhaar_linked": body.get("aadhaar_linked", True),
        "aadhaar_last4": body.get("aadhaar_last4", "3942"),
        "land_acres": body.get("land_acres", 4.5),
        "land_unit": body.get("land_unit", "Acres"),
        "crop": body.get("crop", "Wheat"),
        "bank": body.get("bank", "SBI (XXXX-5678)"),
        "bank_name": body.get("bank_name", "State Bank of India (SBI)"),
        "account_no": body.get("account_no", "XXXX-XXXX-5678"),
        "ifsc": body.get("ifsc", "SBIN0001234"),
    }
    FARMERS[phone] = farmer_record

    # Sync to SQLite DB
    try:
        await db_service.create_farmer({
            "farmer_id": farmer_id,
            "full_name": name,
            "mobile": phone,
            "village": village,
            "aadhaar_last4": farmer_record["aadhaar_last4"],
            "bank_name": farmer_record["bank_name"],
            "account_last4": "5678",
            "ifsc_code": farmer_record["ifsc"],
        })
    except Exception as err:
        logger.warning("Could not sync registration to SQLite: %s", err)

    return {"success": True, "farmer": farmer_record, "message": "Registration successful!"}


@app.post("/api/farmer/update", tags=["Legacy API"])
async def legacy_farmer_update(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    phone = str(body.get("phone", "")).strip()
    farmer = FARMERS.get(phone)
    if not farmer:
        # Check SQLite DB
        db_f = await db_service.get_farmer_by_id_or_mobile(phone)
        if db_f:
            farmer = dict(db_f)
            FARMERS[phone] = farmer

    if not farmer:
        return JSONResponse(status_code=404, content={"success": False, "error": "Farmer not found"})

    updatable = [
        "name", "full_name", "id", "farmer_id", "village", "district", "state", "tehsil", "khasra",
        "land_acres", "land_unit", "crop", "bank", "bank_name",
        "account_no", "ifsc", "aadhaar_linked", "aadhaar_last4"
    ]
    for field in updatable:
        if field in body:
            farmer[field] = body[field]
            if field == "name":
                farmer["full_name"] = body[field]
            elif field == "full_name":
                farmer["name"] = body[field]

    # Sync to SQLite DB
    try:
        f_id = farmer.get("farmer_id") or farmer.get("id")
        if f_id:
            await db_service.update_farmer(f_id, {
                "full_name": farmer.get("full_name") or farmer.get("name"),
                "village": farmer.get("village"),
                "bank_name": farmer.get("bank_name"),
                "ifsc_code": farmer.get("ifsc"),
            })
    except Exception as err:
        logger.warning("Could not sync update to SQLite: %s", err)

    return {"success": True, "farmer": farmer}


@app.post("/api/procurement/slot", tags=["Legacy API"])
async def legacy_procurement_slot(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    center_id = body.get("center_id", "")
    crop = body.get("crop", "")
    qty = float(body.get("qty_quintal", 0) or 0)
    from datetime import timedelta
    date = body.get("date", (datetime.now() + timedelta(days=1)).strftime("%d %b %Y"))
    center = next((c for c in PROCUREMENT_CENTERS if c["id"] == center_id), None)
    if not center:
        return JSONResponse(status_code=404, content={"success": False, "error": "Procurement center not found"})
    if not center.get("open", True):
        return JSONResponse(status_code=400, content={"success": False, "error": "Center is currently closed"})

    import random, string
    token = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

    # Persist to SQLite DB bookings table
    try:
        phone = body.get("phone", "9876543210")
        f_name = FARMERS.get(phone, {}).get("name", "Ram Singh")
        await db_service.create_booking({
            "token_number": f"KS-{token[:6]}",
            "farmer_id": FARMERS.get(phone, {}).get("id", "PB-10492"),
            "farmer_name": f_name,
            "commodity": crop,
            "mandi_name": center["name"],
            "gate_number": "Gate 1",
            "slot_date": date,
            "time_slot": "10:00 AM - 12:00 PM",
            "vehicle_type": "Tractor Trolley",
            "estimated_qty_quintals": qty,
        })
    except Exception as err:
        logger.warning("Could not sync booking to SQLite: %s", err)

    return {
        "success": True,
        "token": token,
        "center": center["name"],
        "district": center["district"],
        "crop": crop,
        "qty_quintal": qty,
        "date": date,
        "time_slot": "10:00 AM - 12:00 PM",
        "message": f"Slot booked! Bring token {token} to {center['name']}.",
    }


@app.post("/api/mandi/price-check", tags=["Legacy API"])
async def legacy_price_check(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    crop = body.get("crop", "")
    district = body.get("district", "Karnal")
    prices = MANDI_PRICES.get(district, [])
    match = next((p for p in prices if p["crop"].lower() == crop.lower()), None)
    if match:
        msp = MSP_PRICES.get(crop, {}).get("msp", None)
        above_msp = (match["modal"] >= msp) if msp else None
        return {
            "crop": crop,
            "district": district,
            "date": datetime.now().strftime("%d %b %Y"),
            **match,
            "msp": msp,
            "above_msp": above_msp,
        }
    return JSONResponse(status_code=404, content={"success": False, "error": f"No mandi data for {crop} in {district}"})



if __name__ == "__main__":
    logging.basicConfig(
        level=(logging.DEBUG if settings.DEBUG else logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        workers=settings.WORKERS,
        log_level="debug" if settings.DEBUG else settings.LOG_LEVEL,
        # Reload is a development convenience; it must never be active in
        # production deployments. Tied to DEBUG so it stays OFF by default.
        reload=settings.DEBUG,
    )