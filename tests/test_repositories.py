"""
Unit tests for the simpler repositories:
  - repositories/user_repository.py   -> UserRepository
  - repositories/queue_repository.py  -> QueueRepository
  - repositories/invite_repository.py -> InviteRepository

These exercise real queries against the in-memory SQLite database.
"""
from datetime import datetime, timezone

from tests.base import BaseBackendTest
from repositories.user_repository import UserRepository
from repositories.queue_repository import QueueRepository
from repositories.invite_repository import InviteRepository


class TestUserRepository(BaseBackendTest):
    def setUp(self):
        super().setUp()
        self.repo = UserRepository()

    def test_find_by_email(self):
        self.make_user(email="find@me.com")
        self.assertIsNotNone(self.repo.find_by_email("find@me.com"))
        self.assertIsNone(self.repo.find_by_email("nobody@x.com"))

    def test_find_by_username_and_id(self):
        user = self.make_user(username="zoe", email="zoe@x.com")
        self.assertEqual(self.repo.find_by_username("zoe").id, user.id)
        self.assertEqual(self.repo.find_by_id(user.id).username, "zoe")

    def test_find_by_role(self):
        self.make_user(username="c1", email="c1@x.com", role="client")
        self.make_user(username="a1", email="a1@x.com", role="admin")
        self.make_user(username="a2", email="a2@x.com", role="admin")
        self.assertEqual(len(self.repo.find_by_role("admin")), 2)
        self.assertEqual(len(self.repo.find_by_role("client")), 1)

    def test_create_stages_user_without_commit_until_save(self):
        user = self.repo.create("newbie", "new@x.com", b"hashbytes", "client")
        self.repo.save()
        self.assertIsNotNone(user.id)
        # create() must store the verified flag as False initially
        self.assertFalse(user.verified)
        self.assertEqual(user.password, b"hashbytes")

    def test_delete_removes_user(self):
        user = self.make_user(email="del@x.com")
        self.repo.delete(user)
        self.repo.save()
        self.assertIsNone(self.repo.find_by_email("del@x.com"))

    def test_rollback_discards_staged_changes(self):
        self.repo.create("temp", "temp@x.com", b"h", "client")
        self.repo.rollback()
        self.assertIsNone(self.repo.find_by_email("temp@x.com"))


class TestQueueRepository(BaseBackendTest):
    def setUp(self):
        super().setUp()
        self.repo = QueueRepository()

    def test_create_and_find_by_id(self):
        svc = self.make_service()
        q = self.repo.create(svc.id, "Walk-ins", "WI", "#fff")
        self.repo.save()
        self.assertEqual(self.repo.find_by_id(q.id).name, "Walk-ins")

    def test_find_by_service_ordered(self):
        svc = self.make_service()
        self.repo.create(svc.id, "First", "F", "#fff")
        self.repo.create(svc.id, "Second", "S", "#000")
        self.repo.save()
        result = self.repo.find_by_service(svc.id)
        self.assertEqual(len(result), 2)

    def test_find_by_token(self):
        q = self.make_queue()
        self.assertEqual(self.repo.find_by_token(q.join_token).id, q.id)
        self.assertIsNone(self.repo.find_by_token("does-not-exist"))

    def test_find_by_code_and_service_scoped(self):
        svc_a = self.make_service(name="A")
        svc_b = self.make_service(name="B")
        self.repo.create(svc_a.id, "Q", "DUP", "#fff")
        self.repo.create(svc_b.id, "Q", "DUP", "#fff")
        self.repo.save()
        found = self.repo.find_by_code_and_service("DUP", svc_a.id)
        self.assertEqual(found.service_id, svc_a.id)


class TestInviteRepository(BaseBackendTest):
    def setUp(self):
        super().setUp()
        self.repo = InviteRepository()

    def test_get_expiry_is_in_future_by_configured_hours(self):
        expiry = self.repo.get_expiry()
        delta = expiry - datetime.now(timezone.utc)
        # 48h default, allow a minute of slack
        self.assertGreater(delta.total_seconds(), 47 * 3600)

    def test_create_and_find_by_token(self):
        svc = self.make_service()
        inv = self.repo.create(svc.id, "manager")
        self.repo.save()
        self.assertEqual(self.repo.find_by_token(inv.token).admin_role, "manager")

    def test_find_by_service_excludes_used_and_expired(self):
        svc = self.make_service()
        good = self.repo.create(svc.id, "agent")
        used = self.repo.create(svc.id, "agent")
        used.consume()
        self.repo.save()
        active = self.repo.find_by_service(svc.id)
        ids = {i.id for i in active}
        self.assertIn(good.id, ids)
        self.assertNotIn(used.id, ids)

    def test_consume_marks_used(self):
        svc = self.make_service()
        inv = self.repo.create(svc.id, "agent")
        self.repo.save()
        self.repo.consume(inv)
        self.repo.save()
        self.assertTrue(self.repo.find_by_token(inv.token).used)
