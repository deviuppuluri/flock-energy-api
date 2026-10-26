"""The adapter: the ONLY file that talks to the legacy Urja portal.

Idea: the rest of the app (main.py) never knows how the portal works. It just
asks this client for meters. If the portal changes, only the client and the
parsers change.

What the portal does (observed, see PROTOCOL.md):
- Login: POST /login with form fields `email` and `password`. A browser-style
  `Origin` header is required (without it the portal answers 403).
- Success is proven by the session cookie `__Secure-better-auth.session_token`,
  NOT by the HTTP status code.
- The session cookie lasts about 1 hour.
- Meter list: JSON from GET /portal/meters/search?q=&page=
- Meter detail: HTML page GET /meters/<id> (nameplate + network path) and
  JSON from GET /portal/meters/<id>/geo (coordinates)
- Consumption history: NOT YET INVESTIGATED (raises NotImplementedYet)

Rules for this adapter:
- Read-only. Apart from the login itself we only send GET requests.
- No blind retries: if the session looks expired we log in again and retry
  ONCE; if that fails too we raise an error.
- Never print or log the password or cookies.
"""

from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from app.config import Settings, get_settings
from app.errors import (  # noqa: F401  (re-exported so other files can import from here)
    ConfigError,
    LegacyPortalError,
    MeterNotFound,
    NotImplementedYet,
    UpstreamAuthError,
    UpstreamError,
    UpstreamTimeout,
)
from app.models import ConsumptionResponse, MeterDetail, MeterListResponse
from app.parsers import (  # noqa: F401
    normalize_whitespace,
    parse_geo,
    parse_meter_detail_html,
    parse_meter_list,
    parse_number,
)

SESSION_COOKIE = "__Secure-better-auth.session_token"


def _looks_unauthenticated(response: httpx.Response) -> bool:
    """True if the portal is telling us we are not logged in (any known sign)."""
    if response.status_code in (401, 403):
        return True
    # An expired session is redirected to the login page.
    return response.url.path.startswith("/login")


class LegacyClient:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        http: Optional[httpx.Client] = None,
    ) -> None:
        self._settings = settings or get_settings()
        # One reusable client keeps cookies between requests (a "session").
        # `http` can be replaced in tests so no real network call happens.
        self._http = http or httpx.Client(
            base_url=self._settings.portal_base_url,
            timeout=self._settings.request_timeout,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._http.close()

    # -- low-level helpers ---------------------------------------------------
    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Send one request and translate low-level errors into our own."""
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise UpstreamTimeout("The portal did not answer in time.") from exc
        except httpx.HTTPError as exc:
            raise UpstreamError("Could not reach the portal.") from exc
        if response.status_code >= 500:
            raise UpstreamError(
                f"The portal returned a server error (HTTP {response.status_code})."
            )
        return response

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
        return self._send("GET", path, params=params)

    def _has_session(self) -> bool:
        return any(cookie.name == SESSION_COOKIE for cookie in self._http.cookies.jar)

    # -- authentication --------------------------------------------------------
    def login(self) -> None:
        """Log in with the credentials from settings.

        Success means the session cookie was set. An HTTP 200 alone proves nothing.
        """
        if not self._settings.has_credentials:
            raise ConfigError(
                "Portal credentials are missing. Set PORTAL_USERNAME and PORTAL_PASSWORD in .env."
            )
        base = self._settings.portal_base_url
        self._http.cookies.clear()  # start clean so an old cookie cannot fake success

        # Read the login page first: include any hidden form fields it has.
        page = self._send("GET", "/login")
        form: Dict[str, str] = {}
        for field in BeautifulSoup(page.text, "html.parser").find_all(
            "input", attrs={"type": "hidden"}
        ):
            name = field.get("name")
            if name:
                form[name] = field.get("value", "")
        form["email"] = self._settings.portal_username
        form["password"] = self._settings.portal_password

        response = self._send(
            "POST",
            "/login",
            data=form,
            headers={"Origin": base, "Referer": f"{base}/login"},
            follow_redirects=False,
        )
        if response.status_code in (401, 403) or not self._has_session():
            raise UpstreamAuthError(f"Portal login failed (HTTP {response.status_code}).")

    def _fetch(self, path: str, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
        """GET a portal page, logging in first and once more if the session expired."""
        if not self._has_session():
            self.login()
        response = self._get(path, params)
        if _looks_unauthenticated(response):
            self.login()
            response = self._get(path, params)
            if _looks_unauthenticated(response):
                raise UpstreamAuthError(
                    "The portal rejected the session even after logging in again."
                )
        return response

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        if response.status_code != 200:
            raise UpstreamError(f"The portal returned HTTP {response.status_code}.")
        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamError("The portal returned data in an unexpected format.") from exc

    # -- data ------------------------------------------------------------------
    def list_meters(self, q: str = "", page: int = 1) -> MeterListResponse:
        response = self._fetch("/portal/meters/search", {"q": q, "page": page})
        return parse_meter_list(self._json(response))

    def get_meter(self, meter_id: str) -> MeterDetail:
        safe_id = quote(meter_id, safe="")

        page = self._fetch(f"/meters/{safe_id}")
        if page.status_code == 404:
            raise MeterNotFound(f"Meter '{meter_id}' was not found in the portal.")
        if page.status_code != 200:
            raise UpstreamError(f"The portal returned HTTP {page.status_code}.")
        detail = parse_meter_detail_html(page.text, meter_id)

        geo = self._fetch(f"/portal/meters/{safe_id}/geo")
        location = None if geo.status_code == 404 else parse_geo(self._json(geo))
        return detail.model_copy(update={"location": location})

    def get_consumption(self, meter_id: str) -> ConsumptionResponse:
        raise NotImplementedYet(
            "Consumption history has not been implemented yet: its portal request is not documented."
        )
