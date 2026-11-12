"""iCloud Home Address: keep the Home address on an iCloud contact current."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .carddav import CardDAVClient
from .const import CONF_APP_PASSWORD, CONF_APPLE_ID, DOMAIN
from .services import async_setup_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type ICloudHomeConfigEntry = ConfigEntry[CardDAVClient]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ICloudHomeConfigEntry) -> bool:
    entry.runtime_data = CardDAVClient(
        async_get_clientsession(hass),
        entry.data[CONF_APPLE_ID],
        entry.data[CONF_APP_PASSWORD],
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ICloudHomeConfigEntry) -> bool:
    return True
