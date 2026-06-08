"""
Unit tests for repositories/ticket_repository.py -> TicketRepository.

This is the richest repository: position allocation, priority-aware
reindexing, the rolling-average duration computation, and the various
status-filtered queries the web + mobile clients depend on.
"""
from datetime import datetime, timedelta

from tests.base import BaseBackendTest
from repositories.ticket_repository import TicketRepository


class TestTicketRepository(BaseBackendTest):
    def setUp(self):
        super().setUp()
        self.repo = TicketRepository()
        self.queue = self.make_queue()

    # --- status constants / validity sets ---
    def test_valid_status_and_priority_sets(self):
        self.assertIn("served", self.repo.VALID_STATUSES)
        self.assertIn("urgent", self.repo.VALID_PRIORITIES)

    # --- next_position ---
    def test_next_position_starts_at_zero(self):
        self.assertEqual(self.repo.next_position(self.queue.id), 0)

    def test_next_position_after_existing(self):
        self.make_ticket(queue=self.queue, code="A1", status="pending", position=0)
        self.make_ticket(queue=self.queue, code="A2", status="pending", position=1)
        self.assertEqual(self.repo.next_position(self.queue.id), 2)

    # --- next_code_number ---
    def test_next_code_number_is_count_plus_one(self):
        self.make_ticket(queue=self.queue, code="A1")
        self.assertEqual(self.repo.next_code_number(self.queue.id), 2)

    # --- create ---
    def test_create_stages_ticket(self):
        t = self.repo.create(self.queue.id, self.queue.service_id, "GEN-001", 0,
                             customer_identifier="cust@x.com")
        self.repo.save()
        self.assertIsNotNone(t.id)
        self.assertEqual(t.status, "pending")  # model default

    # --- find_by_queue excludes served ---
    def test_find_by_queue_excludes_served(self):
        self.make_ticket(queue=self.queue, code="A1", status="pending", position=0)
        self.make_ticket(queue=self.queue, code="A2", status="served", position=1)
        result = self.repo.find_by_queue(self.queue.id)
        codes = {t.code for t in result}
        self.assertIn("A1", codes)
        self.assertNotIn("A2", codes)

    # --- customer identifier lookups (case-insensitive) ---
    def test_find_by_customer_identifier_is_case_insensitive(self):
        self.make_ticket(queue=self.queue, code="A1", status="pending",
                         customer_identifier="Customer@X.com")
        result = self.repo.find_by_customer_identifier("customer@x.com")
        self.assertEqual(len(result), 1)

    def test_has_visited_true_even_for_served(self):
        self.make_ticket(queue=self.queue, code="A1", status="served",
                         customer_identifier="visited@x.com")
        self.assertTrue(self.repo.has_visited(self.queue.service_id, "visited@x.com"))
        self.assertFalse(self.repo.has_visited(self.queue.service_id, "never@x.com"))

    def test_has_visited_false_for_empty_identifier(self):
        self.assertFalse(self.repo.has_visited(self.queue.service_id, ""))

    # --- reindex_positions: priority then arrival ---
    def test_reindex_orders_by_priority_then_arrival(self):
        base = datetime(2024, 1, 1, 9, 0, 0)
        # Insert in arrival order: normal, urgent, high
        self.make_ticket(queue=self.queue, code="N", status="pending",
                         priority="normal", position=0, issued_at=base)
        self.make_ticket(queue=self.queue, code="U", status="pending",
                         priority="urgent", position=1,
                         issued_at=base + timedelta(minutes=1))
        self.make_ticket(queue=self.queue, code="H", status="pending",
                         priority="high", position=2,
                         issued_at=base + timedelta(minutes=2))

        self.repo.reindex_positions(self.queue.id)
        self.repo.save()

        by_code = {t.code: t.position for t in self.repo.find_by_queue(self.queue.id)}
        # urgent first (0), high (1), normal last (2)
        self.assertEqual(by_code["U"], 0)
        self.assertEqual(by_code["H"], 1)
        self.assertEqual(by_code["N"], 2)

    def test_reindex_ignores_non_pending(self):
        self.make_ticket(queue=self.queue, code="ACT", status="active", position=0)
        self.make_ticket(queue=self.queue, code="PEN", status="pending", position=5)
        self.repo.reindex_positions(self.queue.id)
        self.repo.save()
        active = next(t for t in self.repo.find_by_queue(self.queue.id)
                      if t.code == "ACT")
        # active ticket position is untouched by reindex
        self.assertEqual(active.position, 0)

    # --- compute_rolling_avg_duration ---
    def test_rolling_avg_falls_back_when_no_samples(self):
        self.assertEqual(
            self.repo.compute_rolling_avg_duration(self.queue.id, fallback=15), 15
        )

    def test_rolling_avg_uses_served_ticket_waits(self):
        base = datetime(2024, 1, 1, 9, 0, 0)
        # Two served tickets with 4 and 6 minute waits -> average 5
        self.make_ticket(queue=self.queue, code="S1", status="served",
                         issued_at=base, called_at=base + timedelta(minutes=4))
        self.make_ticket(queue=self.queue, code="S2", status="served",
                         issued_at=base, called_at=base + timedelta(minutes=6))
        self.assertEqual(
            self.repo.compute_rolling_avg_duration(self.queue.id, fallback=99), 5
        )

    def test_rolling_avg_never_below_one(self):
        base = datetime(2024, 1, 1, 9, 0, 0)
        # Zero-minute wait should clamp to 1
        self.make_ticket(queue=self.queue, code="S1", status="served",
                         issued_at=base, called_at=base)
        self.assertEqual(
            self.repo.compute_rolling_avg_duration(self.queue.id, fallback=99), 1
        )
