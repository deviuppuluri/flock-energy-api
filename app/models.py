"""Pydantic models: the shape of the JSON that OUR API returns.

Field names here are our own clean snake_case names. The portal uses other
names (for example `serialNo`, `installStatus`); app/parsers.py does the
translation. Every field below comes from data we actually observed in the
portal, except the Consumption models, which are PROVISIONAL until the
consumption request has been investigated.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])


class ErrorDetail(BaseModel):
    code: str = Field(description="Short machine-readable error name.")
    message: str = Field(description="Human-readable explanation.")


class ErrorResponse(BaseModel):
    """Every error from our API uses this same shape."""

    error: ErrorDetail


class MeterSummary(BaseModel):
    """One row of the portal's meter list."""

    meter_id: str = Field(examples=["J100000"])
    serial_no: Optional[str] = None
    make: Optional[str] = None
    phase_type: Optional[str] = Field(
        default=None, description="As shown by the portal (values seen: 'single', 'three')."
    )
    installation_status: Optional[str] = Field(
        default=None,
        description="As shown by the portal (values seen: Installed, Decommissioned, Faulty).",
    )
    dt_code: Optional[str] = Field(
        default=None, description="Code of the distribution transformer (DT), e.g. 'DT-001'."
    )


class MeterListResponse(BaseModel):
    """One page of meters, plus paging information from the portal."""

    items: List[MeterSummary]
    total: int = Field(description="Total meters matching the search, across all pages.")
    page: int
    page_size: int


class HierarchyNode(BaseModel):
    """One level of the network path above a meter (zone ... transformer)."""

    name: str = Field(examples=["Jaipur Zone 1"])
    code: Optional[str] = Field(default=None, examples=["Z-01"])


class Location(BaseModel):
    latitude: float
    longitude: float


class MeterDetail(BaseModel):
    """Details of one meter (nameplate + network path + location)."""

    meter_id: str
    serial_no: Optional[str] = None
    make: Optional[str] = None
    phase_type: Optional[str] = None
    installation_status: Optional[str] = None
    installation_type: Optional[str] = None
    hierarchy: List[HierarchyNode] = Field(
        default_factory=list,
        description="Network path from the top level down to the transformer, in the portal's order.",
    )
    location: Optional[Location] = Field(
        default=None, description="Null when the portal has no coordinates for this meter."
    )
    attributes: Dict[str, str] = Field(
        default_factory=dict,
        description="Any extra nameplate label/value pairs the portal shows that we do not model.",
    )


class ConsumptionReading(BaseModel):
    """One consumption data point. PROVISIONAL: not yet investigated."""

    period: str = Field(description="Date or time label as normalized by the adapter.")
    value: Optional[float] = Field(default=None, description="Null when the portal shows no value.")
    unit: Optional[str] = None


class ConsumptionResponse(BaseModel):
    meter_id: str
    readings: List[ConsumptionReading]
