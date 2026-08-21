"""CLI entrypoint for syncing AI credit overage usage."""

from __future__ import annotations

import argparse
import json

from app.billing.usage_metering import StripeUsageMeteringService
from app.db.database import get_db_session


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", type=int, default=None, help="Limit sync to one Agentys user_id")
    parser.add_argument("--send", action="store_true", help="Send real Stripe meter events")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    args = parser.parse_args()

    dry_run = not args.send
    with get_db_session() as session:
        service = StripeUsageMeteringService(session)
        results = service.sync_active_subscriptions(dry_run=dry_run, user_id=args.user_id)
        payload = {
            "dry_run": dry_run or not service.config.enabled,
            "sync_enabled": service.config.enabled,
            "results": [result.to_dict() for result in results],
        }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"Stripe usage sync: dry_run={payload['dry_run']} sync_enabled={payload['sync_enabled']}")
    for result in payload["results"]:
        print(
            "user={user_id} plan={plan} status={status} reason={reason} "
            "used={used_credits} included={included_credits} "
            "metered={metered_credits} cost=${cost_usd:.6f}".format(**result)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
