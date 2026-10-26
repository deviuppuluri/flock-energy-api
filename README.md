# Urja Meter Ops REST API Wrapper

A small, read-only REST API that sits in front of the legacy **Urja Meter Ops**
web portal and exposes its smart-meter data as clean, documented JSON.

> **Project status (keep this section honest):**
> - Working against the live portal (verified by the author): login, meter list, meter details (nameplate, network path, location).
> - **Pending:** consumption history. Its portal request has not been documented yet, so
>   `GET /api/v1/meters/{meter_id}/consumption` returns **HTTP 501 Not Implemented**
>   instead of fake data. Findings are tracked in [PROTOCOL.md](PROTOCOL.md).

## Problem being solved

The portal is built for people using a browser. Other programs cannot easily
read its data. This project logs in to the portal on their behalf and returns the
data as JSON so nobody has to use the original website.

## Main features

- `GET /health` (checks that this API process is running)
- `GET /api/v1/meters?q=&page=` (meter listing, 20 per page, optional search)
- `GET /api/v1/meters/{meter_id}` (nameplate, network path, location)
- `GET /api/v1/meters/{meter_id}/consumption` (consumption history: **not implemented yet, returns 501**)
- Automatic OpenAPI documentation (Swagger UI at `/docs`)
- One consistent JSON error format
- Automated tests that run without the live portal

## Technology stack

Python 3.10+, FastAPI, Uvicorn, httpx, BeautifulSoup4, Pydantic, python-dotenv, pytest.
All free, no API keys.

## Project structure

```
flock-energy-api/
├── app/
│   ├── main.py      # URLs (endpoints) and error mapping
│   ├── client.py    # adapter: the only code that talks to the legacy portal
│   ├── parsers.py   # turns portal JSON/HTML into our models (no network)
│   ├── errors.py    # our own error types
│   ├── models.py    # Pydantic models: shape of our JSON
│   └── config.py    # reads settings/credentials from .env
├── tests/
│   ├── test_api.py      # endpoint tests using a fake adapter
│   ├── test_client.py   # adapter tests using a fake portal (no network)
│   └── test_parsers.py  # parser tests (no network)
├── scripts/export_openapi.py   # regenerates openapi.json
├── scripts/probe_portal.py     # investigation helper: summarises portal pages
├── openapi.json     # generated API specification
├── PROTOCOL.md      # how the legacy portal really behaves
├── REFLECTION.md    # my reflection answers
├── .env.example     # template for secrets (safe to commit)
└── requirements.txt
```

## Prerequisites

- Windows with Python 3.10 or newer
- Git
- (Optional) VS Code

## Setup on Windows (PowerShell)

```powershell
cd flock-energy-api
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If activation is blocked, run once:
`Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

## Environment configuration

```powershell
Copy-Item .env.example .env
```

Open `.env` and fill in `PORTAL_USERNAME` and `PORTAL_PASSWORD` with the
credentials provided for the assignment. `.env` is listed in `.gitignore` and
must **never** be committed.

## Run the server

```powershell
python -m uvicorn app.main:app --reload
```

- API: http://127.0.0.1:8000
- Swagger docs: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health

Stop the server with **Ctrl + C** in the terminal.

## Endpoints and sample responses

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Is this API running? |
| GET | `/api/v1/meters?q=&page=` | One page of meters (search text `q`, page number `page`) |
| GET | `/api/v1/meters/{meter_id}` | One meter's details |
| GET | `/api/v1/meters/{meter_id}/consumption` | Consumption history (501 for now) |

Real response of `/health`:

```json
{"status": "ok"}
```

Error format used by every error (this is the real shape; the message text is an example):

```json
{"error": {"code": "not_implemented", "message": "Meter listing has not been investigated yet."}}
```

Status codes: `404` meter not found, `422` invalid meter id, `501` portal part
not implemented yet, `502` portal error or login failure, `504` portal timeout.

Example of `GET /api/v1/meters?page=1` (**illustrative**: shortened, built from the
field names and sample values seen in the portal; run the API to see real output):

```json
{
  "items": [
    {"meter_id": "J100000", "serial_no": "SE33962", "make": "HPL",
     "phase_type": "single", "installation_status": "Decommissioned", "dt_code": "DT-001"}
  ],
  "total": 403,
  "page": 1,
  "page_size": 20
}
```

Example of `GET /api/v1/meters/J100000` (**illustrative**, shortened):

```json
{
  "meter_id": "J100000",
  "serial_no": "SE33962",
  "make": "HPL",
  "phase_type": "single",
  "installation_status": "Decommissioned",
  "installation_type": "Whole Current",
  "hierarchy": [{"name": "Jaipur Zone 1", "code": "Z-01"}],
  "location": {"latitude": 26.93, "longitude": 75.83},
  "attributes": {}
}
```

## Authentication and session design

API users do **not** log in. The adapter (`app/client.py`) owns one reusable
HTTP session, logs in to the portal with credentials from `.env`, keeps the
session cookie, and detects an expired session. The exact login flow is
documented in `PROTOCOL.md` once verified. A `POST /api/v1/auth/login` endpoint
is intentionally **not** included, because exposing portal login to API users would
add risk without benefit.

## Run the tests

```powershell
python -m pytest -v
```

Tests are mocked, so they never contact the live portal.

## Regenerate OpenAPI documentation

```powershell
python scripts/export_openapi.py
```

A test fails if `openapi.json` is out of date, so it cannot silently drift from the code.

## Assumptions

- Meter ids contain only letters, digits, `-`, `_` or `.` (only ids like `J100000` were seen).
- An expired portal session shows up as HTTP 401/403 or a redirect to `/login` (**NOT YET VERIFIED**).
- The portal uses `,` as thousands separator and `.` as decimal mark in consumption data (**NOT YET VERIFIED**).

## Design decisions and trade-offs

- **Adapter layer:** portal details are isolated in `client.py`, so portal changes do not touch the API.
- **Honest 501 instead of fake data:** unfinished parts say so.
- **Read-only:** no write operations are sent to the portal.
- **Parsers separate from the client:** `app/parsers.py` has no network code, so page/JSON reading is tested without the portal.
- **One automatic re-login:** if a request looks unauthenticated the client logs in again once and retries once; it never loops.

## Intentionally omitted

- Paid hosting, databases or API keys
- `POST /api/v1/auth/login` (see above)
- Hierarchy endpoint (optional extension, only if the portal provides the data)

## Current limitations

- Consumption history is not implemented (501).
- Meter details read an HTML page, so a portal redesign could break `parse_meter_detail_html`; the parser fails loudly instead of returning wrong data.
- Only the portal's fixed page size (20) is supported for the list.

## Future improvements

- Caching of portal responses
- Pagination and date-range filters if the portal supports them
- Optional live integration tests, separate from the mocked tests

## More documentation

- [PROTOCOL.md](PROTOCOL.md): legacy portal findings
- [REFLECTION.md](REFLECTION.md): reflection answers

## Publishing to GitHub

1. Check `.env` is ignored: `git status` must NOT list `.env`.
2. `git init`
3. `git add .` then `git commit -m "Initial commit"`
4. Create a new **public** repository on github.com (without README or .gitignore).
5. `git remote add origin <your-repo-url>` then `git push -u origin main`
