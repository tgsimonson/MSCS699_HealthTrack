"""activity and trend metrics for the pattern rules

each metric returns None when there is not enough data, so a quiet week of missing uploads never looks like a
decline (the DATA_GAP rule covers missing uploads). windows use the patient's local calendar days and end
yesterday, because today's totals are still filling in.

  consecutive_missed_sessions   floor(days since the last exercise session / (7 / prescribed sessions per week))
  minutes_in_zone_wow_pct       % change in exercise minutes inside the prescribed heart rate zone, last 7 days
                                versus the 7 days before
  resting_hr_7d_minus_baseline  7-day average resting heart rate minus the prescription baseline
  steps_7d_vs_prior_pct         % change in average daily steps, last 7 days versus the 7 days before
  hours_since_last_reading      hours since the newest reading from any device
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from statistics import mean
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import ExercisePrescription, Patient
from app.repositories.monitoring import ActivityRepository, VitalSignRepository

SESSION_MIN_MINUTES = 10           # a day with at least this much exercise-phase data counts as a session
MAX_GAP = timedelta(minutes=2)     # a gap longer than this between readings is not counted as exercise time
LOOKBACK_DAYS = 28
DEFAULT_SESSIONS_PER_WEEK = 3


@dataclass
class PatternResult:
    value: float
    title: str
    details: dict = field(default_factory=dict)


class PatternMetrics:
    def __init__(self, session: Session, patient: Patient, rx: ExercisePrescription | None, now: datetime) -> None:
        self.patient, self.rx, self.now = patient, rx, now
        self.vitals, self.activity = VitalSignRepository(session), ActivityRepository(session)
        self.tz = ZoneInfo(patient.timezone or "America/Denver")
        self.today = now.astimezone(self.tz).date()
        self._exercise: dict[date, list[tuple[datetime, int]]] | None = None

    def compute(self, wanted: set[str]) -> dict[str, PatternResult]:
        out: dict[str, PatternResult] = {}
        for metric in wanted:
            fn = getattr(self, metric, None)
            if fn is not None and (result := fn()) is not None:
                out[metric] = result
        return out

    # ---------------------------------------------------------------- helpers
    def _utc(self, d: date) -> datetime:
        return datetime.combine(d, time.min, self.tz).astimezone(timezone.utc)

    def _exercise_by_day(self) -> dict[date, list[tuple[datetime, int]]]:
        if self._exercise is None:
            rows = self.vitals.exercise_heart_rates(self.patient.patient_id, self._utc(self.today - timedelta(days=LOOKBACK_DAYS)),
                                                    self._utc(self.today + timedelta(days=1)))
            by_day: dict[date, list[tuple[datetime, int]]] = defaultdict(list)
            for at, hr in rows:
                by_day[at.astimezone(self.tz).date()].append((at, hr))
            self._exercise = by_day
        return self._exercise

    @staticmethod
    def _minutes(readings: list[tuple[datetime, int]], lo: int | None = None, hi: int | None = None) -> float:
        """exercise minutes from reading spacing (gaps capped), optionally only while heart rate was in [lo, hi]"""
        total = 0.0
        for (at, hr), (nxt, _) in zip(readings, readings[1:], strict=False):
            if lo is None or lo <= hr <= hi:
                total += min(nxt - at, MAX_GAP).total_seconds() / 60
        return total

    def _week(self, offset_weeks: int) -> tuple[date, date]:
        end = self.today - timedelta(days=1 + 7 * offset_weeks)
        return end - timedelta(days=6), end

    # ---------------------------------------------------------------- metrics
    def consecutive_missed_sessions(self) -> PatternResult | None:
        per_week = self.rx.sessions_per_week if self.rx else DEFAULT_SESSIONS_PER_WEEK
        interval = 7 / per_week
        days = self._exercise_by_day()
        sessions = sorted(d for d, r in days.items() if d < self.today and self._minutes(r) >= SESSION_MIN_MINUTES)
        start = max(self.patient.enrollment_date or self.today, self.today - timedelta(days=LOOKBACK_DAYS))
        last = sessions[-1] if sessions else start
        through = self.today - timedelta(days=1)
        days_since = (through - last).days
        if days_since < 0:
            return None
        missed = math.floor(days_since / interval)
        label = f"last session {last:%b %d}" if sessions else f"no sessions since {last:%b %d}"
        return PatternResult(missed, f"Missed {missed} consecutive prescribed sessions ({label})",
                             {"last_session_date": last.isoformat() if sessions else None,
                              "days_since_last_session": days_since, "sessions_per_week": per_week})

    def minutes_in_zone_wow_pct(self) -> PatternResult | None:
        if self.rx is None:
            return None
        lo, hi = self.rx.target_hr_min, self.rx.target_hr_max
        days = self._exercise_by_day()

        def total(week: tuple[date, date]) -> float:
            return sum(self._minutes(r, lo, hi) for d, r in days.items() if week[0] <= d <= week[1])

        this, prior = total(self._week(0)), total(self._week(1))
        if prior < 30:                      # not enough baseline to call a decline
            return None
        pct = (this - prior) / prior * 100
        return PatternResult(pct, f"Minutes in target zone down {abs(pct):.0f}% week over week "
                                  f"({this:.0f} vs {prior:.0f} min)" if pct < 0 else
                             f"Minutes in target zone up {pct:.0f}% week over week",
                             {"this_week_minutes": round(this, 1), "prior_week_minutes": round(prior, 1),
                              "target_zone": [lo, hi]})

    def resting_hr_7d_minus_baseline(self) -> PatternResult | None:
        start, end = self._week(0)
        recent = [a.resting_hr for a in self.activity.list(self.patient.patient_id, start, end) if a.resting_hr]
        if len(recent) < 4:
            return None
        if self.rx is not None:
            baseline, basis = float(self.rx.resting_hr_baseline), "prescription"
        else:
            earlier = [a.resting_hr for a in self.activity.list(self.patient.patient_id, start - timedelta(days=21),
                                                                 start - timedelta(days=1)) if a.resting_hr]
            if len(earlier) < 5:
                return None
            baseline, basis = mean(earlier), "prior 3 weeks"
        avg = mean(recent)
        diff = avg - baseline
        return PatternResult(diff, f"Resting heart rate {abs(diff):.0f} bpm {'above' if diff >= 0 else 'below'} "
                                   f"baseline ({avg:.0f} vs {baseline:.0f} bpm)",
                             {"avg_7d": round(avg, 1), "baseline": round(baseline, 1), "baseline_source": basis,
                              "days": len(recent)})

    def steps_7d_vs_prior_pct(self) -> PatternResult | None:
        w0, w1 = self._week(0), self._week(1)
        rows = self.activity.list(self.patient.patient_id, w1[0], w0[1])
        this = [a.steps for a in rows if w0[0] <= a.activity_date <= w0[1]]
        prior = [a.steps for a in rows if w1[0] <= a.activity_date <= w1[1]]
        if len(this) < 4 or len(prior) < 4 or mean(prior) < 500:
            return None
        a, b = mean(this), mean(prior)
        pct = (a - b) / b * 100
        return PatternResult(pct, f"Daily steps {'down' if pct < 0 else 'up'} {abs(pct):.0f}% "
                                  f"({a:,.0f} vs {b:,.0f} per day)",
                             {"avg_steps_7d": round(a), "avg_steps_prior_7d": round(b)})

    def hours_since_last_reading(self) -> PatternResult | None:
        last = self.vitals.last_reading_at(self.patient.patient_id)
        if last is None:
            return None
        hours = (self.now - last).total_seconds() / 3600
        return PatternResult(hours, f"No readings received for {hours:.0f} hours",
                             {"last_reading_at": last.isoformat()})
