import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.icloud_home import vcard
from custom_components.icloud_home.const import DOMAIN, NOMINATIM_URL
from custom_components.icloud_home.diagnostics import async_get_config_entry_diagnostics

from .conftest import ME, mock_icloud

GEOCODED = {
    "Sub Thoroughfare": "123",
    "Thoroughfare": "Campground Ln",
    "Locality": "Fredericksburg",
    "Administrative Area": "TX",
    "Postal Code": "78624",
    "Country": "United States",
    "Location": [30.27, -98.87],
}


async def setup(hass, config_entry):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED


def puts(aioclient_mock):
    return [(url, data, headers) for m, url, data, headers in aioclient_mock.mock_calls if m.upper() == "PUT"]


async def call(hass, **data):
    return await hass.services.async_call(
        DOMAIN, "set_home_address", data, blocking=True, return_response=True
    )


async def test_geocoded_sensor_address_is_written(hass: HomeAssistant, aioclient_mock, config_entry):
    mock_icloud(aioclient_mock)
    await setup(hass, config_entry)
    hass.states.async_set("sensor.iphone_geocoded_location", "123 Campground Ln", GEOCODED)

    resp = await call(hass, entity_id="sensor.iphone_geocoded_location")

    assert resp == {
        "changed": True,
        "dry_run": False,
        "address": {
            "street": "123 Campground Ln",
            "city": "Fredericksburg",
            "state": "TX",
            "postal_code": "78624",
            "country": "United States",
        },
    }
    [(url, body, headers)] = puts(aioclient_mock)
    assert url.path == "/1/carddav/card/me.vcf"
    assert headers["If-Match"] == '"e1"'
    assert "123 Campground Ln;Fredericksburg;TX;78624;United States" in vcard.unfold(body.decode())
    assert b"9 Work St" in body
    assert not any(str(u).startswith(NOMINATIM_URL) for _, u, _, _ in aioclient_mock.mock_calls)


async def test_device_tracker_is_reverse_geocoded(hass: HomeAssistant, aioclient_mock, config_entry):
    mock_icloud(aioclient_mock)
    aioclient_mock.get(
        NOMINATIM_URL,
        json={
            "address": {
                "house_number": "500",
                "road": "River Rd",
                "town": "Kerrville",
                "state": "Texas",
                "postcode": "78028",
                "country": "United States",
            }
        },
    )
    await setup(hass, config_entry)
    hass.states.async_set(
        "device_tracker.iphone", "not_home", {"latitude": 30.05, "longitude": -99.14}
    )

    resp = await call(hass, entity_id="device_tracker.iphone", street="Site 12")

    assert resp["address"] == {
        "street": "Site 12",
        "city": "Kerrville",
        "state": "Texas",
        "postal_code": "78028",
        "country": "United States",
    }
    [nominatim] = [c for c in aioclient_mock.mock_calls if str(c[1]).startswith(NOMINATIM_URL)]
    assert nominatim[1].query["lat"] == "30.05"
    assert nominatim[3]["User-Agent"].startswith("ha-icloud-home/")


async def test_unchanged_address_skips_put(hass: HomeAssistant, aioclient_mock, config_entry):
    current = vcard.set_home_address(
        ME, {"street": "1 A St", "city": "X", "state": "TX", "postal_code": "1", "country": ""}
    )
    mock_icloud(aioclient_mock, me=current)
    await setup(hass, config_entry)

    resp = await call(hass, street="1 A St", city="X", state="TX", postal_code="1")
    assert resp["changed"] is False
    assert puts(aioclient_mock) == []


async def test_dry_run_does_not_touch_icloud(hass: HomeAssistant, aioclient_mock, config_entry):
    mock_icloud(aioclient_mock)
    await setup(hass, config_entry)
    resp = await call(hass, city="Austin", postal_code="78701", dry_run=True)
    assert resp["dry_run"] is True
    assert aioclient_mock.call_count == 0


async def test_partial_address_is_refused(hass: HomeAssistant, aioclient_mock, config_entry):
    mock_icloud(aioclient_mock)
    await setup(hass, config_entry)
    hass.states.async_set("sensor.nowhere", "x", {"Locality": "Austin"})
    with pytest.raises(ServiceValidationError):
        await call(hass, entity_id="sensor.nowhere")
    assert puts(aioclient_mock) == []


async def test_auth_failure_starts_reauth(hass: HomeAssistant, aioclient_mock, config_entry):
    mock_icloud(aioclient_mock, auth_ok=False)
    await setup(hass, config_entry)
    with pytest.raises(HomeAssistantError):
        await call(hass, city="Austin", postal_code="78701")
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_diagnostics_redact_credentials(hass: HomeAssistant, aioclient_mock, config_entry):
    mock_icloud(aioclient_mock)
    await setup(hass, config_entry)
    diag = await async_get_config_entry_diagnostics(hass, config_entry)
    assert "abcd" not in str(diag)
    assert "pat@example.com" not in str(diag)
    assert diag["contacts"] == {
        "address_books": 2,
        "address_books_failed": 0,
        "card_urls": 7,
        "cards_fetched": 7,
        "groups": 1,
        "unnamed": 1,
        "listed": 5,
        "selected_card_found": True,
    }
    assert "Pat" not in str(diag)
    assert "carddav" not in str(diag)


async def test_diagnostics_scrub_urls_from_errors(hass: HomeAssistant, aioclient_mock, config_entry):
    mock_icloud(aioclient_mock, auth_ok=False)
    await setup(hass, config_entry)
    diag = await async_get_config_entry_diagnostics(hass, config_entry)
    assert diag["contacts"]["error"].startswith("AuthError")
    assert "icloud.com" not in str(diag)
