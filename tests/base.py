"""
Shared base for the Tickety Flask backend unit tests.

Design
------
The production app factory (`create_app`) reads `DATABASE_URL` from the
environment, configures CORS, registers every blueprint, and starts an
APScheduler background job. None of that is wanted in a unit test, so instead
of booting the whole stack we build a *minimal* Flask app, bind the real
`db` (the same SQLAlchemy instance the models use) to an isolated in-memory
SQLite database, and create the schema fresh for every test.

`BaseBackendTest` is the reusable foundation (OOP: inheritance + encapsulated
setup/teardown). Concrete test classes extend it and use the `make_*`
factory helpers to build a real object graph (User -> Service -> Queue ->
Ticket) without repeating boilerplate.

Run from the backend project root so `from models import ...` resolves:
    pytest
"""
import os
import unittest
from datetime import datetime, time, timezone, timedelta

# A value must exist before models import (the factory reads it in prod);
# the base class overrides the URI on its own app anyway.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from flask import Flask  # noqa: E402

from models import (  # noqa: E402
    db,
    User,
    Service,
    Admin,
    Queue,
    Ticket,
    InviteToken,
    ServiceSchedule,
    Notification,
)


class BaseBackendTest(unittest.TestCase):
    """Foundation for every backend test: isolated app + fresh schema."""

    def setUp(self) -> None:
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            BASE_URL="http://testhost",
            BREVO_API_KEY="test-brevo-key",
            MAIL_DEFAULT_SENDER="noreply@tickety.test",
        )
        db.init_app(self.app)
        self._ctx = self.app.app_context()
        self._ctx.push()
        db.create_all()
        self.db = db

    def tearDown(self) -> None:
        db.session.remove()
        db.drop_all()
        self._ctx.pop()

    # ------------------------------------------------------------------ #
    # Object-graph factory helpers (use the REAL model field names)       #
    # ------------------------------------------------------------------ #
    def make_user(self, *, username="alice", email="alice@example.com",
                  password=b"hashed-bytes", role="client", verified=False) -> User:
        user = User(username=username, email=email, password=password,
                    role=role, verified=verified)
        db.session.add(user)
        db.session.commit()
        return user

    def make_service(self, *, name="Front Desk", owner=None) -> Service:
        owner = owner or self.make_user()
        service = Service(name=name, owner_id=owner.id)
        db.session.add(service)
        db.session.commit()
        return service

    def make_queue(self, *, service=None, name="General", code="GEN",
                   color="#DC0F0F") -> Queue:
        service = service or self.make_service()
        queue = Queue(service_id=service.id, name=name, code=code, color=color)
        db.session.add(queue)
        db.session.commit()
        return queue

    def make_ticket(self, *, queue=None, code="GEN-001", status="pending",
                    priority="normal", position=0, customer_identifier=None,
                    issued_at=None, called_at=None) -> Ticket:
        queue = queue or self.make_queue()
        ticket = Ticket(
            queue_id=queue.id,
            service_id=queue.service_id,
            code=code,
            status=status,
            priority=priority,
            position=position,
            customer_identifier=customer_identifier,
        )
        if issued_at is not None:
            ticket.issued_at = issued_at
        if called_at is not None:
            ticket.called_at = called_at
        db.session.add(ticket)
        db.session.commit()
        return ticket

    def make_schedule(self, *, service=None, day_of_week=None, is_open=True,
                      opening="08:00", closing="17:00", avg_duration=10
                      ) -> ServiceSchedule:
        service = service or self.make_service()
        oh, om = (int(x) for x in opening.split(":"))
        ch, cm = (int(x) for x in closing.split(":"))
        schedule = ServiceSchedule(
            service_id=service.id,
            day_of_week=day_of_week,
            is_open=is_open,
            opening_time=time(oh, om),
            closing_time=time(ch, cm),
            avg_duration=avg_duration,
        )
        db.session.add(schedule)
        db.session.commit()
        return schedule

    # Convenience re-exports so subclasses need fewer imports.
    utcnow = staticmethod(lambda: datetime.now(timezone.utc))
    naive_utcnow = staticmethod(datetime.utcnow)
    timedelta = timedelta
