"""
Visual test: Verify signature rendering is consistent across all compose contexts.
"""
import os
import time
from playwright.sync_api import sync_playwright

BASE = "http://localhost:1420"
OUT = os.path.join(os.path.dirname(__file__), "..", "audit-screenshots", "signature-test")
os.makedirs(OUT, exist_ok=True)

def screenshot(page, name, element=None):
    path = os.path.join(OUT, f"{name}.png")
    if element:
        element.screenshot(path=path)
    else:
        page.screenshot(path=path)
    print(f"  [OK] {name}.png")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page(viewport={"width": 1280, "height": 900})

    # Capture console errors
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)

    print("\n=== Signature Visual Test ===\n")

    print("[1] Loading app...")
    page.goto(BASE)

    # Wait for React to mount — look for any rendered content
    try:
        page.wait_for_selector('#root > *', timeout=15000)
        print("  React mounted")
    except:
        print("  [WARN] React did not mount in 15s")
        if errors:
            print(f"  Console errors: {errors[:3]}")

    page.wait_for_timeout(3000)
    screenshot(page, "01-app-loaded")

    # Check what's on screen
    root_html = page.evaluate("() => document.getElementById('root')?.children.length || 0")
    print(f"  Root children: {root_html}")

    # 2. Compose
    print("\n[2] Compose modal...")
    page.keyboard.press("c")
    page.wait_for_timeout(2000)
    screenshot(page, "02-after-c-key")

    compose_visible = page.locator('.gmail-modal-overlay').is_visible()
    print(f"  Modal visible: {compose_visible}")

    if compose_visible:
        sig = page.locator('.nm-signature-footer').first
        sig_visible = sig.is_visible() if sig.count() > 0 else False
        print(f"  .nm-signature-footer visible: {sig_visible}")
        if sig_visible:
            screenshot(page, "02b-compose-sig", sig)
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)

    # 3. Reply
    print("\n[3] Reply...")
    email_count = page.locator('.swipeable-email-item').count()
    print(f"  Emails found: {email_count}")

    if email_count > 0:
        page.locator('.swipeable-email-item').first.click()
        page.wait_for_timeout(3000)
        screenshot(page, "03-email-detail")

        page.keyboard.press("r")
        page.wait_for_timeout(3000)
        screenshot(page, "04-reply")

        rc_count = page.locator('.rc-signature-footer').count()
        old_count = page.locator('.agentys-signature').count()
        print(f"  .rc-signature-footer count: {rc_count}")
        print(f"  .agentys-signature count: {old_count}")

        if rc_count > 0:
            screenshot(page, "04b-reply-sig", page.locator('.rc-signature-footer').first)

        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)

        # 4. Forward
        print("\n[4] Forward...")
        page.locator('.swipeable-email-item').first.click()
        page.wait_for_timeout(2000)
        page.keyboard.press("f")
        page.wait_for_timeout(3000)
        screenshot(page, "05-forward")

        fwd_rc = page.locator('.rc-signature-footer').count()
        print(f"  .rc-signature-footer count: {fwd_rc}")
        if fwd_rc > 0:
            screenshot(page, "05b-fwd-sig", page.locator('.rc-signature-footer').first)

    if errors:
        print(f"\n  Console errors ({len(errors)}):")
        for e in errors[:5]:
            print(f"    - {e[:120]}")

    print(f"\n=== Done. Screenshots: {OUT} ===")
    browser.close()
