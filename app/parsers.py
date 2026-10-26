"""Parsers: turn raw portal responses into our clean models.

No network code lives here, only "text/JSON in, models out". That makes this
file easy to test without the live portal (see tests/test_parsers.py).

Every parser checks that the data looks the way we observed it. If the portal
changes shape, we raise `UpstreamError` with a clear message instead of
returning wrong or half-empty data.
"""

import re
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from app.errors import MeterNotFound, UpstreamError
from app.models import (
    HierarchyNode,
    Location,
    MeterDetail,
    MeterListResponse,
    MeterSummary,
)

# ---------------------------------------------------------------------------
# Small cleaning helpers
# ---------------------------------------------------------------------------
_MISSING_MARKERS = {"", "-", "--", "n/a", "na", "null", "none"}


def normalize_whitespace(text: Optional[str]) -> str:
    """Collapse tabs, new lines, repeated and non-breaking spaces into single spaces."""
    if text is None:
        return ""
    return " ".join(text.split())


def parse_number(text: Optional[str]) -> Optional[float]:
    """Turn text like ' 1,234.5 ' into 1234.5.

    Returns None for empty/missing markers such as '-' or 'N/A'. Raises
    ValueError for text that is not a number, so bad data is never hidden.

    ASSUMPTION (NOT YET VERIFIED for consumption values): comma = thousands
    separator, dot = decimal point. Coordinates from the portal do use a dot.
    """
    cleaned = normalize_whitespace(text)
    if cleaned.lower() in _MISSING_MARKERS:
        return None
    return float(cleaned.replace(",", ""))


def clean_text(value: Any) -> Optional[str]:
    """Whitespace-normalized string, or None when the value is missing/blank."""
    if value is None:
        return None
    cleaned = normalize_whitespace(value if isinstance(value, str) else str(value))
    return cleaned or None


def _as_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise UpstreamError(f"The portal list response has an invalid '{field}' value.")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise UpstreamError(f"The portal list response has an invalid '{field}' value.")


# ---------------------------------------------------------------------------
# Meter list: JSON from GET /portal/meters/search
# ---------------------------------------------------------------------------
def parse_meter_list(payload: Any) -> MeterListResponse:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise UpstreamError("The portal meter list has an unexpected format.")

    items: List[MeterSummary] = []
    for row in payload["data"]:
        if not isinstance(row, dict):
            raise UpstreamError("The portal meter list contains an unexpected row.")
        meter_id = clean_text(row.get("meterId"))
        if not meter_id:
            raise UpstreamError("A meter in the portal list has no meterId.")
        items.append(
            MeterSummary(
                meter_id=meter_id,
                serial_no=clean_text(row.get("serialNo")),
                make=clean_text(row.get("make")),
                phase_type=clean_text(row.get("phaseType")),
                installation_status=clean_text(row.get("installStatus")),
                dt_code=clean_text(row.get("dtCode")),
            )
        )

    return MeterListResponse(
        items=items,
        total=_as_int(payload.get("total"), "total"),
        page=_as_int(payload.get("page"), "page"),
        page_size=_as_int(payload.get("pageSize"), "pageSize"),
    )


# ---------------------------------------------------------------------------
# Meter location: JSON from GET /portal/meters/<id>/geo
# The portal sends coordinates as TEXT ("26.93..."), so we convert to numbers.
# ---------------------------------------------------------------------------
def parse_geo(payload: Any) -> Optional[Location]:
    if not isinstance(payload, dict):
        raise UpstreamError("The portal location response has an unexpected format.")
    data = payload.get("data")
    if data is None:
        return None
    if not isinstance(data, dict):
        raise UpstreamError("The portal location response has an unexpected format.")

    def as_text(value: Any) -> Optional[str]:
        return None if value is None else str(value)

    try:
        latitude = parse_number(as_text(data.get("latitude")))
        longitude = parse_number(as_text(data.get("longitude")))
    except ValueError as exc:
        raise UpstreamError("The portal returned a location that is not a number.") from exc

    if latitude is None or longitude is None:
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise UpstreamError("The portal returned coordinates outside the valid range.")
    return Location(latitude=latitude, longitude=longitude)


# ---------------------------------------------------------------------------
# Meter detail: HTML page GET /meters/<id>
# The Nameplate section and the network path are part of the page itself
# (they are NOT loaded by a separate request).
# ---------------------------------------------------------------------------
_NAMEPLATE_LABELS = {
    "Meter ID": "meter_id",
    "Serial No": "serial_no",
    "Make": "make",
    "Phase Type": "phase_type",
    "Installation Status": "installation_status",
    "Installation Type": "installation_type",
}

# "Jaipur Zone 1 (Z-01)" -> name "Jaipur Zone 1", code "Z-01"
_NODE_PATTERN = re.compile(r"^(?P<name>.*?)\s*\((?P<code>[^()]+)\)$")
_SEPARATOR = "›"  # the "›" arrow between path items


def parse_meter_detail_html(html: str, meter_id: str) -> MeterDetail:
    soup = BeautifulSoup(html, "html.parser")

    heading = next(
        (h for h in soup.find_all("h2") if normalize_whitespace(h.get_text()).lower() == "nameplate"),
        None,
    )
    nameplate = heading.find_next("dl") if heading else None
    if nameplate is None:
        page_text = normalize_whitespace(soup.get_text()).lower()
        if "not found" in page_text:
            raise MeterNotFound(f"Meter '{meter_id}' was not found in the portal.")
        raise UpstreamError(
            "The meter page has no 'Nameplate' section. The portal layout may have changed."
        )

    known: Dict[str, Optional[str]] = {}
    extra: Dict[str, str] = {}
    for term in nameplate.find_all("dt"):
        label = normalize_whitespace(term.get_text())
        description = term.find_next_sibling("dd")
        value = clean_text(description.get_text()) if description else None
        field = _NAMEPLATE_LABELS.get(label)
        if field:
            known[field] = value
        elif label and value is not None:
            extra[label] = value

    found_id = known.get("meter_id")
    if not found_id:
        raise UpstreamError("The meter page has no 'Meter ID' field.")
    if found_id != meter_id:
        raise UpstreamError(
            f"The portal returned meter '{found_id}' when '{meter_id}' was requested."
        )

    hierarchy: List[HierarchyNode] = []
    title = soup.find("h1")
    path_nav = title.find_next_sibling("nav") if title else None
    if path_nav is not None:
        for span in path_nav.find_all("span"):
            text = normalize_whitespace(span.get_text())
            if not text or text == _SEPARATOR:
                continue
            match = _NODE_PATTERN.match(text)
            if match and match.group("name"):
                hierarchy.append(
                    HierarchyNode(name=match.group("name"), code=match.group("code"))
                )
            else:
                hierarchy.append(HierarchyNode(name=text, code=None))

    return MeterDetail(
        meter_id=found_id,
        serial_no=known.get("serial_no"),
        make=known.get("make"),
        phase_type=known.get("phase_type"),
        installation_status=known.get("installation_status"),
        installation_type=known.get("installation_type"),
        hierarchy=hierarchy,
        attributes=extra,
    )
