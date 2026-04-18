from models import db, PendingRegistration, ResetCode
from datetime import datetime, timedelta, timezone


# =============================================================
# OTP REPOSITORY
# Responsibilities:
#   - Abstract all database operations for OTP codes
#   - Handles TWO separate OTP flows:
#
#     1. REGISTRATION flow  → PendingRegistration table
#        Used by: register(), verify_email(), resend_otp()
#        The pending row holds the full registration payload.
#        On successful verification it is consumed (deleted)
#        and a real User row is created in its place.
#
#     2. PASSWORD RESET flow → ResetCode table  (future feature)
#        Used by: forgot_password(), reset_password()
#        Applies to already-existing verified users only.
#
# OOP Principle: Single Responsibility, Encapsulation
# =============================================================
class OTPRepository:

    OTP_EXPIRY_MINUTES = 10

    # ----------------------------------------------------------
    # SHARED HELPERS
    # ----------------------------------------------------------
    def get_expiry(self) -> datetime:
        """Calculate and return an expiry datetime from now."""
        return datetime.now(timezone.utc) + timedelta(minutes=self.OTP_EXPIRY_MINUTES)

    # ==========================================================
    # REGISTRATION FLOW  (PendingRegistration table)
    # ==========================================================

    def find_pending_by_email(self, email: str) -> PendingRegistration | None:
        """Find an existing pending registration record by email."""
        return PendingRegistration.query.filter_by(email=email).first()

    def find_pending_by_email_and_code(
        self, email: str, code: str
    ) -> PendingRegistration | None:
        """Find a pending registration matching both email and OTP code."""
        return PendingRegistration.query.filter_by(email=email, code=code).first()

    def upsert_pending(
        self,
        email:           str,
        username:        str,
        hashed_password: bytes,
        role:            str,
        code:            str,
    ) -> PendingRegistration:
        """
        Insert a new PendingRegistration or update the existing one for
        this email (covers the resend-OTP case without duplicating rows).

        Does NOT commit — caller controls the transaction.

        NOTE: hashed_password is stored here so that:
          - The raw password never needs to be passed around again
          - verify_email() can create the User directly from this row
        """
        expiry  = self.get_expiry()
        record  = self.find_pending_by_email(email)

        if record:
            # Update credentials in case user changed them before resending
            record.username        = username
            record.hashed_password = hashed_password
            record.role            = role
            record.update_code(code, expiry)
        else:
            record = PendingRegistration(
                username        = username,
                email           = email,
                hashed_password = hashed_password,
                role            = role,
                code            = code,
                expire_at       = expiry,
            )
            db.session.add(record)

        return record

    def delete_pending(self, record: PendingRegistration):
        """
        Remove a pending registration after it has been successfully
        verified and the real User row has been created.
        Does NOT commit — caller controls the transaction.
        """
        db.session.delete(record)

    # ==========================================================
    # PASSWORD RESET FLOW  (ResetCode table — future feature)
    # ==========================================================

    def find_reset_by_email(self, email: str) -> ResetCode | None:
        """Find an existing password-reset OTP record by email."""
        return ResetCode.query.filter_by(email=email).first()

    def find_reset_by_email_and_code(
        self, email: str, code: str
    ) -> ResetCode | None:
        """Find a reset OTP record matching both email and code."""
        return ResetCode.query.filter_by(email=email, code=code).first()

    def upsert_reset(self, email: str, code: str) -> ResetCode:
        """
        Insert a new ResetCode or update the existing one for this email.
        Does NOT commit — caller controls the transaction.
        """
        expiry = self.get_expiry()
        record = self.find_reset_by_email(email)

        if record:
            record.update_code(code, expiry)
        else:
            record = ResetCode(email=email, code=code, expire_at=expiry)
            db.session.add(record)

        return record

    def delete_reset(self, record: ResetCode):
        """Remove a used or expired reset OTP from the database."""
        db.session.delete(record)