"""Turn an entity or coordinates into a postal address."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import aiohttp

from .const import NOMINATIM_URL, USER_AGENT

# Companion app geocoded sensors: iOS uses "Postal Code" style keys, Android
# uses snake_case. Generic lowercase names cover other integrations.
_KEYS = {
    "city": ("Locality", "locality", "city", "town", "village"),
    "state": ("Administrative Area", "admin_area", "state", "region"),
    "postal_code": ("Postal Code", "postal_code", "postcode", "zip"),
    "country": ("Country", "country"),
}


def _first(attrs: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        if value := attrs.get(key):
            return str(value).strip()
    return ""


def from_attributes(attrs: Mapping[str, Any]) -> dict[str, str] | None:
    """Read an address from entity attributes, or None if there isn't one."""
    address = {field: _first(attrs, keys) for field, keys in _KEYS.items()}
    number = _first(attrs, ("Sub Thoroughfare", "sub_thoroughfare", "house_number"))
    road = _first(attrs, ("Thoroughfare", "thoroughfare", "street", "road"))
    address["street"] = f"{number} {road}".strip() if road else _first(attrs, ("Name", "name"))
    return address if address["city"] and address["postal_code"] else None


def coordinates(attrs: Mapping[str, Any]) -> tuple[float, float] | None:
    lat, lon = attrs.get("latitude"), attrs.get("longitude")
    if lat is None or lon is None:
        loc = attrs.get("Location") or attrs.get("location")
        if isinstance(loc, (list, tuple)) and len(loc) == 2:
            lat, lon = loc
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


async def reverse_geocode(
    session: aiohttp.ClientSession, lat: float, lon: float
) -> dict[str, str] | None:
    """Reverse geocode with OpenStreetMap Nominatim (one call per update)."""
    resp = await session.get(
        NOMINATIM_URL,
        params={"lat": lat, "lon": lon, "format": "jsonv2", "addressdetails": 1, "zoom": 18},
        headers={"User-Agent": USER_AGENT},
        timeout=aiohttp.ClientTimeout(total=20),
    )
    try:
        resp.raise_for_status()
        data = await resp.json()
    finally:
        resp.release()
    raw = data.get("address") or {}
    address = {
        "street": " ".join(p for p in (raw.get("house_number"), raw.get("road")) if p),
        "city": next(
            (raw[k] for k in ("city", "town", "village", "hamlet", "municipality", "county") if raw.get(k)),
            "",
        ),
        "state": raw.get("state", ""),
        "postal_code": raw.get("postcode", ""),
        "country": raw.get("country", ""),
    }
    return address if address["city"] and address["postal_code"] else None
