"""Diagnostics with credentials redacted."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_APP_PASSWORD, CONF_APPLE_ID, CONF_CARD_URL

TO_REDACT = {CONF_APP_PASSWORD, CONF_APPLE_ID, CONF_CARD_URL}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    return {"entry": async_redact_data(dict(entry.data), TO_REDACT)}
