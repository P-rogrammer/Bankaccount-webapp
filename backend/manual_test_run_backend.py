"""
Runs the same scenarios as test_backend.py using plain assertions and
Flask's test client directly, since pytest isn't installable in this
sandbox (no network access). test_backend.py (pytest-based) is the real
suite to keep/run in the actual dev environment.
"""

import json
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))

from bank_account import BankAccount
from account_storage import StorageError
import account_manager as account_manager_module
from app import create_app

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


def reset_numbering():
    BankAccount.all_account_numbers = []
    BankAccount.last_account_number = 999


def new_client(tmpdir, name):
    storage_path = os.path.join(tmpdir, name)
    flask_app = create_app(storage_path)
    flask_app.testing = True
    return flask_app, flask_app.test_client(), storage_path


tmpdir = tempfile.mkdtemp(prefix="bankaccount_backend_test_")

try:
    # ---- Startup ----
    reset_numbering()
    flask_app, _, _ = new_client(tmpdir, "startup_empty.json")
    check("app initializes with empty storage", flask_app.account_manager.all_accounts() == [])

    reset_numbering()
    path = os.path.join(tmpdir, "startup_existing.json")
    with open(path, "w") as f:
        json.dump({"accounts": [{"account_number": 1000, "name": "Alice", "balance": 100}]}, f)
    flask_app = create_app(path)
    account = flask_app.account_manager.get_account(1000)
    check("app loads existing data", account.name == "Alice" and account.balance == 100)

    reset_numbering()
    path = os.path.join(tmpdir, "startup_corrupt.json")
    with open(path, "w") as f:
        f.write("not valid json")
    try:
        create_app(path)
        check("app fails to start on corrupted storage", False)
    except StorageError:
        check("app fails to start on corrupted storage", True)

    # ---- Frontend serving (Task 4.1) ----
    reset_numbering()
    flask_app, client, _ = new_client(tmpdir, "frontend.json")
    resp = client.get("/")
    html = resp.get_data(as_text=True)
    check("index page is served", resp.status_code == 200
          and "/static/js/app.js" in html and "/static/css/style.css" in html)

    resp = client.get("/static/js/app.js")
    check("app.js static asset served", resp.status_code == 200)

    resp = client.get("/static/css/style.css")
    check("style.css static asset served", resp.status_code == 200)

    resp = client.post("/accounts", json={"name": "Alice"})
    check("api routes still work alongside frontend routes", resp.status_code == 201)

    # ---- Routing edge cases (Task 5.1 regression) ----
    resp = client.get("/accounts/not-a-number")
    check("non-integer account number in URL -> 404 not_found",
          resp.status_code == 404 and resp.get_json()["error"]["code"] == "not_found")

    resp = client.get("/accounts/-5")
    check("negative account number in URL -> 404 not_found",
          resp.status_code == 404 and resp.get_json()["error"]["code"] == "not_found")

    resp = client.get("/this/route/does/not/exist")
    check("unmatched route -> 404 with JSON envelope",
          resp.status_code == 404 and resp.get_json()["error"]["code"] == "not_found")

    resp = client.delete("/accounts")
    check("wrong HTTP method -> 405 with JSON envelope",
          resp.status_code == 405 and resp.get_json()["error"]["code"] == "method_not_allowed")

    resp = client.get("/accounts/9999")
    check("valid int but unknown account -> account_not_found (distinct from not_found)",
          resp.status_code == 404 and resp.get_json()["error"]["code"] == "account_not_found")

    # ---- Create account ----
    reset_numbering()
    flask_app, client, _ = new_client(tmpdir, "create.json")
    resp = client.post("/accounts", json={"name": "Alice"})
    body = resp.get_json()
    check("create account success", resp.status_code == 201 and body["data"]["name"] == "Alice"
          and body["data"]["balance"] == 0 and isinstance(body["data"]["account_number"], int))

    resp = client.post("/accounts", json={})
    check("create account missing name -> 400", resp.status_code == 400 and resp.get_json()["error"]["code"] == "bad_request")

    resp = client.post("/accounts", json={"name": 123})
    check("create account non-string name -> 400", resp.status_code == 400)

    resp = client.post("/accounts")
    check("create account no body -> 400", resp.status_code == 400)

    # ---- List / get ----
    reset_numbering()
    flask_app, client, _ = new_client(tmpdir, "list.json")
    client.post("/accounts", json={"name": "Alice"})
    client.post("/accounts", json={"name": "Bob"})
    resp = client.get("/accounts")
    names = {a["name"] for a in resp.get_json()["data"]}
    check("list accounts", resp.status_code == 200 and names == {"Alice", "Bob"})

    created = client.post("/accounts", json={"name": "Carol"}).get_json()["data"]
    resp = client.get(f"/accounts/{created['account_number']}")
    check("get existing account", resp.status_code == 200 and resp.get_json()["data"]["name"] == "Carol")

    resp = client.get("/accounts/9999")
    check("get nonexistent account -> 404", resp.status_code == 404 and resp.get_json()["error"]["code"] == "account_not_found")

    # ---- Deposit ----
    reset_numbering()
    flask_app, client, _ = new_client(tmpdir, "deposit.json")
    created = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]
    resp = client.post(f"/accounts/{created['account_number']}/deposit", json={"amount": 100})
    check("deposit success", resp.status_code == 200 and resp.get_json()["data"]["balance"] == 100)

    resp = client.post(f"/accounts/{created['account_number']}/deposit", json={"amount": -10})
    check("deposit negative -> 422 invalid_amount", resp.status_code == 422 and resp.get_json()["error"]["code"] == "invalid_amount")

    resp = client.post(f"/accounts/{created['account_number']}/deposit", json={"amount": 0})
    check("deposit zero -> 422 invalid_amount", resp.status_code == 422 and resp.get_json()["error"]["code"] == "invalid_amount")

    resp = client.post(f"/accounts/{created['account_number']}/deposit", json={})
    check("deposit missing amount -> 400", resp.status_code == 400 and resp.get_json()["error"]["code"] == "bad_request")

    for bad in ["100", True, False, None, [], {}]:
        resp = client.post(f"/accounts/{created['account_number']}/deposit", json={"amount": bad})
        check(f"deposit invalid amount type ({bad!r}) -> 400", resp.status_code == 400 and resp.get_json()["error"]["code"] == "bad_request")

    resp2 = client.post(f"/accounts/{created['account_number']}/deposit", json={"amount": 20.5})
    check("deposit resulting balance correct", resp2.get_json()["data"]["balance"] == 120.5)

    resp = client.post("/accounts/9999/deposit", json={"amount": 100})
    check("deposit on nonexistent account -> 404", resp.status_code == 404)

    # ---- Withdraw ----
    reset_numbering()
    flask_app, client, _ = new_client(tmpdir, "withdraw.json")
    created = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]
    client.post(f"/accounts/{created['account_number']}/deposit", json={"amount": 100})
    resp = client.post(f"/accounts/{created['account_number']}/withdraw", json={"amount": 40})
    check("withdraw success", resp.status_code == 200 and resp.get_json()["data"]["balance"] == 60)

    resp = client.post(f"/accounts/{created['account_number']}/withdraw", json={"amount": 1000})
    check("withdraw insufficient balance -> 422", resp.status_code == 422 and resp.get_json()["error"]["code"] == "insufficient_balance")

    resp = client.post(f"/accounts/{created['account_number']}/withdraw", json={"amount": 0})
    check("withdraw zero -> 422 invalid_amount", resp.status_code == 422 and resp.get_json()["error"]["code"] == "invalid_amount")

    resp = client.post(f"/accounts/{created['account_number']}/withdraw", json={"amount": -5})
    check("withdraw negative -> 422 invalid_amount", resp.status_code == 422 and resp.get_json()["error"]["code"] == "invalid_amount")

    resp = client.post(f"/accounts/{created['account_number']}/withdraw", json={})
    check("withdraw missing amount -> 400", resp.status_code == 400)

    for bad in ["50", True, None]:
        resp = client.post(f"/accounts/{created['account_number']}/withdraw", json={"amount": bad})
        check(f"withdraw invalid amount type ({bad!r}) -> 400", resp.status_code == 400)

    resp2 = client.post(f"/accounts/{created['account_number']}/withdraw", json={"amount": 10})
    check("withdraw resulting balance correct", resp2.get_json()["data"]["balance"] == 50)

    resp = client.post("/accounts/9999/withdraw", json={"amount": 10})
    check("withdraw on nonexistent account -> 404", resp.status_code == 404)

    # ---- Transfer ----
    reset_numbering()
    flask_app, client, storage_path = new_client(tmpdir, "transfer.json")
    alice = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]
    bob = client.post("/accounts", json={"name": "Bob"}).get_json()["data"]
    client.post(f"/accounts/{alice['account_number']}/deposit", json={"amount": 100})

    resp = client.post(f"/accounts/{alice['account_number']}/transfer",
                        json={"destination_account_number": bob["account_number"], "amount": 40})
    body = resp.get_json()["data"]
    check("transfer success", resp.status_code == 200 and body["source"]["balance"] == 60 and body["destination"]["balance"] == 40)

    src_after = client.get(f"/accounts/{alice['account_number']}").get_json()["data"]
    dst_after = client.get(f"/accounts/{bob['account_number']}").get_json()["data"]
    check("transfer correct source/destination balance", src_after["balance"] == 60 and dst_after["balance"] == 40)

    data = json.load(open(storage_path))
    records = {r["account_number"]: r["balance"] for r in data["accounts"]}
    check("transfer is persisted", records[alice["account_number"]] == 60 and records[bob["account_number"]] == 40)

    resp = client.post("/accounts/9999/transfer", json={"destination_account_number": bob["account_number"], "amount": 10})
    check("transfer source not found -> 404", resp.status_code == 404 and resp.get_json()["error"]["code"] == "account_not_found")

    resp = client.post(f"/accounts/{alice['account_number']}/transfer", json={"destination_account_number": 9999, "amount": 10})
    check("transfer destination not found -> 404", resp.status_code == 404 and resp.get_json()["error"]["code"] == "account_not_found")

    resp = client.post(f"/accounts/{alice['account_number']}/transfer", json={"amount": 10})
    check("transfer missing destination -> 400", resp.status_code == 400 and resp.get_json()["error"]["code"] == "bad_request")

    resp = client.post(f"/accounts/{alice['account_number']}/transfer", json={"destination_account_number": bob["account_number"]})
    check("transfer missing amount -> 400", resp.status_code == 400)

    for bad in ["40", True, None]:
        resp = client.post(f"/accounts/{alice['account_number']}/transfer",
                            json={"destination_account_number": bob["account_number"], "amount": bad})
        check(f"transfer invalid amount type ({bad!r}) -> 400", resp.status_code == 400)

    resp = client.post(f"/accounts/{alice['account_number']}/transfer",
                        json={"destination_account_number": bob["account_number"], "amount": 0})
    check("transfer zero amount -> 422 invalid_amount", resp.status_code == 422 and resp.get_json()["error"]["code"] == "invalid_amount")

    resp = client.post(f"/accounts/{alice['account_number']}/transfer",
                        json={"destination_account_number": bob["account_number"], "amount": -5})
    check("transfer negative amount -> 422 invalid_amount", resp.status_code == 422 and resp.get_json()["error"]["code"] == "invalid_amount")

    resp = client.post(f"/accounts/{alice['account_number']}/transfer",
                        json={"destination_account_number": bob["account_number"], "amount": 100000})
    check("transfer insufficient balance -> 422", resp.status_code == 422 and resp.get_json()["error"]["code"] == "insufficient_balance")

    resp = client.post(f"/accounts/{alice['account_number']}/transfer",
                        json={"destination_account_number": alice["account_number"], "amount": 10})
    check("self-transfer -> 422 self_transfer", resp.status_code == 422 and resp.get_json()["error"]["code"] == "self_transfer")

    before_src = client.get(f"/accounts/{alice['account_number']}").get_json()["data"]["balance"]
    before_dst = client.get(f"/accounts/{bob['account_number']}").get_json()["data"]["balance"]
    resp = client.post(f"/accounts/{alice['account_number']}/transfer",
                        json={"destination_account_number": bob["account_number"], "amount": 100000})
    after_src = client.get(f"/accounts/{alice['account_number']}").get_json()["data"]["balance"]
    after_dst = client.get(f"/accounts/{bob['account_number']}").get_json()["data"]["balance"]
    check("failed transfer leaves both balances unchanged", before_src == after_src and before_dst == after_dst)

    # ---- Storage error mapping ----
    reset_numbering()
    flask_app, client, _ = new_client(tmpdir, "storage_error.json")
    created = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]

    real_save = account_manager_module.AccountManager._save

    def boom(self):
        raise StorageError("simulated storage failure")

    account_manager_module.AccountManager._save = boom
    try:
        resp = client.post(f"/accounts/{created['account_number']}/deposit", json={"amount": 10})
        check("storage failure maps to 503", resp.status_code == 503 and resp.get_json()["error"]["code"] == "storage_error")
    finally:
        account_manager_module.AccountManager._save = real_save

finally:
    shutil.rmtree(tmpdir, ignore_errors=True)

print(f"\n{passed} passed, {failed} failed")
