from models import db, InviteToken
from datetime import datetime, timedelta, timezone


# =============================================================
# INVITE REPOSITORY
# Responsibilities:
#   - Abstract all DB operations for InviteToken
# OOP Principle: Single Responsibility, Encapsulation
# =============================================================
class InviteRepository:

    INVITE_EXPIRY_HOURS = 48

    def get_expiry(self) -> datetime:
        return datetime.now(timezone.utc) + timedelta(hours=self.INVITE_EXPIRY_HOURS)

    def find_by_token(self, token: str) -> InviteToken | None:
        return InviteToken.query.filter_by(token=token).first()

    def find_by_service(self, service_id: int) -> list[InviteToken]:
        """Return all unexpired, unused invite tokens for a service."""
        return (InviteToken.query
                .filter_by(service_id=service_id, used=False)
                .filter(InviteToken.expires_at > datetime.now(timezone.utc))
                .order_by(InviteToken.created_at.desc())
                .all())

    def create(self, service_id: int, admin_role: str) -> InviteToken:
        """
        Create a new invite token for the given service and role.
        Does NOT commit — caller controls the transaction.
        """
        invite = InviteToken(
            service_id = service_id,
            admin_role = admin_role,
            expires_at = self.get_expiry(),
        )
        db.session.add(invite)
        return invite

    def consume(self, invite: InviteToken):
        """Mark an invite token as used. Does NOT commit."""
        invite.consume()

    def delete(self, invite: InviteToken):
        db.session.delete(invite)

    def save(self):     db.session.commit()
    def rollback(self): db.session.rollback()