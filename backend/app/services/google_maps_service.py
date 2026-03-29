"""
Google Maps Platform service.

Supports:
  - Geocoding (address → coordinates)
  - Reverse geocoding (coordinates → address)
  - Places search (nearby & text search)
  - Distance matrix
  - Directions

All methods return consistent {success, result, error} dicts.
Gracefully degrades when key is absent.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_BASE = "https://maps.googleapis.com/maps/api"
_TIMEOUT = 15


class GoogleMapsService:
    def __init__(self) -> None:
        self._key: str = settings.google_maps_api_key or os.getenv("GOOGLE_MAPS_API_KEY", "")

    @property
    def available(self) -> bool:
        return bool(self._key)

    def _params(self, extra: Dict[str, Any]) -> Dict[str, Any]:
        return {"key": self._key, **extra}

    # ── Public ────────────────────────────────────────────────────────────────

    async def geocode(self, address: str) -> Dict[str, Any]:
        """Convert address to lat/lng + formatted address."""
        if not self.available:
            return self._no_key("geocode")
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
                r = await c.get(
                    f"{_BASE}/geocode/json",
                    params=self._params({"address": address}),
                )
                r.raise_for_status()
                data = r.json()
            if data.get("status") != "OK" or not data.get("results"):
                return {"success": False, "result": None, "error": data.get("status", "No results")}
            loc = data["results"][0]
            return {
                "success": True,
                "result": {
                    "formatted_address": loc.get("formatted_address"),
                    "lat": loc["geometry"]["location"]["lat"],
                    "lng": loc["geometry"]["location"]["lng"],
                    "place_id": loc.get("place_id"),
                    "types": loc.get("types", []),
                },
                "error": None,
            }
        except Exception as exc:
            return {"success": False, "result": None, "error": str(exc)}

    async def reverse_geocode(self, lat: float, lng: float) -> Dict[str, Any]:
        """Convert lat/lng to address."""
        if not self.available:
            return self._no_key("reverse_geocode")
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
                r = await c.get(
                    f"{_BASE}/geocode/json",
                    params=self._params({"latlng": f"{lat},{lng}"}),
                )
                r.raise_for_status()
                data = r.json()
            if data.get("status") != "OK" or not data.get("results"):
                return {"success": False, "result": None, "error": data.get("status")}
            return {
                "success": True,
                "result": data["results"][0].get("formatted_address"),
                "error": None,
            }
        except Exception as exc:
            return {"success": False, "result": None, "error": str(exc)}

    async def places_search(
        self,
        query: str,
        *,
        location: Optional[Tuple[float, float]] = None,
        radius_m: int = 5000,
        place_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Search for places by text query, optionally near a location."""
        if not self.available:
            return self._no_key("places_search")
        try:
            params: Dict[str, Any] = {"query": query}
            if location:
                params["location"] = f"{location[0]},{location[1]}"
                params["radius"] = radius_m
            if place_type:
                params["type"] = place_type

            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
                r = await c.get(
                    f"{_BASE}/place/textsearch/json",
                    params=self._params(params),
                )
                r.raise_for_status()
                data = r.json()

            places = []
            for p in data.get("results", [])[:10]:
                places.append({
                    "name": p.get("name"),
                    "address": p.get("formatted_address"),
                    "lat": p.get("geometry", {}).get("location", {}).get("lat"),
                    "lng": p.get("geometry", {}).get("location", {}).get("lng"),
                    "rating": p.get("rating"),
                    "types": p.get("types", [])[:3],
                    "place_id": p.get("place_id"),
                    "open_now": p.get("opening_hours", {}).get("open_now"),
                })

            return {"success": True, "result": places, "error": None}
        except Exception as exc:
            return {"success": False, "result": [], "error": str(exc)}

    async def distance_matrix(
        self,
        origins: List[str],
        destinations: List[str],
        *,
        mode: str = "driving",
    ) -> Dict[str, Any]:
        """Compute travel distance and time between origins and destinations."""
        if not self.available:
            return self._no_key("distance_matrix")
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
                r = await c.get(
                    f"{_BASE}/distancematrix/json",
                    params=self._params({
                        "origins": "|".join(origins),
                        "destinations": "|".join(destinations),
                        "mode": mode,
                    }),
                )
                r.raise_for_status()
                data = r.json()

            rows = []
            for row in data.get("rows", []):
                elements = []
                for elem in row.get("elements", []):
                    elements.append({
                        "distance": elem.get("distance", {}).get("text"),
                        "duration": elem.get("duration", {}).get("text"),
                        "status": elem.get("status"),
                    })
                rows.append(elements)

            return {
                "success": True,
                "result": {
                    "origin_addresses": data.get("origin_addresses", []),
                    "destination_addresses": data.get("destination_addresses", []),
                    "rows": rows,
                },
                "error": None,
            }
        except Exception as exc:
            return {"success": False, "result": None, "error": str(exc)}

    async def directions(
        self,
        origin: str,
        destination: str,
        *,
        mode: str = "driving",
        waypoints: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Get turn-by-turn directions."""
        if not self.available:
            return self._no_key("directions")
        try:
            params: Dict[str, Any] = {
                "origin": origin,
                "destination": destination,
                "mode": mode,
            }
            if waypoints:
                params["waypoints"] = "|".join(waypoints)

            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
                r = await c.get(
                    f"{_BASE}/directions/json",
                    params=self._params(params),
                )
                r.raise_for_status()
                data = r.json()

            if not data.get("routes"):
                return {"success": False, "result": None, "error": "No route found"}

            route = data["routes"][0]
            leg = route["legs"][0]

            steps = [
                {
                    "instruction": s.get("html_instructions", "").replace("<b>", "").replace("</b>", ""),
                    "distance": s.get("distance", {}).get("text"),
                    "duration": s.get("duration", {}).get("text"),
                }
                for s in leg.get("steps", [])
            ]

            return {
                "success": True,
                "result": {
                    "summary": route.get("summary"),
                    "total_distance": leg.get("distance", {}).get("text"),
                    "total_duration": leg.get("duration", {}).get("text"),
                    "steps": steps,
                },
                "error": None,
            }
        except Exception as exc:
            return {"success": False, "result": None, "error": str(exc)}

    def _no_key(self, operation: str) -> Dict[str, Any]:
        return {
            "success": False,
            "result": None,
            "error": f"Google Maps API key not configured. Cannot perform {operation}.",
        }


google_maps_service = GoogleMapsService()
