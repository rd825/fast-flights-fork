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
| `payload[3][0]` | List of itineraries (`None` when no results) | `oneway_nonstop` |
| `payload[7][1][0]` | Alliances: `[code, name]` pairs | `oneway_nonstop` |
| `payload[7][1][1]` | Airlines: `[code, name]` pairs | `oneway_nonstop` |

## Per itinerary `k = payload[3][0][i]`

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

## Wanted (parity work) — indices to discover

| Field | Status | Notes |
|-------|--------|-------|
| Marketing carrier code + flight number | **DONE** | `s[22]` (parser extracts to `SingleFlight.airline_code/flight_number/airline_name`) |
| Per-segment airline | **DONE** | `s[22][3]` display name; `s[22][0]` code also maps via `payload[7][1][1]` |
| Layover durations | **DONE** | `flight[13]` (parser extracts to `Flights.layovers`) |
| Round-trip step-2 (pinned outbound) payload shape | TODO | see two-step spike |
| Multi-city payload shape | TODO | leg-1 options at full multi-city fare (hypothesis) |
