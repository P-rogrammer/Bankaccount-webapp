"""
Task 5.1 - actual browser test using Playwright (headless Chromium), since
the environment does support it. Drives the real UI: clicking buttons,
filling forms, reading rendered text - not calling the API directly.
"""

import os
import subprocess
import sys
import tempfile
import time

import requests
from playwright.sync_api import sync_playwright

PROJECT_ROOT = "/home/claude/bankaccount-webapp"
PORT = 5098
BASE = f"http://127.0.0.1:{PORT}"

passed = 0
failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"PASS: {name}")
    else:
        failed += 1
        print(f"FAIL: {name}")


def start_server(storage_path):
    code = (
        "import sys; "
        f"sys.path.insert(0, {PROJECT_ROOT + '/backend'!r}); "
        "from app import create_app; "
        f"app = create_app({storage_path!r}); "
        f"app.run(port={PORT}, use_reloader=False)"
    )
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for _ in range(50):
        try:
            requests.get(f"{BASE}/accounts", timeout=0.5)
            return proc
        except requests.exceptions.ConnectionError:
            time.sleep(0.1)
    raise RuntimeError("server did not start")


def stop_server(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


tmpdir = tempfile.mkdtemp(prefix="browser_test_")
storage_path = os.path.join(tmpdir, "accounts.json")
screenshots_dir = os.path.join(tmpdir, "screenshots")
os.makedirs(screenshots_dir, exist_ok=True)

proc = start_server(storage_path)
try:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1000, "height": 1000})

        console_errors = []
        page_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))

        # 1. Open application
        page.goto(BASE)
        page.wait_for_selector(".accounts-table")  # tbody itself can be zero-height when empty
        check("page loads with title", "BankAccount" in page.title())
        check("empty state shown initially", page.is_visible("#accounts-empty"))
        page.screenshot(path=os.path.join(screenshots_dir, "01_initial_load.png"), full_page=True)

        # 2. Create two accounts
        page.fill("#create-name", "Alice")
        page.click("#create-account-form button[type=submit]")
        page.wait_for_selector("#create-account-message.success")
        check("create Alice success message shown", "created" in page.inner_text("#create-account-message").lower())

        page.fill("#create-name", "Bob")
        page.click("#create-account-form button[type=submit]")
        page.wait_for_selector("text=Bob")

        rows = page.locator("#accounts-table-body tr")
        check("both accounts appear in the table", rows.count() == 2)
        check("empty state hidden once accounts exist", not page.is_visible("#accounts-empty"))
        page.screenshot(path=os.path.join(screenshots_dir, "02_two_accounts.png"), full_page=True)

        # Grab the real account numbers from the rendered table for use below.
        first_row_text = rows.nth(0).inner_text()
        second_row_text = rows.nth(1).inner_text()
        alice_number = first_row_text.split()[0]
        bob_number = second_row_text.split()[0]

        # 3. Deposit into Alice
        page.fill("#deposit-account-number", alice_number)
        page.fill("#deposit-amount", "200")
        page.click("#deposit-form button[type=submit]")
        page.wait_for_selector("#deposit-message.success")
        check("deposit success message shown", "200.00" in page.inner_text("#deposit-message"))
        check(
            "table reflects deposit after refresh-on-success",
            "200.00" in page.locator(f"tr:has-text('{alice_number}')").inner_text(),
        )

        # 4. Withdraw from Alice
        page.fill("#withdraw-account-number", alice_number)
        page.fill("#withdraw-amount", "50")
        page.click("#withdraw-form button[type=submit]")
        page.wait_for_selector("#withdraw-message.success")
        check(
            "table reflects withdrawal",
            "150.00" in page.locator(f"tr:has-text('{alice_number}')").inner_text(),
        )
        page.screenshot(path=os.path.join(screenshots_dir, "03_after_deposit_withdraw.png"), full_page=True)

        # 5. Transfer from Alice to Bob
        page.fill("#transfer-source", alice_number)
        page.fill("#transfer-destination", bob_number)
        page.fill("#transfer-amount", "75")
        page.click("#transfer-form button[type=submit]")
        page.wait_for_selector("#transfer-message.success")
        check(
            "transfer updates source balance in table",
            "75.00" in page.locator(f"tr:has-text('{alice_number}')").inner_text(),
        )
        check(
            "transfer updates destination balance in table",
            "75.00" in page.locator(f"tr:has-text('{bob_number}')").inner_text(),
        )
        page.screenshot(path=os.path.join(screenshots_dir, "04_after_transfer.png"), full_page=True)

        # 6. Trigger an error: withdraw more than the balance
        page.fill("#withdraw-account-number", alice_number)
        page.fill("#withdraw-amount", "999999")
        page.click("#withdraw-form button[type=submit]")
        page.wait_for_selector("#withdraw-message.error")
        error_text = page.inner_text("#withdraw-message")
        check("insufficient-balance error is shown in the UI", "insufficient" in error_text.lower() or "balance" in error_text.lower())
        check("error message does not leak a traceback", "Traceback" not in error_text and ".py" not in error_text)
        check(
            "failed withdrawal did not change the displayed balance",
            "75.00" in page.locator(f"tr:has-text('{alice_number}')").inner_text(),
        )
        page.screenshot(path=os.path.join(screenshots_dir, "05_error_shown.png"), full_page=True)

        # 7. Self-transfer error
        page.fill("#transfer-source", alice_number)
        page.fill("#transfer-destination", alice_number)
        page.fill("#transfer-amount", "10")
        page.click("#transfer-form button[type=submit]")
        page.wait_for_selector("#transfer-message.error")
        check("self-transfer error shown in UI", "same account" in page.inner_text("#transfer-message").lower()
              or "self" in page.inner_text("#transfer-message").lower())

        # 8. Refresh the page and verify persisted data
        page.reload()
        page.wait_for_selector(".accounts-table")
        rows_after_reload = page.locator("#accounts-table-body tr")
        check("accounts still present after page refresh", rows_after_reload.count() == 2)
        check(
            "balances persisted across refresh (source)",
            "75.00" in page.locator(f"tr:has-text('{alice_number}')").inner_text(),
        )
        check(
            "balances persisted across refresh (destination)",
            "75.00" in page.locator(f"tr:has-text('{bob_number}')").inner_text(),
        )
        page.screenshot(path=os.path.join(screenshots_dir, "06_after_page_refresh.png"), full_page=True)

        # 9. Keyboard usability: tab to the create-account field and submit with Enter
        page.click("body")
        page.fill("#create-name", "Carol")
        page.locator("#create-name").press("Enter")
        page.wait_for_selector("text=Carol")
        check("form submits via Enter key (keyboard usability)", page.locator("#accounts-table-body tr").count() == 3)

        # 10. No uncaught JS exceptions during the whole flow.
        # Note: Chrome logs a "Failed to load resource: ... 422" console
        # entry for ANY non-2xx fetch response, whether or not the app's
        # own JS correctly catches it - the two 422s here were deliberately
        # triggered (insufficient balance, self-transfer) and were both
        # caught and displayed correctly (see checks above), so they are
        # expected noise, not bugs. Only page_errors (uncaught exceptions)
        # indicate an actual JS problem.
        check("no uncaught JavaScript exceptions during the session", len(page_errors) == 0)
        expected_resource_errors = sum(1 for e in console_errors if "Failed to load resource" in e)
        unexpected_console_errors = [e for e in console_errors if "Failed to load resource" not in e]
        check(
            "no unexpected console errors beyond the two deliberately-triggered 422s",
            expected_resource_errors == 2 and len(unexpected_console_errors) == 0,
        )

        browser.close()
finally:
    stop_server(proc)

print(f"\n{passed} passed, {failed} failed")
print(f"\nScreenshots saved in: {screenshots_dir}")
if page_errors:
    print("Uncaught JS exceptions:", page_errors)
if console_errors:
    print("All console error-level messages (informational):", console_errors)
