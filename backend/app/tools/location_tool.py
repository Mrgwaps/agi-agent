"""
LocationTool — Google Maps geocoding, places, directions, and distance.

Routes all operations through google_maps_service which handles
API key management and error handling gracefully.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class LocationTool(BaseTool):
    name = "location"
    description = (
        "Access Google Maps data: geocode addresses to coordinates, search for nearby "
        "places, get turn-by-turn directions, and calculate travel distances. "
        "Use for any task involving maps, locations, navigation, or place discovery."
    )
    requires_approval = False
    schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["geocode", "reverse_geocode", "places_search", "directions", "distance_matrix"],
                "description": "Which Maps operation to perform",
            },
            "address": {
                "type": "string",
                "description": "Address to geocode (for geocode operation)",
            },
            "lat": {
                "type": "number",
                "description": "Latitude (for reverse_geocode)",
            },
            "lng": {
                "type": "number",
                "description": "Longitude (for reverse_geocode)",
            },
            "query": {
                "type": "string",
                "description": "Text search query (for places_search)",
            },
            "origin": {
                "type": "string",
                "description": "Starting point address or coordinates (for directions/distance)",
            },
            "destination": {
                "type": "string",
                "description": "Ending point address or coordinates (for directions/distance)",
            },
            "mode": {
                "type": "string",
                "enum": ["driving", "walking", "bicycling", "transit"],
                "description": "Travel mode (default: driving)",
                "default": "driving",
            },
            "radius_m": {
                "type": "integer",
                "description": "Search radius in meters for places_search (default 5000)",
                "default": 5000,
            },
        },
        "required": ["operation"],
    }

    async def execute(self, input: Dict[str, Any], task_id: str) -> Dict[str, Any]:
        from app.services.google_maps_service import google_maps_service

        operation: str = input.get("operation", "geocode")

        if operation == "geocode":
            address = input.get("address", "")
            if not address:
                return {"success": False, "result": None, "error": "address is required for geocode"}
            result = await google_maps_service.geocode(address)

        elif operation == "reverse_geocode":
            lat = input.get("lat")
            lng = input.get("lng")
            if lat is None or lng is None:
                return {"success": False, "result": None, "error": "lat and lng required for reverse_geocode"}
            result = await google_maps_service.reverse_geocode(float(lat), float(lng))

        elif operation == "places_search":
            query = input.get("query", "")
            if not query:
                return {"success": False, "result": None, "error": "query is required for places_search"}
            lat = input.get("lat")
            lng = input.get("lng")
            location = (float(lat), float(lng)) if lat is not None and lng is not None else None
            result = await google_maps_service.places_search(
                query,
                location=location,
                radius_m=int(input.get("radius_m", 5000)),
            )

        elif operation == "directions":
            origin = input.get("origin", "")
            destination = input.get("destination", "")
            if not origin or not destination:
                return {"success": False, "result": None, "error": "origin and destination required"}
            result = await google_maps_service.directions(
                origin, destination, mode=input.get("mode", "driving")
            )

        elif operation == "distance_matrix":
            origin = input.get("origin", "")
            destination = input.get("destination", "")
            if not origin or not destination:
                return {"success": False, "result": None, "error": "origin and destination required"}
            result = await google_maps_service.distance_matrix(
                [origin], [destination], mode=input.get("mode", "driving")
            )

        else:
            return {"success": False, "result": None, "error": f"Unknown operation: {operation}"}

        if result["success"]:
            import json
            return {
                "success": True,
                "result": json.dumps(result["result"], indent=2) if not isinstance(result["result"], str) else result["result"],
                "error": None,
            }

        return result
