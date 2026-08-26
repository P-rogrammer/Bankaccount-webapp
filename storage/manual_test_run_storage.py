"""
Runs the same scenarios as test_account_storage.py using plain assertions
and tempfile, since pytest isn't installable in this sandbox (no network).
test_account_storage.py (pytest-based) is the real suite to keep/run in
the actual dev environment.
"""

import json
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.dirname(__file__))

from bank_account import BankAccount, InvalidAmountError
import account_storage as storage_module
from account_storage import (
    load_accounts,
    save_accounts,
    StorageReadError,
    InvalidStorageDataError,
)

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


tmpdir = tempfile.mkdtemp(prefix="bankaccount_storage_test_")

try:
    # ---- Saving ----
    reset_numbering()
    path = os.path.join(tmpdir, "t1.json")
    acc = BankAccount("Alice")
    acc.deposit(100)
    save_accounts(path, [acc])
    data = json.loads(open(path).read())
    check("save one account", data == {"accounts": [{"account_number": acc.account_number, "name": "Alice", "balance": 100}]})

    reset_numbering()
    path = os.path.join(tmpdir, "t2.json")
    acc1 = BankAccount("Alice")
    acc2 = BankAccount("Bob")
    save_accounts(path, [acc1, acc2])
    data = json.loads(open(path).read())
    check("save multiple accounts", len(data["accounts"]) == 2)

    reset_numbering()
    path = os.path.join(tmpdir, "t3.json")
    acc = BankAccount("Alice")
    acc.deposit(100)
    save_accounts(path, [acc])
    acc.withdraw(30)
    save_accounts(path, [acc])
    data = json.loads(open(path).read())
    check("updated balance is persisted", data["accounts"][0]["balance"] == 70)

    # ---- Loading ----
    reset_numbering()
    path = os.path.join(tmpdir, "t4.json")
    original = BankAccount("Alice")
    original.deposit(50)
    save_accounts(path, [original])
    loaded = load_accounts(path)
    check("load existing accounts", len(loaded) == 1 and loaded[0].account_number == original.account_number
          and loaded[0].name == "Alice" and loaded[0].balance == 50)

    reset_numbering()
    path = os.path.join(tmpdir, "t5.json")
    acc1 = BankAccount("Alice")
    acc2 = BankAccount("Bob")
    save_accounts(path, [acc1, acc2])
    loaded = load_accounts(path)
    check("load multiple accounts", {a.name for a in loaded} == {"Alice", "Bob"})

    path = os.path.join(tmpdir, "t6.json")
    with open(path, "w") as f:
        json.dump({"accounts": []}, f)
    loaded = load_accounts(path)
    check("load empty storage", loaded == [])

    path = os.path.join(tmpdir, "does_not_exist.json")
    loaded = load_accounts(path)
    check("load missing storage file", loaded == [])

    # ---- Account numbers ----
    reset_numbering()
    path = os.path.join(tmpdir, "t7.json")
    original = BankAccount("Alice")
    save_accounts(path, [original])
    loaded = load_accounts(path)
    check("existing account numbers survive reload", loaded[0].account_number == original.account_number)

    reset_numbering()
    path = os.path.join(tmpdir, "t8.json")
    original = BankAccount("Alice")
    save_accounts(path, [original])
    reset_numbering()  # simulate restart
    loaded = load_accounts(path)
    new_account = BankAccount("Bob")
    check("new accounts do not collide with loaded numbers",
          new_account.account_number != loaded[0].account_number and new_account.account_number > loaded[0].account_number)

    reset_numbering()
    path = os.path.join(tmpdir, "t9.json")
    original = BankAccount("Alice")
    save_accounts(path, [original])
    reset_numbering()
    load_accounts(path)
    new1 = BankAccount("Bob")
    new2 = BankAccount("Carol")
    check("multiple newly created accounts remain unique after load",
          len({original.account_number, new1.account_number, new2.account_number}) == 3)

    # ---- Invalid data ----
    path = os.path.join(tmpdir, "t10.json")
    with open(path, "w") as f:
        f.write("{ this is not valid json")
    expect_raises("invalid JSON raises StorageReadError", StorageReadError, lambda: load_accounts(path))

    path = os.path.join(tmpdir, "t11.json")
    with open(path, "w") as f:
        json.dump({"accounts": [{"account_number": 1000, "name": "Alice"}]}, f)
    expect_raises("missing required field raises InvalidStorageDataError", InvalidStorageDataError, lambda: load_accounts(path))

    path = os.path.join(tmpdir, "t12.json")
    with open(path, "w") as f:
        json.dump({"accounts": [{"account_number": "not-a-number", "name": "Alice", "balance": 10}]}, f)
    expect_raises("invalid field type raises InvalidStorageDataError", InvalidStorageDataError, lambda: load_accounts(path))

    path = os.path.join(tmpdir, "t13.json")
    with open(path, "w") as f:
        json.dump({"accounts": [
            {"account_number": 1000, "name": "Alice", "balance": 10},
            {"account_number": 1000, "name": "Bob", "balance": 20},
        ]}, f)
    expect_raises("duplicate account numbers raises InvalidStorageDataError", InvalidStorageDataError, lambda: load_accounts(path))

    # ---- Error handling / separation ----
    path = os.path.join(tmpdir, "t14.json")
    with open(path, "w") as f:
        f.write("not json at all")
    expect_raises("storage error distinguishable (1/2)", StorageReadError, lambda: load_accounts(path))
    reset_numbering()
    acc = BankAccount("Alice")
    expect_raises("storage error distinguishable (2/2, business error still InvalidAmountError)", InvalidAmountError, lambda: acc.deposit(-5))

    # failed save does not corrupt existing file
    reset_numbering()
    path = os.path.join(tmpdir, "t15.json")
    original = BankAccount("Alice")
    save_accounts(path, [original])
    original_contents = open(path).read()

    real_replace = storage_module.os.replace

    def boom(*args, **kwargs):
        raise OSError("simulated disk failure")

    storage_module.os.replace = boom
    try:
        try:
            save_accounts(path, [BankAccount("Bob")])
            failed += 1
            print("FAIL: failed save should have raised")
        except Exception:
            passed += 1
            print("PASS: failed save raised as expected")
    finally:
        storage_module.os.replace = real_replace

    check("failed save does not corrupt existing file", open(path).read() == original_contents)

finally:
    shutil.rmtree(tmpdir, ignore_errors=True)

print(f"\n{passed} passed, {failed} failed")
