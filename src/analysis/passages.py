"""Infer when buses leave stops from the vehicle-positions feed.

`current_status` is always IN_TRANSIT_TO, so a departure from stop A is taken as
the midpoint between the last ping whose `stop_id` is A and the first ping whose
`stop_id` is something else. `stop_id` sometimes jumps past a stop the bus went by
between pings; the skipped stops are filled in from the route's stop order and get
the same time. `trip_id` in positions gets stuck across round trips, so passages are
keyed by vehicle and stop, never by trip.
"""

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from analysis.data import TZ

MAX_PING_GAP = 90
MAX_SKIPPED = 3
SERVICE_DAY_ROLLOVER = timedelta(hours=4)


@dataclass(frozen=True, slots=True)
class Passage:
    vehicle_id: str
    route_id: str
    stop_id: str
    direction_id: str
    t: float
    day: date
    secs: float
    occupancy: str | None
    filled: bool


def service_day(t: float) -> tuple[date, float]:
    """Service day (local, rolling over at 04:00) and seconds since its midnight."""
    local = datetime.fromtimestamp(t, TZ)
    day = (local - SERVICE_DAY_ROLLOVER).date()
    midnight = datetime(day.year, day.month, day.day, tzinfo=TZ)
    return day, (local - midnight).total_seconds()


def detect(conn: sqlite3.Connection, route_ids: list[str], patterns: dict[str, tuple[str, ...]]) -> Iterator[Passage]:
    """Yield passages for vehicles reporting any of `route_ids`.

    `patterns` maps direction_id to the ordered stop_ids used to place stops and
    fill skips. The first stop of each pattern is a terminal and is not emitted
    as a departure unless the bus actually reported it.
    """
    index = {d: {s: i for i, s in enumerate(stops)} for d, stops in patterns.items()}
    marks = ",".join("?" * len(route_ids))
    rows = conn.execute(
        f"select vehicle_id, ts, route_id, stop_id, occupancy from positions "
        f"where route_id in ({marks}) and stop_id is not null order by vehicle_id, ts",
        route_ids,
    )
    prev = None
    for vehicle, ts, route, stop, occ in rows:
        if prev and prev[0] == vehicle and prev[3] != stop and ts - prev[1] < MAX_PING_GAP:
            for direction, ix in index.items():
                a, b = ix.get(prev[3]), ix.get(stop)
                if a is None or b is None or not 0 < b - a <= MAX_SKIPPED + 1:
                    continue
                t = (prev[1] + ts) / 2
                day, secs = service_day(t)
                for s in patterns[direction][a:b]:
                    yield Passage(vehicle, prev[2], s, direction, t, day, secs, prev[4], s != prev[3])
                break
        prev = (vehicle, ts, route, stop, occ)
