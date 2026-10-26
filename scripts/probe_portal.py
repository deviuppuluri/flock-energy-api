"""Safe probe of the legacy portal (READ-ONLY apart from the login itself).

Run from the project root:   python scripts/probe_portal.py
Optional meter id:           python scripts/probe_portal.py J100000

It logs in using PORTAL_USERNAME / PORTAL_PASSWORD from your .env file, then
fetches /meters and /meters/<id> and prints a STRUCTURE SUMMARY only:
status codes, content types, table headings, counts. It never prints the
password, cookie values, or page data rows.
"""

import re
import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402

_ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
METER_ID = _ARGS[0] if _ARGS else "J100000"
SAVE = "--save" in sys.argv  # also save cleaned HTML into probe_output/
# Extra read-only GET addresses to fetch, e.g. --extra="/portal/meters/J100000/geo"
EXTRAS = [a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--extra=")]
SESSION_COOKIE = "__Secure-better-auth.session_token"


def say(line: str) -> None:
    print(line)


def clean(text: str) -> str:
    return " ".join(text.split())


def login(client: httpx.Client, settings) -> bool:
    """Try the login the way the browser did (fields: email, password)."""
    base = settings.portal_base_url
    try:
        page = client.get("/login")
    except httpx.HTTPError as exc:
        say(f"LOGIN PAGE: network problem: {type(exc).__name__}")
        return False
    soup = BeautifulSoup(page.text, "html.parser")
    form = soup.find("form")
    inputs = soup.find_all("input")
    hidden = [i for i in inputs if (i.get("type") or "").lower() == "hidden" and i.get("name")]
    say(
        f"LOGIN PAGE: status={page.status_code} "
        f"form_method={form.get('method') if form else None} "
        f"form_action={form.get('action') if form else None}"
    )
    say(f"LOGIN PAGE input_names={[i.get('name') for i in inputs]}")
    say(f"LOGIN PAGE hidden_field_names={[i.get('name') for i in hidden]}")
    say(f"LOGIN PAGE cookie_names_set={[c.name for c in client.cookies.jar]}")

    # Send what a browser would: the form fields (+ any hidden ones) and
    # Origin/Referer headers. Values are never printed.
    data = {"email": settings.portal_username, "password": settings.portal_password}
    for field in hidden:
        data[field.get("name")] = field.get("value", "")
    headers = {"Origin": base, "Referer": f"{base}/login"}
    try:
        resp = client.post("/login", data=data, headers=headers, follow_redirects=False)
    except httpx.HTTPError as exc:
        say(f"LOGIN POST: network problem: {type(exc).__name__}")
        return False
    has_cookie = any(c.name == SESSION_COOKIE for c in client.cookies.jar)
    say(
        f"LOGIN POST: status={resp.status_code} location={resp.headers.get('location')} "
        f"content_type={resp.headers.get('content-type')} session_cookie_set={has_cookie}"
    )
    if resp.status_code >= 400:
        text = clean(BeautifulSoup(resp.text, "html.parser").get_text())
        say(f"LOGIN POST reply text (first 200 chars): {text[:200]}")
    return has_cookie


def save_clean_copy(html: str, filename: str) -> None:
    """Save the page WITHOUT scripts, styles or hidden fields (no tokens)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()
    for tag in soup.find_all("input", attrs={"type": "hidden"}):
        tag.decompose()
    out_dir = ROOT / "probe_output"
    out_dir.mkdir(exist_ok=True)
    (out_dir / filename).write_text(soup.prettify(), encoding="utf-8")
    say(f"saved cleaned copy: probe_output/{filename}")


def describe_page(name: str, resp: httpx.Response, filename: str = "page.html") -> None:
    ctype = resp.headers.get("content-type", "?")
    say(f"\n== {name} ==")
    say(f"status={resp.status_code} final_path={resp.url.path} content_type={ctype}")
    if resp.url.path.startswith("/login"):
        say("RESULT: sent back to the login page, so NOT authenticated")
        return
    if "json" in ctype:
        say("RESULT: JSON response")
        try:
            data = resp.json()
            kind = type(data).__name__
            keys = list(data)[:15] if isinstance(data, dict) else f"{len(data)} items"
            say(f"json type={kind} top-level={keys}")
        except ValueError:
            say("json could not be parsed")
        return

    html = resp.text
    soup = BeautifulSoup(html, "html.parser")
    say(f"html_length={len(html)}")
    tables = soup.find_all("table")
    say(f"tables={len(tables)}")
    for i, table in enumerate(tables[:3], start=1):
        heads = [clean(th.get_text()) for th in table.find_all("th")]
        rows = table.find_all("tr")
        say(f"  table {i}: headings={heads[:12]} rows={len(rows)}")
    say(f"definition_lists(dt)={len(soup.find_all('dt'))}")
    say(f"headings(h1/h2/h3)={[clean(h.get_text()) for h in soup.find_all(['h1', 'h2', 'h3'])][:10]}")
    meter_links = soup.find_all("a", href=re.compile(r"^/meters/[^/?#]+"))
    say(f"links_to_meter_pages={len(meter_links)}")
    scripts = soup.find_all("script")
    markers = {
        "react_router_context": "__reactRouterContext" in html,
        "remix_context": "__remixContext" in html,
        "next_data": "__NEXT_DATA__" in html,
        "json_script_tags": sum(1 for s in scripts if "json" in (s.get("type") or "")),
    }
    say(f"embedded_data_markers={markers}")
    say(f"forms={len(soup.find_all('form'))} buttons={len(soup.find_all('button'))}")
    if SAVE:
        save_clean_copy(html, filename)


def main() -> None:
    settings = get_settings()
    if not settings.has_credentials:
        say("STOP: PORTAL_USERNAME / PORTAL_PASSWORD are empty in your .env file.")
        return
    with httpx.Client(
        base_url=settings.portal_base_url,
        timeout=settings.request_timeout,
        follow_redirects=True,
    ) as client:
        if not login(client, settings):
            say("STOP: login did not set the session cookie.")
            return
        pages = (
            ("METER LIST", "/meters", "meters.html"),
            ("METER DETAIL", f"/meters/{METER_ID}", "meter_detail.html"),
        )
        for name, path, filename in pages:
            try:
                describe_page(f"{name} ({path})", client.get(path), filename)
            except httpx.HTTPError as exc:
                say(f"{name}: network problem: {type(exc).__name__}")

        for n, path in enumerate(EXTRAS, start=1):
            say(f"\n== API {n} ({path.split('?')[0]}) ==")
            try:
                resp = client.get(path)
            except httpx.HTTPError as exc:
                say(f"network problem: {type(exc).__name__}")
                continue
            say(
                f"status={resp.status_code} "
                f"content_type={resp.headers.get('content-type')} length={len(resp.text)}"
            )
            out_dir = ROOT / "probe_output"
            out_dir.mkdir(exist_ok=True)
            (out_dir / f"api_{n}.json").write_text(resp.text, encoding="utf-8")
            say(f"saved: probe_output/api_{n}.json")


if __name__ == "__main__":
    main()
