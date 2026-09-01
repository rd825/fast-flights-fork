"""Offline parser tests against captured ds:1 fixtures.

Each assertion here is backed by a fixture captured from live Google Flights
(see scripts/capture_fixture.py and docs/ds1-schema.md). Re-capture and
re-check these if Google shifts payload indices.
"""

import json
import pathlib

import pytest

from fast_flights.parser import parse_js

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load(name: str):
    raw = (FIXTURES / f"{name}.ds1.json").read_text(encoding="utf-8")
    # parse_js expects the raw script body; wrap the stored JSON back into it.
    return parse_js("data:" + raw + ",x")


def find(result, *flight_numbers: str):
    """The itinerary flown as exactly `flight_numbers` (e.g. "B6 988", "B6 2261").

    Pick by flight number, never by list index: results now concatenate two
    payload buckets, so index 0 depends on which bucket a fixture happens to
    populate. Naming the flight keeps the assertion about parsing."""
    want = list(flight_numbers)
    for flight in result:
        got = [f"{s.airline_code} {s.flight_number}" for s in flight.flights]
        if got == want:
            return flight
    raise AssertionError(f"no itinerary flown as {want}")


def test_nonstop_flight_numbers_and_airline():
    result = load("oneway_nonstop")
    assert len(result) > 0
    nonstop = find(result, "B6 324")
    seg = nonstop.flights[0]
    assert seg.airline_code == "B6"
    assert seg.flight_number == "324"
    assert seg.airline_name == "JetBlue"
    # nonstop → no layovers
    assert nonstop.layovers is None


def test_every_segment_has_flight_number():
    for name in ("oneway_nonstop", "oneway_1stop", "roundtrip_step1"):
        result = load(name)
        assert len(result) > 0
        for flight in result:
            for seg in flight.flights:
                assert seg.airline_code, f"{name}: missing airline_code"
                assert seg.flight_number, f"{name}: missing flight_number"
                assert seg.flight_number.isdigit()
                assert len(seg.airline_code) == 2


def test_one_stop_layover():
    result = load("oneway_1stop")
    first = find(result, "AC 774", "AC 834")
    assert len(first.flights) == 2
    assert first.layovers is not None and len(first.layovers) == 1
    lv = first.layovers[0]
    assert lv.airport_code == "YUL"
    assert lv.duration == 80
    # the layover airport is the connection point between the two segments
    assert first.flights[0].to_airport.code == lv.airport_code
    assert first.flights[1].from_airport.code == lv.airport_code


def test_layover_matches_segment_gap():
    """Layover duration equals the wall-clock gap between segments (same
    airport, so no timezone traps)."""
    result = load("oneway_1stop")
    first = find(result, "AC 774", "AC 834")
    arr = first.flights[0].arrival
    dep = first.flights[1].departure
    gap = (dep.time[0] * 60 + dep.time[1]) - (arr.time[0] * 60 + (arr.time[1] if len(arr.time) > 1 else 0))
    assert gap == first.layovers[0].duration


def test_empty_results_payload_returns_empty_not_raise():
    """No-service routes ship a truncated payload (no airline metadata);
    the parser must return an empty ResultList, not IndexError."""
    result = load("empty_results")
    assert list(result) == []
    assert result.metadata.airlines == []


def test_metadata_still_populated():
    result = load("oneway_nonstop")
    codes = {a.code for a in result.metadata.airlines}
    assert "B6" in codes
    assert len(result.metadata.alliances) >= 3


def test_backwards_compat_fields_unchanged():
    """v3.0.2 consumers: the original fields still parse identically."""
    result = load("oneway_nonstop")
    first = find(result, "B6 324")
    seg = first.flights[0]
    assert seg.from_airport.code == "LAX"
    assert seg.to_airport.code == "JFK"
    assert seg.departure.date == [2026, 9, 10]
    assert seg.duration == 331
    assert isinstance(first.price, int) and first.price > 0
    assert first.airlines == ["JetBlue"]


def test_both_result_buckets_are_read():
    """Regression: Google splits results into "Top departing flights"
    (payload[2][0]) and "Other departing flights" (payload[3][0]). Reading only
    the latter dropped the curated — and often cheapest — itineraries entirely.

    The counts below are the two buckets of the captured fixture: 3 + 27 and
    4 + 9. B6 1524 and B6 988 exist ONLY in the curated bucket."""
    nonstop = load("oneway_nonstop")
    assert len(nonstop) == 30
    assert find(nonstop, "B6 1524").price == 204  # top bucket
    assert find(nonstop, "B6 324").price == 204  # other bucket

    one_stop = load("oneway_1stop")
    assert len(one_stop) == 13
    curated = find(one_stop, "B6 988", "B6 2261")  # top bucket only
    assert curated.price == 533
    assert curated.layovers is not None and curated.layovers[0].airport_code == "BOS"
    assert find(one_stop, "AC 774", "AC 834").price == 641  # other bucket


def test_curated_bucket_leads_the_results():
    """Order follows the page: the "Top departing flights" bucket comes first,
    so the fixture's four curated itineraries lead the list."""
    result = load("roundtrip_step1")
    assert len(result) == 8
    assert [f"{f.flights[0].airline_code} {f.flights[0].flight_number}" for f in result[:4]] == [
        "B6 988", "BA 282", "IB 352", "AA 2222",
    ]


def test_missing_curated_bucket_still_parses():
    """The pinned-outbound booking page ships no payload[2] at all — the other
    bucket must still come through (this is the round-trip step-2 fetch)."""
    result = load("roundtrip_step2_pinned")
    assert len(result) == 1
