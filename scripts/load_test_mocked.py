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

"""Run mocked Agentys load stages and write a degradation report."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STAGES = "50,100,150,200,300,400,600,800,1000,1250,1500,2000"
PERF_RE = re.compile(
    r"phase=process_background_total email_id=(?P<email_id>\S+).*? ms=(?P<ms>\d+)"
)
QUEUE_FULL_RE = re.compile(
    r"\[DRAFT-QUEUE\] status=full email_id=(?P<email_id>\S+)"
)
QUEUE_EVENT_RE = re.compile(
    r"\[DRAFT-QUEUE\] status=(?P<status>enqueued|duplicate|full) "
    r"email_id=(?P<email_id>\S+) account_id=(?P<account_id>\S+)"
)


@dataclass
class AccountStageStats:
    account_id: str
    attempts: int = 0
    accepted: int = 0
    backpressure: int = 0
    duplicates: int = 0


@dataclass
class StageResult:
    label: str
    users: int
    account_pool_size: int
    target_drafts_per_minute: int | None
    status: str
    reason: str
    requests: int
    failures: int
    requests_per_second: float
    process_requests: int
    draft_attempts_per_minute: float
    draft_accepts_per_minute: float
    aggregate_p95_ms: int | None
    process_p95_ms: int | None
    background_count: int
    background_p95_ms: int | None
    backpressure_count: int
    per_account_stats: list[AccountStageStats]
    drain_completed: bool
    locust_exit_code: int
    server_alive: bool
    csv_path: Path
    html_path: Path


def parse_duration_seconds(value: str) -> int:
    raw = value.strip().lower()
    if raw.endswith("ms"):
        return max(1, int(raw[:-2]) // 1000)
    if raw.endswith("s"):
        return int(raw[:-1])
    if raw.endswith("m"):
        return int(raw[:-1]) * 60
    if raw.endswith("h"):
        return int(raw[:-1]) * 3600
    return int(raw)


def percentile(values: list[int], pct: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((pct / 100) * (len(ordered) - 1)))))
    return ordered[index]


def read_stats(csv_path: Path) -> dict[str, dict[str, str]]:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        return {row["Name"]: row for row in csv.DictReader(handle)}


def int_field(row: dict[str, str] | None, key: str) -> int | None:
    if not row:
        return None
    value = row.get(key)
    if value in (None, ""):
        return None
    return int(float(value))


def float_field(row: dict[str, str] | None, key: str) -> float:
    if not row:
        return 0.0
    value = row.get(key)
    if value in (None, ""):
        return 0.0
    return float(value)


def wait_for_health(url: str, timeout_seconds: int) -> bool:
    deadline = time.monotonic() + timeout_seconds
    health_url = f"{url.rstrip('/')}/api/health"
    while time.monotonic() < deadline:
        try:
            with urlopen(health_url, timeout=2) as response:
                if 200 <= response.status < 500:
                    return True
        except URLError:
            pass
        except OSError:
            pass
        time.sleep(1)
    return False


def _capacity_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float | str):
        try:
            return int(float(value))
        except ValueError:
            return 0
    return 0


def read_capacity(url: str) -> dict[str, object] | None:
    capacity_url = f"{url.rstrip('/')}/api/health/capacity"
    try:
        with urlopen(capacity_url, timeout=2) as response:
            if response.status != 200:
                return None
            payload = response.read().decode("utf-8")
    except (OSError, URLError):
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def wait_for_capacity_idle(url: str, timeout_seconds: int) -> bool:
    if timeout_seconds <= 0:
        return True

    deadline = time.monotonic() + timeout_seconds
    last_state: tuple[int, int, int] | None = None
    while time.monotonic() < deadline:
        capacity = read_capacity(url)
        draft_queue = capacity.get("draft_queue") if capacity else None
        if isinstance(draft_queue, dict):
            queue_depth = _capacity_int(draft_queue.get("queue_depth"))
            active_workers = _capacity_int(draft_queue.get("active_workers"))
            jobs_total = _capacity_int(draft_queue.get("jobs_total"))
            last_state = (queue_depth, active_workers, jobs_total)
            if queue_depth == 0 and active_workers == 0 and jobs_total == 0:
                return True
        time.sleep(1)

    if last_state is not None:
        queue_depth, active_workers, jobs_total = last_state
        print(
            "[load] drain timeout "
            f"queue_depth={queue_depth} active_workers={active_workers} jobs_total={jobs_total}",
            flush=True,
        )
    return False


def is_server_alive(process: subprocess.Popen[bytes], url: str) -> bool:
    if process.poll() is not None:
        return False
    return wait_for_health(url, timeout_seconds=3)


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=20)
        return
    except subprocess.TimeoutExpired:
        pass
    process.terminate()
    try:
        process.wait(timeout=10)
        return
    except subprocess.TimeoutExpired:
        pass
    process.kill()
    process.wait(timeout=10)


def parse_background_ms(log_path: Path, stage_prefix: str) -> list[int]:
    if not log_path.exists():
        return []
    values: list[int] = []
    with log_path.open(encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if stage_prefix not in line:
                continue
            match = PERF_RE.search(line)
            if match:
                values.append(int(match.group("ms")))
    return values


def parse_backpressure_count(log_path: Path, stage_prefix: str) -> int:
    if not log_path.exists():
        return 0
    count = 0
    with log_path.open(encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if stage_prefix not in line:
                continue
            if QUEUE_FULL_RE.search(line):
                count += 1
    return count


def parse_queue_events_by_account(log_path: Path, stage_prefix: str) -> list[AccountStageStats]:
    if not log_path.exists():
        return []
    stats: dict[str, AccountStageStats] = {}
    with log_path.open(encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if stage_prefix not in line:
                continue
            match = QUEUE_EVENT_RE.search(line)
            if not match:
                continue
            account_id = match.group("account_id")
            entry = stats.setdefault(account_id, AccountStageStats(account_id=account_id))
            entry.attempts += 1
            status = match.group("status")
            if status == "full":
                entry.backpressure += 1
            else:
                entry.accepted += 1
                if status == "duplicate":
                    entry.duplicates += 1

    def sort_key(item: AccountStageStats) -> tuple[int, int | str]:
        try:
            return (0, int(item.account_id))
        except ValueError:
            return (1, item.account_id)

    return sorted(stats.values(), key=sort_key)


def classify_stage(
    *,
    locust_exit_code: int,
    server_alive: bool,
    drain_completed: bool,
    failures: int,
    aggregate_p95_ms: int | None,
    process_p95_ms: int | None,
    background_p95_ms: int | None,
    backpressure_count: int,
    max_failure_rate: float,
    http_p95_degraded_ms: int,
    background_p95_degraded_ms: int,
    requests: int,
) -> tuple[str, str]:
    if not server_alive:
        return "crashed", "API health check failed or process exited"
    if locust_exit_code != 0:
        return "crashed", f"Locust exited with code {locust_exit_code}"
    if requests <= 0:
        return "crashed", "No successful sampling window"

    failure_rate = failures / max(1, requests)
    degraded_reasons: list[str] = []
    if not drain_completed:
        degraded_reasons.append("drain_timeout")
    if failure_rate > max_failure_rate:
        degraded_reasons.append(f"failure_rate={failure_rate:.3%}")
    if aggregate_p95_ms is not None and aggregate_p95_ms > http_p95_degraded_ms:
        degraded_reasons.append(f"aggregate_p95={aggregate_p95_ms}ms")
    if process_p95_ms is not None and process_p95_ms > http_p95_degraded_ms:
        degraded_reasons.append(f"process_accept_p95={process_p95_ms}ms")
    if background_p95_ms is not None and background_p95_ms > background_p95_degraded_ms:
        degraded_reasons.append(f"background_p95={background_p95_ms}ms")
    if backpressure_count > 0:
        degraded_reasons.append(f"backpressure={backpressure_count}")

    if degraded_reasons:
        return "degraded", ", ".join(degraded_reasons)
    return "healthy", "within thresholds"


def run_stage(
    *,
    users: int,
    account_pool_size: int,
    stage_label: str,
    target_drafts_per_minute: int | None,
    spawn_rate: int,
    duration: str,
    host: str,
    run_id: str,
    output_dir: Path,
    server_log: Path,
    worker_log: Path | None,
    env: dict[str, str],
    thresholds: argparse.Namespace,
) -> StageResult:
    stage_prefix = f"load-{run_id}-{stage_label}-"
    base = output_dir / f"stage-{stage_label}"
    html_path = output_dir / f"stage-{stage_label}.html"
    command = [
        sys.executable,
        "-m",
        "locust",
        "-f",
        str(ROOT / "tests/load/locustfile.py"),
        "--headless",
        "-u",
        str(users),
        "-r",
        str(spawn_rate),
        "-t",
        duration,
        "--host",
        host,
        "--csv",
        str(base),
        "--html",
        str(html_path),
    ]
    stage_env = dict(env)
    stage_env["LOAD_RUN_ID"] = run_id
    stage_env["LOAD_STAGE_USERS"] = str(users)
    stage_env["LOAD_STAGE_LABEL"] = stage_label
    if target_drafts_per_minute is not None:
        stage_env["LOAD_TARGET_DRAFTS_PER_MINUTE"] = str(target_drafts_per_minute)
    else:
        stage_env.pop("LOAD_TARGET_DRAFTS_PER_MINUTE", None)
    if account_pool_size > 0:
        stage_env["LOAD_ACCOUNT_POOL_SIZE"] = str(account_pool_size)
    else:
        stage_env.pop("LOAD_ACCOUNT_POOL_SIZE", None)
    stage_env.setdefault("LOAD_ACCOUNT_ID", "1")
    if target_drafts_per_minute is None:
        print(
            f"[load] stage users={users} accounts={account_pool_size or 1} "
            f"duration={duration}",
            flush=True,
        )
    else:
        print(
            f"[load] stage users={users} target_drafts_per_minute={target_drafts_per_minute} "
            f"accounts={account_pool_size or 1} duration={duration}",
            flush=True,
        )
    completed = subprocess.run(command, cwd=ROOT, env=stage_env, check=False)
    post_stage_alive = wait_for_health(host, timeout_seconds=3)
    drain_completed = False
    if post_stage_alive:
        print(
            f"[load] draining stage queue timeout={thresholds.drain_timeout_seconds}s",
            flush=True,
        )
        drain_completed = wait_for_capacity_idle(
            host,
            timeout_seconds=thresholds.drain_timeout_seconds,
        )

    csv_path = Path(f"{base}_stats.csv")
    stats = read_stats(csv_path) if csv_path.exists() else {}
    aggregate = stats.get("Aggregated")
    process = stats.get("emails:process-cached")
    requests = int_field(aggregate, "Request Count") or 0
    failures = int_field(aggregate, "Failure Count") or 0
    process_requests = int_field(process, "Request Count") or 0
    aggregate_p95 = int_field(aggregate, "95%")
    process_p95 = int_field(process, "95%")
    rps = float_field(aggregate, "Requests/s")

    background_values = parse_background_ms(server_log, stage_prefix)
    if worker_log is not None:
        background_values.extend(parse_background_ms(worker_log, stage_prefix))
    background_p95 = percentile(background_values, 95)
    per_account_stats = parse_queue_events_by_account(server_log, stage_prefix)
    backpressure_count = sum(item.backpressure for item in per_account_stats)
    if not per_account_stats:
        backpressure_count = parse_backpressure_count(server_log, stage_prefix)
    duration_seconds = max(1, parse_duration_seconds(duration))
    draft_attempts_per_minute = process_requests * 60.0 / duration_seconds
    draft_accepts_per_minute = max(0, process_requests - backpressure_count) * 60.0 / duration_seconds
    alive = wait_for_health(host, timeout_seconds=3)
    status, reason = classify_stage(
        locust_exit_code=completed.returncode,
        server_alive=alive,
        drain_completed=drain_completed,
        failures=failures,
        aggregate_p95_ms=aggregate_p95,
        process_p95_ms=process_p95,
        background_p95_ms=background_p95,
        backpressure_count=backpressure_count,
        max_failure_rate=thresholds.max_failure_rate,
        http_p95_degraded_ms=thresholds.http_p95_degraded_ms,
        background_p95_degraded_ms=thresholds.background_p95_degraded_ms,
        requests=requests,
    )
    print(
        "[load] result "
        f"label={stage_label} users={users} status={status} requests={requests} failures={failures} "
        f"rps={rps:.2f} http_p95={aggregate_p95} process_p95={process_p95} "
        f"bg_p95={background_p95} backpressure={backpressure_count} "
        f"drain_completed={drain_completed} "
        f"draft_attempts_per_minute={draft_attempts_per_minute:.2f} "
        f"draft_accepts_per_minute={draft_accepts_per_minute:.2f}",
        flush=True,
    )
    return StageResult(
        label=stage_label,
        users=users,
        account_pool_size=account_pool_size,
        target_drafts_per_minute=target_drafts_per_minute,
        status=status,
        reason=reason,
        requests=requests,
        failures=failures,
        requests_per_second=rps,
        process_requests=process_requests,
        draft_attempts_per_minute=draft_attempts_per_minute,
        draft_accepts_per_minute=draft_accepts_per_minute,
        aggregate_p95_ms=aggregate_p95,
        process_p95_ms=process_p95,
        background_count=len(background_values),
        background_p95_ms=background_p95,
        backpressure_count=backpressure_count,
        per_account_stats=per_account_stats,
        drain_completed=drain_completed,
        locust_exit_code=completed.returncode,
        server_alive=alive,
        csv_path=csv_path,
        html_path=html_path,
    )


def write_report(
    *,
    report_path: Path,
    results: list[StageResult],
    run_id: str,
    duration: str,
    stages: list[int],
    server_log: Path,
    worker_log: Path | None,
    thresholds: argparse.Namespace,
) -> None:
    healthy = [r for r in results if r.status == "healthy"]
    degraded = next((r for r in results if r.status == "degraded"), None)
    crashed = next((r for r in results if r.status == "crashed"), None)

    def _stage_name(result: StageResult | None) -> str:
        if result is None:
            return "non observé"
        if result.target_drafts_per_minute is not None:
            return f"{result.target_drafts_per_minute} drafts/min"
        return f"{result.users} users"

    lines = [
        "# Rapport de charge mockée",
        "",
        f"- Run ID: `{run_id}`",
        f"- Date UTC: `{datetime.now(timezone.utc).isoformat()}`",
        f"- Durée par palier: `{duration}`",
        f"- Paliers demandés: `{','.join(map(str, stages))}`",
        f"- Mode: `{'drafts_per_minute' if any(r.target_drafts_per_minute is not None for r in results) else 'users'}`",
        f"- Comptes simulés: `{max((r.account_pool_size or 1) for r in results) if results else 1}`",
        f"- Log serveur: `{server_log}`",
        f"- Log worker: `{worker_log}`" if worker_log else "- Log worker: `n/a`",
        (
            "- Seuils: "
            f"failure_rate>{thresholds.max_failure_rate:.2%}, "
            f"http_p95>{thresholds.http_p95_degraded_ms}ms, "
            f"background_p95>{thresholds.background_p95_degraded_ms}ms, "
            f"drain_timeout>{thresholds.drain_timeout_seconds}s"
        ),
        "",
        "## Verdict",
        "",
        f"- Dernier palier sain: `{_stage_name(healthy[-1]) if healthy else 'aucun'}`",
        f"- Premier palier dégradé: `{_stage_name(degraded)}`",
        f"- Premier palier crash/échec dur: `{_stage_name(crashed)}`",
        "",
        "## Détail par palier",
        "",
        "| Stage | Users | Target drafts/min | Draft attempts/min | Draft accepts/min | Statut | Drain | Raison | Reqs | Failures | RPS | HTTP p95 | Process 202 p95 | Background p95 | Backpressure | Background samples |",
        "|---|---:|---:|---:|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        lines.append(
            "| "
            f"{result.label} | "
            f"{result.users} | "
            f"{result.target_drafts_per_minute if result.target_drafts_per_minute is not None else ''} | "
            f"{result.draft_attempts_per_minute:.2f} | "
            f"{result.draft_accepts_per_minute:.2f} | "
            f"{result.status} | {'oui' if result.drain_completed else 'non'} | {result.reason} | "
            f"{result.requests} | {result.failures} | {result.requests_per_second:.2f} | "
            f"{result.aggregate_p95_ms if result.aggregate_p95_ms is not None else ''} | "
            f"{result.process_p95_ms if result.process_p95_ms is not None else ''} | "
            f"{result.background_p95_ms if result.background_p95_ms is not None else ''} | "
            f"{result.backpressure_count} | "
            f"{result.background_count} |"
        )
    account_rows: list[tuple[StageResult, AccountStageStats]] = []
    for result in results:
        if not result.per_account_stats:
            continue
        sorted_accounts = sorted(
            result.per_account_stats,
            key=lambda item: (-item.backpressure, -item.attempts, item.account_id),
        )
        account_rows.extend((result, item) for item in sorted_accounts[: thresholds.account_report_limit])

    if account_rows:
        lines.extend(
            [
                "",
                f"## Détail par compte (top {thresholds.account_report_limit})",
                "",
                "| Stage | Account | Attempts | Accepted | Backpressure | Duplicates |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for result, account in account_rows:
            lines.append(
                "| "
                f"{result.label} | {account.account_id} | "
                f"{account.attempts} | {account.accepted} | "
                f"{account.backpressure} | {account.duplicates} |"
            )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stages", default=DEFAULT_STAGES)
    parser.add_argument(
        "--draft-rates-per-minute",
        default="",
        help="Comma-separated business-throughput stages. When set, --stages is ignored.",
    )
    parser.add_argument(
        "--users-per-rate-stage",
        type=int,
        default=100,
        help="Virtual users kept active for each drafts/minute stage.",
    )
    parser.add_argument(
        "--account-pool-size",
        type=int,
        default=0,
        help="Spread Locust users across this many simulated X-Account-Id values.",
    )
    parser.add_argument(
        "--account-report-limit",
        type=int,
        default=25,
        help="Maximum account rows shown per stage in the markdown report.",
    )
    parser.add_argument("--duration", default="10m")
    parser.add_argument("--spawn-rate", type=int, default=25)
    parser.add_argument("--host", default="http://127.0.0.1:5050")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--data-dir", default=str(Path(tempfile.gettempdir()) / "agentys-load-data"))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--max-failure-rate", type=float, default=0.001)
    parser.add_argument("--http-p95-degraded-ms", type=int, default=250)
    parser.add_argument("--background-p95-degraded-ms", type=int, default=1500)
    parser.add_argument(
        "--drain-timeout-seconds",
        type=int,
        default=120,
        help="Seconds to wait for accepted draft jobs to finish after each stage.",
    )
    parser.add_argument("--mock-llm-latency-ms", type=int, default=80)
    parser.add_argument(
        "--redis-url",
        default="",
        help="Redis URL for DRAFT_QUEUE_BACKEND=redis load runs.",
    )
    parser.add_argument(
        "--start-draft-worker",
        action="store_true",
        help="Start python -m app.workers.draft_worker alongside the API.",
    )
    parser.add_argument("--stop-on-crash", action="store_true", default=True)
    parser.add_argument("--no-stop-on-crash", action="store_false", dest="stop_on_crash")
    args = parser.parse_args()

    draft_rate_stages = [
        int(item.strip())
        for item in args.draft_rates_per_minute.split(",")
        if item.strip()
    ]
    stages = (
        draft_rate_stages
        if draft_rate_stages
        else [int(item.strip()) for item in args.stages.split(",") if item.strip()]
    )
    output_dir = Path(args.output_dir) if args.output_dir else ROOT / "tasks/load-reports" / args.run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    server_log = output_dir / "server.log"
    worker_log = output_dir / "worker.log" if args.start_draft_worker else None
    report_path = output_dir / "report.md"
    metadata_path = output_dir / "run.json"

    env = dict(os.environ)
    env.update(
        {
            "AGENTYS_LOAD_TEST_MODE": "true",
            "AGENTYS_DATA_DIR": str(data_dir),
            "AGENTYS_MOCK_LLM_LATENCY_MS": str(args.mock_llm_latency_ms),
            "PYTHONUNBUFFERED": "1",
        }
    )
    if args.redis_url:
        env["REDIS_URL"] = args.redis_url
    server_cmd = [
        sys.executable,
        "run_api.py",
        "--host",
        "127.0.0.1",
        "--port",
        str(args.port),
    ]

    print(f"[load] output_dir={output_dir}", flush=True)
    print(f"[load] data_dir={data_dir}", flush=True)
    worker = None
    worker_log_handle = None
    try:
        if args.start_draft_worker:
            worker_log_handle = worker_log.open("wb") if worker_log else None
            worker = subprocess.Popen(
                [sys.executable, "-m", "app.workers.draft_worker"],
                cwd=ROOT,
                env=env,
                stdout=worker_log_handle,
                stderr=subprocess.STDOUT,
            )
            print(f"[load] worker_log={worker_log}", flush=True)
    except Exception:
        if worker_log_handle is not None:
            worker_log_handle.close()
        raise
    with server_log.open("wb") as log_handle:
        server = subprocess.Popen(
            server_cmd,
            cwd=ROOT,
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        try:
            if not wait_for_health(args.host, timeout_seconds=60):
                print("[load] API did not become healthy", file=sys.stderr, flush=True)
                return 2
            results: list[StageResult] = []
            for stage in stages:
                target_drafts_per_minute = stage if draft_rate_stages else None
                users = args.users_per_rate_stage if draft_rate_stages else stage
                stage_label = (
                    f"dpm{target_drafts_per_minute}"
                    if target_drafts_per_minute is not None
                    else f"u{users}"
                )
                if not is_server_alive(server, args.host):
                    results.append(
                        StageResult(
                            label=stage_label,
                            users=users,
                            account_pool_size=args.account_pool_size,
                            target_drafts_per_minute=target_drafts_per_minute,
                            status="crashed",
                            reason="API process exited before stage",
                            requests=0,
                            failures=0,
                            requests_per_second=0.0,
                            process_requests=0,
                            draft_attempts_per_minute=0.0,
                            draft_accepts_per_minute=0.0,
                            aggregate_p95_ms=None,
                            process_p95_ms=None,
                            background_count=0,
                            background_p95_ms=None,
                            backpressure_count=0,
                            per_account_stats=[],
                            drain_completed=False,
                            locust_exit_code=-1,
                            server_alive=False,
                            csv_path=output_dir / f"stage-{stage_label}_stats.csv",
                            html_path=output_dir / f"stage-{stage_label}.html",
                        )
                    )
                    break
                result = run_stage(
                    users=users,
                    account_pool_size=args.account_pool_size,
                    stage_label=stage_label,
                    target_drafts_per_minute=target_drafts_per_minute,
                    spawn_rate=args.spawn_rate,
                    duration=args.duration,
                    host=args.host,
                    run_id=args.run_id,
                    output_dir=output_dir,
                    server_log=server_log,
                    worker_log=worker_log,
                    env=env,
                    thresholds=args,
                )
                results.append(result)
                write_report(
                    report_path=report_path,
                    results=results,
                    run_id=args.run_id,
                    duration=args.duration,
                    stages=stages,
                    server_log=server_log,
                    worker_log=worker_log,
                    thresholds=args,
                )
                if result.status == "crashed" and args.stop_on_crash:
                    break
            metadata_path.write_text(
                json.dumps(
                    {
                        "run_id": args.run_id,
                        "report_path": str(report_path),
                        "server_log": str(server_log),
                        "worker_log": str(worker_log) if worker_log else "",
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "stages": [
                            r.__dict__ | {
                                "per_account_stats": [item.__dict__ for item in r.per_account_stats],
                                "csv_path": str(r.csv_path),
                                "html_path": str(r.html_path),
                            }
                            for r in results
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
            print(f"[load] report={report_path}", flush=True)
            return 0
        finally:
            if server.poll() is None and wait_for_health(args.host, timeout_seconds=2):
                wait_for_capacity_idle(args.host, timeout_seconds=args.drain_timeout_seconds)
            stop_process(server)
            if worker is not None:
                stop_process(worker)
            if worker_log_handle is not None:
                worker_log_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
