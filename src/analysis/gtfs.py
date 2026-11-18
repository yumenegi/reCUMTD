import csv
import io
import zipfile
from collections import Counter, defaultdict
from datetime import date
from functools import cache
from pathlib import Path


def _read(zf: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.TextIOWrapper(zf.open(name), "utf-8-sig")))


def hms(value: str) -> int:
    h, m, s = map(int, value.split(":"))
    return h * 3600 + m * 60 + s


class Gtfs:
    """Static GTFS restricted to the routes with the given short names."""

    def __init__(self, path: Path, short_names: tuple[str, ...]):
        self.path = path
        with zipfile.ZipFile(path) as zf:
            self.routes = {r["route_id"]: r for r in _read(zf, "routes.txt") if r["route_short_name"] in short_names}
            self.trips = {t["trip_id"]: t for t in _read(zf, "trips.txt") if t["route_id"] in self.routes}
            self.stop_names = {s["stop_id"]: s["stop_name"] for s in _read(zf, "stops.txt")}
            self.calendar = _read(zf, "calendar.txt")
            self.calendar_dates = _read(zf, "calendar_dates.txt")
            stop_times = defaultdict(list)
            for r in csv.DictReader(io.TextIOWrapper(zf.open("stop_times.txt"), "utf-8-sig")):
                if r["trip_id"] in self.trips:
                    stop_times[r["trip_id"]].append((int(r["stop_sequence"]), r["stop_id"], hms(r["departure_time"])))
        self.stop_times = {t: sorted(v) for t, v in stop_times.items()}
        self._departures = defaultdict(list)
        for trip_id, rows in self.stop_times.items():
            service = self.trips[trip_id]["service_id"]
            for _, stop_id, dep in rows:
                self._departures[stop_id].append((service, dep))

    def active_services(self, day: date) -> set[str]:
        ds = day.strftime("%Y%m%d")
        weekday = day.strftime("%A").lower()
        active = {c["service_id"] for c in self.calendar if c["start_date"] <= ds <= c["end_date"] and c[weekday] == "1"}
        for x in self.calendar_dates:
            if x["date"] == ds:
                if x["exception_type"] == "1":
                    active.add(x["service_id"])
                else:
                    active.discard(x["service_id"])
        return active

    def scheduled_departures(self, day: date, stop_id: str) -> list[int]:
        """Seconds after local midnight of the service day; may exceed 24 h."""
        active = self.active_services(day)
        return sorted(dep for service, dep in self._departures.get(stop_id, []) if service in active)

    def main_pattern(self, route_id: str, direction_id: str) -> tuple[str, ...]:
        """The most common stop sequence for a route and direction."""
        patterns = Counter(
            tuple(stop for _, stop, _ in self.stop_times[t])
            for t, trip in self.trips.items()
            if trip["route_id"] == route_id and trip["direction_id"] == direction_id
        )
        return patterns.most_common(1)[0][0]


@cache
def load(path: Path, short_names: tuple[str, ...]) -> Gtfs:
    return Gtfs(path, short_names)
