"""NWS api.weather.gov client: active alerts (Small Craft Advisory, marine warnings).

Alerts are fetched live, never cached — they're cheap and must be fresh.
NWS requires a User-Agent identifying the application.
"""
import httpx

ALERTS_URL = "https://api.weather.gov/alerts/active"
HEADERS = {
    "User-Agent": "sailready.ai (ken.e.holden@gmail.com)",
    "Accept": "application/geo+json",
}


async def fetch_active_alerts(lat: float, lon: float) -> list[dict]:
    params = {"point": f"{lat:.4f},{lon:.4f}"}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(ALERTS_URL, params=params, headers=HEADERS)
        resp.raise_for_status()
    features = resp.json().get("features", [])
    alerts = []
    for f in features:
        p = f.get("properties", {})
        alerts.append(
            {
                "event": p.get("event"),
                "severity": p.get("severity"),
                "urgency": p.get("urgency"),
                "headline": p.get("headline"),
                "onset": p.get("onset"),
                "ends": p.get("ends"),
                "area": p.get("areaDesc"),
            }
        )
    return alerts
