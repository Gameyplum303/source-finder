"""Hardened HTTP fetching for the fixed set of upstream scholarly APIs.

Security notes:
- Callers pass hard-coded HTTPS URLs; user input only ever travels as an
  encoded query-string value, so there is no SSRF surface.
- Redirects are not followed (set on the shared client) and response bodies
  are size-capped while streaming.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

USER_AGENT = "SourceFinder/1.0"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
RETRY_STATUSES = {429, 500, 502, 503, 504}
RETRY_DELAY = 1.5


class UpstreamError(Exception):
    """An upstream API failed; the message is safe to log but not to show."""


def make_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(12.0, connect=5.0),
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        transport=transport,
    )


async def fetch_bytes(client: httpx.AsyncClient, url: str, *,
                      params: dict[str, Any], headers: dict[str, str] | None = None) -> bytes:
    """GET `url`, retrying once after a short pause on rate-limit / transient errors."""
    for attempt in range(2):
        try:
            async with client.stream("GET", url, params=params, headers=headers) as resp:
                if resp.status_code in RETRY_STATUSES and attempt == 0:
                    await asyncio.sleep(RETRY_DELAY)
                    continue
                if resp.status_code != 200:
                    raise UpstreamError(f"{url} returned HTTP {resp.status_code}")
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise UpstreamError(f"{url} response too large")
                return bytes(body)
        except httpx.HTTPError as exc:
            raise UpstreamError(f"{url} request failed: {type(exc).__name__}") from exc
    raise UpstreamError(f"{url} kept failing")  # unreachable: attempt 1 returns or raises


async def fetch_json(client: httpx.AsyncClient, url: str, *,
                     params: dict[str, Any], headers: dict[str, str] | None = None) -> Any:
    body = await fetch_bytes(client, url, params=params, headers=headers)
    try:
        return json.loads(body)
    except ValueError as exc:
        raise UpstreamError(f"{url} returned invalid JSON") from exc
