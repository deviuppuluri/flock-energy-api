"""Automated tests for the API endpoints.

These are MOCKED tests: we replace the real LegacyClient with a fake one, so
the tests run in milliseconds and never contact the live portal. The data in
FakeClient is made-up TEST data, not real portal data.

Run:  python -m pytest -v
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.client import LegacyClient
from app.config import Settings
from app.errors import (
    MeterNotFound,
    UpstreamAuthError,
    UpstreamError,
    UpstreamTimeout,
)
from app.main import app, get_client
from app.models import (
    ConsumptionReading,
    ConsumptionResponse,
    Location,
    MeterDetail,
    MeterListResponse,
    MeterSummary,
)


class FakeClient:
    """Stands in for LegacyClient. If `error` is set, every call raises it."""

    def __init__(self, error=None):
        self.error = error
        self.last_list_args = None

    def list_meters(self, q="", page=1):
        if self.error:
            raise self.error
        self.last_list_args = (q, page)
        return MeterListResponse(
            items=[MeterSummary(meter_id="TEST-001", serial_no="S1", make="Acme")],
            total=1,
            page=page,
            page_size=20,
        )

    def get_meter(self, meter_id):
        if self.error:
            raise self.error
        return MeterDetail(
            meter_id=meter_id,
            make="Acme",
            location=Location(latitude=26.9, longitude=75.8),
        )

    def get_consumption(self, meter_id):
        if self.error:
            raise self.error
        return ConsumptionResponse(
            meter_id=meter_id,
            readings=[ConsumptionReading(period="2026-01", value=12.5, unit="kWh")],
        )


@pytest.fixture
def make_client():
    """Returns a function that builds a TestClient using a chosen fake."""

    def _make(fake):
        app.dependency_overrides[get_client] = lambda: fake
        return TestClient(app)

    yield _make
    app.dependency_overrides.clear()  # always clean up after each test


# --- health -----------------------------------------------------------------
def test_health_returns_ok():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- successful responses (mocked adapter) ----------------------------------
def test_list_meters(make_client):
    response = make_client(FakeClient()).get("/api/v1/meters")
    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["meter_id"] == "TEST-001"
    assert body["total"] == 1
    assert body["page_size"] == 20


def test_list_meters_passes_search_and_page(make_client):
    fake = FakeClient()
    response = make_client(fake).get("/api/v1/meters?q=SE33&page=3")
    assert response.status_code == 200
    assert fake.last_list_args == ("SE33", 3)


def test_get_meter(make_client):
    response = make_client(FakeClient()).get("/api/v1/meters/TEST-001")
    assert response.status_code == 200
    body = response.json()
    assert body["meter_id"] == "TEST-001"
    assert body["location"] == {"latitude": 26.9, "longitude": 75.8}


def test_get_consumption(make_client):
    response = make_client(FakeClient()).get("/api/v1/meters/TEST-001/consumption")
    assert response.status_code == 200
    body = response.json()
    assert body["meter_id"] == "TEST-001"
    assert body["readings"][0]["value"] == 12.5


# --- missing / invalid input ------------------------------------------------
def test_unknown_meter_returns_404(make_client):
    client = make_client(FakeClient(error=MeterNotFound("No such meter.")))
    response = client.get("/api/v1/meters/DOES-NOT-EXIST")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "meter_not_found"


def test_invalid_meter_id_returns_422(make_client):
    response = make_client(FakeClient()).get("/api/v1/meters/bad!id")
    assert response.status_code == 422


def test_invalid_page_returns_422(make_client):
    response = make_client(FakeClient()).get("/api/v1/meters?page=0")
    assert response.status_code == 422


def test_too_long_search_returns_422(make_client):
    response = make_client(FakeClient()).get("/api/v1/meters?q=" + "a" * 101)
    assert response.status_code == 422


# --- upstream (portal) problems ---------------------------------------------
def test_upstream_auth_failure_returns_502(make_client):
    client = make_client(FakeClient(error=UpstreamAuthError("Login failed.")))
    response = client.get("/api/v1/meters")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_auth_failed"


def test_upstream_timeout_returns_504(make_client):
    client = make_client(FakeClient(error=UpstreamTimeout("Too slow.")))
    response = client.get("/api/v1/meters")
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "upstream_timeout"


def test_unexpected_upstream_error_returns_502(make_client):
    client = make_client(FakeClient(error=UpstreamError("Portal broke.")))
    response = client.get("/api/v1/meters")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_error"


# --- real adapter, but no network is needed to reach these errors -----------
def test_consumption_is_not_implemented_yet(make_client):
    """The real client must honestly say consumption is not built yet."""
    settings = Settings("https://example.test", "u", "p", 5.0)
    client = make_client(LegacyClient(settings=settings))
    response = client.get("/api/v1/meters/J100000/consumption")
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "not_implemented"


def test_missing_credentials_returns_500_configuration_error(make_client):
    settings = Settings("https://example.test", "", "", 5.0)
    client = make_client(LegacyClient(settings=settings))
    response = client.get("/api/v1/meters")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "configuration_error"


# --- OpenAPI file stays in sync with the code -------------------------------
def test_saved_openapi_matches_code():
    spec_file = Path(__file__).resolve().parent.parent / "openapi.json"
    if not spec_file.exists():
        pytest.skip("openapi.json not generated yet. Run: python scripts/export_openapi.py")
    saved = json.loads(spec_file.read_text(encoding="utf-8"))
    current = json.loads(json.dumps(app.openapi()))
    assert saved == current, "Run: python scripts/export_openapi.py"
