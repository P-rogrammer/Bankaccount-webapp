"""
Runs the same scenarios as test_account_manager.py using plain assertions,
since pytest isn't installable in this sandbox (no network access).
test_account_manager.py (pytest-based) is the real suite to keep/run.
"""

import json
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "storage"))
sys.path.insert(0, os.path.dirname(__file__))

from bank_account import BankAccount, InvalidAmountError, InsufficientBalanceError, SelfTransferError
from account_storage import InvalidStorageDataError, StorageReadError
from account_manager import AccountManager, AccountNotFoundError

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


def expect_raises(name, exc_type, fn):
    global passed, failed
    try:
        fn()
        failed += 1
        print(f"FAIL: {name} (no exception raised)")
    except exc_type:
        passed += 1
        print(f"PASS: {name}")
    except Exception as e:
        failed += 1
        print(f"FAIL: {name} (wrong exception: {type(e).__name__}: {e})")


def reset_numbering():
    BankAccount.all_account_numbers = []
    BankAccount.last_account_number = 999


tmpdir = tempfile.mkdtemp(prefix="bankaccount_manager_test_")

try:
    # ---- Startup ----
    reset_numbering()
    path = os.path.join(tmpdir, "t1.json")
    with open(path, "w") as f:
        json.dump({"accounts": [{"account_number": 1000, "name": "Alice", "balance": 100}]}, f)
    manager = AccountManager(path)
    acc = manager.get_account(1000)
    check("existing accounts are loaded at startup", acc.name == "Alice" and acc.balance == 100)

    reset_numbering()
    path = os.path.join(tmpdir, "does_not_exist.json")
    manager = AccountManager(path)
    check("missing storage starts with no accounts", manager.all_accounts() == [])

    reset_numbering()
    path = os.path.join(tmpdir, "t2.json")
    with open(path, "w") as f:
        f.write("not valid json")
    expect_raises("invalid storage does not silently produce empty list", StorageReadError, lambda: AccountManager(path))

    reset_numbering()
    path = os.path.join(tmpdir, "t3.json")
    with open(path, "w") as f:
        json.dump({"accounts": [{"account_number": 1000, "name": "Alice"}]}, f)
    expect_raises("invalid account records at startup raise", InvalidStorageDataError, lambda: AccountManager(path))

    # ---- Creation ----
    reset_numbering()
    path = os.path.join(tmpdir, "t4.json")
    manager = AccountManager(path)
    account = manager.create_account("Alice")
    data = json.load(open(path))
    check("newly created account can be persisted", any(r["account_number"] == account.account_number for r in data["accounts"]))

    reset_numbering()
    path = os.path.join(tmpdir, "t5.json")
    manager = AccountManager(path)
    created = manager.create_account("Alice")
    reloaded = AccountManager(path)
    acc = reloaded.get_account(created.account_number)
    check("persisted account can be loaded again", acc.name == "Alice" and acc.balance == 0)

    # ---- Deposit ----
    reset_numbering()
    path = os.path.join(tmpdir, "t6.json")
    manager = AccountManager(path)
    account = manager.create_account("Alice")
    manager.deposit(account.account_number, 100)
    data = json.load(open(path))
    record = next(r for r in data["accounts"] if r["account_number"] == account.account_number)
    check("successful deposit can be persisted", record["balance"] == 100)

    reset_numbering()
    path = os.path.join(tmpdir, "t7.json")
    manager = AccountManager(path)
    account = manager.create_account("Alice")
    manager.deposit(account.account_number, 100)
    reloaded = AccountManager(path)
    check("reload restores deposit", reloaded.get_account(account.account_number).balance == 100)

    reset_numbering()
    path = os.path.join(tmpdir, "t8.json")
    manager = AccountManager(path)
    account = manager.create_account("Alice")
    manager.deposit(account.account_number, 50)
    before = open(path).read()
    expect_raises("failed deposit raises", InvalidAmountError, lambda: manager.deposit(account.account_number, -10))
    check("failed deposit does not modify persisted state", open(path).read() == before)
    check("failed deposit does not modify in-memory balance", manager.get_account(account.account_number).balance == 50)

    # ---- Withdrawal ----
    reset_numbering()
    path = os.path.join(tmpdir, "t9.json")
    manager = AccountManager(path)
    account = manager.create_account("Alice")
    manager.deposit(account.account_number, 100)
    manager.withdraw(account.account_number, 40)
    data = json.load(open(path))
    record = next(r for r in data["accounts"] if r["account_number"] == account.account_number)
    check("successful withdrawal can be persisted", record["balance"] == 60)

    reset_numbering()
    path = os.path.join(tmpdir, "t10.json")
    manager = AccountManager(path)
    account = manager.create_account("Alice")
    manager.deposit(account.account_number, 100)
    manager.withdraw(account.account_number, 40)
    reloaded = AccountManager(path)
    check("reload restores withdrawal", reloaded.get_account(account.account_number).balance == 60)

    reset_numbering()
    path = os.path.join(tmpdir, "t11.json")
    manager = AccountManager(path)
    account = manager.create_account("Alice")
    manager.deposit(account.account_number, 50)
    before = open(path).read()
    expect_raises("failed withdrawal raises", InsufficientBalanceError, lambda: manager.withdraw(account.account_number, 1000))
    check("failed withdrawal does not modify persisted state", open(path).read() == before)
    check("failed withdrawal does not modify in-memory balance", manager.get_account(account.account_number).balance == 50)

    reset_numbering()
    path = os.path.join(tmpdir, "t12.json")
    manager = AccountManager(path)
    manager.create_account("Alice")
    before = open(path).read()
    expect_raises("operation on nonexistent account raises", AccountNotFoundError, lambda: manager.deposit(9999, 10))
    check("operation on nonexistent account does not touch storage", open(path).read() == before)

    # ---- Transfer ----
    reset_numbering()
    path = os.path.join(tmpdir, "t_transfer1.json")
    manager = AccountManager(path)
    alice = manager.create_account("Alice")
    bob = manager.create_account("Bob")
    manager.deposit(alice.account_number, 100)
    manager.transfer(alice.account_number, bob.account_number, 40)
    data = json.load(open(path))
    records = {r["account_number"]: r["balance"] for r in data["accounts"]}
    check("successful transfer can be persisted", records[alice.account_number] == 60 and records[bob.account_number] == 40)

    reset_numbering()
    path = os.path.join(tmpdir, "t_transfer2.json")
    manager = AccountManager(path)
    alice = manager.create_account("Alice")
    bob = manager.create_account("Bob")
    manager.deposit(alice.account_number, 100)
    manager.transfer(alice.account_number, bob.account_number, 40)
    reloaded = AccountManager(path)
    check("reload restores transfer", reloaded.get_account(alice.account_number).balance == 60
          and reloaded.get_account(bob.account_number).balance == 40)

    reset_numbering()
    path = os.path.join(tmpdir, "t_transfer3.json")
    manager = AccountManager(path)
    bob = manager.create_account("Bob")
    expect_raises("transfer source not found", AccountNotFoundError, lambda: manager.transfer(9999, bob.account_number, 10))

    reset_numbering()
    path = os.path.join(tmpdir, "t_transfer4.json")
    manager = AccountManager(path)
    alice = manager.create_account("Alice")
    manager.deposit(alice.account_number, 100)
    expect_raises("transfer destination not found", AccountNotFoundError, lambda: manager.transfer(alice.account_number, 9999, 10))

    reset_numbering()
    path = os.path.join(tmpdir, "t_transfer5.json")
    manager = AccountManager(path)
    alice = manager.create_account("Alice")
    bob = manager.create_account("Bob")
    manager.deposit(alice.account_number, 50)
    before = open(path).read()
    expect_raises("failed transfer (insufficient balance) raises", InsufficientBalanceError,
                  lambda: manager.transfer(alice.account_number, bob.account_number, 1000))
    check("failed transfer does not modify persisted state", open(path).read() == before)
    check("failed transfer does not modify either in-memory balance",
          manager.get_account(alice.account_number).balance == 50 and manager.get_account(bob.account_number).balance == 0)

    reset_numbering()
    path = os.path.join(tmpdir, "t_transfer6.json")
    manager = AccountManager(path)
    alice = manager.create_account("Alice")
    manager.deposit(alice.account_number, 50)
    before = open(path).read()
    expect_raises("self-transfer via manager is rejected", SelfTransferError,
                  lambda: manager.transfer(alice.account_number, alice.account_number, 10))
    check("self-transfer does not persist", open(path).read() == before)
    check("self-transfer does not modify balance", manager.get_account(alice.account_number).balance == 50)

    # ---- Restart simulation ----
    reset_numbering()
    path = os.path.join(tmpdir, "t13.json")
    manager = AccountManager(path)
    alice = manager.create_account("Alice")
    manager.deposit(alice.account_number, 200)
    manager.withdraw(alice.account_number, 50)
    reset_numbering()
    restarted = AccountManager(path)
    reloaded_alice = restarted.get_account(alice.account_number)
    check("full restart cycle restores balance", reloaded_alice.balance == 150 and reloaded_alice.name == "Alice")
    bob = restarted.create_account("Bob")
    check("new account after restart does not collide", bob.account_number != alice.account_number and bob.account_number > alice.account_number)

    # ---- Account number continuity ----
    reset_numbering()
    path = os.path.join(tmpdir, "t14.json")
    manager = AccountManager(path)
    manager.create_account("Alice")
    manager.create_account("Bob")
    manager.create_account("Carol")
    reset_numbering()
    restarted = AccountManager(path)
    new_account = restarted.create_account("Dave")
    existing_numbers = {a.account_number for a in restarted.all_accounts() if a.name != "Dave"}
    check("account number continuity across manager restart",
          new_account.account_number not in existing_numbers and new_account.account_number > max(existing_numbers))

finally:
    shutil.rmtree(tmpdir, ignore_errors=True)

print(f"\n{passed} passed, {failed} failed")
