# ds:1 payload schema (reverse-engineered)

Google Flights embeds results as JSON in `<script class="ds:1">` (an
`AF_initDataCallback` body). `parser.parse_js` reads it by array index. This
file is the provenance record for every index we read: what it holds, and
which fixture in `tests/fixtures/` proves it. **When adding an index to the
parser, add a row here with the fixture that demonstrates it.**

Re-capture fixtures with `scripts/capture_fixture.py` (one command per
fixture; see its docstring). If a capture comes back without the ds:1 script,
Google served a consent/anti-bot page — copy the script body from browser
devtools instead.

## Top level

| Path | Meaning | Fixture |
|------|---------|---------|
| `payload[2][0]` | Itineraries — **"Top departing flights"**, Google's curated list (`None`/absent when the page has no curated set, e.g. the pinned booking page) | `oneway_nonstop` |
| `payload[3][0]` | Itineraries — **"Other departing flights"** (`None` when no results) | `oneway_nonstop` |
| `payload[7][1][0]` | Alliances: `[code, name]` pairs | `oneway_nonstop` |
| `payload[7][1][1]` | Airlines: `[code, name]` pairs | `oneway_nonstop` |

**Read BOTH itinerary buckets.** They are disjoint — the "other" list excludes
everything already in the curated one (checked across every fixture here), so
concatenating them in page order needs no de-duplication. Reading only
`payload[3][0]` silently drops the curated results, which routinely hold the
cheapest and simplest fares: on SLC→CUR 2027-02-24 the only 1-stop, single-carrier
fare (American, $869) lived exclusively in `payload[2][0]`, while `payload[3][0]`
offered nothing better than a $1,481 1-stop and a spread of 2-stop itineraries.
The `GetShoppingResults` RPC uses the same two-bucket split at `inner[2][0]` /
`inner[3][0]` (see below).

## Per itinerary `k = payload[2][0][i]` / `payload[3][0][i]`

| Path | Meaning | Fixture |
|------|---------|---------|
| `k[0]` | The flight record (see below) | `oneway_nonstop` |
| `k[1][0][1]` | Price (int, display currency) | `oneway_nonstop` |

## Flight record `flight = k[0]`

| Path | Meaning | Fixture |
|------|---------|---------|
| `flight[0]` | Type (str / `"multi"`) | `oneway_nonstop` |
| `flight[1]` | Airline codes (list of str) | `oneway_nonstop` |
| `flight[2]` | Segments (list; see below) | `oneway_1stop` |
| `flight[13]` | Layovers, one per connection: `[duration_min, airport_code, airport_code, ?, airport_name, ...]`; `None` for nonstop | `oneway_1stop` (80 min at YUL = the 16:35→17:55 gap) |
| `flight[22][7]` | Carbon emission (g) | `oneway_nonstop` |
| `flight[22][8]` | Typical carbon emission on route (g) | `oneway_nonstop` |

## Per segment `s = flight[2][j]`

| Path | Meaning | Fixture |
|------|---------|---------|
| `s[3]` | From-airport code | `oneway_nonstop` |
| `s[4]` | From-airport name | `oneway_nonstop` |
| `s[6]` | To-airport code | `oneway_nonstop` |
| `s[5]` | To-airport name | `oneway_nonstop` |
| `s[8]` | Departure time `[h, m]` | `oneway_nonstop` |
| `s[20]` | Departure date `[y, m, d]` | `oneway_nonstop` |
| `s[10]` | Arrival time `[h, m]` | `oneway_nonstop` |
| `s[21]` | Arrival date `[y, m, d]` | `oneway_nonstop` |
| `s[11]` | Duration (minutes) | `oneway_nonstop` |
| `s[17]` | Plane type | `oneway_nonstop` |
| `s[22]` | Marketing carrier: `[code, flight_number, ?, display_name]`, e.g. `['AC', '774', None, 'Air Canada']` | `oneway_nonstop`, `oneway_1stop` |
| `s[15]` | Codeshares ("also sold as"): list of the same 4-tuple shape, e.g. `[['UA', '8466', None, 'United']]`; `None` if none | `oneway_1stop` (not extracted yet) |

## Known shape variants

- **No-service route** (`empty_results`, SLK→OGS): the payload is tiny
  (~3.5 KB) and `payload[7][1]` has no airlines entry at index 1, so
  `parse_js` currently dies with `IndexError` before reaching the
  itinerary check. Parser should treat missing metadata as "no results".
- **No curated bucket** (`roundtrip_step2_pinned`): the pinned-outbound
  booking page ships `payload[3][0]` only — there is no `payload[2]`. Either
  bucket being absent must degrade to "no itineraries from that bucket",
  never to an empty overall result or a crash.

## Wanted (parity work) — indices to discover

| Field | Status | Notes |
|-------|--------|-------|
| Marketing carrier code + flight number | **DONE** | `s[22]` (parser extracts to `SingleFlight.airline_code/flight_number/airline_name`) |
| Per-segment airline | **DONE** | `s[22][3]` display name; `s[22][0]` code also maps via `payload[7][1][1]` |
| Layover durations | **DONE** | `flight[13]` (parser extracts to `Flights.layovers`) |
| Round-trip step-2 (pinned outbound) payload shape | **DONE** | identical to step-1 — `parse_js` reads it unchanged. Fetch `/travel/flights/booking?tfs=<pinned-outbound tfs>`; itineraries are the RETURN options priced at the TRUE COMBINED round-trip fare (verified vs live UI, `roundtrip_step2_pinned`) |
| Multi-city payload shape | **SOLVED via RPC** | Multi-city results are never embedded in any page (`payload[3]` is `None` on `/travel/flights`, `/search`, `/booking`; fixtures `multicity_*`). They load only via the `GetShoppingResults` RPC — now implemented in `fast_flights/getshopping.py` (see below). |

## GetShoppingResults RPC (`getshopping.py`)

The FlightsFrontendService RPC that the UI calls for results Google won't
embed (all of multi-city; also drives one-way/round-trip). `POST` to
`https://www.google.com/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/GetShoppingResults?hl=&curr=`
with `content-type: application/x-www-form-urlencoded;charset=UTF-8` and body
`f.req=<url-encoded JSON>`.

- **Request body**: `[null, "<filters JSON>"]` url-encoded. `filters` =
  `[[], main, sort, all_results, 0, 1]`. `main` index map (the parts we set):
  `[2]`=trip_type (1 round / 2 one-way / 3 multi-city), `[5]`=seat,
  `[6]`=`[adults, children, infants_lap, infants_seat]`, `[13]`=segments.
  Each **segment**: `[0]`=`[[[origin,0]]]`, `[1]`=`[[[dest,0]]]`, `[3]`=max
  stops, `[6]`=date, **`[8]`=selected/pinned leg** (`[[from,date,to,None,carrier,number],…]`
  — the two-step combined-fare key), `[14]`=classifier (3).
- **Response**: JSONP — `)]}'` prefix, then length-prefixed (UTF-8 **byte**
  counts) `[["wrb.fr", null, "<inner JSON string>"]]` chunks. Flight rows at
  `inner[2][0]` (best) + `inner[3][0]` (other). Each **row**: `row[0]` = the
  same flight-detail array as ds:1 `k[0]` (so `build_flights` decodes it
  unchanged), `row[1][0][-1]` = aggregate price (may be absent → `None`).
- **Combined fares (multi-city / round-trip)**: two-step. Step 1 = outbound
  options. Step 2 = re-issue with the chosen outbound pinned in `segment[8]`;
  the returned next-leg options carry the true combined trip price. Verified
  live: LAX→MAD .. BCN→LAX open-jaw priced as one $1,125 fare.
- Protocol cross-checked against the MIT `fli` library (github.com/punitarani/fli).
  Fixture: `rpc_multicity_leg1.json` (slimmed live response, step 1).
