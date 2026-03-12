from typing import Any

import requests

NOMINATIM_BASE = "https://nominatim.openstreetmap.org/search"

# Nominatim usage policy requires a descriptive User-Agent header
_HEADERS = {"User-Agent": "TravelPlanner/1.0 (travel-planner-app)"}


def search_places(
    query: str,
    city: str | None = None,
    country: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    parts = [p for p in (query, city, country) if p]
    full_query = ", ".join(parts)

    try:
        response = requests.get(
            NOMINATIM_BASE,
            params={
                "q": full_query,
                "format": "json",
                "limit": limit,
                "addressdetails": 1,
            },
            headers=_HEADERS,
            timeout=5,
        )
        response.raise_for_status()
        results = response.json()
    except requests.RequestException:
        return []

    output: list[dict[str, Any]] = []
    for result in results:
        address = result.get("address", {})
        display = result.get("display_name", "")
        name = result.get("name") or display.split(",")[0].strip()
        location = ", ".join(p.strip() for p in display.split(",")[:3])
        output.append(
            {
                "place_id": str(result.get("place_id", "")),
                "name": name,
                "location": location,
                "country": address.get("country", ""),
                "city": (
                    address.get("city")
                    or address.get("town")
                    or address.get("village")
                    or address.get("county", "")
                ),
            }
        )
    return output


def search_place(
    query: str,
    city: str | None = None,
    country: str | None = None,
) -> dict[str, Any]:
    results = search_places(query, city=city, country=country, limit=1)
    return results[0] if results else {}
