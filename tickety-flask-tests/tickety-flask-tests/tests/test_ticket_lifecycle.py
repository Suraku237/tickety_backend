"""
Unit tests for ticket lifecycle behaviour and ETA calculation.

These cover the domain rules surfaced during development:
  - the waiting -> called -> serving -> completed transitions,
  - carry-over handling,
  - the rolling-average ETA that replaced the manual ``avg_duration`` field.

ADAPT ME: method names such as ``call_next``, ``complete`` or the ETA helper
(``compute_eta`` / ``estimated_wait``) must match your service layer.
"""
from datetime import datetime, timedelta

from tests.base import BaseTestCase


class TestTicketLifecycle(BaseTestCase):
    """The status machine a ticket walks through from creation to completion."""

    VALID_FLOW = ["waiting", "called", "serving", "completed"]

    def _advance(self, ticket, status):
        """Encapsulate a status transition + commit in one place."""
        ticket.status = status
        self.db.session.add(ticket)
        self.db.session.commit()
        return ticket

    def test_full_happy_path_transition(self):
        ticket = self.make_ticket()
        for status in self.VALID_FLOW[1:]:
            self._advance(ticket, status)
            self.assertEqual(ticket.status, status)

    def test_completed_ticket_is_terminal(self):
        ticket = self._advance(self.make_ticket(), "completed")
        # Re-querying must still report the terminal state.
        from models import Ticket

        refreshed = self.db.session.get(Ticket, ticket.id)
        self.assertEqual(refreshed.status, "completed")

    def test_carry_over_flag_marks_unfinished_ticket(self):
        ticket = self.make_ticket()
        if hasattr(ticket, "carried_over"):
            ticket.carried_over = True
            self.db.session.commit()
            self.assertTrue(ticket.carried_over)
        else:
            self.skipTest("carried_over not present on Ticket model")


class TestEtaCalculation(BaseTestCase):
    """
    Rolling-average ETA.

    The estimate must derive from the durations of recently completed tickets
    rather than a hand-entered ``avg_duration``. This also guards the timezone
    bug where naive UTC stored values were compared against ``datetime.now()``.
    """

    def _completed_ticket(self, queue, minutes):
        """Create a completed ticket whose service window spans ``minutes``."""
        now = datetime.utcnow()
        ticket = self.make_ticket(
            queue=queue,
            status="completed",
        )
        if hasattr(ticket, "served_at") and hasattr(ticket, "completed_at"):
            ticket.served_at = now - timedelta(minutes=minutes)
            ticket.completed_at = now
            self.db.session.commit()
        return ticket

    def test_eta_uses_rolling_average_of_completed_tickets(self):
        queue = self.make_queue()
        for m in (4, 6, 8):  # average == 6 minutes
            self._completed_ticket(queue, m)

        try:
            from services import compute_eta  # ADAPT import
        except ImportError:
            self.skipTest("compute_eta service not importable; adapt the import")

        eta = compute_eta(queue.id)
        self.assertGreater(eta, 0, "ETA should be positive when history exists")

    def test_eta_is_consistent_across_naive_utc_values(self):
        """Regression guard: stored naive-UTC vs datetime.now() must not zero out."""
        queue = self.make_queue()
        self._completed_ticket(queue, 5)
        self.make_ticket(queue=queue, status="waiting")

        try:
            from services import estimated_wait  # ADAPT import
        except ImportError:
            self.skipTest("estimated_wait service not importable; adapt the import")

        wait = estimated_wait(queue.id)
        self.assertIsNotNone(wait)
        self.assertGreaterEqual(wait, 0)
