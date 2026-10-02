"""Offline-first travel providers — swap stubs for live APIs later without UI changes."""

from .amadeus_hotel import AmadeusHotelProvider
from .aviasales_flight import AviasalesFlightProvider
from .astrology import StubAstrologyProvider
from .base import (
    AstrologyProvider,
    BookingProvider,
    CalendarProvider,
    FlightProvider,
    HotelProvider,
    LanguageProvider,
    PhotoProvider,
    ReservationAvailabilityProvider,
    RestaurantProvider,
    SafetyProvider,
    ShoppingProvider,
    StubResult,
    TransitProvider,
    TranslationProvider,
    WeatherProvider,
)
from .booking import StubBookingProvider
from .calendar import StubCalendarProvider
from .flight import StubFlightProvider
from .hotel import StubHotelProvider
from .language import StubLanguageProvider
from .nuitee_hotel import NuiteeHotelProvider
from .open_meteo_weather import OpenMeteoWeatherProvider
from .photo import StubPhotoProvider
from .reservation_availability import StubReservationAvailabilityProvider
from .restaurant import StubRestaurantProvider
from .safety import StubSafetyProvider
from .shopping import StubShoppingProvider
from .state_dept import StateDeptSafetyProvider
from .transit import StubTransitProvider
from .translation import StubTranslationProvider
from .weather import StubWeatherProvider

__all__ = [
    "AmadeusHotelProvider",
    "AviasalesFlightProvider",
    "AstrologyProvider",
    "BookingProvider",
    "CalendarProvider",
    "FlightProvider",
    "HotelProvider",
    "LanguageProvider",
    "NuiteeHotelProvider",
    "OpenMeteoWeatherProvider",
    "PhotoProvider",
    "ReservationAvailabilityProvider",
    "RestaurantProvider",
    "SafetyProvider",
    "ShoppingProvider",
    "StubAstrologyProvider",
    "StubBookingProvider",
    "StubCalendarProvider",
    "StubFlightProvider",
    "StubHotelProvider",
    "StubLanguageProvider",
    "StubPhotoProvider",
    "StubReservationAvailabilityProvider",
    "StubRestaurantProvider",
    "StubResult",
    "StubSafetyProvider",
    "StubShoppingProvider",
    "StubTransitProvider",
    "StubTranslationProvider",
    "StubWeatherProvider",
    "StateDeptSafetyProvider",
    "TransitProvider",
    "TranslationProvider",
    "WeatherProvider",
]
