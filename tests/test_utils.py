"""
Unit tests for the utility layer:
  - utils/password_service.py  -> PasswordService
  - utils/validator.py         -> Validator

Both are pure logic (no DB), so these tests need no app context.
"""
import unittest

from utils.password_service import PasswordService
from utils.validator import Validator


class TestPasswordService(unittest.TestCase):
    def setUp(self):
        self.svc = PasswordService()

    def test_hash_returns_bytes_and_is_not_plaintext(self):
        hashed = self.svc.hash("s3cret123")
        self.assertIsInstance(hashed, (bytes, bytearray))
        self.assertNotIn(b"s3cret123", hashed)

    def test_hash_is_salted_so_same_input_differs(self):
        self.assertNotEqual(self.svc.hash("samepass1"), self.svc.hash("samepass1"))

    def test_verify_accepts_correct_password(self):
        hashed = self.svc.hash("correct-horse1")
        self.assertTrue(self.svc.verify("correct-horse1", hashed))

    def test_verify_rejects_wrong_password(self):
        hashed = self.svc.hash("correct-horse1")
        self.assertFalse(self.svc.verify("wrong-horse9", hashed))


class TestValidator(unittest.TestCase):
    def setUp(self):
        self.v = Validator()

    # --- username ---
    def test_username_too_short_is_rejected(self):
        self.assertIsNotNone(self.v.validate_username("ab"))

    def test_username_empty_is_rejected(self):
        self.assertIsNotNone(self.v.validate_username(""))

    def test_username_valid_returns_none(self):
        self.assertIsNone(self.v.validate_username("alice"))

    # --- email ---
    def test_email_missing_at_is_rejected(self):
        self.assertIsNotNone(self.v.validate_email("aliceexample.com"))

    def test_email_missing_domain_dot_is_rejected(self):
        self.assertIsNotNone(self.v.validate_email("alice@examplecom"))

    def test_email_valid_returns_none(self):
        self.assertIsNone(self.v.validate_email("alice@example.com"))

    # --- password ---
    def test_password_too_short_is_rejected(self):
        self.assertIsNotNone(self.v.validate_password("a1b2"))

    def test_password_without_digit_is_rejected(self):
        self.assertIsNotNone(self.v.validate_password("nodigitshere"))

    def test_password_valid_returns_none(self):
        self.assertIsNone(self.v.validate_password("longenough1"))

    # --- combined registration ---
    def test_registration_returns_first_error_username(self):
        err = self.v.validate_registration("ab", "bad", "x")
        # username is checked first
        self.assertIn("Username", err)

    def test_registration_all_valid_returns_none(self):
        self.assertIsNone(
            self.v.validate_registration("alice", "alice@example.com", "secret1")
        )


if __name__ == "__main__":
    unittest.main()
