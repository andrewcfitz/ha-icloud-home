"""Diagnostics with credentials redacted."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .carddav import describe
from .const import CONF_APP_PASSWORD, CONF_APPLE_ID, CONF_CARD_NAME, CONF_CARD_URL

TO_REDACT = {CONF_APP_PASSWORD, CONF_APPLE_ID, CONF_CARD_NAME, CONF_CARD_URL}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    # Counts only: no names or card URLs leave the box.
    try:
        contacts, stats = await entry.runtime_data.list_contacts_with_stats()
        listing: dict[str, Any] = {**stats, "listed": len(contacts)}
        listing["selected_card_found"] = entry.data[CONF_CARD_URL] in {u for _, u in contacts}
    except Exception as err:  # noqa: BLE001 - diagnostics should report, not raise
        listing = {"error": describe(err)}
    return {"entry": async_redact_data(dict(entry.data), TO_REDACT), "contacts": listing}
