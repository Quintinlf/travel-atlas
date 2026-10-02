"""Weather — climate normals offline; Open-Meteo forecast when network allowed."""

from __future__ import annotations

from datetime import date
from typing import Any

from .base import StubResult
from .open_meteo_weather import OpenMeteoWeatherProvider


class StubWeatherProvider:
    key = "weather-stub-v1"

    def __init__(
        self,
        climate_service: Any | None = None,
        *,
        open_meteo: OpenMeteoWeatherProvider | None = None,
        allow_network: bool = False,
    ) -> None:
        self.climate_service = climate_service
        self.open_meteo = open_meteo or OpenMeteoWeatherProvider()
        self.allow_network = allow_network

    def forecast(
        self, *, latitude: float, longitude: float, on_date: str | None = None
    ) -> StubResult:
        if self.allow_network and on_date:
            try:
                target = date.fromisoformat(on_date)
            except ValueError:
                target = None
            if target is not None:
                live = self.open_meteo.forecast_range(
                    latitude=latitude,
                    longitude=longitude,
                    start=target,
                    end=target,
                )
                by_date = dict((live.payload or {}).get("by_date") or {})
                cloud = by_date.get(on_date)
                if live.status == "ok" and cloud is not None:
                    return StubResult(
                        provider=self.open_meteo.key,
                        status="ok",
                        payload={
                            "summary": f"Forecast cloud cover ~{cloud:.0f}% on {on_date}.",
                            "cloud_cover_pct": cloud,
                            "on_date": on_date,
                        },
                    )

        payload: dict[str, Any] = {
            "summary": "Live weather unavailable offline — use packing for the season.",
            "on_date": on_date,
        }
        if self.climate_service and (latitude or longitude):
            try:
                months = self.climate_service.get_normals(
                    latitude, longitude, allow_network=False
                )
                if months and on_date:
                    month = int(on_date[5:7])
                    m = next((x for x in months if x.month == month), None)
                    if m:
                        payload = {
                            "summary": (
                                f"Typical {m.name}: high ~{m.avg_high_c:.0f}°C, "
                                f"rain ~{m.rain_mm:.0f} mm (climate normals)."
                            ),
                            "avg_high_c": m.avg_high_c,
                            "rain_mm": m.rain_mm,
                            "on_date": on_date,
                        }
                        return StubResult(
                            provider=self.key, status="stub", payload=payload
                        )
            except Exception:
                pass
        return StubResult(provider=self.key, status="stub", payload=payload)
