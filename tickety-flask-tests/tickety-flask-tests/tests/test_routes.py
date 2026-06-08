"""
Endpoint-level tests for authentication and core ticket routes.

Uses the Flask test client (exposed by ``BaseTestCase.client``) so the HTTP
contract is verified without a running server. Grouped into focused classes so
each route family is an independent object with its own helpers.

ADAPT ME: URL paths and JSON keys must match your real blueprint routes.
"""
import json

from tests.base import BaseTestCase


class _JsonClientMixin:
    """Small mixin adding JSON post/get helpers shared by route tests."""

    def post_json(self, url, payload, headers=None):
        return self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
            headers=headers or {},
        )

    def get_json(self, url, headers=None):
        return self.client.get(url, headers=headers or {})


class TestAuthRoutes(_JsonClientMixin, BaseTestCase):
    """Registration / login flow that the React + Flutter clients depend on."""

    def test_login_with_valid_credentials_returns_token(self):
        self.make_user(email="bob@example.com", password="hunter2")
        resp = self.post_json(
            "/api/login", {"email": "bob@example.com", "password": "hunter2"}
        )
        self.assertIn(resp.status_code, (200, 201))
        body = resp.get_json() or {}
        self.assertTrue(
            "token" in body or "access_token" in body,
            "login should return an auth token",
        )

    def test_login_with_bad_password_is_rejected(self):
        self.make_user(email="carol@example.com", password="correct")
        resp = self.post_json(
            "/api/login", {"email": "carol@example.com", "password": "wrong"}
        )
        self.assertIn(resp.status_code, (400, 401))


class TestTicketRoutes(_JsonClientMixin, BaseTestCase):
    """Creating and reading tickets through the API surface."""

    def test_create_ticket_returns_created_resource(self):
        queue = self.make_queue()
        resp = self.post_json("/api/tickets", {"queue_id": queue.id})
        self.assertIn(resp.status_code, (200, 201))

    def test_list_tickets_for_queue(self):
        queue = self.make_queue()
        self.make_ticket(queue=queue)
        resp = self.get_json(f"/api/queues/{queue.id}/tickets")
        self.assertEqual(resp.status_code, 200)
