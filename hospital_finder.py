"""
Hospital Finder Agent
Finds the nearest available ER to the emergency location.
Uses Google Maps Places API (or mock data in demo mode).
"""
import os, asyncio, logging
import httpx

log = logging.getLogger(__name__)

MOCK_HOSPITALS = [
    {"name": "Sawai Man Singh Hospital",   "distance_km": 2.1, "eta_min": 8,  "phone": "+91-141-2560291", "type": "Government"},
    {"name": "Fortis Escorts Hospital",     "distance_km": 3.4, "eta_min": 12, "phone": "+91-141-2547000", "type": "Private"},
    {"name": "Narayana Multispecialty Hosp","distance_km": 4.8, "eta_min": 16, "phone": "+91-141-4266000", "type": "Private"},
]

class HospitalFinderAgent:
    async def run(self, lat: float | None, lon: float | None, address: str | None) -> dict:
        gmap_key = os.getenv("GOOGLE_MAPS_API_KEY")
        if gmap_key and lat and lon:
            try:
                return await self._google_maps_lookup(lat, lon, gmap_key)
            except Exception as e:
                log.warning(f"Google Maps lookup failed: {e}")
        return {
            "nearest": MOCK_HOSPITALS[0],
            "options": MOCK_HOSPITALS,
            "source": "mock",
            "note": "Set GOOGLE_MAPS_API_KEY env var for live lookup",
        }

    async def _google_maps_lookup(self, lat, lon, key) -> dict:
        url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(url, params={
                "location": f"{lat},{lon}",
                "radius": 10000,
                "type": "hospital",
                "keyword": "emergency",
                "key": key,
            })
            data = r.json()
        results = data.get("results", [])[:3]
        hospitals = [
            {"name": h["name"],
             "distance_km": round(h.get("geometry", {}).get("location", {}).get("lat", lat) - lat, 2),
             "address": h.get("vicinity", ""),
             "rating": h.get("rating", 0)}
            for h in results
        ]
        return {"nearest": hospitals[0] if hospitals else None, "options": hospitals, "source": "google"}
