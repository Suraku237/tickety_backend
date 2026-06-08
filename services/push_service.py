"""
Push notification service (#8).

Sends system push notifications to a user's registered devices via
Firebase Cloud Messaging (FCM HTTP v1). This is what lets a notification
reach the phone's notification tray even when the Tickety app is closed
or the phone was off (delivered on reconnect).

Design goals:
  - Completely OPTIONAL. If FCM is not configured, every method is a safe
    no-op and the rest of the backend works exactly as before.
  - No hard dependency at import time on google-auth; it's imported lazily
    only when push is actually configured, so the app boots without it.

Configuration (environment variables):
  - FCM_PROJECT_ID            : your Firebase project id
  - GOOGLE_APPLICATION_CREDENTIALS : path to the service-account JSON
        (the standard google-auth env var), OR
  - FCM_CREDENTIALS_JSON      : the service-account JSON as a string

If neither credential source is present, push is disabled (no-op).

OOP principle: Encapsulation — all FCM details live behind a small
send_to_user / send_to_email surface.
"""

import os
import json
import logging

import requests

log = logging.getLogger("tickety.push")


class PushService:
    _SCOPE = "https://www.googleapis.com/auth/firebase.messaging"

    def __init__(self):
        self.project_id = os.getenv("FCM_PROJECT_ID")
        self._creds = None          # cached google credentials
        self._enabled = bool(self.project_id) and self._has_credentials()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def is_enabled(self) -> bool:
        return self._enabled

    def health(self) -> dict:
        """Lightweight config report — does NOT contact Google."""
        try:
            import google.oauth2.service_account  # noqa: F401
            google_auth = True
        except Exception:
            google_auth = False
        cred_source = (
            "FCM_CREDENTIALS_JSON" if os.getenv("FCM_CREDENTIALS_JSON")
            else "GOOGLE_APPLICATION_CREDENTIALS" if os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            else None
        )
        return {
            "enabled":               self._enabled,
            "project_id_set":        bool(self.project_id),
            "credentials_set":       self._has_credentials(),
            "credentials_source":    cred_source,
            "google_auth_installed": google_auth,
        }

    def probe(self) -> dict:
        """Live check — actually attempts to mint a Google access token."""
        info = self.health()
        if not self._enabled:
            info["token_ok"] = False
            info["error"]    = "Push not configured (FCM_PROJECT_ID + credentials required)."
            return info
        try:
            token = self._get_access_token()
            info["token_ok"] = bool(token)
            if not token:
                info["error"] = "Could not mint an access token — check the service-account JSON and that google-auth is installed."
        except Exception as e:
            info["token_ok"] = False
            info["error"]    = str(e)
        return info

    def send_to_user(self, user_id: int, title: str, body: str, data: dict | None = None):
        """Send a push to every device registered by this user."""
        if not self._enabled:
            return
        try:
            from models import DeviceToken
            tokens = [d.token for d in DeviceToken.query.filter_by(user_id=user_id).all()]
            self._send_to_tokens(tokens, title, body, data)
        except Exception as e:                       # never let push break a request
            log.warning("push send_to_user failed: %s", e)

    def send_to_email(self, email: str, title: str, body: str, data: dict | None = None):
        """Resolve a user by email (used for ticket customer_identifier) and push."""
        if not self._enabled or not email:
            return
        try:
            from models import User
            user = User.query.filter(
                __import__("models").db.func.lower(User.email) == email.strip().lower()
            ).first()
            if user:
                self.send_to_user(user.id, title, body, data)
        except Exception as e:
            log.warning("push send_to_email failed: %s", e)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _has_credentials(self) -> bool:
        return bool(
            os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            or os.getenv("FCM_CREDENTIALS_JSON")
        )

    def _get_access_token(self) -> str | None:
        """Mint a short-lived OAuth2 access token from the service account."""
        try:
            from google.oauth2 import service_account
            from google.auth.transport.requests import Request as GoogleRequest
        except Exception:
            log.warning("google-auth not installed; push disabled. "
                        "pip install google-auth")
            return None

        if self._creds is None:
            raw = os.getenv("FCM_CREDENTIALS_JSON")
            if raw:
                info = json.loads(raw)
                self._creds = service_account.Credentials.from_service_account_info(
                    info, scopes=[self._SCOPE])
            else:
                path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
                self._creds = service_account.Credentials.from_service_account_file(
                    path, scopes=[self._SCOPE])

        self._creds.refresh(GoogleRequest())
        return self._creds.token

    def _send_to_tokens(self, tokens, title, body, data):
        if not tokens:
            return
        access_token = self._get_access_token()
        if not access_token:
            return
        url = f"https://fcm.googleapis.com/v1/projects/{self.project_id}/messages:send"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        # FCM v1 sends one message per token.
        for token in tokens:
            payload = {
                "message": {
                    "token": token,
                    "notification": {"title": title, "body": body},
                    "data": {k: str(v) for k, v in (data or {}).items()},
                    "android": {"priority": "high"},
                    "apns": {"headers": {"apns-priority": "10"}},
                }
            }
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=8)
                if resp.status_code not in (200, 201):
                    log.info("FCM send -> %s %s", resp.status_code, resp.text[:200])
            except Exception as e:
                log.warning("FCM request failed: %s", e)