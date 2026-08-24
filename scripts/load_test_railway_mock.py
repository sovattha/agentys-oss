#!/usr/bin/env python3
# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Run concurrent-user load tests against the Railway mock stack.

The runner is intentionally API-level and uses only mocked LLM/provider paths.
It supports two scenarios:

- draft-users: POST /process, then poll the shared Redis/RQ job status.
- provider: call the load-only provider probe for Gmail/Outlook-shaped load.
- full-flow: provider list/detail, draft generation, then sent-provider probe.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import aiohttp


DEFAULT_HOST = "https://load-mock-api-production.up.railway.app"
DRAFT_SCENARIOS = {"draft-users", "full-flow"}
PROVIDER_SCENARIOS = {"provider", "full-flow"}


@dataclass
class Counters:
    attempts: int = 0
    ok: int = 0
    accepted: int = 0
    completed: int = 0
    failed: int = 0
    backpressure: int = 0
    provider_backoff: int = 0
    server_errors: int = 0
    client_errors: int = 0
    poll_requests: int = 0
    poll_timeouts: int = 0
    poll_errors: int = 0
    other_status: dict[str, int] = field(default_factory=dict)
    backpressure_reasons: dict[str, int] = field(default_factory=dict)


@dataclass
class CapacitySample:
    ts: str
    ok: bool
    queue_depth: int = 0
    active_workers: int = 0
    jobs_total: int = 0
    submitted_total: int = 0
    completed_total: int = 0
    rejected_total: int = 0
    failed_total: int = 0
    error: str = ""


@dataclass
class StageResult:
    scenario: str
    label: str
    users: int
    provider_kind: str
    started_at: str
    finished_at: str
    duration_seconds: int
    counters: Counters
    response_p50_ms: int | None
    response_p95_ms: int | None
    response_p99_ms: int | None
    ready_p50_ms: int | None
    ready_p95_ms: int | None
    ready_p99_ms: int | None
    queue_wait_p95_ms: int | None
    run_p95_ms: int | None
    poll_p95_ms: int | None
    max_queue_depth: int
    max_jobs_total: int
    max_active_workers: int
    drain_completed: bool
    operation_counts: dict[str, int]
    status: str
    reason: str


class StageState:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.counters = Counters()
        self.response_latencies_ms: list[float] = []
        self.ready_latencies_ms: list[float] = []
        self.queue_wait_ms: list[float] = []
        self.run_ms: list[float] = []
        self.poll_latencies_ms: list[float] = []
        self.operation_counts: dict[str, int] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def percentile(values: list[float], pct: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = math.ceil((pct / 100.0) * len(ordered)) - 1
    return int(ordered[max(0, min(index, len(ordered) - 1))])


def next_poll_interval_seconds(
    attempt: int,
    base_interval_seconds: float,
    max_interval_seconds: float,
) -> float:
    base = max(0.1, base_interval_seconds)
    maximum = max(base, max_interval_seconds)
    return min(maximum, base * (1.5 ** max(0, attempt - 1)))


def parse_stages(raw: str) -> list[int]:
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def parse_provider_mix(raw: str) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            operation, weight_raw = item.split(":", 1)
            weight = max(1, int(weight_raw))
        else:
            operation, weight = item, 1
        operation = operation.strip().lower()
        if operation not in {"detail", "list", "sent"}:
            raise ValueError(f"Unsupported provider operation: {operation}")
        result.append((operation, weight))
    return result or [("detail", 1)]


def choose_provider_operation(mix: list[tuple[str, int]]) -> str:
    total = sum(weight for _, weight in mix)
    cursor = random.randint(1, total)
    for operation, weight in mix:
        cursor -= weight
        if cursor <= 0:
            return operation
    return mix[-1][0]


def scenario_has_drafts(scenario: str) -> bool:
    return scenario in DRAFT_SCENARIOS


def scenario_has_provider(scenario: str) -> bool:
    return scenario in PROVIDER_SCENARIOS


def initial_user_delay(
    *,
    user_index: int,
    stage_users: int,
    period_seconds: float,
    traffic_shape: str,
    burst_window_seconds: float,
) -> float:
    if traffic_shape == "burst":
        return random.uniform(0, max(0.0, burst_window_seconds))
    return (user_index / max(stage_users, 1)) * period_seconds


def validate_live_service_guard(args: argparse.Namespace, stages: list[int]) -> None:
    live_modes = [
        name
        for name, value in {
            "llm": args.llm_mode,
            "provider": args.provider_mode,
        }.items()
        if value == "live"
    ]
    if not live_modes:
        return
    if not args.allow_live_services:
        raise ValueError(
            "Live LLM/provider load tests require --allow-live-services "
            f"(requested: {', '.join(live_modes)})"
        )
    max_users = max(stages) if stages else 0
    if max_users > args.max_live_users and not args.allow_high_volume_live_services:
        raise ValueError(
            "Live LLM/provider load tests are capped at "
            f"{args.max_live_users} users by default; use "
            "--allow-high-volume-live-services to override"
        )


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def append_jsonl(path: Path, payload: Any) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _counter_rate(count: int, total: int) -> float:
    return count / max(1, total)


def classify_stage(
    *,
    scenario: str,
    counters: Counters,
    drain_completed: bool,
    response_p95_ms: int | None,
    ready_p95_ms: int | None,
    max_failure_rate: float,
    response_p95_degraded_ms: int,
    draft_ready_p95_degraded_ms: int,
    provider_backoff_degraded_rate: float,
) -> tuple[str, str]:
    attempts = max(1, counters.attempts)
    server_error_rate = _counter_rate(counters.server_errors, attempts)
    client_error_rate = _counter_rate(counters.client_errors, attempts)
    unexpected_status_count = sum(counters.other_status.values())
    unexpected_status_rate = _counter_rate(unexpected_status_count, attempts)
    if server_error_rate > max_failure_rate or client_error_rate > max_failure_rate:
        return (
            "crashed",
            f"error_rate server={server_error_rate:.2%} client={client_error_rate:.2%}",
        )
    if unexpected_status_rate > max_failure_rate:
        return (
            "crashed",
            f"unexpected_status={unexpected_status_rate:.2%} statuses={counters.other_status}",
        )
    if counters.failed:
        return "crashed", f"failed_jobs={counters.failed}"

    reasons: list[str] = []
    if response_p95_ms is not None and response_p95_ms > response_p95_degraded_ms:
        reasons.append(f"response_p95={response_p95_ms}ms")
    if scenario_has_drafts(scenario):
        if counters.backpressure:
            detail = ""
            if counters.backpressure_reasons:
                detail = f" reasons={counters.backpressure_reasons}"
            reasons.append(
                f"backpressure={_counter_rate(counters.backpressure, attempts):.2%}{detail}"
            )
        accepted = max(1, counters.accepted)
        if not drain_completed:
            reasons.append("drain_timeout")
        if counters.poll_timeouts:
            reasons.append(f"poll_timeouts={_counter_rate(counters.poll_timeouts, accepted):.2%}")
        if ready_p95_ms is not None and ready_p95_ms > draft_ready_p95_degraded_ms:
            reasons.append(f"draft_ready_p95={ready_p95_ms}ms")
    if scenario_has_provider(scenario):
        non_provider_backpressure = max(0, counters.backpressure - counters.provider_backoff)
        if _counter_rate(non_provider_backpressure, attempts) > max_failure_rate:
            reasons.append(
                f"non_provider_backpressure={_counter_rate(non_provider_backpressure, attempts):.2%}"
            )
        provider_backoff_rate = _counter_rate(counters.provider_backoff, attempts)
        if provider_backoff_rate > provider_backoff_degraded_rate:
            reasons.append(f"provider_backoff={provider_backoff_rate:.2%}")

    if reasons:
        return "degraded", ", ".join(reasons)
    return "healthy", "within thresholds"


def account_for_user(user_index: int, users: int, account_pool_size: int) -> str:
    pool = max(1, min(account_pool_size, users)) if account_pool_size > 0 else 1
    return str((user_index % pool) + 1)


def email_payload(email_id: str, account_id: str) -> dict[str, Any]:
    body = (
        "Bonjour,\n\n"
        "Pouvez-vous me confirmer la prochaine étape et le délai prévu ?\n"
        f"Référence de test : {email_id}.\n\n"
        "Merci."
    )
    return {
        "instructions": "Réponds de façon concise et professionnelle.",
        "reply_type": "reply",
        "force": True,
        "cached_email": {
            "sender": f"client.loadtest+acct{account_id}@example.com",
            "sender_name": "Client Load Test",
            "to": [f"agentys.loadtest+acct{account_id}@example.com"],
            "cc": [],
            "subject": "Question test de charge",
            "body": body,
            "body_text": body,
            "body_html": "",
            "conversation_id": f"thread-{email_id}",
            "received_at": utc_now(),
        },
    }


async def fetch_capacity(session: aiohttp.ClientSession, host: str) -> CapacitySample:
    try:
        async with session.get(
            f"{host}/api/health/capacity",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            data = await response.json(content_type=None)
        queue = data.get("draft_queue") or {}
        return CapacitySample(
            ts=utc_now(),
            ok=response.status == 200,
            queue_depth=int(queue.get("queue_depth") or 0),
            active_workers=int(queue.get("active_workers") or 0),
            jobs_total=int(queue.get("jobs_total") or 0),
            submitted_total=int(queue.get("submitted_total") or 0),
            completed_total=int(queue.get("completed_total") or 0),
            rejected_total=int(queue.get("rejected_total") or 0),
            failed_total=int(queue.get("failed_total") or 0),
            error="" if response.status == 200 else f"status={response.status}",
        )
    except Exception as exc:
        return CapacitySample(ts=utc_now(), ok=False, error=f"{type(exc).__name__}: {exc}")


async def wait_for_capacity_idle(
    session: aiohttp.ClientSession,
    host: str,
    timeout_seconds: int,
) -> bool:
    if timeout_seconds <= 0:
        return True
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        sample = await fetch_capacity(session, host)
        if sample.ok and sample.queue_depth == 0 and sample.active_workers == 0 and sample.jobs_total == 0:
            return True
        await asyncio.sleep(3)
    return False


async def monitor_capacity(
    session: aiohttp.ClientSession,
    host: str,
    output_dir: Path,
    stage_label: str,
    stage_end: float,
    samples: list[CapacitySample],
    sample_seconds: float,
) -> None:
    while time.monotonic() < stage_end:
        sample = await fetch_capacity(session, host)
        samples.append(sample)
        append_jsonl(output_dir / "capacity-samples.jsonl", {"stage": stage_label, **asdict(sample)})
        await asyncio.sleep(sample_seconds)


async def poll_draft_status(
    *,
    session: aiohttp.ClientSession,
    host: str,
    status_url: str,
    submitted_at: float,
    state: StageState,
    output_dir: Path,
    timeout_seconds: float,
    poll_interval_seconds: float,
    poll_max_interval_seconds: float,
) -> None:
    url = status_url if status_url.startswith("http") else urljoin(host, status_url)
    deadline = time.monotonic() + timeout_seconds
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        started = time.monotonic()
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as response:
                body = await response.text()
                latency_ms = (time.monotonic() - started) * 1000
                async with state.lock:
                    state.counters.poll_requests += 1
                    state.poll_latencies_ms.append(latency_ms)
                if response.status == 200:
                    data = json.loads(body) if body else {}
                    status = data.get("status")
                    if status == "completed" or data.get("ready") is True:
                        async with state.lock:
                            state.counters.completed += 1
                            state.ready_latencies_ms.append((time.monotonic() - submitted_at) * 1000)
                            if isinstance(data.get("queue_wait_ms"), int | float):
                                state.queue_wait_ms.append(float(data["queue_wait_ms"]))
                            if isinstance(data.get("run_ms"), int | float):
                                state.run_ms.append(float(data["run_ms"]))
                        return
                    if status == "failed":
                        async with state.lock:
                            state.counters.failed += 1
                        append_jsonl(output_dir / "errors.jsonl", {
                            "ts": utc_now(),
                            "event": "draft_failed",
                            "status_url": status_url,
                            "body": body[:500],
                        })
                        return
                elif response.status >= 500:
                    async with state.lock:
                        state.counters.poll_errors += 1
        except Exception as exc:
            async with state.lock:
                state.counters.poll_errors += 1
            append_jsonl(output_dir / "errors.jsonl", {
                "ts": utc_now(),
                "event": "poll_error",
                "status_url": status_url,
                "error": f"{type(exc).__name__}: {exc}",
            })
        await asyncio.sleep(
            next_poll_interval_seconds(
                attempt,
                poll_interval_seconds,
                poll_max_interval_seconds,
            )
        )

    async with state.lock:
        state.counters.poll_timeouts += 1


async def submit_draft_once(
    *,
    session: aiohttp.ClientSession,
    host: str,
    run_id: str,
    stage_label: str,
    account_id: str,
    state: StageState,
    output_dir: Path,
    poll_timeout_seconds: float,
    poll_interval_seconds: float,
    poll_max_interval_seconds: float,
) -> float:
    headers = {"Content-Type": "application/json", "X-Account-Id": account_id}
    email_id = f"load-{run_id}-{stage_label}-a{account_id}-{uuid.uuid4().hex}"
    started = time.monotonic()
    retry_after = 0.0
    try:
        async with session.post(
            f"{host}/api/emails/{email_id}/process",
            json=email_payload(email_id, account_id),
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            body = await response.text()
            latency_ms = (time.monotonic() - started) * 1000
            async with state.lock:
                state.counters.attempts += 1
                state.operation_counts["draft"] = state.operation_counts.get("draft", 0) + 1
                state.response_latencies_ms.append(latency_ms)
            if response.status in {200, 202}:
                try:
                    data = json.loads(body) if body else {}
                except json.JSONDecodeError:
                    data = {}
                status_url = str(data.get("status_url") or "").strip()
                async with state.lock:
                    state.counters.accepted += 1
                if status_url:
                    await poll_draft_status(
                        session=session,
                        host=host,
                        status_url=status_url,
                        submitted_at=started,
                        state=state,
                        output_dir=output_dir,
                        timeout_seconds=poll_timeout_seconds,
                        poll_interval_seconds=poll_interval_seconds,
                        poll_max_interval_seconds=poll_max_interval_seconds,
                    )
            elif response.status in {429, 503}:
                retry_after = float(response.headers.get("Retry-After") or 10)
                try:
                    data = json.loads(body) if body else {}
                except json.JSONDecodeError:
                    data = {}
                reason = str(
                    data.get("reason")
                    or data.get("queue_status")
                    or data.get("code")
                    or response.status
                )
                async with state.lock:
                    state.counters.backpressure += 1
                    state.counters.backpressure_reasons[reason] = (
                        state.counters.backpressure_reasons.get(reason, 0) + 1
                    )
                append_jsonl(output_dir / "backpressure.jsonl", {
                    "ts": utc_now(),
                    "stage": stage_label,
                    "email_id": email_id,
                    "status": response.status,
                    "reason": reason,
                    "body": body[:500],
                })
            elif response.status >= 500:
                async with state.lock:
                    state.counters.server_errors += 1
                    state.counters.other_status[str(response.status)] = (
                        state.counters.other_status.get(str(response.status), 0) + 1
                    )
                append_jsonl(output_dir / "errors.jsonl", {
                    "ts": utc_now(),
                    "stage": stage_label,
                    "email_id": email_id,
                    "status": response.status,
                    "body": body[:500],
                })
            else:
                async with state.lock:
                    state.counters.client_errors += 1
                    state.counters.other_status[str(response.status)] = (
                        state.counters.other_status.get(str(response.status), 0) + 1
                    )
                append_jsonl(output_dir / "errors.jsonl", {
                    "ts": utc_now(),
                    "stage": stage_label,
                    "email_id": email_id,
                    "status": response.status,
                    "body": body[:500],
                })
    except Exception as exc:
        async with state.lock:
            state.counters.attempts += 1
            state.counters.client_errors += 1
            state.operation_counts["draft"] = state.operation_counts.get("draft", 0) + 1
        append_jsonl(output_dir / "errors.jsonl", {
            "ts": utc_now(),
            "stage": stage_label,
            "email_id": email_id,
            "error": f"{type(exc).__name__}: {exc}",
        })
    return retry_after


async def draft_user_loop(
    *,
    session: aiohttp.ClientSession,
    host: str,
    run_id: str,
    stage_label: str,
    stage_users: int,
    user_index: int,
    stage_end: float,
    state: StageState,
    output_dir: Path,
    account_pool_size: int,
    draft_period_seconds: float,
    poll_timeout_seconds: float,
    poll_interval_seconds: float,
    poll_max_interval_seconds: float,
    traffic_shape: str,
    burst_window_seconds: float,
) -> None:
    account_id = account_for_user(user_index, stage_users, account_pool_size)
    await asyncio.sleep(
        initial_user_delay(
            user_index=user_index,
            stage_users=stage_users,
            period_seconds=draft_period_seconds,
            traffic_shape=traffic_shape,
            burst_window_seconds=burst_window_seconds,
        )
    )
    while time.monotonic() < stage_end:
        started = time.monotonic()
        retry_after = await submit_draft_once(
            session=session,
            host=host,
            run_id=run_id,
            stage_label=stage_label,
            account_id=account_id,
            state=state,
            output_dir=output_dir,
            poll_timeout_seconds=poll_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            poll_max_interval_seconds=poll_max_interval_seconds,
        )
        elapsed = time.monotonic() - started
        sleep_for = max(draft_period_seconds - elapsed, 0.0)
        if retry_after:
            sleep_for = max(sleep_for, min(retry_after, draft_period_seconds))
        await asyncio.sleep(sleep_for + random.uniform(0, 0.2))


async def provider_probe_once(
    *,
    session: aiohttp.ClientSession,
    host: str,
    run_id: str,
    stage_label: str,
    account_id: str,
    operation: str,
    state: StageState,
    output_dir: Path,
    provider_kind: str,
    provider_list_limit: int,
) -> float:
    headers = {"X-Account-Id": account_id}
    message_id = f"load-provider-{run_id}-{stage_label}-a{account_id}-{uuid.uuid4().hex}"
    started = time.monotonic()
    retry_after = 0.0
    try:
        async with session.get(
            f"{host}/api/load-test/provider-probe",
            params={
                "operation": operation,
                "provider_kind": provider_kind,
                "limit": str(provider_list_limit),
                "message_id": message_id,
            },
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            body = await response.text()
            latency_ms = (time.monotonic() - started) * 1000
            code = ""
            try:
                data = json.loads(body) if body else {}
                code = str(data.get("code") or "")
            except json.JSONDecodeError:
                data = {}
            async with state.lock:
                state.counters.attempts += 1
                state.response_latencies_ms.append(latency_ms)
                state.operation_counts[operation] = state.operation_counts.get(operation, 0) + 1
            if 200 <= response.status < 300:
                async with state.lock:
                    state.counters.ok += 1
            elif response.status in {429, 503}:
                retry_after = float(response.headers.get("Retry-After") or 10)
                async with state.lock:
                    state.counters.backpressure += 1
                    if code == "EMAIL_PROVIDER_BACKOFF":
                        state.counters.provider_backoff += 1
            elif response.status >= 500:
                async with state.lock:
                    state.counters.server_errors += 1
                    state.counters.other_status[str(response.status)] = (
                        state.counters.other_status.get(str(response.status), 0) + 1
                    )
                append_jsonl(output_dir / "errors.jsonl", {
                    "ts": utc_now(),
                    "stage": stage_label,
                    "operation": operation,
                    "status": response.status,
                    "body": body[:500],
                })
            else:
                async with state.lock:
                    state.counters.client_errors += 1
                    state.counters.other_status[str(response.status)] = (
                        state.counters.other_status.get(str(response.status), 0) + 1
                    )
                append_jsonl(output_dir / "errors.jsonl", {
                    "ts": utc_now(),
                    "stage": stage_label,
                    "operation": operation,
                    "status": response.status,
                    "body": body[:500],
                })
    except Exception as exc:
        async with state.lock:
            state.counters.attempts += 1
            state.counters.client_errors += 1
            state.operation_counts[operation] = state.operation_counts.get(operation, 0) + 1
        append_jsonl(output_dir / "errors.jsonl", {
            "ts": utc_now(),
            "stage": stage_label,
            "operation": operation,
            "error": f"{type(exc).__name__}: {exc}",
        })
    return retry_after


async def provider_user_loop(
    *,
    session: aiohttp.ClientSession,
    host: str,
    run_id: str,
    stage_label: str,
    stage_users: int,
    user_index: int,
    stage_end: float,
    state: StageState,
    output_dir: Path,
    account_pool_size: int,
    provider_kind: str,
    provider_period_seconds: float,
    provider_mix: list[tuple[str, int]],
    provider_list_limit: int,
    traffic_shape: str,
    burst_window_seconds: float,
) -> None:
    account_id = account_for_user(user_index, stage_users, account_pool_size)
    await asyncio.sleep(
        initial_user_delay(
            user_index=user_index,
            stage_users=stage_users,
            period_seconds=provider_period_seconds,
            traffic_shape=traffic_shape,
            burst_window_seconds=burst_window_seconds,
        )
    )
    while time.monotonic() < stage_end:
        operation = choose_provider_operation(provider_mix)
        started = time.monotonic()
        retry_after = await provider_probe_once(
            session=session,
            host=host,
            run_id=run_id,
            stage_label=stage_label,
            account_id=account_id,
            operation=operation,
            state=state,
            output_dir=output_dir,
            provider_kind=provider_kind,
            provider_list_limit=provider_list_limit,
        )
        elapsed = time.monotonic() - started
        sleep_for = max(provider_period_seconds - elapsed, 0.0)
        if retry_after:
            sleep_for = max(sleep_for, min(retry_after, provider_period_seconds))
        await asyncio.sleep(sleep_for + random.uniform(0, 0.2))


async def full_flow_user_loop(
    *,
    session: aiohttp.ClientSession,
    host: str,
    run_id: str,
    stage_label: str,
    stage_users: int,
    user_index: int,
    stage_end: float,
    state: StageState,
    output_dir: Path,
    account_pool_size: int,
    provider_kind: str,
    provider_list_limit: int,
    draft_period_seconds: float,
    poll_timeout_seconds: float,
    poll_interval_seconds: float,
    poll_max_interval_seconds: float,
    traffic_shape: str,
    burst_window_seconds: float,
) -> None:
    account_id = account_for_user(user_index, stage_users, account_pool_size)
    await asyncio.sleep(
        initial_user_delay(
            user_index=user_index,
            stage_users=stage_users,
            period_seconds=draft_period_seconds,
            traffic_shape=traffic_shape,
            burst_window_seconds=burst_window_seconds,
        )
    )
    while time.monotonic() < stage_end:
        started = time.monotonic()
        retry_after = 0.0
        for operation in ("list", "detail"):
            retry_after = max(
                retry_after,
                await provider_probe_once(
                    session=session,
                    host=host,
                    run_id=run_id,
                    stage_label=stage_label,
                    account_id=account_id,
                    operation=operation,
                    state=state,
                    output_dir=output_dir,
                    provider_kind=provider_kind,
                    provider_list_limit=provider_list_limit,
                ),
            )
        retry_after = max(
            retry_after,
            await submit_draft_once(
                session=session,
                host=host,
                run_id=run_id,
                stage_label=stage_label,
                account_id=account_id,
                state=state,
                output_dir=output_dir,
                poll_timeout_seconds=poll_timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                poll_max_interval_seconds=poll_max_interval_seconds,
            ),
        )
        retry_after = max(
            retry_after,
            await provider_probe_once(
                session=session,
                host=host,
                run_id=run_id,
                stage_label=stage_label,
                account_id=account_id,
                operation="sent",
                state=state,
                output_dir=output_dir,
                provider_kind=provider_kind,
                provider_list_limit=provider_list_limit,
            ),
        )
        elapsed = time.monotonic() - started
        sleep_for = max(draft_period_seconds - elapsed, 0.0)
        if retry_after:
            sleep_for = max(sleep_for, min(retry_after, draft_period_seconds))
        await asyncio.sleep(sleep_for + random.uniform(0, 0.2))


async def run_stage(
    *,
    session: aiohttp.ClientSession,
    args: argparse.Namespace,
    scenario: str,
    users: int,
    stage_label: str,
    provider_mix: list[tuple[str, int]],
) -> StageResult:
    state = StageState()
    capacity_samples: list[CapacitySample] = []
    started_at = utc_now()
    stage_end = time.monotonic() + args.stage_seconds
    monitor = asyncio.create_task(
        monitor_capacity(
            session,
            args.host,
            args.output_dir,
            stage_label,
            stage_end,
            capacity_samples,
            args.capacity_sample_seconds,
        )
    )

    if scenario == "draft-users":
        tasks = [
            asyncio.create_task(
                draft_user_loop(
                    session=session,
                    host=args.host,
                    run_id=args.run_id,
                    stage_label=stage_label,
                    stage_users=users,
                    user_index=index,
                    stage_end=stage_end,
                    state=state,
                    output_dir=args.output_dir,
                    account_pool_size=args.account_pool_size,
                    draft_period_seconds=args.draft_period_seconds,
                    poll_timeout_seconds=args.poll_timeout_seconds,
                    poll_interval_seconds=args.poll_interval_seconds,
                    poll_max_interval_seconds=args.poll_max_interval_seconds,
                    traffic_shape=args.traffic_shape,
                    burst_window_seconds=args.burst_window_seconds,
                )
            )
            for index in range(users)
        ]
    elif scenario == "provider":
        tasks = [
            asyncio.create_task(
                provider_user_loop(
                    session=session,
                    host=args.host,
                    run_id=args.run_id,
                    stage_label=stage_label,
                    stage_users=users,
                    user_index=index,
                    stage_end=stage_end,
                    state=state,
                    output_dir=args.output_dir,
                    account_pool_size=args.account_pool_size,
                    provider_kind=args.provider_kind,
                    provider_period_seconds=args.provider_period_seconds,
                    provider_mix=provider_mix,
                    provider_list_limit=args.provider_list_limit,
                    traffic_shape=args.traffic_shape,
                    burst_window_seconds=args.burst_window_seconds,
                )
            )
            for index in range(users)
        ]
    else:
        tasks = [
            asyncio.create_task(
                full_flow_user_loop(
                    session=session,
                    host=args.host,
                    run_id=args.run_id,
                    stage_label=stage_label,
                    stage_users=users,
                    user_index=index,
                    stage_end=stage_end,
                    state=state,
                    output_dir=args.output_dir,
                    account_pool_size=args.account_pool_size,
                    provider_kind=args.provider_kind,
                    provider_list_limit=args.provider_list_limit,
                    draft_period_seconds=args.draft_period_seconds,
                    poll_timeout_seconds=args.poll_timeout_seconds,
                    poll_interval_seconds=args.poll_interval_seconds,
                    poll_max_interval_seconds=args.poll_max_interval_seconds,
                    traffic_shape=args.traffic_shape,
                    burst_window_seconds=args.burst_window_seconds,
                )
            )
            for index in range(users)
        ]

    await asyncio.gather(*tasks)
    await monitor
    drain_completed = True
    if scenario_has_drafts(scenario):
        drain_completed = await wait_for_capacity_idle(
            session,
            args.host,
            args.drain_timeout_seconds,
        )
    capacity_end = await fetch_capacity(session, args.host)
    capacity_samples.append(capacity_end)

    response_p95 = percentile(state.response_latencies_ms, 95)
    ready_p95 = percentile(state.ready_latencies_ms, 95)
    status, reason = classify_stage(
        scenario=scenario,
        counters=state.counters,
        drain_completed=drain_completed,
        response_p95_ms=response_p95,
        ready_p95_ms=ready_p95,
        max_failure_rate=args.max_failure_rate,
        response_p95_degraded_ms=args.response_p95_degraded_ms,
        draft_ready_p95_degraded_ms=args.draft_ready_p95_degraded_ms,
        provider_backoff_degraded_rate=args.provider_backoff_degraded_rate,
    )
    result = StageResult(
        scenario=scenario,
        label=stage_label,
        users=users,
        provider_kind=args.provider_kind,
        started_at=started_at,
        finished_at=utc_now(),
        duration_seconds=args.stage_seconds,
        counters=state.counters,
        response_p50_ms=percentile(state.response_latencies_ms, 50),
        response_p95_ms=response_p95,
        response_p99_ms=percentile(state.response_latencies_ms, 99),
        ready_p50_ms=percentile(state.ready_latencies_ms, 50),
        ready_p95_ms=ready_p95,
        ready_p99_ms=percentile(state.ready_latencies_ms, 99),
        queue_wait_p95_ms=percentile(state.queue_wait_ms, 95),
        run_p95_ms=percentile(state.run_ms, 95),
        poll_p95_ms=percentile(state.poll_latencies_ms, 95),
        max_queue_depth=max((sample.queue_depth for sample in capacity_samples if sample.ok), default=0),
        max_jobs_total=max((sample.jobs_total for sample in capacity_samples if sample.ok), default=0),
        max_active_workers=max((sample.active_workers for sample in capacity_samples if sample.ok), default=0),
        drain_completed=drain_completed,
        operation_counts=dict(state.operation_counts),
        status=status,
        reason=reason,
    )
    write_json(args.output_dir / f"stage-{stage_label}.json", asdict(result))
    return result


def write_report(
    *,
    output_dir: Path,
    run_id: str,
    host: str,
    scenario: str,
    provider_kind: str,
    stages: list[int],
    stage_seconds: int,
    results: list[StageResult],
    finished: bool,
) -> None:
    healthy = [result for result in results if result.status == "healthy"]
    degraded = next((result for result in results if result.status == "degraded"), None)
    crashed = next((result for result in results if result.status == "crashed"), None)

    lines = [
        f"# Load test Railway mock - {run_id}",
        "",
        f"- Host: `{host}`",
        f"- Scenario: `{scenario}`",
        f"- Provider: `{provider_kind}`",
        f"- Statut: `{'terminé' if finished else 'en cours'}`",
        f"- Durée par palier: `{stage_seconds}s`",
        f"- Paliers: `{','.join(str(stage) for stage in stages)}`",
        f"- Dernier palier sain: `{healthy[-1].label if healthy else 'aucun'}`",
        f"- Premier palier dégradé: `{degraded.label if degraded else 'non observé'}`",
        f"- Premier échec dur: `{crashed.label if crashed else 'non observé'}`",
        "",
        "| Stage | Users | Statut | Raison | Attempts | OK/202 | Completed | 429/503 | Provider backoff | 5xx | Client err | Resp p95 | Ready p95 | Queue wait p95 | Run p95 | Poll timeouts | Max queue | Ops |",
        "|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for result in results:
        counters = result.counters
        ok_or_accepted = counters.accepted if scenario_has_drafts(scenario) else counters.ok
        operations = ", ".join(
            f"{name}:{count}" for name, count in sorted(result.operation_counts.items())
        )
        lines.append(
            "| "
            f"{result.label} | {result.users} | {result.status} | {result.reason} | "
            f"{counters.attempts} | {ok_or_accepted} | {counters.completed} | "
            f"{counters.backpressure} | {counters.provider_backoff} | "
            f"{counters.server_errors} | {counters.client_errors} | "
            f"{result.response_p95_ms if result.response_p95_ms is not None else ''} | "
            f"{result.ready_p95_ms if result.ready_p95_ms is not None else ''} | "
            f"{result.queue_wait_p95_ms if result.queue_wait_p95_ms is not None else ''} | "
            f"{result.run_p95_ms if result.run_p95_ms is not None else ''} | "
            f"{counters.poll_timeouts} | {result.max_queue_depth} | {operations} |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `429/503` correspond à une saturation contrôlée ou à un backoff provider.",
            "- `Ready p95` mesure la durée POST `/process` -> statut Redis/RQ `completed`.",
            "- Les scénarios `provider` et `full-flow` utilisent `/api/load-test/provider-probe`, fermé hors `AGENTYS_LOAD_TEST_MODE`.",
            "- En mode mock, les chiffres mesurent la capacité système et les politiques de backoff, pas les quotas réels des API Google/Microsoft.",
            "- Les modes `--llm-mode live` / `--provider-mode live` sont protégés par `--allow-live-services` et doivent rester sur de petits paliers.",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main_async(args: argparse.Namespace) -> int:
    args.host = args.host.rstrip("/")
    if args.soak_hours is not None:
        args.stage_seconds = max(1, int(args.soak_hours * 3600))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    provider_mix = parse_provider_mix(args.provider_mix)
    stages = parse_stages(args.stages)
    validate_live_service_guard(args, stages)
    write_json(args.output_dir / "run-config.json", {
        "run_id": args.run_id,
        "host": args.host,
        "scenario": args.scenario,
        "provider_kind": args.provider_kind,
        "llm_mode": args.llm_mode,
        "provider_mode": args.provider_mode,
        "traffic_shape": args.traffic_shape,
        "burst_window_seconds": args.burst_window_seconds,
        "stages": stages,
        "stage_seconds": args.stage_seconds,
        "account_pool_size": args.account_pool_size,
        "draft_period_seconds": args.draft_period_seconds,
        "poll_interval_seconds": args.poll_interval_seconds,
        "poll_max_interval_seconds": args.poll_max_interval_seconds,
        "provider_period_seconds": args.provider_period_seconds,
        "provider_mix": provider_mix,
        "started_at": utc_now(),
    })

    connector = aiohttp.TCPConnector(
        limit=args.client_limit,
        ttl_dns_cache=300,
        ssl=False,
    )
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=20, sock_read=60)
    results: list[StageResult] = []
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async with session.get(f"{args.host}/api/health/strict") as response:
                if response.status != 200:
                    body = await response.text()
                    raise RuntimeError(f"strict health failed: {response.status} {body[:300]}")

            for users in stages:
                label = f"{args.scenario}-u{users}"
                print(
                    f"[load] stage_start scenario={args.scenario} users={users} label={label}",
                    flush=True,
                )
                append_jsonl(args.output_dir / "events.jsonl", {
                    "ts": utc_now(),
                    "event": "stage_start",
                    "stage": label,
                    "users": users,
                })
                result = await run_stage(
                    session=session,
                    args=args,
                    scenario=args.scenario,
                    users=users,
                    stage_label=label,
                    provider_mix=provider_mix,
                )
                results.append(result)
                print(
                    "[load] stage_done "
                    f"label={label} status={result.status} reason={result.reason} "
                    f"attempts={result.counters.attempts} "
                    f"accepted={result.counters.accepted} ok={result.counters.ok} "
                    f"completed={result.counters.completed} "
                    f"backpressure={result.counters.backpressure} "
                    f"provider_backoff={result.counters.provider_backoff} "
                    f"response_p95={result.response_p95_ms} "
                    f"ready_p95={result.ready_p95_ms}",
                    flush=True,
                )
                append_jsonl(args.output_dir / "events.jsonl", {
                    "ts": utc_now(),
                    "event": "stage_done",
                    **asdict(result),
                })
                write_report(
                    output_dir=args.output_dir,
                    run_id=args.run_id,
                    host=args.host,
                    scenario=args.scenario,
                    provider_kind=args.provider_kind,
                    stages=stages,
                    stage_seconds=args.stage_seconds,
                    results=results,
                    finished=False,
                )
                if result.status == "crashed" and args.stop_on_crash:
                    break
    except Exception as exc:
        append_jsonl(args.output_dir / "errors.jsonl", {
            "ts": utc_now(),
            "fatal": f"{type(exc).__name__}: {exc}",
        })
        write_json(args.output_dir / "run-final.json", {
            "finished_at": utc_now(),
            "fatal": f"{type(exc).__name__}: {exc}",
            "results": [asdict(result) for result in results],
        })
        write_report(
            output_dir=args.output_dir,
            run_id=args.run_id,
            host=args.host,
            scenario=args.scenario,
            provider_kind=args.provider_kind,
            stages=stages,
            stage_seconds=args.stage_seconds,
            results=results,
            finished=True,
        )
        return 2

    write_json(args.output_dir / "run-final.json", {
        "finished_at": utc_now(),
        "results": [asdict(result) for result in results],
    })
    write_report(
        output_dir=args.output_dir,
        run_id=args.run_id,
        host=args.host,
        scenario=args.scenario,
        provider_kind=args.provider_kind,
        stages=stages,
        stage_seconds=args.stage_seconds,
        results=results,
        finished=True,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--run-id", default=datetime.now().strftime("railway-mock-%Y%m%d-%H%M%S"))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--scenario",
        choices=["draft-users", "provider", "full-flow"],
        default="draft-users",
    )
    parser.add_argument("--provider-kind", choices=["gmail", "outlook", "mock-load"], default="mock-load")
    parser.add_argument("--stages", default="100,400,800,1200")
    parser.add_argument("--stage-seconds", type=int, default=180)
    parser.add_argument("--soak-hours", type=float, default=None)
    parser.add_argument("--traffic-shape", choices=["steady", "burst"], default="steady")
    parser.add_argument("--burst-window-seconds", type=float, default=0.0)
    parser.add_argument("--client-limit", type=int, default=1500)
    parser.add_argument("--account-pool-size", type=int, default=1000)
    parser.add_argument("--capacity-sample-seconds", type=float, default=10.0)
    parser.add_argument("--draft-period-seconds", type=float, default=60.0)
    parser.add_argument("--poll-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=1.0)
    parser.add_argument("--poll-max-interval-seconds", type=float, default=5.0)
    parser.add_argument("--drain-timeout-seconds", type=int, default=180)
    parser.add_argument("--provider-period-seconds", type=float, default=15.0)
    parser.add_argument("--provider-mix", default="detail:8,list:1,sent:1")
    parser.add_argument("--provider-list-limit", type=int, default=20)
    parser.add_argument("--llm-mode", choices=["mock", "live"], default="mock")
    parser.add_argument("--provider-mode", choices=["mock", "live"], default="mock")
    parser.add_argument("--allow-live-services", action="store_true")
    parser.add_argument("--max-live-users", type=int, default=25)
    parser.add_argument("--allow-high-volume-live-services", action="store_true")
    parser.add_argument("--max-failure-rate", type=float, default=0.01)
    parser.add_argument("--response-p95-degraded-ms", type=int, default=1000)
    parser.add_argument("--draft-ready-p95-degraded-ms", type=int, default=30000)
    parser.add_argument("--provider-backoff-degraded-rate", type=float, default=0.01)
    parser.add_argument("--stop-on-crash", action="store_true", default=True)
    parser.add_argument("--no-stop-on-crash", action="store_false", dest="stop_on_crash")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.output_dir is None:
        args.output_dir = Path("tasks/load-reports") / args.run_id
    try:
        return asyncio.run(main_async(args))
    except ValueError as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
