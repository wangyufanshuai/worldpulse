from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import ipaddress
import json
import os
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

from fastapi import HTTPException
import requests

from app.services.consistency.hashing import stable_hash


MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_ENTRIES = 500
MAX_ENTRY_CHARS = 200_000
ALLOWED_MIME = {
    "application/rss+xml", "application/atom+xml", "application/feed+json",
    "application/json", "application/xml", "text/xml",
}


@dataclass(frozen=True)
class FeedFetchResult:
    status_code: int
    content: bytes
    content_type: str
    etag: str | None
    last_modified: str | None
    final_url: str


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style", "iframe", "object"}:
            self.ignored += 1
        elif tag.lower() in {"p", "br", "div", "li", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "iframe", "object"} and self.ignored:
            self.ignored -= 1

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.parts.append(data)


def continuous_intelligence_enabled() -> bool:
    return os.getenv("WORLDPULSE_CONTINUOUS_INTELLIGENCE", "0").strip().lower() in {"1", "true", "yes", "on"}


def validate_remote_url(url: str, *, resolve_dns: bool = False, webhook: bool = False) -> str:
    parsed = urlparse(url.strip())
    allow_http = os.getenv("WORLDPULSE_FEED_ALLOW_HTTP", "0").strip().lower() in {"1", "true", "yes", "on"}
    if parsed.scheme not in ({"https", "http"} if allow_http and not webhook else {"https"}):
        raise HTTPException(status_code=422, detail="External endpoints must use HTTPS")
    if parsed.username or parsed.password or not parsed.hostname:
        raise HTTPException(status_code=422, detail="External endpoint cannot contain credentials")
    if parsed.port not in {None, 443} and not (allow_http and parsed.scheme == "http" and parsed.port in {None, 80}):
        raise HTTPException(status_code=422, detail="External endpoint port is not allowed")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise HTTPException(status_code=422, detail="Private or local endpoints are prohibited")
    try:
        address = ipaddress.ip_address(host)
        _require_public_ip(address)
    except ValueError:
        if resolve_dns:
            try:
                addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)}
            except OSError as exc:
                raise HTTPException(status_code=422, detail="External endpoint DNS resolution failed") from exc
            if not addresses:
                raise HTTPException(status_code=422, detail="External endpoint DNS resolution returned no addresses")
            for value in addresses:
                _require_public_ip(ipaddress.ip_address(value))
    if webhook:
        allowed = {item.strip().lower() for item in os.getenv("WORLDPULSE_WEBHOOK_HOST_ALLOWLIST", "").split(",") if item.strip()}
        environment = os.getenv("WORLDPULSE_ENV", "development").strip().lower()
        if environment == "production" and not allowed:
            raise HTTPException(status_code=422, detail="Production webhook host allowlist is required")
        if allowed and host not in allowed:
            raise HTTPException(status_code=422, detail="Webhook host is not allowlisted")
    return url.strip()


def fetch_feed(url: str, *, etag: str | None = None, last_modified: str | None = None) -> FeedFetchResult:
    if not continuous_intelligence_enabled():
        raise HTTPException(status_code=409, detail="Continuous intelligence network access is disabled")
    current = validate_remote_url(url, resolve_dns=True)
    headers = {"Accept": ", ".join(sorted(ALLOWED_MIME)), "User-Agent": "WorldPulse/1.10 feed-monitor"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    session = requests.Session()
    session.trust_env = False
    try:
        for _ in range(4):
            response = session.get(current, headers=headers, timeout=(5, 20), stream=True, allow_redirects=False)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise HTTPException(status_code=422, detail="Feed redirect is missing a location")
                current = validate_remote_url(urljoin(current, location), resolve_dns=True)
                continue
            if response.status_code == 304:
                return FeedFetchResult(304, b"", "", response.headers.get("ETag"), response.headers.get("Last-Modified"), current)
            if response.status_code < 200 or response.status_code >= 300:
                raise HTTPException(status_code=422, detail=f"Feed returned HTTP {response.status_code}")
            media = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if media not in ALLOWED_MIME:
                raise HTTPException(status_code=422, detail="Feed media type is not supported")
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_RESPONSE_BYTES:
                raise HTTPException(status_code=422, detail="Feed response exceeds the 5 MB limit")
            chunks: list[bytes] = []; size = 0
            for chunk in response.iter_content(64 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise HTTPException(status_code=422, detail="Feed response exceeds the 5 MB limit")
                chunks.append(chunk)
            return FeedFetchResult(response.status_code, b"".join(chunks), media, response.headers.get("ETag"), response.headers.get("Last-Modified"), current)
        raise HTTPException(status_code=422, detail="Feed exceeded the redirect limit")
    finally:
        session.close()


def parse_feed(content: bytes, source_type: str, *, cutoff_at: str) -> list[dict[str, Any]]:
    if not content:
        return []
    if source_type == "json_feed":
        return _parse_json_feed(content, cutoff_at)
    if source_type == "rss_atom":
        return _parse_xml_feed(content, cutoff_at)
    raise HTTPException(status_code=422, detail="Unsupported monitoring source type")


def render_entry_markdown(entry: dict[str, Any], *, publisher: str, source_url: str) -> str:
    return (
        f"# {entry['title']}\n\n"
        f"- Publisher: {publisher}\n"
        f"- Source: {source_url}\n"
        f"- Canonical URL: {entry.get('canonical_url') or source_url}\n"
        f"- Published: {entry['published_at']}\n"
        f"- Entry ID: {entry['stable_key']}\n\n"
        "## Untrusted source text\n\n"
        f"{entry['text']}\n"
    )


def _parse_json_feed(content: bytes, cutoff_at: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="JSON Feed is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise HTTPException(status_code=422, detail="JSON Feed requires an items array")
    items = []
    for raw in payload["items"][:MAX_ENTRIES]:
        if not isinstance(raw, dict):
            continue
        text = raw.get("content_text") or _plain_text(str(raw.get("content_html") or raw.get("summary") or ""))
        items.append(_entry(
            stable=str(raw.get("id") or raw.get("url") or ""), title=str(raw.get("title") or "Untitled feed entry"),
            url=str(raw.get("url") or raw.get("external_url") or ""), text=str(text),
            published=str(raw.get("date_published") or raw.get("date_modified") or cutoff_at), cutoff_at=cutoff_at,
        ))
    return _unique(items)


def _parse_xml_feed(content: bytes, cutoff_at: str) -> list[dict[str, Any]]:
    upper = content[:2000].upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise HTTPException(status_code=422, detail="XML external entities and document types are prohibited")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise HTTPException(status_code=422, detail="RSS/Atom feed is malformed") from exc
    local = _local(root.tag)
    results: list[dict[str, Any]] = []
    if local == "rss" or root.find("channel") is not None:
        channel_node = root.find("channel")
        channel = channel_node if channel_node is not None else root
        for item in channel.findall("item")[:MAX_ENTRIES]:
            link = _child_text(item, "link")
            results.append(_entry(
                stable=_child_text(item, "guid") or link, title=_child_text(item, "title") or "Untitled feed entry",
                url=link, text=_plain_text(_child_text(item, "description") or _child_text(item, "content")),
                published=_child_text(item, "pubDate") or cutoff_at, cutoff_at=cutoff_at,
            ))
    elif local == "feed":
        for item in [node for node in list(root) if _local(node.tag) == "entry"][:MAX_ENTRIES]:
            link = ""
            for child in list(item):
                if _local(child.tag) == "link" and (child.attrib.get("rel", "alternate") == "alternate"):
                    link = child.attrib.get("href", ""); break
            results.append(_entry(
                stable=_child_text(item, "id") or link, title=_child_text(item, "title") or "Untitled feed entry",
                url=link, text=_plain_text(_child_text(item, "content") or _child_text(item, "summary")),
                published=_child_text(item, "published") or _child_text(item, "updated") or cutoff_at, cutoff_at=cutoff_at,
            ))
    else:
        raise HTTPException(status_code=422, detail="XML is neither RSS nor Atom")
    return _unique(results)


def _entry(*, stable: str, title: str, url: str, text: str, published: str, cutoff_at: str) -> dict[str, Any]:
    clean_title = _clean(title, 300) or "Untitled feed entry"
    clean_text = _clean(text, MAX_ENTRY_CHARS)
    published_at = _parse_time(published, cutoff_at)
    cutoff = datetime.fromisoformat(cutoff_at.replace("Z", "+00:00"))
    if datetime.fromisoformat(published_at.replace("Z", "+00:00")) > cutoff:
        raise HTTPException(status_code=422, detail="Feed entry contains future data beyond the poll cutoff")
    stable_key = stable.strip() or stable_hash({"title": clean_title, "published_at": published_at})
    core = {"stable_key": stable_key, "title": clean_title, "canonical_url": url.strip(), "published_at": published_at, "text": clean_text}
    return {**core, "content_hash": stable_hash(core)}


def _parse_time(value: str, fallback: str) -> str:
    try:
        parsed = parsedate_to_datetime(value) if "," in value else datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    except (TypeError, ValueError, OverflowError):
        return fallback


def _plain_text(value: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(value)
        return " ".join("".join(parser.parts).split())
    except Exception:
        return re.sub(r"<[^>]+>", " ", value)


def _clean(value: str, limit: int) -> str:
    return " ".join(value.replace("\x00", " ").split())[:limit]


def _child_text(element: ET.Element, local_name: str) -> str:
    local_name = local_name.lower()
    for child in element.iter():
        if child is not element and _local(child.tag) == local_name:
            return "".join(child.itertext()).strip()
    return ""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _unique(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        unique[(item["stable_key"], item["content_hash"])] = item
    return sorted(unique.values(), key=lambda item: (item["published_at"], item["stable_key"]))[:MAX_ENTRIES]


def _require_public_ip(address: ipaddress._BaseAddress) -> None:
    if not address.is_global or address.is_private or address.is_loopback or address.is_link_local or address.is_multicast or address.is_reserved:
        raise HTTPException(status_code=422, detail="Private, local or reserved endpoints are prohibited")
