"""
Unit tests for the service layer + remaining repositories:
  - services/otp_service.py             -> OTPService
  - services/notification_service.py    -> NotificationService
  - repositories/notification_repository.py -> NotificationRepository
  - repositories/otp_repository.py      -> OTPRepository

External email I/O (Brevo via `requests`) is mocked so no network is touched.
"""
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from tests.base import BaseBackendTest
from services.otp_service import OTPService
from services.notification_service import NotificationService
from repositories.notification_repository import NotificationRepository
from repositories.otp_repository import OTPRepository
from models import PendingRegistration


class TestOTPService(BaseBackendTest):
    def setUp(self):
        super().setUp()
        self.svc = OTPService()

    def test_generate_is_six_digits(self):
        code = self.svc.generate()
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())

    def test_generate_zero_padded(self):
        # Force a tiny random value to confirm zfill keeps 6 chars.
        with patch("services.otp_service.secrets.randbelow", return_value=7):
            self.assertEqual(self.svc.generate(), "000007")

    @patch("services.otp_service.requests.post")
    def test_send_returns_true_on_2xx(self, mock_post):
        mock_post.return_value = MagicMock(status_code=201, text="ok")
        # within app context (BaseBackendTest) so current_app.config works
        self.assertTrue(self.svc.send("u@x.com", "user", "123456"))
        mock_post.assert_called_once()

    @patch("services.otp_service.requests.post")
    def test_send_returns_false_on_error_status(self, mock_post):
        mock_post.return_value = MagicMock(status_code=500, text="err")
        self.assertFalse(self.svc.send("u@x.com", "user", "123456"))

    @patch("services.otp_service.requests.post",
           side_effect=__import__("requests").RequestException("boom"))
    def test_send_returns_false_on_network_exception(self, _mock):
        self.assertFalse(self.svc.send("u@x.com", "user", "123456"))


class TestNotificationRepository(BaseBackendTest):
    def setUp(self):
        super().setUp()
        self.repo = NotificationRepository()
        self.service = self.make_service()

    def test_create_and_find_by_service(self):
        self.repo.create(self.service.id, NotificationRepository.TYPE_QUEUE_CREATED,
                         "Queue created: X")
        self.repo.save()
        found = self.repo.find_by_service(self.service.id)
        self.assertEqual(len(found), 1)

    def test_unread_count_and_mark_read(self):
        n = self.repo.create(self.service.id,
                             NotificationRepository.TYPE_TICKET_ISSUED, "New: A1")
        self.repo.save()
        self.assertEqual(self.repo.unread_count(self.service.id), 1)
        self.repo.mark_read(n.id)
        self.repo.save()
        self.assertEqual(self.repo.unread_count(self.service.id), 0)

    def test_mark_all_read(self):
        for i in range(3):
            self.repo.create(self.service.id,
                             NotificationRepository.TYPE_TICKET_ISSUED, f"N{i}")
        self.repo.save()
        self.repo.mark_all_read(self.service.id)
        self.repo.save()
        self.assertEqual(self.repo.unread_count(self.service.id), 0)

    def test_delete_old_keeps_only_n_most_recent(self):
        for i in range(5):
            self.repo.create(self.service.id,
                             NotificationRepository.TYPE_TICKET_ISSUED, f"N{i}")
        self.repo.save()
        self.repo.delete_old(self.service.id, keep=2)
        self.repo.save()
        remaining = self.repo.find_by_service(self.service.id, limit=50)
        self.assertEqual(len(remaining), 2)


class TestNotificationService(BaseBackendTest):
    def setUp(self):
        super().setUp()
        self.svc = NotificationService()
        self.service = self.make_service()
        self.repo = NotificationRepository()

    def _latest_type(self):
        return self.repo.find_by_service(self.service.id)[0].type

    def test_queue_created_emits_correct_type(self):
        self.svc.queue_created(self.service.id, "Pharmacy", "PHA")
        self.assertEqual(self._latest_type(),
                         NotificationRepository.TYPE_QUEUE_CREATED)

    def test_ticket_issued_printed_vs_normal(self):
        self.svc.ticket_issued(self.service.id, "A1", "General", printed=True)
        self.assertEqual(self._latest_type(),
                         NotificationRepository.TYPE_TICKET_PRINTED)
        self.svc.ticket_issued(self.service.id, "A2", "General", printed=False)
        self.assertEqual(self._latest_type(),
                         NotificationRepository.TYPE_TICKET_ISSUED)

    def test_ticket_carried_over_pluralization_in_title(self):
        self.svc.ticket_carried_over(self.service.id, 1, "17:00")
        one = self.repo.find_by_service(self.service.id)[0]
        self.assertIn("1 ticket carried over", one.title)
        self.svc.ticket_carried_over(self.service.id, 3, "17:00")
        many = self.repo.find_by_service(self.service.id)[0]
        self.assertIn("3 tickets carried over", many.title)

    def test_team_joined_maps_role_label(self):
        self.svc.team_joined(self.service.id, "bob", "agent")
        n = self.repo.find_by_service(self.service.id)[0]
        self.assertIn("Counter Agent", n.body)


class TestOTPRepository(BaseBackendTest):
    def setUp(self):
        super().setUp()
        self.repo = OTPRepository()

    def test_get_expiry_in_future(self):
        from datetime import timezone
        delta = self.repo.get_expiry() - datetime.now(timezone.utc)
        self.assertGreater(delta.total_seconds(), 9 * 60)  # ~10 min

    def test_upsert_pending_inserts_then_updates_same_row(self):
        # OTPRepository stages only; the caller controls the transaction.
        rec = self.repo.upsert_pending("a@x.com", "alice", b"h1", "client", "111111")
        self.db.session.commit()
        first_id = rec.id

        # Second upsert for same email updates in place (resend OTP case)
        rec2 = self.repo.upsert_pending("a@x.com", "alice2", b"h2", "client", "222222")
        self.db.session.commit()
        self.assertEqual(rec2.id, first_id)
        self.assertEqual(rec2.code, "222222")
        self.assertEqual(rec2.username, "alice2")
        self.assertEqual(PendingRegistration.query.count(), 1)

    def test_find_pending_by_email_and_code(self):
        self.repo.upsert_pending("b@x.com", "bob", b"h", "client", "999999")
        self.db.session.commit()
        self.assertIsNotNone(
            self.repo.find_pending_by_email_and_code("b@x.com", "999999")
        )
        self.assertIsNone(
            self.repo.find_pending_by_email_and_code("b@x.com", "000000")
        )

    def test_delete_pending(self):
        rec = self.repo.upsert_pending("c@x.com", "cara", b"h", "client", "123123")
        self.db.session.commit()
        self.repo.delete_pending(rec)
        self.db.session.commit()
        self.assertEqual(PendingRegistration.query.count(), 0)
