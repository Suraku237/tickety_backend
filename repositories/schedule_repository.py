from models import db, ServiceSchedule
from datetime import datetime, timezone, time
from services.local_clock import LocalClock


# =============================================================
# SCHEDULE REPOSITORY
# Responsibilities:
#   - Abstract all DB operations for ServiceSchedule
#   - Resolve the effective schedule for a given day
#     (specific day override takes priority over general)
# OOP Principle: Single Responsibility, Encapsulation
#
# TIMEZONE NOTE:
#   "Today" is resolved in the business's LOCAL timezone via
#   LocalClock — otherwise, between local midnight and the UTC
#   midnight, the previous day's override would wrongly apply.
# =============================================================
class ScheduleRepository:

    def __init__(self, clock: LocalClock | None = None):
        self._clock = clock or LocalClock()

    def find_general(self, service_id: int) -> ServiceSchedule | None:
        """Return the general (day_of_week=NULL) schedule row."""
        return ServiceSchedule.query.filter_by(
            service_id=service_id, day_of_week=None
        ).first()

    def find_by_day(self, service_id: int, day_of_week: int) -> ServiceSchedule | None:
        """Return the specific day override row, or None."""
        return ServiceSchedule.query.filter_by(
            service_id=service_id, day_of_week=day_of_week
        ).first()

    def find_all(self, service_id: int) -> list[ServiceSchedule]:
        """
        Return all schedule rows for a service (general + overrides).
        NULL day_of_week (general) comes first, then days 0–6.
        Uses CASE ordering for MySQL compatibility (NULLS FIRST
        syntax is not supported by MySQL).
        """
        return (ServiceSchedule.query
                .filter_by(service_id=service_id)
                .order_by(
                    # NULL (general) = 0 in sort → appears first
                    # specific days = day_of_week + 1 → appear after
                    db.case(
                        (ServiceSchedule.day_of_week == None, 0),
                        else_=ServiceSchedule.day_of_week + 1
                    ).asc()
                )
                .all())

    def resolve_for_today(self, service_id: int) -> ServiceSchedule | None:
        """
        Return the effective schedule for today (business-local day).
        A specific day override takes priority over the general row.
        day_of_week: 0=Mon … 6=Sun  (matches Python's datetime.weekday())
        """
        today    = self._clock.local_weekday()
        override = self.find_by_day(service_id, today)
        if override:
            return override
        return self.find_general(service_id)

    def upsert_general(self, service_id: int, is_open: bool,
                       opening_time: time, closing_time: time,
                       avg_duration: int) -> ServiceSchedule:
        """
        Create or update the general schedule row.
        Does NOT commit — caller controls the transaction.
        """
        row = self.find_general(service_id)
        if row:
            row.is_open      = is_open
            row.opening_time = opening_time
            row.closing_time = closing_time
            row.avg_duration = avg_duration
        else:
            row = ServiceSchedule(
                service_id   = service_id,
                day_of_week  = None,
                is_open      = is_open,
                opening_time = opening_time,
                closing_time = closing_time,
                avg_duration = avg_duration,
            )
            db.session.add(row)
        return row

    def upsert_day(self, service_id: int, day_of_week: int,
                   is_open: bool, opening_time: time,
                   closing_time: time, avg_duration: int) -> ServiceSchedule:
        """
        Create or update a specific day override row.
        Does NOT commit — caller controls the transaction.
        """
        row = self.find_by_day(service_id, day_of_week)
        if row:
            row.is_open      = is_open
            row.opening_time = opening_time
            row.closing_time = closing_time
            row.avg_duration = avg_duration
        else:
            row = ServiceSchedule(
                service_id   = service_id,
                day_of_week  = day_of_week,
                is_open      = is_open,
                opening_time = opening_time,
                closing_time = closing_time,
                avg_duration = avg_duration,
            )
            db.session.add(row)
        return row

    def delete_day(self, service_id: int, day_of_week: int):
        """Remove a specific day override, reverting to general schedule."""
        row = self.find_by_day(service_id, day_of_week)
        if row:
            db.session.delete(row)

    def save(self):     db.session.commit()
    def rollback(self): db.session.rollback()