"""
Unit tests for services/schedule_service.py -> ScheduleService.

Covers the naive-UTC datetime convention, estimated serve-time arithmetic,
open/closed determination, closing-time overflow detection, the warning
payload, the effective-average fallback, and queue recalculation.
"""
import unittest
from datetime import datetime, time, timedelta

from services.schedule_service import ScheduleService, _utcnow, _strip_tz


class _FakeSchedule:
    """Lightweight stand-in for a ServiceSchedule row (no DB needed here)."""
    def __init__(self, is_open=True, opening="00:00", closing="23:59",
                 avg_duration=10):
        self.is_open = is_open
        oh, om = (int(x) for x in opening.split(":"))
        ch, cm = (int(x) for x in closing.split(":"))
        self.opening_time = time(oh, om)
        self.closing_time = time(ch, cm)
        self.avg_duration = avg_duration


class _FakeTicket:
    def __init__(self, id, code, position, est=None, identifier=None):
        self.id = id
        self.code = code
        self.position = position
        self.estimated_serve_at = est
        self.customer_identifier = identifier


class TestScheduleHelpers(unittest.TestCase):
    def test_utcnow_is_naive(self):
        self.assertIsNone(_utcnow().tzinfo)

    def test_strip_tz_removes_tzinfo(self):
        from datetime import timezone
        aware = datetime(2024, 1, 1, tzinfo=timezone.utc)
        self.assertIsNone(_strip_tz(aware).tzinfo)
        self.assertIsNone(_strip_tz(None))


class TestScheduleService(unittest.TestCase):
    def setUp(self):
        self.svc = ScheduleService()

    # --- compute_estimated_serve_at ---
    def test_estimate_is_position_times_duration(self):
        base = datetime(2024, 1, 1, 9, 0, 0)
        est = self.svc.compute_estimated_serve_at(3, 5, base_time=base)
        self.assertEqual(est, base + timedelta(minutes=15))
        self.assertIsNone(est.tzinfo)  # stays naive

    def test_estimate_position_zero_equals_base(self):
        base = datetime(2024, 1, 1, 9, 0, 0)
        self.assertEqual(self.svc.compute_estimated_serve_at(0, 10, base), base)

    # --- is_open_now ---
    def test_is_open_now_false_without_schedule(self):
        self.assertFalse(self.svc.is_open_now(None))

    def test_is_open_now_false_when_marked_closed(self):
        self.assertFalse(self.svc.is_open_now(_FakeSchedule(is_open=False)))

    def test_is_open_now_true_within_hours(self):
        # Wide-open window guarantees "now" is inside it.
        self.assertTrue(
            self.svc.is_open_now(_FakeSchedule(opening="00:00", closing="23:59"))
        )

    # --- exceeds_closing_time ---
    def test_exceeds_closing_true_after_close(self):
        sch = _FakeSchedule(opening="08:00", closing="17:00")
        today = _utcnow().date()
        after_close = datetime.combine(today, time(18, 0))
        self.assertTrue(self.svc.exceeds_closing_time(after_close, sch))

    def test_exceeds_closing_false_before_close(self):
        sch = _FakeSchedule(opening="08:00", closing="17:00")
        today = _utcnow().date()
        before_close = datetime.combine(today, time(9, 0))
        self.assertFalse(self.svc.exceeds_closing_time(before_close, sch))

    def test_exceeds_closing_false_without_schedule_or_estimate(self):
        self.assertFalse(self.svc.exceeds_closing_time(datetime.utcnow(), None))
        self.assertFalse(
            self.svc.exceeds_closing_time(None, _FakeSchedule())
        )

    # --- closing_warning_payload ---
    def test_warning_payload_no_schedule(self):
        self.assertEqual(self.svc.closing_warning_payload(None, []),
                         {"warning": False})

    def test_warning_payload_with_affected_tickets(self):
        sch = _FakeSchedule(closing="17:00")
        tickets = [_FakeTicket(1, "A1", 5,
                               est=datetime(2024, 1, 1, 18, 0),
                               identifier="x@y.com")]
        payload = self.svc.closing_warning_payload(sch, tickets)
        self.assertTrue(payload["warning"])
        self.assertEqual(payload["affected_count"], 1)
        self.assertEqual(payload["affected_tickets"][0]["code"], "A1")

    # --- effective_avg with a fake repo ---
    def test_effective_avg_uses_repo_value(self):
        class _Repo:
            def compute_rolling_avg_duration(self, queue_id, fallback):
                return 7
        sch = _FakeSchedule(avg_duration=10)
        self.assertEqual(self.svc.effective_avg(_Repo(), 1, sch), 7)

    def test_effective_avg_falls_back_on_repo_error(self):
        class _Repo:
            def compute_rolling_avg_duration(self, queue_id, fallback):
                raise RuntimeError("db down")
        sch = _FakeSchedule(avg_duration=12)
        self.assertEqual(self.svc.effective_avg(_Repo(), 1, sch), 12)

    def test_effective_avg_default_when_no_schedule(self):
        class _Repo:
            def compute_rolling_avg_duration(self, queue_id, fallback):
                return fallback
        self.assertEqual(self.svc.effective_avg(_Repo(), 1, None), 10)

    # --- recalculate_queue ---
    def test_recalculate_assigns_estimates_by_position(self):
        base = datetime(2024, 1, 1, 9, 0, 0)
        tickets = [_FakeTicket(1, "A1", 0), _FakeTicket(2, "A2", 1),
                   _FakeTicket(3, "A3", 2)]
        self.svc.recalculate_queue(tickets, avg_duration=10, base_time=base)
        self.assertEqual(tickets[0].estimated_serve_at, base)
        self.assertEqual(tickets[1].estimated_serve_at,
                         base + timedelta(minutes=10))
        self.assertEqual(tickets[2].estimated_serve_at,
                         base + timedelta(minutes=20))

    def test_recalculate_skips_tickets_without_position(self):
        base = datetime(2024, 1, 1, 9, 0, 0)
        t = _FakeTicket(1, "A1", None)
        self.svc.recalculate_queue([t], avg_duration=10, base_time=base)
        self.assertIsNone(t.estimated_serve_at)


if __name__ == "__main__":
    unittest.main()
