# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownArgumentType=false

import json

from selectolax.lexbor import LexborHTMLParser

from .exceptions import FlightsNotFound
from .model import (
    Airline,
    Airport,
    Alliance,
    CarbonEmission,
    Flights,
    JsMetadata,
    Layover,
    SimpleDatetime,
    SingleFlight,
)


def _safe_index(seq, *path):
    """Walk nested list indices, returning None on any miss instead of raising.

    Google occasionally omits trailing/optional entries, so enrichment fields
    must degrade to None rather than kill the whole parse."""
    cur = seq
    for i in path:
        if not isinstance(cur, list) or len(cur) <= i:
            return None
        cur = cur[i]
    return cur


class ResultList(list[Flights]):
    """Searched flights list, with metadata attached."""

    metadata: JsMetadata


def _build_single_flight(single_flight) -> SingleFlight:
    """One segment array -> SingleFlight. The segment schema is identical in
    the embedded ds:1 payload and the FlightsFrontendService RPC response, so
    both paths share this."""
    from_airport = Airport(code=single_flight[3], name=single_flight[4])
    to_airport = Airport(code=single_flight[6], name=single_flight[5])
    departure = SimpleDatetime(date=single_flight[20], time=single_flight[8])
    arrival = SimpleDatetime(date=single_flight[21], time=single_flight[10])

    # Marketing carrier + flight number live in a small sub-array:
    # [22] = [carrier_code, flight_number, ?, carrier_display_name]
    # e.g. ['AC', '774', None, 'Air Canada']. Optional — degrade to
    # None so shape drift never kills the parse.
    carrier = _safe_index(single_flight, 22) or []
    airline_code = _safe_index(carrier, 0)
    flight_number = _safe_index(carrier, 1)
    airline_name = _safe_index(carrier, 3)

    return SingleFlight(
        from_airport=from_airport,
        to_airport=to_airport,
        departure=departure,
        arrival=arrival,
        duration=single_flight[11],
        plane_type=single_flight[17],
        airline_code=airline_code if isinstance(airline_code, str) else None,
        flight_number=flight_number if isinstance(flight_number, str) else None,
        airline_name=airline_name if isinstance(airline_name, str) else None,
    )


def build_flights(flight, price) -> Flights:
    """A flight detail array (``k[0]`` in ds:1, ``row[0]`` in the RPC) + its
    price -> a ``Flights`` itinerary. Shared by the HTML and RPC parsers.

    ``price`` may be ``None`` (the RPC omits an aggregate price for some
    premium-cabin rows); callers decide how to treat that."""
    sg_flights = [_build_single_flight(sf) for sf in flight[2]]

    extras = _safe_index(flight, 22) or []
    carbon = CarbonEmission(
        typical_on_route=_safe_index(extras, 8),
        emission=_safe_index(extras, 7),
    )

    # Layovers: flight[13] is a list of
    # [duration_min, airport_code, airport_code, ?, airport_name, ...]
    # (one per connection), or None for nonstops.
    layovers = None
    raw_layovers = _safe_index(flight, 13)
    if isinstance(raw_layovers, list):
        layovers = []
        for lv in raw_layovers:
            duration_min = _safe_index(lv, 0)
            code = _safe_index(lv, 1)
            name = _safe_index(lv, 4)
            if isinstance(duration_min, int) and isinstance(code, str):
                layovers.append(
                    Layover(
                        duration=duration_min,
                        airport_code=code,
                        airport_name=name if isinstance(name, str) else None,
                    )
                )

    return Flights(
        type=flight[0],
        price=price,
        airlines=flight[1],
        flights=sg_flights,
        carbon=carbon,
        layovers=layovers,
    )


def parse(html: str) -> ResultList:
    parser = LexborHTMLParser(html)

    # find js
    script = parser.css_first(r"script.ds\:1")
    return parse_js(script.text())


# Data discovery by @kftang, huge shout out!
def parse_js(js: str):
    data = js.split("data:", 1)[1].rsplit(",", 1)[0]

    if data.endswith("errorHasStatus: true"):
        raise FlightsNotFound("no flights found; received error")

    payload = json.loads(data)

    alliances = []
    airlines = []

    # No-service routes ship a truncated payload with no airline/alliance
    # metadata (and no itineraries) — treat that as an empty result, not a
    # crash (see docs/ds1-schema.md, "Known shape variants").
    (alliances_data, airlines_data) = (
        _safe_index(payload, 7, 1, 0) or [],
        _safe_index(payload, 7, 1, 1) or [],
    )

    for code, name in alliances_data:
        alliances.append(Alliance(code=code, name=name))

    for code, name in airlines_data:
        airlines.append(Airline(code=code, name=name))

    meta = JsMetadata(alliances=alliances, airlines=airlines)

    flights = ResultList()
    if _safe_index(payload, 3, 0) is None:
        flights.metadata = meta
        return flights

    for k in payload[3][0]:
        flights.append(build_flights(k[0], k[1][0][1]))

    flights.metadata = meta
    return flights
