"""Tests for the adapter (app/client.py) against a FAKE portal.

`httpx.MockTransport` lets us script the portal's replies, so no real network
call is made. FakePortal imitates the behaviour we observed: login needs an
Origin header, success is shown by a session cookie, and an expired session is
redirected to the login page. The data is made-up test data.
"""

from urllib.parse import parse_qs

import httpx
import pytest

from app.client import LegacyClient, SESSION_COOKIE
from app.config import Settings
from app.errors import (
    ConfigError,
    MeterNotFound,
    UpstreamAuthError,
    UpstreamError,
    UpstreamTimeout,
)

BASE = "https://example.test"
SETTINGS = Settings(BASE, "operator@example.test", "secret-for-tests", 5.0)

LIST_PAYLOAD = {
    "data": [
        {
            "meterId": "J100000",
            "serialNo": "SE33962",
            "make": "HPL",
            "phaseType": "single",
            "installStatus": "Installed",
            "dtCode": "DT-001",
        }
    ],
    "total": 1,
    "page": 1,
    "pageSize": 20,
}

DETAIL_HTML = """
<html><body><main>
<h1>Meter J100000</h1>
<nav><span>Zone 1 (Z-01)</span><span>&rsaquo;</span><span>Circle 1 (C-01)</span></nav>
<section><h2>Nameplate</h2>
<dl>
  <div><dt>Meter ID</dt><dd>J100000</dd></div>
  <div><dt>Serial No</dt><dd>SE33962</dd></div>
  <div><dt>Make</dt><dd>HPL</dd></div>
  <div><dt>Phase Type</dt><dd>single</dd></div>
  <div><dt>Installation Status</dt><dd>Installed</dd></div>
  <div><dt>Installation Type</dt><dd>Whole Current</dd></div>
</dl></section>
</main></body></html>
"""

LOGIN_HTML = "<html><body><form method='POST'><input name='email'><input name='password'></form></body></html>"


class FakePortal:
    """A tiny pretend portal. Used as the handler of httpx.MockTransport."""

    def __init__(self):
        self.logins = 0
        self.valid_tokens = set()
        self.always_reject = False  # pretend login "works" but pages still redirect to /login
        self.accept_login = True
        self.list_payload = LIST_PAYLOAD
        self.geo_status = 200
        self.detail_status = 200

    def expire_sessions(self):
        self.valid_tokens.clear()

    def _authenticated(self, request):
        cookie_header = request.headers.get("cookie", "")
        return any(f"{SESSION_COOKIE}={t}" in cookie_header for t in self.valid_tokens)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path

        if path == "/login" and request.method == "GET":
            return httpx.Response(200, text=LOGIN_HTML)

        if path == "/login" and request.method == "POST":
            if request.headers.get("origin") != BASE:
                return httpx.Response(403, text="Cross-site POST form submissions are forbidden")
            form = parse_qs(request.content.decode())
            good = form.get("email") == [SETTINGS.portal_username] and form.get("password") == [
                SETTINGS.portal_password
            ]
            if not (good and self.accept_login):
                return httpx.Response(200, text="Invalid email or password")  # 200 but NO cookie
            self.logins += 1
            token = f"token-{self.logins}"
            self.valid_tokens.add(token)
            return httpx.Response(
                303,
                headers={
                    "location": "/meters",
                    "set-cookie": f"{SESSION_COOKIE}={token}; Path=/; Secure; HttpOnly; Max-Age=3600",
                },
            )

        # Everything below needs a valid session; otherwise redirect to the login page.
        if self.always_reject or not self._authenticated(request):
            return httpx.Response(303, headers={"location": "/login"})

        if path == "/portal/meters/search":
            self.last_params = dict(request.url.params)
            return httpx.Response(200, json=self.list_payload)
        if path == "/meters/J100000":
            return httpx.Response(self.detail_status, text=DETAIL_HTML)
        if path == "/portal/meters/J100000/geo":
            if self.geo_status != 200:
                return httpx.Response(self.geo_status)
            return httpx.Response(
                200, json={"data": {"latitude": "26.938961", "longitude": "75.830957"}}
            )
        return httpx.Response(404, text="Not found")


def make_client(handler, settings=SETTINGS) -> LegacyClient:
    http = httpx.Client(
        base_url=BASE, transport=httpx.MockTransport(handler), follow_redirects=True
    )
    return LegacyClient(settings=settings, http=http)


# --- low-level error translation ---------------------------------------------
def test_get_returns_response_on_success():
    client = make_client(lambda request: httpx.Response(200, text="hello"))
    assert client._get("/anything").text == "hello"


def test_timeout_becomes_upstream_timeout():
    def handler(request):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(UpstreamTimeout):
        make_client(handler)._get("/anything")


def test_network_failure_becomes_upstream_error():
    def handler(request):
        raise httpx.ConnectError("down")

    with pytest.raises(UpstreamError):
        make_client(handler)._get("/anything")


def test_server_error_becomes_upstream_error():
    client = make_client(lambda request: httpx.Response(503))
    with pytest.raises(UpstreamError):
        client._get("/anything")


# --- login --------------------------------------------------------------------
def test_login_sets_session_cookie():
    portal = FakePortal()
    client = make_client(portal)
    client.login()
    assert client._has_session()
    assert portal.logins == 1


def test_login_with_wrong_password_fails_even_though_http_is_200():
    portal = FakePortal()
    portal.accept_login = False
    client = make_client(portal)
    with pytest.raises(UpstreamAuthError):
        client.login()
    assert not client._has_session()


def test_login_without_credentials_is_a_config_error():
    client = make_client(FakePortal(), settings=Settings(BASE, "", "", 5.0))
    with pytest.raises(ConfigError):
        client.login()


# --- meter list ---------------------------------------------------------------
def test_list_meters_logs_in_automatically_and_parses():
    portal = FakePortal()
    client = make_client(portal)
    result = client.list_meters(q="SE3", page=2)
    assert result.total == 1
    assert result.items[0].meter_id == "J100000"
    assert portal.logins == 1
    assert portal.last_params == {"q": "SE3", "page": "2"}


def test_unexpected_list_shape_becomes_upstream_error():
    portal = FakePortal()
    portal.list_payload = {"surprise": True}
    with pytest.raises(UpstreamError):
        make_client(portal).list_meters()


# --- session expiry -----------------------------------------------------------
def test_expired_session_triggers_one_relogin():
    portal = FakePortal()
    client = make_client(portal)
    client.list_meters()
    assert portal.logins == 1

    portal.expire_sessions()  # the portal forgets our session
    result = client.list_meters()  # the client should log in again by itself
    assert result.total == 1
    assert portal.logins == 2


def test_session_rejected_even_after_relogin_raises_auth_error():
    portal = FakePortal()
    portal.always_reject = True
    client = make_client(portal)
    with pytest.raises(UpstreamAuthError):
        client.list_meters()
    assert portal.logins == 2  # first login + exactly one retry, no endless loop


# --- meter detail -------------------------------------------------------------
def test_get_meter_combines_page_and_location():
    detail = make_client(FakePortal()).get_meter("J100000")
    assert detail.meter_id == "J100000"
    assert detail.make == "HPL"
    assert detail.installation_type == "Whole Current"
    assert [n.code for n in detail.hierarchy] == ["Z-01", "C-01"]
    assert detail.location.latitude == 26.938961
    assert detail.location.longitude == 75.830957


def test_get_meter_missing_location_is_null_not_fake():
    portal = FakePortal()
    portal.geo_status = 404
    detail = make_client(portal).get_meter("J100000")
    assert detail.location is None


def test_get_meter_unknown_id_returns_not_found():
    with pytest.raises(MeterNotFound):
        make_client(FakePortal()).get_meter("J999999")
