"""Scénarios Locust pour charger l'API Agentys avec LLM mocké.

Lancer le backend avec :
  AGENTYS_LOAD_TEST_MODE=true python run_api.py
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from locust import HttpUser, between, task

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_account_pool import AccountPool  # noqa: E402
from load_rate_gate import RateGate  # noqa: E402


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


_draft_rate_gate = RateGate()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


_account_pool = AccountPool(
    pool_size=_env_int("LOAD_ACCOUNT_POOL_SIZE", 0),
    start=_env_int("LOAD_ACCOUNT_POOL_START", 1),
)


def _load_account_id() -> str | None:
    pool_size = _env_int("LOAD_ACCOUNT_POOL_SIZE", 0)
    if pool_size > 0:
        return _account_pool.next_account_id()
    return os.getenv("LOAD_ACCOUNT_ID")


class AgentysApiUser(HttpUser):
    wait_time = between(
        float(os.getenv("LOAD_WAIT_MIN_SECONDS", "0.2")),
        float(os.getenv("LOAD_WAIT_MAX_SECONDS", "1.2")),
    )

    def on_start(self) -> None:
        self.headers = {"Content-Type": "application/json"}
        self.account_id = _load_account_id()
        if self.account_id:
            self.headers["X-Account-Id"] = self.account_id

        if os.getenv("LOAD_AUTH_MODE", "none").strip().lower() == "dev-login":
            response = self.client.post("/api/auth/dev-login", name="auth:dev-login")
            if response.ok:
                token = response.json().get("access_token")
                if token:
                    self.headers["Authorization"] = f"Bearer {token}"

    @task(4)
    def health(self) -> None:
        if not _env_bool("LOAD_HEALTH_CHECKS", True):
            return
        self.client.get("/api/health", name="health")

    @task(3)
    def list_emails(self) -> None:
        if not _env_bool("LOAD_LIST_EMAILS", True):
            return
        params = {
            "folder": "inbox",
            "limit": os.getenv("LOAD_EMAIL_LIST_LIMIT", "20"),
            "offset": "0",
        }
        self.client.get(
            "/api/emails",
            params=params,
            headers=self.headers,
            name="emails:list",
        )

    @task(1)
    def open_uncached_email_detail(self) -> None:
        if not _env_bool("LOAD_OPEN_EMAIL_DETAIL", False):
            return

        run_id = os.getenv("LOAD_RUN_ID", "").strip() or "detail"
        email_id = f"load-detail-{run_id}-{uuid.uuid4().hex}"
        with self.client.get(
            f"/api/emails/{email_id}",
            headers=self.headers,
            name="emails:detail-uncached",
            catch_response=True,
        ) as response:
            if response.status_code not in (200, 429):
                response.failure(f"unexpected status {response.status_code}: {response.text[:300]}")

    @task(2)
    def process_cached_email(self) -> None:
        if not _env_bool("LOAD_PROCESS_EMAILS", True):
            return
        if not _draft_rate_gate.allow():
            return

        run_id = os.getenv("LOAD_RUN_ID", "").strip()
        stage_label = os.getenv("LOAD_STAGE_LABEL", "").strip()
        prefix = "load"
        if run_id:
            prefix += f"-{run_id}"
        if stage_label:
            prefix += f"-{stage_label}"
        if self.account_id:
            prefix += f"-a{self.account_id}"
        email_id = f"{prefix}-{uuid.uuid4().hex}"
        body = (
            "Bonjour,\n\n"
            "Pouvez-vous me confirmer la prochaine étape et le délai prévu ?\n"
            f"Référence de test : {email_id}.\n\n"
            "Merci."
        )
        payload = {
            "instructions": os.getenv("LOAD_DRAFT_INSTRUCTIONS", ""),
            "reply_type": "reply",
            "force": True,
            "cached_email": {
                "sender": f"client.loadtest+acct{self.account_id or 'default'}@example.com",
                "sender_name": "Client Load Test",
                "to": [f"agentys.loadtest+acct{self.account_id or 'default'}@example.com"],
                "cc": [],
                "subject": "Question test de charge",
                "body": body,
                "body_text": body,
                "body_html": "",
                "conversation_id": f"thread-{email_id}",
                "received_at": datetime.now(timezone.utc).isoformat(),
            },
        }

        with self.client.post(
            f"/api/emails/{email_id}/process",
            json=payload,
            headers=self.headers,
            name="emails:process-cached",
            catch_response=True,
        ) as response:
            if response.status_code in (429, 503):
                response.success()
            elif response.status_code not in (200, 202):
                response.failure(f"unexpected status {response.status_code}: {response.text[:300]}")
