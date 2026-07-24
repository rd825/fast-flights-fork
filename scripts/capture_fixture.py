"""Capture live Google Flights ds:1 payloads as test fixtures.

Google embeds search results as a JSON blob inside ``<script class="ds:1">``;
the parser reads it by hard-coded array index, so when Google shifts indices
the fix starts with re-capturing fixtures. This script makes that one command.

Usage (from the repo root):

    # one-way, nonstop-ish route
    python scripts/capture_fixture.py --name oneway_nonstop \
        --leg LAX:JFK:2026-09-10 --max-stops 0

    # round-trip step 1
    python scripts/capture_fixture.py --name roundtrip_step1 \
        --trip round-trip --leg LAX:MAD:2026-09-10 --leg MAD:LAX:2026-09-20

    # raw tfs (e.g. a hand-built pinned-outbound query), against either page
    python scripts/capture_fixture.py --name roundtrip_step2_pinned \
        --tfs "<urlsafe-b64>" --path flights/search

Writes ``tests/fixtures/<name>.ds1.json`` (the decoded payload) and, with
``--save-html``, ``tests/fixtures/<name>.html`` (the full page). Always
finishes by round-tripping the payload through ``parse_js`` and printing an
itinerary summary, so a capture that the parser can't read fails loudly here
rather than later in a test.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from primp import Client
from selectolax.lexbor import LexborHTMLParser

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fast_flights.parser import parse_js  # noqa: E402
from fast_flights.querying import FlightQuery, Passengers, create_query  # noqa: E402

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures"
BASE = "https://www.google.com/travel/"


def fetch_html(params: dict[str, str], path: str, proxy: str | None) -> str:
    client = Client(
        impersonate="chrome_145",
        impersonate_os="macos",
        referer=True,
        proxy=proxy,
        cookie_store=True,
    )
    res = client.get(BASE + path, params=params)
    return res.text


def extract_ds1(html: str) -> str:
    """The raw JSON text between ``data:`` and the trailing key of the ds:1
    script body — same split as ``parser.parse_js``."""
    tree = LexborHTMLParser(html)
    script = tree.css_first(r"script.ds\:1")
    if script is None:
        raise SystemExit(
            "no <script class='ds:1'> in response — consent page or anti-bot? "
            "Fallback: copy the script body from browser devtools."
        )
    return script.text().split("data:", 1)[1].rsplit(",", 1)[0]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", required=True, help="fixture file stem")
    ap.add_argument(
        "--leg",
        action="append",
        default=[],
        metavar="FROM:TO:YYYY-MM-DD",
        help="repeatable; ignored when --tfs is given",
    )
    ap.add_argument("--trip", default="one-way", choices=["one-way", "round-trip", "multi-city"])
    ap.add_argument("--max-stops", type=int, default=None)
    ap.add_argument("--adults", type=int, default=1)
    ap.add_argument("--currency", default="USD")
    ap.add_argument("--language", default="en")
    ap.add_argument("--tfs", default=None, help="raw b64 tfs; bypasses --leg/--trip")
    ap.add_argument(
        "--path",
        default="flights",
        choices=["flights", "flights/search", "flights/booking"],
        help="which Google Flights page to hit",
    )
    ap.add_argument("--proxy", default=None)
    ap.add_argument("--save-html", action="store_true")
    args = ap.parse_args()

    if args.tfs:
        params = {"tfs": args.tfs, "hl": args.language, "curr": args.currency}
    else:
        if not args.leg:
            ap.error("either --tfs or at least one --leg is required")
        legs = []
        for raw in args.leg:
            frm, to, date = raw.split(":")
            legs.append(FlightQuery(date=date, from_airport=frm, to_airport=to))
        query = create_query(
            flights=legs,
            trip=args.trip,
            passengers=Passengers(adults=args.adults),
            language=args.language,
            currency=args.currency,
            max_stops=args.max_stops,
        )
        params = query.params()
        print(f"tfs: {params['tfs']}")

    html = fetch_html(params, args.path, args.proxy)
    ds1 = extract_ds1(html)

    FIXTURES.mkdir(parents=True, exist_ok=True)
    if args.save_html:
        (FIXTURES / f"{args.name}.html").write_text(html, encoding="utf-8")
        print(f"wrote {FIXTURES / f'{args.name}.html'} ({len(html):,} chars)")

    if ds1.endswith("errorHasStatus: true"):
        (FIXTURES / f"{args.name}.ds1.json").write_text(ds1, encoding="utf-8")
        print(f"wrote {FIXTURES / f'{args.name}.ds1.json'} (error payload — 'no flights')")
        return

    payload = json.loads(ds1)
    out = FIXTURES / f"{args.name}.ds1.json"
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")

    try:
        result = parse_js("data:" + ds1 + ",x")
    except Exception as exc:  # fixture is still useful — it reproduces the crash
        print(f"parse_js FAILED on this payload: {type(exc).__name__}: {exc}")
        return
    print(f"parse_js: {len(result)} itineraries")
    for fl in result[:3]:
        segs = " / ".join(
            f"{s.from_airport.code}->{s.to_airport.code} {s.departure.date} {s.departure.time}"
            for s in fl.flights
        )
        print(f"  {fl.price} {args.currency}  [{', '.join(fl.airlines)}]  {segs}")


if __name__ == "__main__":
    main()
