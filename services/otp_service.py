import secrets
import requests
from flask import current_app


# =============================================================
# OTP SERVICE
# Responsibilities:
#   - Generate secure OTP codes
#   - Send OTP emails via Brevo API
# OOP Principle: Single Responsibility, Abstraction
# =============================================================
# services/otp_service.py
class OTPService:
    # ... previous generate method ...

    def send(self, email: str, username: str, otp_code: str) -> bool:
        # Fetch config from app factory
        api_key      = current_app.config.get("BREVO_API_KEY")
        
        payload = {
            "sender": {
                "email": "kwetejunior9@gmail.com", # Your specific verified sender
                "name": "TICKETY"
            },
            "to": [{"email": email}],
            "subject": f"{otp_code} is your TICKETY verification code",
            "htmlContent": self._build_email_html(username, otp_code),
        }
        # ... rest of the send logic using requests.post

        headers = {
            "accept":       "application/json",
            "content-type": "application/json",
            "api-key":      api_key,
        }

        try:
            response = requests.post(
                "https://api.brevo.com/v3/smtp/email",
                json=payload,
                headers=headers,
            )
            return response.status_code in [200, 201]
        except requests.RequestException:
            return False

    def _build_email_html(self, username: str, otp_code: str) -> str:
        """Build and return the HTML body for the OTP email."""
        return f"""
        <html>
            <body style="font-family: Arial, sans-serif; background:#0D0D0D;
                         color:#F5F5F5; padding:40px;">
                <div style="max-width:480px; margin:auto; background:#161616;
                            border-radius:16px; padding:40px;
                            border:1px solid #2A2A2A;">
                    <div style="display:flex; align-items:center; margin-bottom:32px;">
                        <div style="background:#DC0F0F; border-radius:10px;
                                    padding:10px; margin-right:12px;">
                            🎟
                        </div>
                        <span style="font-size:20px; font-weight:900;
                                     letter-spacing:4px;">QLINE</span>
                    </div>
                    <h2 style="margin:0 0 8px; font-size:24px;">
                        Welcome, {username}!
                    </h2>
                    <p style="color:#808080; margin:0 0 32px;">
                        Use the code below to verify your account.
                        It expires in <strong style="color:#F5F5F5;">10 minutes</strong>.
                    </p>
                    <div style="background:#0D0D0D; border:2px solid #DC0F0F;
                                border-radius:12px; padding:24px;
                                text-align:center; font-size:36px;
                                font-weight:900; letter-spacing:10px;
                                color:#DC0F0F;">
                        {otp_code}
                    </div>
                    <p style="color:#444; font-size:12px; margin-top:24px;
                              text-align:center;">
                        If you did not create a QLINE account, ignore this email.
                    </p>
                </div>
            </body>
        </html>
        """