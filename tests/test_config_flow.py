from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.icloud_home.const import (
    CONF_APP_PASSWORD,
    CONF_APPLE_ID,
    CONF_CARD_NAME,
    CONF_CARD_URL,
    DOMAIN,
)

from .conftest import mock_icloud

CREDS = {CONF_APPLE_ID: " Pat@Example.com ", CONF_APP_PASSWORD: "abcd-efgh-ijkl-mnop"}


async def test_user_flow_asks_for_credentials_then_card(hass: HomeAssistant, aioclient_mock):
    mock_icloud(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert set(result["data_schema"].schema) == {CONF_APPLE_ID, CONF_APP_PASSWORD}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["step_id"] == "card"
    options = result["data_schema"].schema[CONF_CARD_URL].config["options"]
    # Second address book, N-only and ORG-only cards, and a card the multiget
    # skipped all make the list; groups and nameless cards don't.
    assert [o["label"] for o in options] == [
        "Aaron Other",
        "Acme RV Park",
        "Jo Smith",
        "Pat Tester",
        "Zed Skipped",
    ]

    # iCloud's addressbook-home-set carries an explicit :443, so the stored
    # URL is whatever the server handed back, not ME_URL verbatim.
    me = next(o["value"] for o in options if o["label"] == "Pat Tester")
    assert me.endswith("/1/carddav/card/me.vcf")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CARD_URL: me}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Pat Tester"
    assert result["data"] == {
        CONF_APPLE_ID: "Pat@Example.com",
        CONF_APP_PASSWORD: "abcd-efgh-ijkl-mnop",
        CONF_CARD_URL: me,
        CONF_CARD_NAME: "Pat Tester",
    }
    assert result["result"].unique_id == "pat@example.com"

    # Credentials go out as Basic auth on every request, never in the URL.
    assert all(h and h["Authorization"].startswith("Basic ") for _, _, _, h in aioclient_mock.mock_calls)
    assert not any("abcd" in str(url) for _, url, _, _ in aioclient_mock.mock_calls)


async def test_user_flow_bad_password(hass: HomeAssistant, aioclient_mock):
    mock_icloud(aioclient_mock, auth_ok=False)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_duplicate_apple_id_aborts(hass: HomeAssistant, aioclient_mock, config_entry):
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_password(hass: HomeAssistant, aioclient_mock, config_entry):
    config_entry.add_to_hass(hass)
    mock_icloud(aioclient_mock)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_APP_PASSWORD: "new1-new2-new3-new4"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_APP_PASSWORD] == "new1-new2-new3-new4"
