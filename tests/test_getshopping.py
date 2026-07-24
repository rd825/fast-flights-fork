"""GetShoppingResults RPC — request encoding + response decoding (offline).

The live POST is exercised by the app's smoke script; here we lock the request
shape and the response decoder against a captured fixture so wire-format drift
fails a test rather than silently returning nothing.
"""

import json
import pathlib

import pytest

from fast_flights.getshopping import (
    MULTI_CITY,
    ONE_WAY,
    PinnedLeg,
    ShoppingSegment,
    _encode,
    _row_price,
    _rows,
    _segment_array,
)
from fast_flights.parser import build_flights

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_rows(name: str):
    inner = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return _rows(inner)


# --- request encoding ------------------------------------------------------

def test_segment_array_shape():
    seg = ShoppingSegment("LAX", "MAD", "2026-09-10")
    arr = _segment_array(seg)
    assert arr[0] == [[["LAX", 0]]]   # departure airport
    assert arr[1] == [[["MAD", 0]]]   # arrival airport
    assert arr[6] == "2026-09-10"     # travel date
    assert arr[8] is None             # no pinned leg
    assert arr[14] == 3               # classifier


def test_segment_array_pins_selected_leg():
    seg = ShoppingSegment(
        "LAX", "MAD", "2026-09-10",
        selected=[
            PinnedLeg("LAX", "2026-09-10", "BOS", "DL", "639"),
            PinnedLeg("BOS", "2026-09-10", "MAD", "DL", "62"),
        ],
    )
    arr = _segment_array(seg)
    # segment[8] pins both physical flights: [from, date, to, None, carrier, number]
    assert arr[8] == [
        ["LAX", "2026-09-10", "BOS", None, "DL", "639"],
        ["BOS", "2026-09-10", "MAD", None, "DL", "62"],
    ]


def test_encode_is_urlencoded_json_with_trip_type():
    seg = [ShoppingSegment("LAX", "MAD", "2026-09-10")]
    encoded = _encode(ONE_WAY, seg, seat="economy", adults=1, children=0, infants_lap=0, infants_seat=0)
    # url-decodes to [null, "<filters json>"]; filters[1][2] == trip_type
    import urllib.parse
    outer = json.loads(urllib.parse.unquote(encoded))
    assert outer[0] is None
    filters = json.loads(outer[1])
    assert filters[1][2] == ONE_WAY          # main[2] trip type
    assert filters[1][6] == [1, 0, 0, 0]     # passengers
    assert filters[2] == 1                    # sort = BEST


def test_encode_multi_city_carries_all_segments():
    segs = [ShoppingSegment("LAX", "MAD", "2026-09-10"), ShoppingSegment("BCN", "LAX", "2026-09-20")]
    encoded = _encode(MULTI_CITY, segs, seat="economy", adults=2, children=1, infants_lap=0, infants_seat=0)
    import urllib.parse
    filters = json.loads(json.loads(urllib.parse.unquote(encoded))[1])
    assert filters[1][2] == MULTI_CITY
    assert len(filters[1][13]) == 2           # two segments
    assert filters[1][6] == [2, 1, 0, 0]


# --- response decoding -----------------------------------------------------

def test_rows_decode_into_flights():
    rows = load_rows("rpc_multicity_leg1")
    assert len(rows) > 0
    flights = [build_flights(r[0], _row_price(r)) for r in rows]
    # every itinerary has priced segments with flight numbers (RPC schema ==
    # ds:1 schema, so the enrichment fields populate the same way)
    for f in flights:
        assert f.price is None or f.price > 0
        for s in f.flights:
            assert s.airline_code and s.flight_number
            assert s.from_airport.code and s.to_airport.code


def test_row_price_reads_aggregate():
    rows = load_rows("rpc_multicity_leg1")
    prices = [_row_price(r) for r in rows]
    assert any(isinstance(p, (int, float)) and p > 0 for p in prices)


def test_rows_are_leg1_of_open_jaw():
    # every leg-1 option departs the origin (LAX) — confirms we're reading
    # the outbound segment, not a concatenated round trip
    rows = load_rows("rpc_multicity_leg1")
    for r in rows:
        f = build_flights(r[0], _row_price(r))
        assert f.flights[0].from_airport.code == "LAX"
        assert f.flights[-1].to_airport.code == "MAD"
