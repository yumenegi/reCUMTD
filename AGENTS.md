# Bus bunching

Exploring **bus bunching** on the Champaign-Urbana MTD (Mass Transit District) network using real-time data collected from MTD's GTFS-RT feeds. The project has three parts:

1. **Measure:** detect bunching and headway irregularity in the real data.
2. **Simulate:** build a route and corridor simulation calibrated on that data.
3. **Test holding strategies:** compare policies (schedule-based, headway-based, and others) in simulation against a no-control baseline.

Data visualization runs through all three parts.

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
- `gtfs_versions` in each snapshot records the sha256 and path of the static GTFS zip that was active when collection started.
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

Verified on the 2026-11-11 snapshot:

- `positions.current_status` is always `IN_TRANSIT_TO` (or NULL). There is never a `STOPPED_AT`, so **stop arrivals and departures must be inferred** from changes in `stop_id` and from lat/lon distance to stops in `stops.txt`.
- These columns are always NULL in `positions`: `speed`, `bearing`, `stop_sequence`, `start_date`. `congestion` is always `RUNNING_SMOOTHLY`, so it carries no information.
- `predictions.delay` and `predictions.next_delay` are always NULL. Derive delay by comparing `next_arrival` to `stop_times.txt`.
- `stop_id` looks like `WESTPO:1` (stop:boarding point) and matches `stops.txt`.
- `route_id` encodes the service variant, e.g. `GREEN`, `GREEN ALT`, `GREEN EVENING`, `ILLINI EVENING`. Bunching analysis usually wants these grouped by base route and direction.
- `predictions.vehicle_id` is `''` when the trip has no vehicle assigned yet. The same trip can show up on two buses.
- `occupancy` is populated: EMPTY, MANY_SEATS_AVAILABLE, FEW_SEATS_AVAILABLE, STANDING_ROOM_ONLY, FULL. It's a usable proxy for passenger load.

## Environment

- The project is managed with **uv**. Dependencies go in `pyproject.toml` via `uv add <pkg>` (`uv add --dev <pkg>` for dev-only tools). Commit `uv.lock`. Run everything with `uv run …`, e.g. `uv run python -m …` or `uv run pytest`. Don't use bare `pip`, `uv pip install`, or a manually activated venv.
- Any web server or viz preview must run on **port 8080**, bound to **0.0.0.0**. No other port is reachable from the host.
- Never `git commit` or `git push`. Leave changes for the user to commit.
