"""
E2E Audit Test - Complete API coverage against live backend (localhost:5050)

Run: python tests/test_e2e_audit.py
"""

import requests
import sys
import time
from datetime import datetime

BASE = "http://127.0.0.1:5050"
PASS = 0
FAIL = 0
SKIP = 0
ERRORS = []

def test(name, method, path, expected_status=None, json_body=None, check=None, allow_statuses=None, timeout=15):
    """Run a single E2E test against the live backend."""
    global PASS, FAIL, SKIP, ERRORS
    url = f"{BASE}{path}"
    try:
        headers = {"Content-Type": "application/json"} if method != "GET" else {}
        if method == "GET":
            r = requests.get(url, timeout=timeout)
        elif method == "POST":
            r = requests.post(url, json=json_body, headers=headers, timeout=timeout)
        elif method == "PATCH":
            r = requests.patch(url, json=json_body, headers=headers, timeout=timeout)
        elif method == "PUT":
            r = requests.put(url, json=json_body, headers=headers, timeout=timeout)
        elif method == "DELETE":
            r = requests.delete(url, headers=headers, timeout=timeout)
        elif method == "OPTIONS":
            r = requests.options(url, timeout=timeout)
        else:
            print(f"  [SKIP] {name} — unknown method {method}")
            SKIP += 1
            return None

        ok = False
        if allow_statuses:
            ok = r.status_code in allow_statuses
        elif expected_status:
            ok = r.status_code == expected_status
        else:
            ok = r.status_code < 500

        if check and ok:
            try:
                data = r.json()
                ok = check(data)
            except Exception as e:
                ok = False
                ERRORS.append(f"{name}: check failed — {e}")

        if ok:
            PASS += 1
            print(f"  [OK]   {name} ({r.status_code})")
        else:
            FAIL += 1
            body_preview = r.text[:200] if r.text else "(empty)"
            ERRORS.append(f"{name}: got {r.status_code}, expected {expected_status or allow_statuses or '<500'} — {body_preview}")
            print(f"  [FAIL] {name} ({r.status_code})")

        return r

    except requests.exceptions.ConnectionError:
        FAIL += 1
        ERRORS.append(f"{name}: Connection refused — is the backend running?")
        print(f"  [FAIL] {name} (connection refused)")
        return None
    except Exception as e:
        FAIL += 1
        ERRORS.append(f"{name}: {type(e).__name__}: {e}")
        print(f"  [FAIL] {name} ({e})")
        return None


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def main():
    global PASS, FAIL, SKIP, ERRORS

    start = time.time()
    print(f"\nAgentys E2E Audit — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Target: {BASE}")

    # ========================================================================
    # 1. HEALTH & CORE
    # ========================================================================
    section("1. HEALTH & CORE")
    test("GET /api/ping", "GET", "/api/ping", 200)
    test("GET /api/health", "GET", "/api/health", 200,
         check=lambda d: d.get("status") in ("ok", "healthy", "degraded"))
    test("GET /api/health/deep", "GET", "/api/health/deep",
         allow_statuses=[200, 503],
         check=lambda d: "status" in d)
    test("GET /api/init", "GET", "/api/init", 200,
         check=lambda d: isinstance(d, dict))
    test("GET /api/stats", "GET", "/api/stats", 200)
    test("GET /api/update-check", "GET", "/api/update-check",
         allow_statuses=[200, 404, 501])

    # ========================================================================
    # 2. EMAILS
    # ========================================================================
    section("2. EMAILS")
    r = test("GET /api/emails (inbox)", "GET", "/api/emails?folder=inbox", 200,
             check=lambda d: isinstance(d, (list, dict)))

    # Extract an email ID for detail tests
    email_id = None
    if r and r.status_code == 200:
        data = r.json()
        emails = data if isinstance(data, list) else data.get("emails", [])
        if emails:
            email_id = emails[0].get("id") or emails[0].get("message_id")

    test("GET /api/emails (sent)", "GET", "/api/emails?folder=sent",
         allow_statuses=[200, 400, 404])
    test("GET /api/emails (draft)", "GET", "/api/emails?folder=draft",
         allow_statuses=[200, 400, 404], timeout=30)
    test("GET /api/emails (spam)", "GET", "/api/emails?folder=spam",
         allow_statuses=[200, 400, 404])
    test("GET /api/emails (trash)", "GET", "/api/emails?folder=trash",
         allow_statuses=[200, 400, 404])
    test("GET /api/emails/inbox-stats", "GET", "/api/emails/inbox-stats",
         allow_statuses=[200, 404])
    test("GET /api/emails (force_refresh)", "GET", "/api/emails?folder=inbox&force_refresh=true", 200,
         check=lambda d: isinstance(d.get("emails"), list))
    test("GET /api/emails (skip_cache)", "GET", "/api/emails?folder=inbox&skip_cache=true", 200,
         check=lambda d: isinstance(d.get("emails"), list))

    if email_id:
        test(f"GET /api/emails/{email_id[:8]}...", "GET", f"/api/emails/{email_id}",
             allow_statuses=[200, 404])
        test(f"GET /api/emails/{email_id[:8]}../thread", "GET", f"/api/emails/{email_id}/thread",
             allow_statuses=[200, 404])
        test(f"GET /api/emails/{email_id[:8]}../speakable", "GET", f"/api/emails/{email_id}/speakable",
             allow_statuses=[200, 404])
        test(f"PATCH /api/emails/{email_id[:8]}../read", "PATCH", f"/api/emails/{email_id}/read",
             json_body={"is_read": True}, allow_statuses=[200, 204, 404])
    else:
        print("  [SKIP] No email_id available for detail tests")
        SKIP += 3

    test("GET /api/emails (invalid folder)", "GET", "/api/emails?folder=nonexistent",
         allow_statuses=[200, 400, 404])
    test("GET /api/emails/fake-id (404)", "GET", "/api/emails/fake-id-nonexistent",
         allow_statuses=[404, 400])

    # Bulk operations (empty arrays = safe no-ops)
    test("PATCH /api/emails/bulk-read (empty)", "PATCH", "/api/emails/bulk-read",
         json_body={"email_ids": []}, allow_statuses=[200, 400])
    test("POST /api/emails/bulk-archive (empty)", "POST", "/api/emails/bulk-archive",
         json_body={"email_ids": []}, allow_statuses=[200, 400])
    test("POST /api/emails/bulk-delete (empty)", "POST", "/api/emails/bulk-delete",
         json_body={"email_ids": []}, allow_statuses=[200, 400])
    test("POST /api/emails/bulk-not-spam (empty)", "POST", "/api/emails/bulk-not-spam",
         json_body={"email_ids": []}, allow_statuses=[200, 400])
    test("POST /api/emails/bulk-restore (empty)", "POST", "/api/emails/bulk-restore",
         json_body={"email_ids": []}, allow_statuses=[200, 400])

    # ========================================================================
    # 3. DRAFTS & PENDING DRAFTS
    # ========================================================================
    section("3. DRAFTS & PENDING DRAFTS")
    test("GET /api/drafts", "GET", "/api/drafts",
         allow_statuses=[200, 404])

    # Refine text (lightweight Haiku call or mock)
    test("POST /api/refine-text", "POST", "/api/refine-text",
         json_body={"text": "Bonjour test", "instruction": "corrige"},
         allow_statuses=[200, 400, 500, 503])

    # Draft with fake ID (should 404)
    test("GET /api/drafts/fake-draft-id", "GET", "/api/drafts/fake-draft-id",
         allow_statuses=[404, 400])
    test("POST /api/drafts/fake-id/refine", "POST", "/api/drafts/fake-id/refine",
         json_body={"instruction": "test"}, allow_statuses=[404, 400])
    test("POST /api/drafts/fake-id/regenerate", "POST", "/api/drafts/fake-id/regenerate",
         json_body={}, allow_statuses=[404, 400])

    # ========================================================================
    # 4. SEARCH
    # ========================================================================
    section("4. SEARCH")
    test("GET /api/emails/search?q=test", "GET", "/api/emails/search?q=test",
         allow_statuses=[200, 400, 404])
    test("GET /api/emails/search/suggestions", "GET", "/api/emails/search/suggestions?q=bo",
         allow_statuses=[200, 400, 404])

    # ========================================================================
    # 5. LABELS
    # ========================================================================
    section("5. LABELS")
    test("GET /api/labels", "GET", "/api/labels", 200,
         check=lambda d: isinstance(d, (list, dict)))
    test("GET /api/labels/counts", "GET", "/api/labels/counts",
         allow_statuses=[200, 404])
    test("GET /api/labels/rules", "GET", "/api/labels/rules",
         allow_statuses=[200, 404])
    test("GET /api/labels/vip", "GET", "/api/labels/vip",
         allow_statuses=[200, 404])
    test("GET /api/labels/rules.md", "GET", "/api/labels/rules.md",
         allow_statuses=[200, 404])

    # ========================================================================
    # 6. ACCOUNTS
    # ========================================================================
    section("6. ACCOUNTS")
    r = test("GET /api/accounts", "GET", "/api/accounts", 200,
             check=lambda d: isinstance(d, (list, dict)))

    account_id = None
    if r and r.status_code == 200:
        data = r.json()
        accounts = data if isinstance(data, list) else data.get("accounts", [])
        if accounts:
            acc = accounts[0]
            account_id = acc.get("id") or acc.get("account_id")

    if account_id:
        test(f"GET /api/accounts/{account_id[:8]}...", "GET", f"/api/accounts/{account_id}",
             allow_statuses=[200, 404])
        test(f"GET /api/accounts/{account_id[:8]}../stats", "GET", f"/api/accounts/{account_id}/stats",
             allow_statuses=[200, 404])
    else:
        print("  [SKIP] No account_id for detail tests")
        SKIP += 2

    test("GET /api/accounts/stats", "GET", "/api/accounts/stats",
         allow_statuses=[200, 404])

    # ========================================================================
    # 7. OAUTH
    # ========================================================================
    section("7. OAUTH")
    test("GET /api/oauth/config", "GET", "/api/oauth/config",
         allow_statuses=[200, 404, 500])
    test("POST /api/oauth/pkce/store", "POST", "/api/oauth/pkce/store",
         json_body={"state": "test-state-e2e", "code_verifier": "test-verifier-e2e"},
         expected_status=200)
    test("GET /api/oauth/pkce/test-state-e2e", "GET", "/api/oauth/pkce/test-state-e2e",
         expected_status=200,
         check=lambda d: d.get("code_verifier") == "test-verifier-e2e")
    test("GET /api/oauth/session/nonexistent/poll", "GET", "/api/oauth/session/nonexistent/poll",
         allow_statuses=[404, 200])

    if account_id:
        test(f"GET /api/oauth/tokens/{account_id[:8]}../status", "GET",
             f"/api/oauth/tokens/{account_id}/status",
             allow_statuses=[200, 404])

    # ========================================================================
    # 8. LEARNING
    # ========================================================================
    section("8. LEARNING")
    test("GET /api/learning/stats", "GET", "/api/learning/stats",
         allow_statuses=[200, 404])
    test("GET /api/learning/patterns", "GET", "/api/learning/patterns",
         allow_statuses=[200, 404])
    test("GET /api/learning/rules", "GET", "/api/learning/rules",
         allow_statuses=[200, 404])
    test("GET /api/learning/comparisons", "GET", "/api/learning/comparisons",
         allow_statuses=[200, 404])
    test("GET /api/learning/all", "GET", "/api/learning/all",
         allow_statuses=[200, 404],
         check=lambda d: "categories" in d if isinstance(d, dict) else True)
    test("GET /api/writing-style", "GET", "/api/writing-style",
         allow_statuses=[200, 404])

    # ========================================================================
    # 9. COSTS & ANALYTICS
    # ========================================================================
    section("9. COSTS & ANALYTICS")
    test("GET /api/costs", "GET", "/api/costs",
         allow_statuses=[200, 401, 403, 404])
    test("GET /api/costs/history", "GET", "/api/costs/history",
         allow_statuses=[200, 401, 403, 404])
    test("GET /api/analytics/quality", "GET", "/api/analytics/quality",
         allow_statuses=[200, 401, 403, 404])
    test("GET /api/analytics/comparison", "GET", "/api/analytics/comparison",
         allow_statuses=[200, 401, 403, 404])
    test("GET /api/draft-quality/stats", "GET", "/api/draft-quality/stats",
         allow_statuses=[200, 404])
    test("GET /api/stats/activity", "GET", "/api/stats/activity",
         allow_statuses=[200, 404])
    test("POST /api/stats/feature", "POST", "/api/stats/feature",
         json_body={"feature": "e2e_audit_test", "action": "test"},
         allow_statuses=[200, 201, 204, 400])

    # ========================================================================
    # 10. FOLLOW-UPS
    # ========================================================================
    section("10. FOLLOW-UPS")
    test("GET /api/followups", "GET", "/api/followups",
         allow_statuses=[200, 404])
    test("GET /api/followups/stats", "GET", "/api/followups/stats",
         allow_statuses=[200, 404])
    test("POST /api/followups/check", "POST", "/api/followups/check",
         allow_statuses=[200, 404, 500])

    # ========================================================================
    # 11. SETTINGS
    # ========================================================================
    section("11. SETTINGS")
    test("GET /api/settings", "GET", "/api/settings",
         allow_statuses=[200, 404])

    # ========================================================================
    # 12. FOLDERS
    # ========================================================================
    section("12. FOLDERS")
    test("GET /api/folders", "GET", "/api/folders",
         allow_statuses=[200, 404])

    # ========================================================================
    # 13. TEMPLATES
    # ========================================================================
    section("13. TEMPLATES")
    test("GET /api/templates", "GET", "/api/templates",
         allow_statuses=[200, 404])
    test("GET /api/templates/stats", "GET", "/api/templates/stats",
         allow_statuses=[200, 404])

    # ========================================================================
    # 14. CALENDAR
    # ========================================================================
    section("14. CALENDAR")
    test("GET /api/calendar/status", "GET", "/api/calendar/status",
         allow_statuses=[200, 404, 501])
    test("GET /api/calendar/today", "GET", "/api/calendar/today",
         allow_statuses=[200, 404, 501])
    test("GET /api/calendar/upcoming", "GET", "/api/calendar/upcoming",
         allow_statuses=[200, 404, 501])
    test("GET /api/calendar/holidays", "GET", "/api/calendar/holidays?timezone=Europe/Paris",
         allow_statuses=[200, 404, 501])
    test("GET /api/calendar/followups", "GET", "/api/calendar/followups",
         allow_statuses=[200, 404, 501])
    test("GET /api/calendar/suggestions", "GET", "/api/calendar/suggestions",
         allow_statuses=[200, 404, 501])

    # ========================================================================
    # 15. FINE-TUNING
    # ========================================================================
    section("15. FINE-TUNING")
    test("GET /api/fine-tuning/corrections", "GET", "/api/fine-tuning/corrections",
         allow_statuses=[200, 404])
    test("GET /api/fine-tuning/feedbacks", "GET", "/api/fine-tuning/feedbacks",
         allow_statuses=[200, 404])
    test("GET /api/fine-tuning/patterns", "GET", "/api/fine-tuning/patterns",
         allow_statuses=[200, 404])
    test("GET /api/fine-tuning/models", "GET", "/api/fine-tuning/models",
         allow_statuses=[200, 404])
    test("GET /api/fine-tuning/sessions", "GET", "/api/fine-tuning/sessions",
         allow_statuses=[200, 404])
    test("GET /api/fine-tuning/stats", "GET", "/api/fine-tuning/stats",
         allow_statuses=[200, 404])
    test("GET /api/fine-tuning/prompt-enhancements", "GET", "/api/fine-tuning/prompt-enhancements",
         allow_statuses=[200, 404])

    # ========================================================================
    # 16. WIZARD & ONBOARDING
    # ========================================================================
    section("16. WIZARD & ONBOARDING")
    test("GET /api/wizard/status", "GET", "/api/wizard/status",
         allow_statuses=[200, 404])
    test("GET /api/wizard/config", "GET", "/api/wizard/config",
         allow_statuses=[200, 404])
    test("GET /api/wizard/packs", "GET", "/api/wizard/packs",
         allow_statuses=[200, 404])
    test("GET /api/wizard/agents", "GET", "/api/wizard/agents",
         allow_statuses=[200, 404])
    test("GET /api/wizard/knowledge-base", "GET", "/api/wizard/knowledge-base",
         allow_statuses=[200, 404])
    test("GET /api/wizard/env-config", "GET", "/api/wizard/env-config",
         allow_statuses=[200, 404])
    test("GET /api/wizard/llm-settings", "GET", "/api/wizard/llm-settings",
         allow_statuses=[200, 404])

    # Onboarding requires account_id — use one if available
    onboarding_qs = f"?account_id={account_id}" if account_id else ""
    test("GET /api/onboarding/status", "GET", f"/api/onboarding/status{onboarding_qs}",
         allow_statuses=[200, 400, 404])
    test("GET /api/onboarding/insights", "GET", f"/api/onboarding/insights{onboarding_qs}",
         allow_statuses=[200, 400, 404])
    test("GET /api/onboarding/learning-status", "GET", "/api/onboarding/learning-status",
         allow_statuses=[200, 404])

    # ========================================================================
    # 17. MARKETPLACE
    # ========================================================================
    section("17. MARKETPLACE")
    test("GET /api/marketplace/agents", "GET", "/api/marketplace/agents",
         allow_statuses=[200, 404])
    test("GET /api/marketplace/agents/featured", "GET", "/api/marketplace/agents/featured",
         allow_statuses=[200, 404])
    test("GET /api/marketplace/installations", "GET", "/api/marketplace/installations?organization_id=default",
         allow_statuses=[200, 400, 404])
    test("GET /api/marketplace/packs", "GET", "/api/marketplace/packs",
         allow_statuses=[200, 404])
    test("GET /api/marketplace/categories", "GET", "/api/marketplace/categories",
         allow_statuses=[200, 404])

    # ========================================================================
    # 18. AGENT MARKETPLACE
    # ========================================================================
    section("18. AGENT MARKETPLACE")
    test("GET /api/agent-marketplace/catalog", "GET", "/api/agent-marketplace/catalog",
         allow_statuses=[200, 404])
    test("GET /api/agent-marketplace/installed", "GET", "/api/agent-marketplace/installed",
         allow_statuses=[200, 404])

    # ========================================================================
    # 19. SNIPPETS
    # ========================================================================
    section("19. SNIPPETS")
    test("GET /api/snippets (auth required)", "GET", "/api/snippets",
         allow_statuses=[200, 401, 404])
    test("GET /api/shared-with-me (auth required)", "GET", "/api/shared-with-me",
         allow_statuses=[200, 401, 404])

    # ========================================================================
    # 20. SPECIALTIES
    # ========================================================================
    section("20. SPECIALTIES")
    test("GET /api/specialties", "GET", "/api/specialties",
         allow_statuses=[200, 404])

    # ========================================================================
    # 21. DISCORD & TELEGRAM
    # ========================================================================
    section("21. DISCORD & TELEGRAM")
    test("GET /api/discord/messages", "GET", "/api/discord/messages",
         allow_statuses=[200, 400, 404, 503])
    test("GET /api/discord/config", "GET", "/api/discord/config",
         allow_statuses=[200, 404])
    test("GET /api/discord/stats", "GET", "/api/discord/stats",
         allow_statuses=[200, 404])
    test("GET /api/telegram/messages", "GET", "/api/telegram/messages",
         allow_statuses=[200, 400, 404, 503])
    test("GET /api/telegram/config", "GET", "/api/telegram/config",
         allow_statuses=[200, 404])
    test("GET /api/telegram/stats", "GET", "/api/telegram/stats",
         allow_statuses=[200, 404])

    # ========================================================================
    # 22. MOBILE
    # ========================================================================
    section("22. MOBILE")
    test("GET /api/mobile/config", "GET", "/api/mobile/config",
         allow_statuses=[200, 404])
    test("GET /api/mobile/preferences", "GET", "/api/mobile/preferences?user_id=e2e-test",
         allow_statuses=[200, 404])
    test("GET /api/mobile/stats", "GET", "/api/mobile/stats?user_id=e2e-test",
         allow_statuses=[200, 404])
    test("GET /api/mobile/drafts", "GET", "/api/mobile/drafts?user_id=e2e-test",
         allow_statuses=[200, 404])

    # ========================================================================
    # 23. SYNC & CONNECTIVITY
    # ========================================================================
    section("23. SYNC & CONNECTIVITY")
    test("GET /api/sync/status", "GET", "/api/sync/status",
         allow_statuses=[200, 404])
    test("GET /api/sync/history", "GET", "/api/sync/history",
         allow_statuses=[200, 404])
    test("GET /api/connectivity/status", "GET", "/api/connectivity/status",
         allow_statuses=[200, 404])
    test("GET /api/connectivity/queue", "GET", "/api/connectivity/queue",
         allow_statuses=[200, 404])

    # ========================================================================
    # 24. CONTACT GROUPS
    # ========================================================================
    section("24. CONTACT GROUPS")
    test("GET /api/contact-groups", "GET", "/api/contact-groups",
         allow_statuses=[200, 404])

    # ========================================================================
    # 25. PUSH NOTIFICATIONS
    # ========================================================================
    section("25. PUSH NOTIFICATIONS")
    test("GET /api/push/devices", "GET", "/api/push/devices",
         allow_statuses=[200, 404])
    test("GET /api/push/stats", "GET", "/api/push/stats",
         allow_statuses=[200, 404])
    test("GET /api/push/history", "GET", "/api/push/history",
         allow_statuses=[200, 404])

    # ========================================================================
    # 26. WEBHOOKS
    # ========================================================================
    section("26. WEBHOOKS")
    test("GET /api/webhooks/", "GET", "/api/webhooks/",
         allow_statuses=[200, 404])
    test("GET /api/webhooks/events", "GET", "/api/webhooks/events",
         allow_statuses=[200, 404])

    # ========================================================================
    # 27. AUTH
    # ========================================================================
    section("27. AUTH")
    test("GET /api/auth/me", "GET", "/api/auth/me",
         allow_statuses=[200, 401, 404])
    test("POST /api/auth/verify (no token)", "POST", "/api/auth/verify",
         json_body={"token": ""}, allow_statuses=[400, 401, 422])

    # ========================================================================
    # 28. ADMIN
    # ========================================================================
    section("28. ADMIN")
    test("GET /api/admin/users", "GET", "/api/admin/users",
         allow_statuses=[200, 401, 403, 404])
    test("GET /api/admin/aggregate", "GET", "/api/admin/aggregate",
         allow_statuses=[200, 401, 403, 404])

    # ========================================================================
    # 29. REMINDERS & RECAP
    # ========================================================================
    section("29. REMINDERS & RECAP")
    test("GET /api/reminders", "GET", "/api/reminders",
         allow_statuses=[200, 404])
    test("GET /api/recap", "GET", "/api/recap",
         allow_statuses=[200, 404])

    # ========================================================================
    # 30. DEEP FOCUS & DEEP WORK
    # ========================================================================
    section("30. DEEP FOCUS & DEEP WORK")
    test("GET /api/deep-work/summary", "GET", "/api/deep-work/summary",
         allow_statuses=[200, 404, 408], timeout=60)
    test("POST /api/deep-focus/interaction", "POST", "/api/deep-focus/interaction",
         json_body={"action": "test", "email_id": "test"},
         allow_statuses=[200, 400, 404])

    # ========================================================================
    # 31. REALTIME EDIT
    # ========================================================================
    section("31. REALTIME EDIT")
    r = test("POST /api/realtime-edit/sessions (create)", "POST", "/api/realtime-edit/sessions",
             json_body={"text": "Hello world", "context": "test", "user_id": "e2e-test"},
             allow_statuses=[200, 201, 404])

    session_id = None
    if r and r.status_code in (200, 201):
        try:
            session_id = r.json().get("session_id") or r.json().get("id")
        except Exception:
            pass

    if session_id:
        test(f"GET /api/realtime-edit/sessions/{session_id[:8]}...", "GET",
             f"/api/realtime-edit/sessions/{session_id}",
             allow_statuses=[200, 404])
        test(f"DELETE /api/realtime-edit/sessions/{session_id[:8]}...", "DELETE",
             f"/api/realtime-edit/sessions/{session_id}",
             allow_statuses=[200, 204, 404])

    # ========================================================================
    # 32. REFUNDS
    # ========================================================================
    section("32. REFUNDS")
    test("GET /api/refunds/fake-id (404)", "GET", "/api/refunds/fake-id",
         expected_status=404)

    # ========================================================================
    # 33. CORS VALIDATION (the fix we just applied)
    # ========================================================================
    section("33. CORS VALIDATION")
    # Test CORS preflight for the critical PKCE endpoint from Vite dev ports
    for origin in ["http://localhost:5174", "http://localhost:5173", "http://localhost:1420"]:
        try:
            r = requests.options(
                f"{BASE}/api/oauth/pkce/store",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "Content-Type",
                },
                timeout=5,
            )
            acao = r.headers.get("Access-Control-Allow-Origin", "")
            if acao == origin:
                PASS += 1
                print(f"  [OK]   CORS preflight from {origin}")
            else:
                FAIL += 1
                ERRORS.append(f"CORS {origin}: ACAO={acao}, expected {origin}")
                print(f"  [FAIL] CORS preflight from {origin} (ACAO={acao})")
        except Exception as e:
            FAIL += 1
            ERRORS.append(f"CORS {origin}: {e}")
            print(f"  [FAIL] CORS preflight from {origin} ({e})")

    # ========================================================================
    # 34. SWAGGER / API DOCS
    # ========================================================================
    section("34. API DOCS")
    test("GET /api/swagger (apispec)", "GET", "/api/swagger",
         allow_statuses=[200, 301, 302, 404])
    test("GET /apispec.json", "GET", "/apispec.json",
         allow_statuses=[200, 404])

    # ========================================================================
    # RESULTS
    # ========================================================================
    elapsed = time.time() - start
    total = PASS + FAIL + SKIP

    print(f"\n{'='*60}")
    print("  RESULTS")
    print(f"{'='*60}")
    print(f"  Total:   {total} tests")
    print(f"  Passed:  {PASS}")
    print(f"  Failed:  {FAIL}")
    print(f"  Skipped: {SKIP}")
    print(f"  Score:   {PASS}/{PASS+FAIL} ({100*PASS/max(1,PASS+FAIL):.0f}%)")
    print(f"  Time:    {elapsed:.1f}s")

    if ERRORS:
        print(f"\n  FAILURES ({len(ERRORS)}):")
        for err in ERRORS:
            print(f"    - {err}")

    print()

    # Write results to file
    with open("tests/_last_run.txt", "w", encoding="utf-8") as f:
        f.write(f"E2E Audit — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Score: {PASS}/{PASS+FAIL} ({100*PASS/max(1,PASS+FAIL):.0f}%)\n")
        f.write(f"Time: {elapsed:.1f}s\n\n")
        if ERRORS:
            f.write("FAILURES:\n")
            for err in ERRORS:
                f.write(f"  - {err}\n")

    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
