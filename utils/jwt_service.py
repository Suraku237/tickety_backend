import jwt
import os
from datetime import datetime, timedelta, timezone

# =============================================================
# JWT SERVICE
# Responsibilities:
#   - Generate JWT tokens for authenticated users
#   - Verify and decode JWT tokens
#   - Handle token expiration
# OOP Principle: Encapsulation, Single Responsibility
# =============================================================
class JWTService:

    # Fixed: was 'JWT_SECRET' but .env defines 'JWT_SECRET_KEY'
    SECRET = os.getenv('JWT_SECRET_KEY', 'dev-secret-key-change-in-production')
    ALGORITHM = 'HS256'
    EXPIRY_DAYS = 30

    @staticmethod
    def generate(user_id, email, role):
        """
        Generate JWT token for authenticated user.
        Token expires after EXPIRY_DAYS.
        """
        # Fixed: replaced deprecated datetime.utcnow() with timezone-aware now()
        now = datetime.now(timezone.utc)
        payload = {
            'user_id': str(user_id),
            'email': email,
            'role': role,
            'exp': now + timedelta(days=JWTService.EXPIRY_DAYS),
            'iat': now,
        }
        try:
            token = jwt.encode(payload, JWTService.SECRET, algorithm=JWTService.ALGORITHM)
            return token
        except Exception as e:
            raise Exception(f"Failed to generate token: {str(e)}")

    @staticmethod
    def verify(token):
        """
        Verify and decode JWT token.
        Returns payload dict if valid, None if expired or invalid.
        """
        try:
            payload = jwt.decode(token, JWTService.SECRET, algorithms=[JWTService.ALGORITHM])
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
        except Exception:
            return None

    @staticmethod
    def decode(token):
        """Alias for verify() — decode without validation."""
        return JWTService.verify(token)
