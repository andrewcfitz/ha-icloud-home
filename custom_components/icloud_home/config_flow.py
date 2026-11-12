"""Config flow: Apple ID + app-specific password, then pick your contact card."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .carddav import AuthError, CardDAVClient, CardDAVError
from .const import CONF_APP_PASSWORD, CONF_APPLE_ID, CONF_CARD_NAME, CONF_CARD_URL, DOMAIN

PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


class ICloudHomeConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._credentials: dict[str, str] = {}
        self._contacts: list[tuple[str, str]] = []

    def _client(self, data: Mapping[str, Any]) -> CardDAVClient:
        return CardDAVClient(
            async_get_clientsession(self.hass), data[CONF_APPLE_ID], data[CONF_APP_PASSWORD]
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_APPLE_ID] = user_input[CONF_APPLE_ID].strip()
            await self.async_set_unique_id(user_input[CONF_APPLE_ID].lower())
            self._abort_if_unique_id_configured()
            try:
                contacts = await self._client(user_input).list_contacts()
            except AuthError:
                errors["base"] = "invalid_auth"
            except (CardDAVError, aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            else:
                if contacts:
                    self._credentials, self._contacts = user_input, contacts
                    return await self.async_step_card()
                errors["base"] = "no_contacts"

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {vol.Required(CONF_APPLE_ID): str, vol.Required(CONF_APP_PASSWORD): PASSWORD}
                ),
                user_input,
            ),
            errors=errors,
        )

    async def async_step_card(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        names = {url: name for name, url in self._contacts}
        if user_input is not None:
            url = user_input[CONF_CARD_URL]
            return self.async_create_entry(
                title=names[url],
                data={**self._credentials, CONF_CARD_URL: url, CONF_CARD_NAME: names[url]},
            )

        options = [SelectOptionDict(value=url, label=name) for name, url in self._contacts]
        return self.async_show_form(
            step_id="card",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CARD_URL): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
                    )
                }
            ),
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, CONF_APP_PASSWORD: user_input[CONF_APP_PASSWORD]}
            try:
                await self._client(data).get_card(entry.data[CONF_CARD_URL])
            except AuthError:
                errors["base"] = "invalid_auth"
            except (CardDAVError, aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_APP_PASSWORD): PASSWORD}),
            description_placeholders={CONF_APPLE_ID: entry.data[CONF_APPLE_ID]},
            errors=errors,
        )
