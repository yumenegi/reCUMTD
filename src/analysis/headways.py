import bisect
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date

from analysis.passages import Passage

BUNCHED = 0.25
CLOSE = 0.5
GAP = 1.5
MAX_HEADWAY = 3 * 3600


@dataclass(frozen=True, slots=True)
class Headway:
    stop_id: str
    direction_id: str
    day: date
    lead: Passage
    follow: Passage
    observed: float
    scheduled: float

    @property
    def ratio(self) -> float:
        return self.observed / self.scheduled


def scheduled_headway(schedule: list[int], secs: float) -> float | None:
    """Median of the scheduled gaps around `secs`, or None if there are none."""
    i = bisect.bisect_left(schedule, secs)
    gaps = [schedule[j] - schedule[j - 1] for j in (i - 1, i, i + 1) if 0 < j < len(schedule)]
    return statistics.median(gaps) if gaps else None


def pair(passages: Iterable[Passage], schedule_for: Callable[[date, str], list[int]], skip_stops: set[str] = frozenset()) -> list[Headway]:
    """Headways between consecutive buses at each stop on each service day."""
    by_stop = defaultdict(list)
    for p in passages:
        if p.stop_id not in skip_stops:
            by_stop[(p.day, p.stop_id)].append(p)
    out = []
    for (day, stop), ps in by_stop.items():
        ps.sort(key=lambda p: p.t)
        schedule = schedule_for(day, stop)
        for lead, follow in zip(ps, ps[1:]):
            if lead.vehicle_id == follow.vehicle_id:
                continue
            observed = follow.t - lead.t
            scheduled = scheduled_headway(schedule, follow.secs)
            if not scheduled or scheduled <= 0 or observed > MAX_HEADWAY:
                continue
            out.append(Headway(stop, follow.direction_id, day, lead, follow, observed, scheduled))
    return out


@dataclass(frozen=True)
class Summary:
    n: int
    scheduled_min: float
    median_min: float
    bunched: int
    close: int
    gaps: int
    cv_h: float

    def __str__(self) -> str:
        pct = lambda k: f"{k:3d} ({k / self.n:5.1%})"
        return (
            f"n={self.n:4d} sched={self.scheduled_min:4.1f}m med={self.median_min:4.1f}m  "
            f"bunched<{BUNCHED:.0%}={pct(self.bunched)}  close<{CLOSE:.0%}={pct(self.close)}  "
            f"gap>{GAP:.0%}={pct(self.gaps)}  cv_h={self.cv_h:.2f}"
        )


def summarize(hs: list[Headway]) -> Summary | None:
    """Bunching shares and cv_h = std(observed - scheduled) / mean(scheduled)."""
    if not hs:
        return None
    mean_sched = statistics.mean(h.scheduled for h in hs)
    return Summary(
        n=len(hs),
        scheduled_min=mean_sched / 60,
        median_min=statistics.median(h.observed for h in hs) / 60,
        bunched=sum(h.ratio < BUNCHED for h in hs),
        close=sum(h.ratio < CLOSE for h in hs),
        gaps=sum(h.ratio > GAP for h in hs),
        cv_h=statistics.pstdev(h.observed - h.scheduled for h in hs) / mean_sched,
    )
