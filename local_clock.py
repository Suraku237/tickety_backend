"""
Local clock for the service's timezone.

PROBLEM THIS SOLVES:
  Schedule opening/closing times are entered by the boss in LOCAL time
  (e.g. Cameroon, UTC+1), but the backend stores and compares datetimes
  in UTC. Comparing a local closing time against UTC "now" made a
  10:00 closing take effect at 11:00 local — services closed 1 hour late.

DESIGN (OOP):
  - Single Responsibility: all "what time is it for the business?"
    questions are answered here and nowhere else.
  - Encapsulation: the offset source (env var) is a private detail;
    callers only use the public now_/local_/to-UTC methods.

CONFIGURATION:
  APP_TZ_OFFSET_MINUTES  — minutes ahead of UTC for the business's
  local timezone. Cameroon (WAT, UTC+1) = 60. Defaults to 0 (UTC).
  Add to .env:
      APP_TZ_OFFSET_MINUTES=60
"""

import os
from datetime import datetime, timedelta, time, date


class LocalClock:

    _ENV_KEY = "APP_TZ_OFFSET_MINUTES"

    def __init__(self, offset_minutes: int | None = None):
        """
        offset_minutes overrides the environment (useful for tests);
        otherwise the offset is read from APP_TZ_OFFSET_MINUTES (default 0).
        """
        if offset_minutes is not None:
            self._offset = timedelta(minutes=offset_minutes)
        else:
            try:
                self._offset = timedelta(minutes=int(os.getenv(self._ENV_KEY, "0")))
            except ValueError:
                self._offset = timedelta(0)

    # ---------------------------------------------------------
    # "Now" in each frame of reference (both returned naive,
    # matching the storage convention used across the backend).
    # ---------------------------------------------------------
    def now_utc(self) -> datetime:
        """Current UTC time, naive (matches DB storage convention)."""
        return datetime.utcnow()

    def now_local(self) -> datetime:
        """Current business-local time, naive."""
        return self.now_utc() + self._offset

    def local_time(self) -> time:
        """Current business-local wall-clock time (for schedule checks)."""
        return self.now_local().time()

    def local_today(self) -> date:
        """Today's date in the business's timezone."""
        return self.now_local().date()

    def local_weekday(self) -> int:
        """Weekday (0=Mon … 6=Sun) in the business's timezone."""
        return self.now_local().weekday()

    # ---------------------------------------------------------
    # Frame conversion — for comparing local schedule times
    # against stored UTC timestamps.
    # ---------------------------------------------------------
    def local_to_utc(self, dt_local: datetime) -> datetime:
        """Convert a naive business-local datetime to naive UTC."""
        return dt_local - self._offset

    def utc_to_local(self, dt_utc: datetime) -> datetime:
        """Convert a naive UTC datetime to naive business-local."""
        return dt_utc + self._offset

    def __repr__(self):
        mins = int(self._offset.total_seconds() // 60)
        return f"<LocalClock offset={mins:+d}min>"