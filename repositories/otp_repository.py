from models import db, ResetCode
from datetime import datetime, timedelta, timezone


# =============================================================
# OTP REPOSITORY
# Responsibilities:
#   - Abstract all database operations related to ResetCode
#   - Provide upsert, lookup, and delete methods
# OOP Principle: Single Responsibility, Encapsulation
# =============================================================
class OTPRepository:

    OTP_EXPIRY_MINUTES = 10

    def get_expiry(self) -> datetime:
        """Calculate and return an expiry datetime from now."""
        return datetime.now(timezone.utc) + timedelta(minutes=self.OTP_EXPIRY_MINUTES)

    def find_by_email(self, email: str) -> ResetCode | None:
        """Find an existing OTP record by email."""
        return ResetCode.query.filter_by(email=email).first()

    def find_by_email_and_code(self, email: str, code: str) -> ResetCode | None:
        """Find an OTP record matching both email and code."""
        return ResetCode.query.filter_by(email=email, code=code).first()

    def upsert(self, email: str, code: str) -> ResetCode:
        """
        Insert a new OTP record or update the existing one for this email.
        Does NOT commit — caller controls the transaction.
        """
        expiry  = self.get_expiry()
        record  = self.find_by_email(email)

        if record:
            record.update_code(code, expiry)
        else:
            record = ResetCode(email=email, code=code, expire_at=expiry)
            db.session.add(record)

        return record

    def delete(self, record: ResetCode):
        """Remove a used or expired OTP record from the database."""
        db.session.delete(record)