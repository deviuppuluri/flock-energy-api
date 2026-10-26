"""The REST API (FastAPI app).

This file defines the URLs people can call. It does NOT know how the legacy
portal works; it asks `LegacyClient` (app/client.py) for data and turns the
result, or any error, into clean JSON.

Run it with:  python -m uvicorn app.main:app --reload
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, Path, Query, Request
from fastapi.responses import JSONResponse

from app.client import LegacyClient
from app.errors import (
    ConfigError,
    LegacyPortalError,
    MeterNotFound,
    NotImplementedYet,
    UpstreamAuthError,
    UpstreamError,
    UpstreamTimeout,
)
from app.models import (
    ConsumptionResponse,
    ErrorResponse,
    HealthResponse,
    MeterDetail,
    MeterListResponse,
)

app = FastAPI(
    title="Urja Meter Ops API",
    version="0.2.0",
    description=(
        "A read-only REST wrapper around the legacy Urja Meter Ops web portal. "
        "Authentication with the portal is handled automatically by the adapter, "
        "so API users never see portal credentials."
    ),
)


# ---------------------------------------------------------------------------
# Dependency: one shared LegacyClient (so the portal session/cookies are reused).
# Tests replace this with a fake client, so they never touch the live portal.
# ---------------------------------------------------------------------------
@lru_cache
def get_client() -> LegacyClient:
    return LegacyClient()


ClientDep = Annotated[LegacyClient, Depends(get_client)]


# ---------------------------------------------------------------------------
# Error handling: one place that maps adapter errors to HTTP status codes.
# ---------------------------------------------------------------------------
# Order matters: more specific errors must come before their parent classes.
_ERROR_MAP = (
    (MeterNotFound, 404, "meter_not_found"),
    (NotImplementedYet, 501, "not_implemented"),
    (ConfigError, 500, "configuration_error"),
    (UpstreamTimeout, 504, "upstream_timeout"),
    (UpstreamAuthError, 502, "upstream_auth_failed"),
    (UpstreamError, 502, "upstream_error"),
)


@app.exception_handler(LegacyPortalError)
async def legacy_portal_error_handler(request: Request, exc: LegacyPortalError):
    for error_type, status_code, code in _ERROR_MAP:
        if isinstance(exc, error_type):
            return JSONResponse(
                status_code=status_code,
                content={"error": {"code": code, "message": str(exc)}},
            )
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "Unexpected error."}},
    )


# Meter ids seen so far look like 'J100000'. We allow letters, digits, '-', '_'
# and '.', which keeps the id safe to place inside a portal URL.
MeterId = Annotated[
    str,
    Path(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.\-]+$",
        description="Meter identifier as used by the portal, e.g. J100000.",
    ),
]

_ERROR_RESPONSES = {
    404: {"model": ErrorResponse, "description": "Meter not found."},
    500: {"model": ErrorResponse, "description": "API configuration problem (e.g. missing credentials)."},
    501: {"model": ErrorResponse, "description": "Not implemented yet."},
    502: {"model": ErrorResponse, "description": "Portal error or login failure."},
    504: {"model": ErrorResponse, "description": "Portal timed out."},
}


def _errors(*codes: int) -> dict:
    return {code: _ERROR_RESPONSES[code] for code in codes}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    """Is OUR API process running? (Does not contact the legacy portal.)"""
    return HealthResponse(status="ok")


@app.get(
    "/api/v1/meters",
    response_model=MeterListResponse,
    responses=_errors(500, 502, 504),
    tags=["meters"],
)
def list_meters(
    client: ClientDep,
    q: Annotated[
        str,
        Query(max_length=100, description="Search text (meter number or serial). Empty = all."),
    ] = "",
    page: Annotated[int, Query(ge=1, le=100000, description="Page number, starting at 1.")] = 1,
) -> MeterListResponse:
    """One page of meters from the legacy portal (the portal decides the page size)."""
    return client.list_meters(q=q, page=page)


@app.get(
    "/api/v1/meters/{meter_id}",
    response_model=MeterDetail,
    responses=_errors(404, 500, 502, 504),
    tags=["meters"],
)
def get_meter(meter_id: MeterId, client: ClientDep) -> MeterDetail:
    """Details of one meter: nameplate, network path and location."""
    return client.get_meter(meter_id)


@app.get(
    "/api/v1/meters/{meter_id}/consumption",
    response_model=ConsumptionResponse,
    responses=_errors(404, 501, 502, 504),
    tags=["meters"],
)
def get_consumption(meter_id: MeterId, client: ClientDep) -> ConsumptionResponse:
    """Consumption history of one meter. NOT IMPLEMENTED YET (returns 501)."""
    return client.get_consumption(meter_id)
