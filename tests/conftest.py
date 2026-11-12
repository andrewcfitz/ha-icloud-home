"""Fixtures: a fake iCloud CardDAV account behind HA's aiohttp mock."""

from __future__ import annotations

import pytest

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.icloud_home.const import (
    CONF_APP_PASSWORD,
    CONF_APPLE_ID,
    CONF_CARD_NAME,
    CONF_CARD_URL,
    DOMAIN,
)

pytest_plugins = "pytest_homeassistant_custom_component"

ROOT = "https://contacts.icloud.com/"
HOST = "https://p01-contacts.icloud.com"
BOOK = f"{HOST}/1/carddav/card/"
ME_URL = f"{BOOK}me.vcf"

ME = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nN:Tester;Pat;;;\r\nFN:Pat Tester\r\n"
    "item1.ADR;type=HOME;type=pref:;;1 Old Rd;Oldtown;TX;75001;United States\r\n"
    "item1.X-ABADR:us\r\n"
    "item2.ADR;type=WORK:;;9 Work St;Worktown;TX;75002;United States\r\n"
    "END:VCARD\r\n"
)
OTHER = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Aaron Other\r\nEND:VCARD\r\n"
GROUP = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Family\r\n"
    "X-ADDRESSBOOKSERVER-KIND:group\r\nEND:VCARD\r\n"
)
CARDS = {ME_URL: ME, f"{BOOK}other.vcf": OTHER, f"{BOOK}group.vcf": GROUP}


def multistatus(*responses: str) -> str:
    return (
        '<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" '
        'xmlns:c="urn:ietf:params:xml:ns:carddav">' + "".join(responses) + "</d:multistatus>"
    )


def mock_icloud(aioclient_mock: AiohttpClientMocker, me: str = ME, auth_ok: bool = True) -> None:
    if not auth_ok:
        aioclient_mock.request("PROPFIND", ROOT, status=401)
        aioclient_mock.get(ME_URL, status=401)
        return
    aioclient_mock.request("PROPFIND", ROOT, status=301, headers={"Location": f"{HOST}/"})
    aioclient_mock.request(
        "PROPFIND",
        f"{HOST}/",
        status=207,
        text=multistatus(
            "<d:response><d:href>/</d:href><d:propstat><d:prop><d:current-user-principal>"
            "<d:href>/1/principal/</d:href></d:current-user-principal></d:prop></d:propstat>"
            "</d:response>"
        ),
    )
    aioclient_mock.request(
        "PROPFIND",
        f"{HOST}/1/principal/",
        status=207,
        text=multistatus(
            "<d:response><d:href>/1/principal/</d:href><d:propstat><d:prop>"
            f"<c:addressbook-home-set><d:href>{HOST}:443/1/carddav/</d:href>"
            "</c:addressbook-home-set></d:prop></d:propstat></d:response>"
        ),
    )
    aioclient_mock.request(
        "PROPFIND",
        f"{HOST}/1/carddav/",
        status=207,
        text=multistatus(
            "<d:response><d:href>/1/carddav/</d:href><d:propstat><d:prop><d:resourcetype>"
            "<d:collection/></d:resourcetype></d:prop></d:propstat></d:response>",
            "<d:response><d:href>/1/carddav/card/</d:href><d:propstat><d:prop><d:resourcetype>"
            "<d:collection/><c:addressbook/></d:resourcetype></d:prop></d:propstat></d:response>",
        ),
    )
    aioclient_mock.request(
        "PROPFIND",
        BOOK,
        status=207,
        text=multistatus(
            "<d:response><d:href>/1/carddav/card/</d:href></d:response>",
            *(
                f"<d:response><d:href>{url.removeprefix(HOST)}</d:href></d:response>"
                for url in CARDS
            ),
        ),
    )
    aioclient_mock.request(
        "REPORT",
        BOOK,
        status=207,
        text=multistatus(
            *(
                f"<d:response><d:href>{url.removeprefix(HOST)}</d:href><d:propstat><d:prop>"
                f"<c:address-data>{card}</c:address-data></d:prop></d:propstat></d:response>"
                for url, card in CARDS.items()
            )
        ),
    )
    aioclient_mock.get(ME_URL, text=me, headers={"ETag": '"e1"'})
    aioclient_mock.put(ME_URL, status=204)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="pat@example.com",
        title="Pat Tester",
        data={
            CONF_APPLE_ID: "pat@example.com",
            CONF_APP_PASSWORD: "abcd-efgh-ijkl-mnop",
            CONF_CARD_URL: ME_URL,
            CONF_CARD_NAME: "Pat Tester",
        },
    )
