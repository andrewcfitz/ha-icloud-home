"""Just enough CardDAV to find a contact on iCloud and rewrite it."""

from __future__ import annotations

import base64
import logging
import re
from urllib.parse import unquote, urljoin, urlsplit
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

import aiohttp

from . import vcard
from .const import ICLOUD_ROOT

_LOGGER = logging.getLogger(__name__)

NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:carddav"}
XMLNS = 'xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav"'
REDIRECTS = (301, 302, 307, 308)
TIMEOUT = aiohttp.ClientTimeout(total=30)
MAX_FALLBACK_GETS = 25


def _path(url: str) -> str:
    return unquote(urlsplit(url).path)


def describe(err: BaseException) -> str:
    """Error text safe to show or share: iCloud URLs embed the account ID."""
    text = re.sub(r"https?://\S+", "<url>", str(err)) or "no details"
    return f"{type(err).__name__}: {text}"


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

    async def discover_addressbooks(self) -> list[str]:
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
        books = [
            urljoin(base, self._href(resp, "d:href"))
            for resp in tree.findall("d:response", NS)
            if resp.find(".//d:resourcetype/c:addressbook", NS) is not None
        ]
        if not books:
            raise CardDAVError("no address book found on the account")
        return books

    async def _card_hrefs(self, book: str) -> list[str]:
        tree, base = await self._xml(
            "PROPFIND",
            book,
            f"<d:propfind {XMLNS}><d:prop><d:getetag/><d:resourcetype/></d:prop></d:propfind>",
            1,
        )
        return [
            url
            for r in tree.findall("d:response", NS)
            if (url := urljoin(base, self._href(r, "d:href"))).rstrip("/") != book.rstrip("/")
            and r.find(".//d:resourcetype/d:collection", NS) is None
        ]

    async def _fetch_cards(self, book: str, urls: list[str]) -> dict[str, str]:
        """Fetch vCards by multiget, falling back to GET for a few it skips."""
        by_path = {_path(u): u for u in urls}
        cards: dict[str, str] = {}
        # Multiget hrefs go back exactly as the server listed them: encoded
        # paths, not absolute URLs.
        paths = [urlsplit(u).path for u in urls]
        for i in range(0, len(paths), 50):
            chunk = "".join(f"<d:href>{xml_escape(p)}</d:href>" for p in paths[i : i + 50])
            tree, _ = await self._xml(
                "REPORT",
                book,
                f"<c:addressbook-multiget {XMLNS}><d:prop><c:address-data/></d:prop>"
                f"{chunk}</c:addressbook-multiget>",
                1,
            )
            for resp in tree.findall("d:response", NS):
                data = resp.find(".//c:address-data", NS)
                url = by_path.get(_path(self._href(resp, "d:href")))
                if url and data is not None and data.text:
                    cards[url] = data.text
        missing = [u for u in urls if u not in cards]
        # A handful of stragglers are worth a GET each; hundreds mean the
        # multiget itself misbehaved, and per-card GETs would stall the flow.
        for url in missing[:MAX_FALLBACK_GETS]:
            try:
                cards[url], _ = await self.get_card(url)
            except (CardDAVError, aiohttp.ClientError, TimeoutError):
                continue
        return cards

    async def list_contacts(self) -> list[tuple[str, str]]:
        """Return (display name, card URL) for every contact, groups excluded."""
        contacts, _ = await self.list_contacts_with_stats()
        return contacts

    async def list_contacts_with_stats(self) -> tuple[list[tuple[str, str]], dict[str, int]]:
        stats = {
            "address_books": 0,
            "address_books_failed": 0,
            "card_urls": 0,
            "cards_fetched": 0,
            "groups": 0,
            "unnamed": 0,
        }
        contacts: list[tuple[str, str]] = []
        last_error: Exception | None = None
        for book in await self.discover_addressbooks():
            stats["address_books"] += 1
            try:
                urls = await self._card_hrefs(book)
                # iCloud's addressbook-query is unreliable, so fetch the cards
                # and read names locally.
                cards = await self._fetch_cards(book, urls)
            except AuthError:
                raise
            except (CardDAVError, aiohttp.ClientError, TimeoutError) as err:
                # One broken (e.g. shared or read-only) book shouldn't hide the rest.
                _LOGGER.warning("Skipping address book %s: %s", book, err)
                stats["address_books_failed"] += 1
                last_error = err
                continue
            stats["card_urls"] += len(urls)
            stats["cards_fetched"] += len(cards)
            for url, data in cards.items():
                if vcard.is_group(data):
                    stats["groups"] += 1
                elif name := vcard.display_name(data):
                    contacts.append((name, url))
                else:
                    stats["unnamed"] += 1
        if last_error is not None and stats["address_books_failed"] == stats["address_books"]:
            raise last_error
        return sorted(contacts, key=lambda c: c[0].lower()), stats

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
