"""Tests for app/parsers.py (no network, no FastAPI needed).

The sample data below follows the shapes observed in the real portal; the
values are sample/test data.
"""

import pytest

from app.errors import MeterNotFound, UpstreamError
from app.parsers import (
    clean_text,
    normalize_whitespace,
    parse_geo,
    parse_meter_detail_html,
    parse_meter_list,
    parse_number,
)

LIST_PAYLOAD = {
    "data": [
        {
            "meterId": "J100000",
            "serialNo": "SE33962",
            "make": "HPL",
            "phaseType": "single",
            "installStatus": "Decommissioned",
            "dtCode": "DT-001",
        },
        {
            "meterId": " J100001 ",
            "serialNo": "GE84132",
            "make": "L&T",
            "phaseType": "single",
            "installStatus": "Installed",
            "dtCode": None,
        },
    ],
    "total": 403,
    "page": 1,
    "pageSize": 20,
}

DETAIL_HTML = """
<html><body><main>
<a href="/meters">&larr; Back to meters</a>
<h1>Meter J100000</h1>
<nav>
  <span>Jaipur Zone 1 (Z-01)</span><span class="x">&rsaquo;</span>
  <span>Circle 1 (C-01)</span><span class="x">&rsaquo;</span>
  <span>Malviya Nagar DT 1 (DT-001)</span>
</nav>
<section>
  <div><h2>Nameplate</h2>
  <dl>
    <div><dt>Meter ID</dt><dd>J100000</dd></div>
    <div><dt>Serial No</dt><dd>SE33962</dd></div>
    <div><dt>Make</dt><dd>HPL</dd></div>
    <div><dt>Phase Type</dt><dd>single</dd></div>
    <div><dt>Installation Status</dt><dd>Decommissioned</dd></div>
    <div><dt>Installation Type</dt><dd>Whole   Current</dd></div>
    <div><dt>Extra Label</dt><dd>Extra value</dd></div>
  </dl></div>
  <div><h2>Location</h2><p>Loading location...</p></div>
</section>
</main></body></html>
"""


# --- cleaning helpers --------------------------------------------------------
def test_normalize_whitespace():
    assert normalize_whitespace("  Meter \n\t 42  ") == "Meter 42"
    assert normalize_whitespace(None) == ""


def test_clean_text_returns_none_for_blank():
    assert clean_text("   ") is None
    assert clean_text(None) is None
    assert clean_text(" a  b ") == "a b"


def test_parse_number_handles_commas_and_spaces():
    assert parse_number(" 1,234.5 ") == 1234.5


def test_parse_number_returns_none_for_missing_markers():
    for missing in ["", "-", "N/A", None, "  "]:
        assert parse_number(missing) is None


def test_parse_number_rejects_garbage():
    with pytest.raises(ValueError):
        parse_number("abc")


# --- meter list --------------------------------------------------------------
def test_parse_meter_list_maps_and_normalizes_fields():
    result = parse_meter_list(LIST_PAYLOAD)
    assert result.total == 403
    assert result.page == 1
    assert result.page_size == 20
    assert len(result.items) == 2
    first = result.items[0]
    assert first.meter_id == "J100000"
    assert first.serial_no == "SE33962"
    assert first.installation_status == "Decommissioned"
    assert first.dt_code == "DT-001"
    # whitespace trimmed, missing value stays None (not a fake value)
    assert result.items[1].meter_id == "J100001"
    assert result.items[1].dt_code is None


def test_parse_meter_list_rejects_wrong_shape():
    with pytest.raises(UpstreamError):
        parse_meter_list({"oops": 1})
    with pytest.raises(UpstreamError):
        parse_meter_list([])


def test_parse_meter_list_rejects_row_without_meter_id():
    payload = {"data": [{"serialNo": "X"}], "total": 1, "page": 1, "pageSize": 20}
    with pytest.raises(UpstreamError):
        parse_meter_list(payload)


def test_parse_meter_list_rejects_missing_total():
    with pytest.raises(UpstreamError):
        parse_meter_list({"data": [], "page": 1, "pageSize": 20})


# --- location ----------------------------------------------------------------
def test_parse_geo_converts_text_to_numbers():
    location = parse_geo({"data": {"latitude": "26.938961", "longitude": "75.830957"}})
    assert location.latitude == 26.938961
    assert location.longitude == 75.830957


def test_parse_geo_returns_none_when_missing():
    assert parse_geo({"data": None}) is None
    assert parse_geo({"data": {"latitude": None, "longitude": None}}) is None
    assert parse_geo({"data": {"latitude": "-", "longitude": ""}}) is None


def test_parse_geo_rejects_bad_values():
    with pytest.raises(UpstreamError):
        parse_geo({"data": {"latitude": "abc", "longitude": "75.8"}})
    with pytest.raises(UpstreamError):
        parse_geo({"data": {"latitude": "126.0", "longitude": "75.8"}})
    with pytest.raises(UpstreamError):
        parse_geo("not a dict")


# --- meter detail (HTML) -----------------------------------------------------
def test_parse_meter_detail_html():
    detail = parse_meter_detail_html(DETAIL_HTML, "J100000")
    assert detail.meter_id == "J100000"
    assert detail.serial_no == "SE33962"
    assert detail.make == "HPL"
    assert detail.phase_type == "single"
    assert detail.installation_status == "Decommissioned"
    assert detail.installation_type == "Whole Current"  # repeated spaces collapsed
    assert detail.attributes == {"Extra Label": "Extra value"}
    assert [n.name for n in detail.hierarchy] == ["Jaipur Zone 1", "Circle 1", "Malviya Nagar DT 1"]
    assert [n.code for n in detail.hierarchy] == ["Z-01", "C-01", "DT-001"]
    assert detail.location is None  # filled in later by the client from /geo


def test_parse_meter_detail_rejects_changed_layout():
    with pytest.raises(UpstreamError):
        parse_meter_detail_html("<html><body><h1>Hello</h1></body></html>", "J100000")


def test_parse_meter_detail_reports_not_found_page():
    html = "<html><body><h1>Meter not found</h1></body></html>"
    with pytest.raises(MeterNotFound):
        parse_meter_detail_html(html, "J999999")


def test_parse_meter_detail_rejects_wrong_meter():
    with pytest.raises(UpstreamError):
        parse_meter_detail_html(DETAIL_HTML, "J100001")
