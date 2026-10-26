# PROTOCOL.md: Legacy Portal Findings

This document records how the legacy **Urja Meter Ops** portal
(`https://urja-ops.flockenergy.tech`) actually behaves.

**How findings were obtained**

- **Chrome DevTools:** I watched the Network tab while using the portal.
- **Probe script:** `scripts/probe_portal.py` logs in from code and prints a summary of the pages.
- **Saved page copies:** cleaned HTML of `/meters` and `/meters/J100000` (scripts, hidden fields and cookies removed).

**Status legend**

- `VERIFIED`: observed directly (date: 2026-10-26).
- `INFERRED`: a conclusion from what I observed; not directly proven.
- `NOT YET VERIFIED`: not observed. Do not rely on it.

No secret values (passwords, cookie values, tokens) are written in this file.

## 1. Login workflow

- `VERIFIED` Login page: `GET /login`, a form with **Email** and **Password** fields and a **Sign in** button.
- `VERIFIED` Login request: `POST /login` with form fields named `email` and `password`.
- `VERIFIED` In the browser, a successful login ends in a **redirect (HTTP 303) to `/meters`**.
- `VERIFIED` Wrong credentials show the message "invalid email and password" on the page (seen in the browser).
- `VERIFIED` From code, a form POST **without** browser-style headers was answered with **403**, and a **JSON** body with **415**. Sending a form with `Origin` and `Referer` headers (and any hidden form fields from the login page) **did** set the session cookie.
- `INFERRED` The portal is a **SvelteKit** app (the page structure and the 403/415 behaviour match SvelteKit's cross-site form protection). Which of the extra headers was strictly required was not tested separately.
- `NOT YET VERIFIED` The exact HTTP status of the login POST when sent from code (login success is judged by the cookie, not the status).

## 2. Authentication mechanism and session

- `VERIFIED` Mechanism: **session cookie** named `__Secure-better-auth.session_token` (the portal uses the Better Auth library).
- `VERIFIED` Cookie attributes seen: `Max-Age=3600` (1 hour), `Path=/`, `HttpOnly`, `Secure`, `SameSite=Lax`.
- `VERIFIED` With the cookie, pages `/meters` and `/meters/<id>` load; the probe was not sent back to the login page.
- `NOT YET VERIFIED` What an expired session looks like. **Assumption in code:** HTTP 401/403, or a redirect to `/login`. The client treats any of these as "expired", logs in again **once**, and retries the request **once**.

## 3. Endpoints

| Purpose | Method | Path | Response format | Status |
|---|---|---|---|---|
| Login | POST | `/login` | redirect / cookie | VERIFIED |
| Meter list | GET | `/portal/meters/search?q=<text>&page=<n>` | JSON | VERIFIED |
| Meter nameplate + network path | GET | `/meters/<meter_id>` | HTML (server-rendered) | VERIFIED |
| Meter location | GET | `/portal/meters/<meter_id>/geo` | JSON | VERIFIED |
| Consumption history | NOT YET VERIFIED | NOT YET VERIFIED | NOT YET VERIFIED | NOT YET VERIFIED |
| Network hierarchy (own endpoint) | NOT YET VERIFIED | NOT YET VERIFIED | NOT YET VERIFIED | NOT YET VERIFIED |

The meter pages themselves show "Loading..." for Location and Consumption in the
raw HTML: those sections are filled in by the browser after the page opens.

## 4. Data format details

**Meter list** (`VERIFIED`)

```json
{
  "data": [
    {"meterId": "J100000", "serialNo": "SE33962", "make": "HPL",
     "phaseType": "single", "installStatus": "Decommissioned", "dtCode": "DT-001"}
  ],
  "total": 403,
  "page": 1,
  "pageSize": 20
}
```

- 403 meters in total, 20 per page. `q` (search text) and `page` are the parameters I used.
- Values seen: `phaseType` = `single` / `three`; `installStatus` = `Installed` / `Decommissioned` / `Faulty`.
- `NOT YET VERIFIED`: whether the page size can be changed, how `q` matches (meter number, serial, both), what happens for a page past the end.

**Meter detail page** (`VERIFIED`, HTML)

- A **Nameplate** section: a definition list with the labels `Meter ID`, `Serial No`, `Make`, `Phase Type`, `Installation Status`, `Installation Type`.
- A **network path** under the page title: Zone > Circle > Division > Subdivision > Substation > Feeder > Transformer, each written like `Jaipur Zone 1 (Z-01)` (name and code).

**Meter location** (`VERIFIED`)

```json
{"data": {"latitude": "26.93...", "longitude": "75.83..."}}
```

- Coordinates arrive as **text**; the adapter converts them to numbers.
- `NOT YET VERIFIED`: what the reply looks like when a meter has no coordinates (the adapter returns `null` for a 404 or empty values).

**Consumption and hierarchy**

- `NOT YET VERIFIED`: fields, units, time granularity, date-range parameters.
- The portal has a **Transformers** page in its navigation (`/transformers`). It has not been investigated.

## 5. HTML parsing requirements

- Only the meter detail page needs HTML parsing (BeautifulSoup). The parser looks for the `Nameplate` heading, reads the `dt`/`dd` pairs after it, and reads the path items directly after the page title.
- If the `Nameplate` section is missing the adapter raises an error (it does not return empty data).

## 6. Data quirks and inconsistencies

- Field names differ between the list (`installStatus`, `serialNo`) and the detail page (labels such as `Installation Status`, `Serial No`). The adapter uses one set of names (`installation_status`, `serial_no`).
- Coordinates are strings, not numbers.
- Some serial numbers contain `&` (for example `L&84997`).
- `NOT YET VERIFIED`: date formats, number formats, and missing-value markers in consumption data.

## 7. Uncertainties and limitations

- Consumption history is not implemented because its request has not been identified yet.
- Unknown-meter behaviour is not verified (assumed: HTTP 404, or a page saying "not found").
- I only studied a few meters; other meters could expose fields I have not seen (unknown labels go into `attributes`).
- The session length (1 hour) comes from the cookie's `Max-Age`; real expiry behaviour is not tested.
