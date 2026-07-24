"""FlightsFrontendService.GetShoppingResults — the RPC that powers the
Google Flights UI, called directly (no browser).

The public HTML page embeds one-way / round-trip results in its ``ds:1``
script (see :mod:`fast_flights.parser`), but **multi-city results are never
embedded** — the page fetches them from this RPC via an async ``batchexecute``
XHR. Replicating the RPC is therefore the only browserless way to get
open-jaw itineraries, and as a bonus it drives one-way and round-trip too.

Request/response protocol reverse-engineered from live captures and
cross-checked against the MIT-licensed ``fli`` library
(github.com/punitarani/fli). The response rows share the exact segment
schema as ``ds:1``, so decoding reuses :func:`fast_flights.parser.build_flights`.

Multi-city / round-trip return the true COMBINED fare via a two-step flow:
step 1 lists leg-1 (outbound) options; step 2 re-issues the request with the
chosen leg pinned (``segment[8]``), and the returned next-leg options carry
the combined trip price. The caller bounds the fan-out.
"""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass

from primp import Client

from .parser import ResultList, build_flights

_URL = (
    "https://www.google.com/_/FlightsFrontendUi/data/"
    "travel.frontend.flights.FlightsFrontendService/GetShoppingResults"
)
_HEADERS = {"content-type": "application/x-www-form-urlencoded;charset=UTF-8"}

# trip_type ints (Google's TripType enum)
ROUND_TRIP = 1
ONE_WAY = 2
MULTI_CITY = 3

# seat ints (Google's SeatType enum)
_SEAT = {"economy": 1, "premium-economy": 2, "business": 3, "first": 4}


@dataclass
class PinnedLeg:
    """One physical flight of an already-chosen leg, used to pin it in a
    step-2 request so Google prices the remaining leg(s) as one trip."""

    from_airport: str
    date: str  # YYYY-MM-DD
    to_airport: str
    airline: str  # carrier IATA, e.g. "DL"
    flight_number: str  # bare number, e.g. "639"


@dataclass
class ShoppingSegment:
    """One leg of the search. ``selected`` pins an already-chosen leg (list of
    its physical flights) for the two-step combined-fare flow."""

    from_airport: str
    to_airport: str
    date: str  # YYYY-MM-DD
    selected: list[PinnedLeg] | None = None
    max_stops: int = 0  # 0 = any


def _segment_array(seg: ShoppingSegment) -> list:
    selected = None
    if seg.selected:
        selected = [
            [leg.from_airport, leg.date, leg.to_airport, None, leg.airline, leg.flight_number]
            for leg in seg.selected
        ]
    return [
        [[[seg.from_airport, 0]]],   # 0 departure airport
        [[[seg.to_airport, 0]]],     # 1 arrival airport
        None,                        # 2 time restrictions
        seg.max_stops,               # 3 max stops (0=any)
        None, None,                  # 4/5 airline include/exclude
        seg.date,                    # 6 travel date
        None,                        # 7 max duration
        selected,                    # 8 selected flight (pins a chosen leg)
        None, None, None, None,      # 9-12 layover restrictions
        None,                        # 13 emissions filter
        3,                           # 14 classifier (3=outbound/only leg)
    ]


def _encode(trip_type: int, segments: list[ShoppingSegment], *,
            seat: str, adults: int, children: int, infants_lap: int, infants_seat: int) -> str:
    """Build the url-encoded ``f.req`` body (main-filter index map documented
    in fli/models/google_flights/flights.py)."""
    main = [
        None, None, trip_type, None, [],
        _SEAT.get(seat, 1),
        [adults, children, infants_lap, infants_seat],
        None, None, None, None, None, None,
        [_segment_array(s) for s in segments],  # 13 segments
        None, None, None, 1,
    ] + [None] * 10 + [0]
    filters = [[], main, 1, 1, 0, 1]  # outer[2]=sort BEST, outer[3]=all results
    inner = json.dumps(filters, separators=(",", ":"))
    return urllib.parse.quote(json.dumps([None, inner], separators=(",", ":")))


def _parse_wire(body: bytes) -> object | None:
    """Return the inner JSON of the first ``wrb.fr`` chunk, or None.

    Response shape: ``)]}'`` prefix, then one or more length-prefixed chunks
    ``<byte_len>\\n[["wrb.fr", null, "<inner json string>"]]``. Length headers
    count UTF-8 bytes, so we operate on bytes."""
    raw = body.lstrip()
    if raw.startswith(b")]}'"):
        raw = raw[4:].lstrip()
    if not raw:
        return None

    chunks: list = []
    if b"0" <= raw[:1] <= b"9":  # length-prefixed multi-chunk
        cursor = 0
        while cursor < len(raw):
            end = raw.find(b"\n", cursor)
            if end == -1:
                break
            try:
                length = int(raw[cursor:end])
            except ValueError:
                break
            cursor = end + 1
            take = max(length - 1, 0)
            piece = raw[cursor:cursor + take]
            cursor += take
            try:
                chunks.append(json.loads(piece.strip().decode("utf-8")))
            except Exception:
                continue
    else:  # single chunk, no length header
        try:
            chunks.append(json.loads(raw.decode("utf-8")))
        except Exception:
            return None

    for outer in chunks:
        if not isinstance(outer, list):
            continue
        for row in outer:
            if isinstance(row, list) and len(row) >= 3 and row[0] == "wrb.fr" and isinstance(row[2], str):
                try:
                    return json.loads(row[2])
                except Exception:
                    return None
    return None


def _rows(inner) -> list:
    """Flight rows live at inner[2][0] (best) and inner[3][0] (other)."""
    out: list = []
    for i in (2, 3):
        block = inner[i] if isinstance(inner, list) and len(inner) > i else None
        if isinstance(block, list) and block and isinstance(block[0], list):
            out.extend(block[0])
    return out


def _row_price(row):
    """Per-row aggregate price, or None when Google didn't surface one
    (``row[1][0]`` empty — common for premium-cabin rows)."""
    block = row[1] if len(row) > 1 and isinstance(row[1], list) else None
    head = block[0] if block and isinstance(block[0], list) else None
    if head:
        val = head[-1]
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return val
    return None


def search_shopping(
    segments: list[ShoppingSegment],
    *,
    trip_type: int,
    seat: str = "economy",
    adults: int = 1,
    children: int = 0,
    infants_lap: int = 0,
    infants_seat: int = 0,
    currency: str = "USD",
    language: str = "en",
    proxy: str | None = None,
    retries: int = 2,
) -> ResultList:
    """POST GetShoppingResults and decode the itineraries.

    Returns a ``ResultList`` of ``Flights`` (no ``.metadata`` — the RPC omits
    the airline/alliance lookup the HTML carries). The endpoint intermittently
    answers a cold connection with an empty body, so an empty parse is retried
    (up to ``retries`` extra attempts) before giving up. Timeouts/network
    errors are also retried; the last is re-raised only if every attempt
    fails, so a flaky call surfaces as ``[]`` rather than an exception when at
    least one attempt returned cleanly."""
    body = "f.req=" + _encode(
        trip_type, segments, seat=seat,
        adults=adults, children=children,
        infants_lap=infants_lap, infants_seat=infants_seat,
    )
    url = _URL + f"?hl={language}&curr={currency}"
    last_exc: Exception | None = None
    got_response = False
    for _ in range(retries + 1):
        try:
            client = Client(
                impersonate="chrome_145", impersonate_os="macos",
                referer=True, proxy=proxy, cookie_store=True, timeout=30,
            )
            res = client.post(url, content=body.encode("utf-8"), headers=_HEADERS)
        except Exception as exc:  # noqa: BLE001 — flaky endpoint; retry then re-raise
            last_exc = exc
            continue
        got_response = True
        raw = res.text.encode("utf-8") if isinstance(res.text, str) else res.content
        inner = _parse_wire(raw)
        result = ResultList()
        if inner is not None:
            for row in _rows(inner):
                try:
                    result.append(build_flights(row[0], _row_price(row)))
                except (IndexError, TypeError, KeyError):
                    continue  # half-populated advert/sponsor row — skip
        if result:
            return result
        # empty parse — usually a cold-connection blip; loop and retry
    # Every attempt raised (never got a clean response) => surface the error
    # so the provider's guard turns it into []. If we *did* get a response but
    # it was genuinely empty (e.g. no-service route), return [].
    if not got_response and last_exc is not None:
        raise last_exc
    return ResultList()
