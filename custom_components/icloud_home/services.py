"""The icloud_home.set_home_address action."""

from __future__ import annotations

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, ATTR_LATITUDE, ATTR_LONGITUDE
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import address as addr
from .carddav import AuthError, CardDAVError
from .const import (
    ADDRESS_FIELDS,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DRY_RUN,
    CONF_CARD_URL,
    DOMAIN,
    SERVICE_SET_HOME_ADDRESS,
)

SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_ENTITY_ID): cv.entity_id,
        vol.Inclusive(ATTR_LATITUDE, "coordinates"): cv.latitude,
        vol.Inclusive(ATTR_LONGITUDE, "coordinates"): cv.longitude,
        **{vol.Optional(field): cv.string for field in ADDRESS_FIELDS},
        vol.Optional(ATTR_DRY_RUN, default=False): cv.boolean,
    }
)


def _entry(hass: HomeAssistant, entry_id: str | None):
    entries = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.state is ConfigEntryState.LOADED and (entry_id is None or e.entry_id == entry_id)
    ]
    if not entries:
        raise ServiceValidationError("No loaded iCloud Home Address entry matches")
    if len(entries) > 1:
        raise ServiceValidationError("Several iCloud accounts are set up; pass config_entry_id")
    return entries[0]


async def _resolve(hass: HomeAssistant, data: dict) -> dict[str, str]:
    explicit = {f: data[f].strip() for f in ADDRESS_FIELDS if data.get(f)}

    base: dict[str, str] | None = None
    coords = None
    if ATTR_LATITUDE in data:
        coords = (data[ATTR_LATITUDE], data[ATTR_LONGITUDE])
    elif entity_id := data.get(ATTR_ENTITY_ID):
        if (state := hass.states.get(entity_id)) is None:
            raise ServiceValidationError(f"{entity_id} does not exist")
        base = addr.from_attributes(state.attributes)
        if base is None:
            coords = addr.coordinates(state.attributes)
            if coords is None and not explicit:
                raise ServiceValidationError(f"{entity_id} has neither an address nor coordinates")

    if base is None and coords is not None:
        try:
            base = await addr.reverse_geocode(async_get_clientsession(hass), *coords)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HomeAssistantError(f"Reverse geocoding failed: {err}") from err

    address = {f: "" for f in ADDRESS_FIELDS} | (base or {}) | explicit
    # A half-resolved fix (no city or ZIP) would blank the card; refuse it.
    if not (address["city"] and address["postal_code"]):
        raise ServiceValidationError(f"Could not resolve a full address (got {address})")
    return address


def async_setup_services(hass: HomeAssistant) -> None:
    async def set_home_address(call: ServiceCall) -> ServiceResponse:
        entry = _entry(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        address = await _resolve(hass, dict(call.data))
        if call.data[ATTR_DRY_RUN]:
            return {"changed": False, "dry_run": True, "address": address}
        try:
            changed = await entry.runtime_data.set_home_address(entry.data[CONF_CARD_URL], address)
        except AuthError as err:
            entry.async_start_reauth(hass)
            raise HomeAssistantError(str(err)) from err
        except (CardDAVError, aiohttp.ClientError, TimeoutError) as err:
            raise HomeAssistantError(f"Updating the iCloud contact failed: {err}") from err
        return {"changed": changed, "dry_run": False, "address": address}

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_HOME_ADDRESS,
        set_home_address,
        schema=SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
