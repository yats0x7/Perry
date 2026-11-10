"""Server-side catalog lookups that turn a spoken song name into something the desktop can play.

Spotify's Mac app can play a `spotify:track:…` URI but cannot search, so a `media.search`
step is upgraded to `media.play_track` when Spotify Web API credentials are configured
(client-credentials flow: catalog search only, no access to the user's account). The plan
shown for approval already contains the resolved track, so the user sees exactly what will play.
"""

from __future__ import annotations

import base64
import logging
import time

import httpx

from perry_protocol import DesktopManifest, Plan

log = logging.getLogger("perry.catalog")


class SpotifyCatalog:
    def __init__(self, client_id: str, client_secret: str, market: str = "IN"):
        self.cid, self.secret, self.market = client_id.strip(), client_secret.strip(), market
        self._token: str | None = None
        self._exp = 0.0
        self.http = httpx.AsyncClient(timeout=10)

    @property
    def configured(self) -> bool:
        return bool(self.cid and self.secret)

    async def _bearer(self) -> str:
        if self._token and time.time() < self._exp - 60:
            return self._token
        auth = base64.b64encode(f"{self.cid}:{self.secret}".encode()).decode()
        r = await self.http.post("https://accounts.spotify.com/api/token", data={"grant_type": "client_credentials"},
                                 headers={"Authorization": f"Basic {auth}"})
        r.raise_for_status()
        body = r.json()
        self._token, self._exp = body["access_token"], time.time() + float(body.get("expires_in", 3600))
        return self._token

    async def find_track(self, query: str) -> dict | None:
        r = await self.http.get("https://api.spotify.com/v1/search", headers={"Authorization": f"Bearer {await self._bearer()}"},
                                params={"q": query, "type": "track", "limit": 1, "market": self.market})
        r.raise_for_status()
        items = r.json().get("tracks", {}).get("items", [])
        if not items:
            return None
        t = items[0]
        return {"uri": t["uri"], "name": t["name"], "artists": ", ".join(a["name"] for a in t.get("artists", []))}


async def enrich_plan(plan: Plan, manifest: DesktopManifest, spotify: SpotifyCatalog | None) -> Plan:
    if not spotify or not spotify.configured or not any(t.id == "media.play_track" for t in manifest.tools):
        return plan
    for step in plan.steps:
        if step.tool != "media.search":
            continue
        q = str(step.args.get("query", "")).strip()
        try:
            hit = await spotify.find_track(q)
        except Exception as e:  # noqa: BLE001 — keep the search fallback
            log.warning("Spotify lookup failed for %r: %s", q, e)
            continue
        if hit:
            step.tool = "media.play_track"
            step.args = {"uri": hit["uri"], "label": f"{hit['name']} — {hit['artists']}"[:200]}
            step.reason = f"Play “{hit['name']}” by {hit['artists']} on Spotify"
    return plan
