# Bus bunching

Exploring **bus bunching** on the Champaign-Urbana MTD (Mass Transit District) network using real-time data collected from MTD's GTFS-RT feeds. The project has three parts:

1. **Measure:** detect bunching and headway irregularity in the real data.
2. **Simulate:** build a route and corridor simulation calibrated on that data.
3. **Test holding strategies:** compare policies (schedule-based, headway-based, and others) in simulation against a no-control baseline.

Data visualization runs through all three parts.

## Literature

The simulator is built from the papers in `docs/literature/`. Start with **`docs/literature/main.pdf`**, a synthesis of all of them (causes of bunching, holding strategies, learning-based control, and research gaps, framed around the 13 Silver at Illini Union). The other PDFs there are the seven source papers it cites.

## Case study: 13/130 Silver

The simulator and analysis focus on the **13 Silver** (weekday daytime) and **130 Silver** (evenings, late night, weekends), with **Illini Union** as the key stop. From the GTFS zip `gtfs_20261110T021620Z_5e033a2a.zip`:

- `route_short_name` `13` is `route_id` `SILVER`. `130` covers every other `SILVER*` route_id: `SILVER EVENING`, `SILVER LATE NIGHT`, `SILVER SATURDAY`, `SILVER SUNDAY`, `SILVER EVENING SATURDAY`, `SILVER EVENING SUNDAY`, and the `SILVER LIMITED*` variants. Select by `route_short_name in ('13', '130')`, not by matching `route_id` text.
- Base pattern: Lincoln Square Garage South ↔ PAR (North Side Shelter), with 17 stops in direction 0 (northbound) and 18 in direction 1 (southbound). Evening and weekend trips also run a Vet-Med extension (21 or 22 stops). Silver Limited runs Transit Plaza ↔ Lincoln Square (9 or 13 stops). Some trips have only one stop (Lincoln Square Garage South or PAR); drop them.
- Illini Union is `IU:1` in direction 0 and `IU:9` in direction 1.
- Headsigns don't match direction reliably (some direction-0 trips are signed "North to PAR"), so group by `direction_id`.
- Scheduled headway at Illini Union: about **10 min** on weekdays from 08:00 to 17:00 (13), then 20 min in the evening and late at night (130). Weekends run every 20 min.
- MTD splits one day's service across many `service_id`s. Resolve active services for a date from `calendar.txt` plus `calendar_dates.txt` before computing headways.
- **Thanksgiving break** (in `gtfs_20261112T021631Z_2df8e61e.zip`): 2026-11-21 to 11-29 runs a reduced schedule. Weekdays have 64 `SILVER` trips plus Silver Limited in the evening, weekends run Silver Limited only, and there is no service on Thanksgiving (11-26). Regular semester service returns on 11-30. Keep break days out of calibration for normal-semester service.

## Data

Data is collected on a VPS and published to the public Hugging Face dataset **[hikarinko/cumtd](https://huggingface.co/datasets/hikarinko/cumtd)**. That dataset is the source of truth. `data/` is a local copy of it and is git-ignored.

Fetch or update the local copy with **`./sync.sh`** (extra args go to `hf download`, e.g. `./sync.sh --dry-run`). It downloads only new or changed snapshots and GTFS zips, deliberately skips the dataset's `mtd.sqlite` (+ `-wal`, `-shm`), and prints the newest snapshot path. Run it before analysis so you're not working on stale data. If you edit it, give each glob its own `--include` flag; listing both after a single flag fails.

```
data/
├── snapshots/mtd-<UTC yyyymmddThhmmssZ>.sqlite   ← the ONLY data source for analysis
├── gtfs/gtfs_<UTC ts>_<sha8>.zip                   static GTFS (stops, stop_times, trips, shapes, …)
└── mtd.sqlite (+ -wal, -shm)                       the collector's live DB, NOT used here
```

- Always read the **newest snapshot**. Ignore `mtd.sqlite`.
- For reproducible results, record which snapshot file (and the dataset commit, if relevant) an analysis or simulation calibration used.
- Open snapshots read-only: `sqlite3.connect("file:<path>?mode=ro&immutable=1", uri=True)`. Never write to them. Put derived data in separate files.
- `gtfs_versions` in each snapshot lists every static GTFS zip the collector fetched (sha256, path, `fetched_at`), not just the one from the start. The 2026-11-16 snapshot has two: `gtfs_20261110T021620Z_5e033a2a.zip`, and `gtfs_20261112T021631Z_2df8e61e.zip` from 2026-11-11 20:16 local. Use the version that was in effect on the date you're analyzing.
- All timestamps are **unix seconds, UTC**. Service runs on **America/Chicago** local time, and `start_date` (YYYYMMDD) is the local service date. Convert times before grouping by day or hour.

### Tables

| Table | Grain | Notes |
|---|---|---|
| `positions` | one row per (vehicle_id, ts) | vehicle-positions feed, polled every 10 s; vehicles report about every 15 s, so duplicate polls collapse on the primary key |
| `predictions` | one row per (trip_id, vehicle_id, fetched_at) | trip-updates feed, polled every 60 s; the next stop's predicted arrival/departure plus `stops_left` |
| `feed_polls` | one row per poll | `error` is non-null on failed polls; use it to tell collection gaps apart from service gaps |
| `meta` | key/value | `started_at` |
| `gtfs_versions` | one row per static GTFS version | |

### Known data quirks

Verified on the 2026-11-11 and 2026-11-16 snapshots:

- `positions.current_status` is always `IN_TRANSIT_TO` (or NULL). There is never a `STOPPED_AT`, so **stop arrivals and departures must be inferred** from changes in `stop_id` and from lat/lon distance to stops in `stops.txt`.
- These columns are always NULL in `positions`: `speed`, `bearing`, `stop_sequence`, `start_date`. `congestion` is always `RUNNING_SMOOTHLY`, so it carries no information.
- `predictions.delay` and `predictions.next_delay` are always NULL. Derive delay by comparing `next_arrival` to `stop_times.txt`.
- `stop_id` looks like `WESTPO:1` (stop:boarding point) and matches `stops.txt`.
- `route_id` encodes the service variant, e.g. `GREEN`, `GREEN ALT`, `GREEN EVENING`, `ILLINI EVENING`. Bunching analysis usually wants these grouped by base route and direction.
- `predictions.vehicle_id` is `''` when the trip has no vehicle assigned yet. The same trip can show up on two buses.
- `predictions.start_date` is the **calendar date the trip actually starts**, not the GTFS service date. A Friday-service trip scheduled at `24:05:00` gets Saturday's `start_date`. To join with GTFS, subtract a day when the trip's first `departure_time` is 24:00 or later. Trips also appear in `predictions` about an hour before they start.
- **`positions.trip_id` gets stuck.** A bus can report the same `trip_id` for several round trips in a row, or a revenue `trip_id` while it shuttles between `WESTPO:1` and `LSE:8` (deadheading or layover). Don't key stop events on `trip_id`. Key them on `(vehicle_id, stop_id)`, and get direction from the boarding point (e.g. `IU:1` vs `IU:9`). `route_id` was reliable for Silver.
- **`stop_id` can skip a stop** when a bus passes it in less than one ping interval (e.g. `GRNGWN:8 → PLAZA:3`, never reporting `IU:9`). Fill skipped stops from the GTFS stop order. A departure is about the midpoint between the last ping with the old `stop_id` and the first ping with the new one.
- **Ping rate before 2026-11-12 is sparse.** Vehicles reported about every 73 s on 11-10 and every 37 s on 11-11, then about every 15 s from 11-12 on. On 11-10 and 11-11 only about half of Silver's Illini Union passages can be recovered, so use 11-12 onward for headway measurement.
- `occupancy` is populated: EMPTY, MANY_SEATS_AVAILABLE, FEW_SEATS_AVAILABLE, STANDING_ROOM_ONLY, FULL. It's a usable proxy for passenger load.

## Environment

- Two packages in one uv project (src layout, build backend `uv_build`, listed in `[tool.uv.build-backend] module-name`), Python 3.14 (pinned in `.python-version`):
  - `sim` (`src/sim/`) holds the simulator. `uv run sim` runs its entry point.
  - `analysis` (`src/analysis/`) holds the measurements from the snapshots: `data` (snapshot and GTFS-version lookup), `gtfs` (schedule, active services, stop patterns), `passages` (stop departures inferred from positions, handling the quirks above), and `headways` (pairing and bunching metrics). The case-study report is `uv run python -m analysis.silver [--csv PATH]`.
- The project is managed with **uv**. Dependencies go in `pyproject.toml` via `uv add <pkg>` (`uv add --dev <pkg>` for dev-only tools). Commit `uv.lock`. Run everything with `uv run …`, e.g. `uv run python -m …` or `uv run pytest`. Don't use bare `pip`, `uv pip install`, or a manually activated venv.
- Any web server or viz preview must run on **port 8080**, bound to **0.0.0.0**. No other port is reachable from the host.
- Never `git commit` or `git push`. Leave changes for the user to commit.
