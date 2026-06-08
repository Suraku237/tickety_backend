"""
Base test case for the Tickety Flask backend.

Object-Oriented design notes
-----------------------------
- ``BaseTestCase`` encapsulates all shared setup/teardown logic (app context,
  in-memory database, test client) behind a single reusable class.
- Concrete test classes *inherit* from it, so no fixture wiring is duplicated.
- Helper behaviour (creating users, queues, tickets, authenticating) is exposed
  as protected-style methods so subclasses compose tests from a small vocabulary.

ADAPT ME: update the import block below to match your real module names
(e.g. ``from app import create_app, db`` or ``from backend import app, db``).
"""
import unittest

try:
    # Preferred: an application factory.
    from app import create_app, db  # type: ignore
    _HAS_FACTORY = True
except ImportError:  # pragma: no cover - fallback for a module-level app
    from app import app as _app, db  # type: ignore
    _HAS_FACTORY = False


class BaseTestCase(unittest.TestCase):
    """Reusable foundation for every Tickety backend test."""

    #: Overridable test configuration. Subclasses may extend via ``config_overrides``.
    BASE_CONFIG = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "WTF_CSRF_ENABLED": False,
        "SECRET_KEY": "test-secret-key",
    }

    #: Per-class configuration tweaks; merged over ``BASE_CONFIG``.
    config_overrides: dict = {}

    def setUp(self) -> None:
        """Spin up an isolated app + fresh schema for each test method."""
        config = {**self.BASE_CONFIG, **self.config_overrides}

        if _HAS_FACTORY:
            self.app = create_app(config)
        else:
            self.app = _app
            self.app.config.update(config)

        self.db = db
        self._ctx = self.app.app_context()
        self._ctx.push()
        self.db.create_all()
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        """Drop the schema and pop the context so tests stay independent."""
        self.db.session.remove()
        self.db.drop_all()
        self._ctx.pop()

    # ----------------------------------------------------------------- #
    # Encapsulated domain helpers (override the bodies to fit your code) #
    # ----------------------------------------------------------------- #
    def make_user(self, **overrides):
        """Persist and return a ``User``. ADAPT field names to your model."""
        from models import User  # local import keeps base import-safe

        defaults = {"name": "Test User", "email": "user@example.com"}
        defaults.update(overrides)
        user = User(**defaults)
        if hasattr(user, "set_password"):
            user.set_password(overrides.get("password", "password123"))
        self.db.session.add(user)
        self.db.session.commit()
        return user

    def make_queue(self, **overrides):
        """Persist and return a ``Queue``. ADAPT to your model."""
        from models import Queue

        defaults = {"name": "Front Desk"}
        defaults.update(overrides)
        queue = Queue(**defaults)
        self.db.session.add(queue)
        self.db.session.commit()
        return queue

    def make_ticket(self, queue=None, **overrides):
        """Persist and return a ``Ticket`` attached to ``queue``."""
        from models import Ticket

        queue = queue or self.make_queue()
        defaults = {"queue_id": queue.id, "status": "waiting"}
        defaults.update(overrides)
        ticket = Ticket(**defaults)
        self.db.session.add(ticket)
        self.db.session.commit()
        return ticket

    def auth_headers(self, token: str) -> dict:
        """Build a bearer-auth header dict for client requests."""
        return {"Authorization": f"Bearer {token}"}
