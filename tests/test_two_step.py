"""Two-step round-trip flow, step 2 (offline).

Fixture provenance: `roundtrip_step2_pinned.ds1.json` was captured from
/travel/flights/booking with a tfs that pins the chosen outbound (BA 280
LAX-LHR + BA 462 LHR-MAD, 2026-09-10) and leaves the return leg
(MAD-LAX 2026-09-20) as an open search. Google's response lists the RETURN
options priced at the TRUE COMBINED round-trip fare — verified against the
live UI ($1,080 round trip) at capture time. This is the native equivalent
of SerpApi's departure_token step.
"""

import pathlib

from fast_flights.parser import parse_js

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load(name: str):
    raw = (FIXTURES / f"{name}.ds1.json").read_text(encoding="utf-8")
    return parse_js("data:" + raw + ",x")


def test_step2_lists_return_leg_options():
    result = load("roundtrip_step2_pinned")
    assert len(result) >= 1
    for flight in result:
        # every itinerary is a RETURN: MAD -> LAX on the return date
        assert flight.flights[0].from_airport.code == "MAD"
        assert flight.flights[-1].to_airport.code == "LAX"
        assert flight.flights[0].departure.date == [2026, 9, 20]


def test_step2_price_is_combined_round_trip_fare():
    result = load("roundtrip_step2_pinned")
    # $1,080 was the round-trip total shown in the live UI for this pinned
    # outbound — NOT a one-way MAD-LAX fare.
    assert result[0].price == 1080


def test_step2_returns_carry_flight_numbers():
    result = load("roundtrip_step2_pinned")
    for flight in result:
        for seg in flight.flights:
            assert seg.airline_code and seg.flight_number
