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


def test_nonstop_flight_numbers_and_airline():
    result = load("oneway_nonstop")
    assert len(result) > 0
    first = result[0]
    seg = first.flights[0]
    assert seg.airline_code == "B6"
    assert seg.flight_number == "324"
    assert seg.airline_name == "JetBlue"
    # nonstop → no layovers
    assert first.layovers is None


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
    first = result[0]
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
    first = result[0]
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
    first = result[0]
    seg = first.flights[0]
    assert seg.from_airport.code == "LAX"
    assert seg.to_airport.code == "JFK"
    assert seg.departure.date == [2026, 9, 10]
    assert seg.duration == 331
    assert isinstance(first.price, int) and first.price > 0
    assert first.airlines == ["JetBlue"]
