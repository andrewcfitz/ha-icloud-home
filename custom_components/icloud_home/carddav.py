"""Just enough CardDAV to find a contact on iCloud and rewrite it."""

from __future__ import annotations

import base64
from urllib.parse import urljoin
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

import aiohttp

from . import vcard
from .const import ICLOUD_ROOT

NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:carddav"}
XMLNS = 'xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav"'
REDIRECTS = (301, 302, 307, 308)
TIMEOUT = aiohttp.ClientTimeout(total=30)


class CardDAVError(Exception):
    """Talking to the CardDAV server failed."""


class AuthError(CardDAVError):
    """The server rejected the Apple ID or app-specific password."""


class CardDAVClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        user: str,
        password: str,
        root: str = ICLOUD_ROOT,
    ) -> None:
        self._session = session
        self._root = root
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self._auth = f"Basic {token}"

    async def _request(
        self,
        method: str,
        url: str,
        body: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[bytes, dict[str, str], str]:
        hdrs = {"Authorization": self._auth, **(headers or {})}
        # Redirects are followed by hand: iCloud bounces to a per-account
        # pNN-contacts host, and aiohttp drops Authorization across hosts.
        for _ in range(5):
            resp = await self._session.request(
                method,
                url,
                data=body.encode() if body is not None else None,
                headers=hdrs,
                allow_redirects=False,
                timeout=TIMEOUT,
            )
            try:
                if resp.status in REDIRECTS and "Location" in resp.headers:
                    url = urljoin(url, resp.headers["Location"])
                    continue
                if resp.status == 401:
                    raise AuthError("iCloud rejected the Apple ID or app-specific password")
                if resp.status == 412:
                    raise CardDAVError("contact changed on the server mid-update; try again")
                if resp.status >= 400:
                    raise CardDAVError(f"{method} {url} returned HTTP {resp.status}")
                return await resp.read(), dict(resp.headers), url
            finally:
                resp.release()
        raise CardDAVError(f"too many redirects for {url}")

    async def _xml(self, method: str, url: str, body: str, depth: int) -> tuple[ET.Element, str]:
        raw, _, final = await self._request(
            method,
            url,
            body,
            {"Depth": str(depth), "Content-Type": "application/xml; charset=utf-8"},
        )
        try:
            return ET.fromstring(raw), final
        except ET.ParseError as err:
            raise CardDAVError(f"unreadable response from {final}") from err

    @staticmethod
    def _href(tree: ET.Element, path: str) -> str:
        node = tree.find(path, NS)
        if node is None or not node.text:
            raise CardDAVError(f"server response is missing {path}")
        return node.text

    async def discover_addressbook(self) -> str:
        tree, base = await self._xml(
            "PROPFIND",
            self._root,
            f"<d:propfind {XMLNS}><d:prop><d:current-user-principal/></d:prop></d:propfind>",
            0,
        )
        principal = urljoin(base, self._href(tree, ".//d:current-user-principal/d:href"))

        tree, base = await self._xml(
            "PROPFIND",
            principal,
            f"<d:propfind {XMLNS}><d:prop><c:addressbook-home-set/></d:prop></d:propfind>",
            0,
        )
        home = urljoin(base, self._href(tree, ".//c:addressbook-home-set/d:href"))

        tree, base = await self._xml(
            "PROPFIND",
            home,
            f"<d:propfind {XMLNS}><d:prop><d:resourcetype/></d:prop></d:propfind>",
            1,
        )
        for resp in tree.findall("d:response", NS):
            if resp.find(".//d:resourcetype/c:addressbook", NS) is not None:
                return urljoin(base, self._href(resp, "d:href"))
        raise CardDAVError("no address book found on the account")

    async def list_contacts(self) -> list[tuple[str, str]]:
        """Return (full name, card URL) for every contact, groups excluded."""
        book = await self.discover_addressbook()
        tree, base = await self._xml(
            "PROPFIND",
            book,
            f"<d:propfind {XMLNS}><d:prop><d:getetag/></d:prop></d:propfind>",
            1,
        )
        hrefs = [
            h
            for h in (self._href(r, "d:href") for r in tree.findall("d:response", NS))
            if urljoin(base, h).rstrip("/") != book.rstrip("/")
        ]

        # iCloud's addressbook-query is unreliable, so fetch the cards and
        # read FN locally.
        contacts: list[tuple[str, str]] = []
        for i in range(0, len(hrefs), 100):
            chunk = "".join(f"<d:href>{xml_escape(h)}</d:href>" for h in hrefs[i : i + 100])
            tree, mbase = await self._xml(
                "REPORT",
                book,
                f"<c:addressbook-multiget {XMLNS}><d:prop><c:address-data/></d:prop>"
                f"{chunk}</c:addressbook-multiget>",
                1,
            )
            for resp in tree.findall("d:response", NS):
                data = resp.find(".//c:address-data", NS)
                if data is None or not data.text or vcard.is_group(data.text):
                    continue
                if name := vcard.full_name(data.text):
                    contacts.append((name, urljoin(mbase, self._href(resp, "d:href"))))
        return sorted(contacts, key=lambda c: c[0].lower())

    async def get_card(self, url: str) -> tuple[str, str | None]:
        raw, headers, _ = await self._request("GET", url)
        etag = next((v for k, v in headers.items() if k.lower() == "etag"), None)
        return raw.decode("utf-8"), etag

    async def set_home_address(self, url: str, address: dict[str, str]) -> bool:
        """Write the HOME address. Returns False when it was already current."""
        old, etag = await self.get_card(url)
        new = vcard.set_home_address(old, address)
        if vcard.same(old, new):
            return False
        headers = {"Content-Type": "text/vcard; charset=utf-8"}
        if etag:
            headers["If-Match"] = etag
        await self._request("PUT", url, new, headers)
        return True
