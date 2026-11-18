"""Bunching report for the 13/130 Silver case study.

    uv run python -m analysis.silver [--snapshot PATH] [--csv PATH] [--min-coverage 0.9]
"""

import argparse
import csv
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from analysis import data, gtfs, headways, passages

SHORT_NAMES = ("13", "130")
BASE_ROUTE = "SILVER"
ILLINI_UNION = {"0": "IU:1", "1": "IU:9"}
GROUPS = ("13 weekday", "130 weekday eve/night", "130 weekend")


def group(h: headways.Headway) -> str:
    if h.follow.route_id == BASE_ROUTE:
        return GROUPS[0]
    return GROUPS[2] if h.day.weekday() >= 5 else GROUPS[1]


def coverage(ps: list[passages.Passage], schedule_for, t_min: float, t_max: float) -> dict[date, float]:
    """Per service day, the worst ratio of observed to scheduled passages at Illini Union,
    counting only scheduled departures inside the snapshot's time range."""
    observed = defaultdict(int)
    for p in ps:
        if p.stop_id in ILLINI_UNION.values():
            observed[(p.day, p.stop_id)] += 1
    days = {p.day for p in ps}
    out = {}
    for day in sorted(days):
        midnight = datetime(day.year, day.month, day.day, tzinfo=data.TZ).timestamp()
        ratios = []
        for stop in ILLINI_UNION.values():
            n = sum(t_min <= midnight + s <= t_max for s in schedule_for(day, stop))
            if n:
                ratios.append(observed[(day, stop)] / n)
        out[day] = min(ratios) if ratios else 0.0
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshot", type=Path, default=None, help="defaults to the newest in data/snapshots")
    ap.add_argument("--csv", type=Path, default=None, help="write every headway to this CSV")
    ap.add_argument("--min-coverage", type=float, default=0.9, help="drop service days below this Illini Union coverage")
    args = ap.parse_args()

    snapshot = args.snapshot or data.newest_snapshot()
    conn = data.connect(snapshot)
    versions = data.gtfs_versions(conn)
    latest = gtfs.load(versions[-1][1], SHORT_NAMES)
    patterns = {d: latest.main_pattern(BASE_ROUTE, d) for d in ("0", "1")}
    terminals = {stops[0] for stops in patterns.values()} | {stops[-1] for stops in patterns.values()}

    def schedule_for(day: date, stop: str) -> list[int]:
        return gtfs.load(data.gtfs_for_day(versions, day), SHORT_NAMES).scheduled_departures(day, stop)

    ps = list(passages.detect(conn, sorted(latest.routes), patterns))
    t_min, t_max = conn.execute("select min(ts), max(ts) from positions").fetchone()
    cov = coverage(ps, schedule_for, t_min, t_max)
    kept = {d for d, c in cov.items() if c >= args.min_coverage}
    hs = [h for h in headways.pair((p for p in ps if p.day in kept), schedule_for, terminals)]

    print(f"snapshot: {snapshot.name}")
    print("gtfs:", ", ".join(p.name for _, p in versions))
    print("Illini Union coverage by service day:")
    for d, c in cov.items():
        print(f"  {d} {d:%a} {c:6.1%} {'kept' if d in kept else 'dropped'}")

    at_iu = [h for h in hs if h.stop_id == ILLINI_UNION[h.direction_id]]
    print("\n=== Illini Union")
    for g in GROUPS:
        for d, stop in ILLINI_UNION.items():
            s = headways.summarize([h for h in at_iu if group(h) == g and h.direction_id == d])
            if s:
                print(f"{g:22s} {stop:5s} {s}")

    base = [h for h in at_iu if group(h) == GROUPS[0]]
    print(f"\n=== {GROUPS[0]} at Illini Union, by day")
    for d in sorted({h.day for h in base}):
        print(f"  {d} {d:%a}", headways.summarize([h for h in base if h.day == d]))
    print(f"\n=== {GROUPS[0]} at Illini Union, by hour")
    for hour in sorted({int(h.follow.secs // 3600) for h in base}):
        print(f"  {hour:02d}h", headways.summarize([h for h in base if int(h.follow.secs // 3600) == hour]))

    print(f"\n=== {GROUPS[0]} along the route (share of headways under {headways.CLOSE:.0%} of schedule)")
    for d, stops in patterns.items():
        cells = []
        for stop in stops:
            s = headways.summarize([h for h in hs if group(h) == GROUPS[0] and h.stop_id == stop])
            if s:
                cells.append(f"{stop}:{s.close / s.n:.0%}")
        print(f"  dir {d}:", " ".join(cells))

    print(f"\n=== tightest pairs at Illini Union ({GROUPS[0]})")
    for h in sorted(base, key=lambda h: h.observed)[:10]:
        when = datetime.fromtimestamp(h.follow.t, data.TZ)
        print(f"  {when:%a %m-%d %H:%M} {h.stop_id:5s} {h.observed / 60:4.1f}m (sched {h.scheduled / 60:4.1f}m) "
              f"bus {h.lead.vehicle_id} -> {h.follow.vehicle_id}  {h.lead.occupancy} / {h.follow.occupancy}")

    if args.csv:
        with args.csv.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["snapshot", "day", "group", "stop_id", "direction_id", "lead_vehicle", "follow_vehicle",
                        "follow_ts", "observed_s", "scheduled_s", "ratio", "lead_occupancy", "follow_occupancy", "filled"])
            for h in hs:
                w.writerow([snapshot.name, h.day, group(h), h.stop_id, h.direction_id, h.lead.vehicle_id,
                            h.follow.vehicle_id, round(h.follow.t, 1), round(h.observed, 1), h.scheduled,
                            round(h.ratio, 3), h.lead.occupancy, h.follow.occupancy, h.follow.filled])
        print(f"\nwrote {len(hs)} headways to {args.csv}")


if __name__ == "__main__":
    main()
