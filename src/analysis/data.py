import sqlite3
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def newest_snapshot() -> Path:
    snaps = sorted((DATA / "snapshots").glob("mtd-*.sqlite"))
    if not snaps:
        raise FileNotFoundError("no snapshots in data/snapshots; run ./sync.sh")
    return snaps[-1]


def connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)


def gtfs_versions(conn: sqlite3.Connection) -> list[tuple[int, Path]]:
    rows = conn.execute("select fetched_at, path from gtfs_versions order by fetched_at").fetchall()
    return [(ts, ROOT / p) for ts, p in rows]


def gtfs_for_day(versions: list[tuple[int, Path]], day: date) -> Path:
    """The newest GTFS version fetched before the service day began, else the oldest."""
    start = datetime.combine(day, time(), TZ).timestamp()
    chosen = versions[0][1]
    for ts, path in versions:
        if ts <= start:
            chosen = path
    return chosen
