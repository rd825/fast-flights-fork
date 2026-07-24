from dataclasses import dataclass
from typing import Literal


@dataclass
class Airline:
    code: str
    name: str


@dataclass
class Alliance:
    code: str
    name: str


@dataclass
class JsMetadata:
    airlines: list[Airline]
    alliances: list[Alliance]


@dataclass
class Airport:
    name: str
    code: str


@dataclass
class SimpleDatetime:
    date: tuple[int, int, int]
    time: tuple[int, int]


@dataclass
class SingleFlight:
    from_airport: Airport
    to_airport: Airport
    departure: SimpleDatetime
    arrival: SimpleDatetime

    duration: int
    """Unit: minutes"""

    plane_type: str

    airline_code: str | None = None
    """Marketing carrier IATA designator, e.g. ``"AC"``."""

    flight_number: str | None = None
    """Bare flight number, e.g. ``"774"`` (no carrier prefix)."""

    airline_name: str | None = None
    """Marketing carrier display name, e.g. ``"Air Canada"``."""


@dataclass
class Layover:
    duration: int
    """Unit: minutes"""

    airport_code: str
    airport_name: str | None = None


@dataclass
class CarbonEmission:
    typical_on_route: int
    """Unit: grams"""

    emission: int
    """Unit: grams"""


@dataclass
class Flights:
    type: str | Literal["multi"]
    price: int
    airlines: list[str]
    flights: list[SingleFlight]
    carbon: CarbonEmission
    layovers: list[Layover] | None = None
    """One entry per connection; ``None`` for nonstops (or when absent)."""
