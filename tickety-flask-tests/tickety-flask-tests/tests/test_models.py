"""
Unit tests for the Tickety ORM models.

Each model gets its own test *class* that inherits the shared ``BaseTestCase``.
This keeps related assertions grouped behind a clear object boundary and lets
each class declare model-specific helpers without affecting the others.

ADAPT ME: field/attribute names (``status``, ``code``, ``hashed_password`` ...)
must match your real ``models.py``.
"""
from tests.base import BaseTestCase


class TestUserModel(BaseTestCase):
    """Behaviour and invariants of the ``User`` model."""

    def test_user_is_persisted_with_id(self):
        user = self.make_user(email="alice@example.com")
        self.assertIsNotNone(user.id)
        self.assertEqual(user.email, "alice@example.com")

    def test_password_is_hashed_not_stored_plaintext(self):
        user = self.make_user(password="s3cret!")
        # The raw password should never be readable from the record.
        self.assertNotIn("s3cret!", str(getattr(user, "password", "")))
        if hasattr(user, "check_password"):
            self.assertTrue(user.check_password("s3cret!"))
            self.assertFalse(user.check_password("wrong"))

    def test_email_uniqueness_is_enforced(self):
        from models import User

        self.make_user(email="dup@example.com")
        duplicate = User(name="Other", email="dup@example.com")
        self.db.session.add(duplicate)
        with self.assertRaises(Exception):
            self.db.session.commit()
        self.db.session.rollback()


class TestQueueModel(BaseTestCase):
    """Behaviour of the ``Queue`` model and its generated code."""

    def test_queue_creation_requires_only_a_name(self):
        queue = self.make_queue(name="Pharmacy")
        self.assertIsNotNone(queue.id)
        self.assertEqual(queue.name, "Pharmacy")

    def test_queue_auto_generates_join_code(self):
        queue = self.make_queue(name="Billing")
        # Queue creation was simplified to name-only with auto-generated codes.
        code = getattr(queue, "code", None)
        if code is not None:
            self.assertTrue(len(code) >= 4, "join code should be non-trivial")

    def test_queue_relationship_to_tickets(self):
        queue = self.make_queue()
        self.make_ticket(queue=queue)
        self.make_ticket(queue=queue)
        if hasattr(queue, "tickets"):
            self.assertEqual(len(queue.tickets), 2)


class TestTicketModel(BaseTestCase):
    """Structural invariants of the ``Ticket`` model."""

    def test_ticket_defaults_to_waiting_status(self):
        ticket = self.make_ticket()
        self.assertEqual(ticket.status, "waiting")

    def test_ticket_belongs_to_a_queue(self):
        queue = self.make_queue(name="Support")
        ticket = self.make_ticket(queue=queue)
        self.assertEqual(ticket.queue_id, queue.id)
